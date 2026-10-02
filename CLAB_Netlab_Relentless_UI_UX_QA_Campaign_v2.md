# Claude Code: relentless netlab UI/UX campaign + individual-device restart

**Revision 2 — adds required Restart device implementation with Containerlab VS Code lifecycle parity.**

## Mission — execute, repair, prove

The initial netlab integration in **Containerlab Node Manager** is complete. Your assignment is now an intensive quality campaign across **every implemented netlab-related workflow, button, input, menu, dialog, status, table, preview, download, recovery path, and integration point**.

Product repository: https://github.com/ArchRuger/CLAB-BACKUP-WORKER-v2

**Additional required delivery:** Implement individual-device restart with the same underlying behavior as the Containerlab VS Code extension. This is the one explicitly authorized new feature in addition to the QA/repair campaign. It is a general device action, not dependent on netlab, and must meet the same evidence, repair, and acceptance gates. The full implementation contract is in §7.13; read it before planning or delegating.

The original netlab campaign remains in force. Do not replace it with this feature, leave Restart as a future suggestion, or interpret the existing “test implemented scope” rule as permission to skip this new implementation.

Do not produce an audit and stop. Discover defects, reproduce them, fix their root causes, add regression protection, rebuild the real application, and repeat the affected workflows. Improve usability as well as technical correctness. A feature that technically works but is confusing, easy to misuse, inaccessible, or impossible to recover from is not finished.

**Operating loop: inventory → exercise → break → reproduce → fix → regression-test → deploy → independently retest → checkpoint → continue.**

Be relentless about evidence and finishing repairs, not about generating noise or endlessly rewriting working code. Do not stop at the first clean smoke test, the first successful generation, or the first batch of easy fixes. “Flawless” is the quality target; report demonstrated coverage and remaining uncertainty honestly rather than claiming mathematical proof of zero possible defects.

## 1. Confirmed authority and environment

You are running inside the owner's **isolated, totally unrestricted development VM**. **Bypass permissions are already enabled.** These are supplied facts, not unanswered prerequisites.

You are authorized to use root/sudo; install or repair development dependencies and browser binaries; inspect processes, logs, files, containers, and networks; refresh host helpers; rebuild and replace the running development application; create or redeploy development labs; change development-device configurations; restart services; and induce controlled disconnects, timeouts, failures, and recovery events. Use the VM fully. Do not repeatedly request permission for these normal campaign actions or substitute shallow mocks because privileged live testing takes effort.

This authority belongs to your development session. It does **not** authorize weakening the shipped application's permissions, validation, credential protection, review/confirmation, isolation, or rollback controls. Exercise those product controls through the normal user path. An unrestricted developer must still prove a restricted application works correctly.

Before destructive experiments, establish a recoverable baseline of the relevant development data, configuration, and services. Keep recovery access. Preserve unrelated work, deliberately uncommitted routing settings, credentials, required images, and useful evidence. Never point a unit-test `Store` at persistent product data. Use explicit test identities and scratch state; restore the actual development product to a usable state after fault injection.

Unrestricted permissions do not mean unlimited RAM, CPU, or disk. Inspect resources and clean genuinely disposable artifacts as needed. Do not indiscriminately prune images, volumes, user data, or other agents' work. Use a scratch filesystem or quota-controlled test area for disk-full tests rather than filling the VM's root filesystem.

## 2. Orchestration and model routing

**Fable 5.1 remains the orchestrator.** It owns campaign coverage, prioritization, cross-module decisions, integration, the shared VM, checkpointing, and final acceptance.

| Assignment | Preferred agent/model |
|---|---|
| Locate controls, routes, tests, call sites, and documentation; mechanical coverage bookkeeping | Haiku |
| Browser exploration, bounded UI/backend repairs, test implementation, fixtures, ordinary regression execution | Sonnet |
| Difficult state/race bugs, semantic data loss, configuration safety, platform behavior, restart target isolation/recovery, independent high-risk review | Opus 5.5 |
| Architecture decisions, hard unresolved defects, coordinated integration, final acceptance | Fable 5.1 |
| Independent usability and acceptance passes | A fresh Sonnet or Opus agent selected for the risk, not the implementer |

These are defaults, not ceilings. Use Fable or Opus for implementation when they are the best fit; do not waste strong reasoning on mechanical enumeration or force a weaker agent through a consequential problem. Parallelize independent investigation, isolated browser sessions, and disjoint-file repairs. Do not route every worker to maximum-effort Fable.

Inspect the installed agent configuration and effective runtime routing. Reuse the owner's established routing. Resolve installed model identifiers rather than guessing; distinguish requested model from observed model. Check for overrides that silently force all subagents onto one model. Preserve intentionally local routing files and do not commit them accidentally.

Give each worker a bounded charter: surfaces to inspect, risk to attack, allowed files, shared-state restrictions, required evidence, and completion criteria. Require reproducible results, not “looks good.” Keep one coordinator in control of the live lab, deployment, shared test data, and version files. Independent reviewers must not merely repeat the author's assertions.

## 3. Establish the actual implemented scope

Read `CLAUDE.md`, relevant current sections of `agent instructions.md`, repository maintenance rules, and the integration's architecture and pickup notes. Inspect Git status, branch, HEAD, remote, pending work, current version, installed helpers, running image, engine version, served browser assets, and test environment. Do not overwrite unrelated changes or blindly pull into a dirty checkout.

**Preliminary source-review anchor:** `main` was inspected at `0cac864e2efed3e7b21973277763db8a1f2eda09`. At that revision the integration records described the generation engine and Design tab, while device application was still an explicitly separate, unimplemented stage. The earlier browser evidence recorded 20 fixture-manager checks; it was not an exhaustive real-VM UI acceptance campaign. These observations may be stale by the time you execute. Verify the checkout and running product yourself.

Start with these actual integration locations, then follow all dependencies:

- `docs/NETWORK-DESIGN.md` and `docs/netlab-integration/{PICKUP,DECISIONS,LEDGER,TESTS}.md`.
- `clab-backup-ui/app/static/network-design.js`, its markup in `index.html`, the relevant CSS, `shell.js`, `app.js`, navigation, browser draft storage, and shared dialog/error/download helpers.
- `clab-backup-ui/app/network_design.py`, `design_intent.py`, `design_adapter.py`, `design_engine.py`, `design_capabilities.py`, and `design_capability_data.json`.
- State persistence, topology/discovery mapping, file lifecycle, job guards, credentials, public serialization, and any now-present provisioning or design-export modules.
- `tests/test_network_design_ui.js`, all design-related Python tests, and the explicit CI test lists.
- `docs/netlab-integration/tools/check_design_ui.py`, `check_design_live.py`, existing fixture-manager/browser tools, and earlier evidence files.

For the restart feature, additionally inspect the extension source identified in §7.13, the installed Containerlab lifecycle capabilities, the manager’s lab/node action handlers and host-helper argument validation, and discovery/readiness/session reconciliation. Trace actual behavior; do not infer node support from a lab-wide Restart button.

Separate **implemented behavior**, **UI promises**, **documented limitations**, **future work**, and **unsupported platform combinations**. Existing documentation is evidence to check, not authority over contrary runtime behavior.

Test everything now implemented, including additions after the inspection anchor. Do not resurrect the original integration assignment or implement an entire unfinished provisioning subsystem merely to make a QA checklist green. A broken or misleading exposed control is a defect; an honestly unavailable future phase is not a tested success. Repair incomplete user journeys that the shipped UI already promises, and record truly absent capability separately.

**Scope exception:** Individual-device restart in §7.13 is explicitly authorized new functionality. Implement it even if it is absent at baseline; the restrictions above still prohibit unrelated expansion or unsafe completion of unfinished provisioning.

Run baseline tests before repairs. Record inherited failures rather than taking ownership for introducing them, but fix inherited defects within this campaign's scope. Missing tooling is an environment task to resolve, not automatic permission to skip browser testing.

## 4. Build a coverage contract before declaring anything tested

Create a compact campaign workspace such as `docs/netlab-ui-qa/`. Maintain:

- `PICKUP.md`: current build, branch, work in progress, running jobs, recovery steps, exact next action.
- A machine-readable coverage inventory and a readable summary.
- A defect ledger with reproduction, evidence, fixes, and independent retest status.
- Reusable test tools and an evidence index. Reuse existing tooling instead of creating a competing framework.

Enumerate the surface from **source, rendered DOM, conditional states, and actual navigation**. Compare those inventories. Include hidden/disabled controls, repeated per-node/per-file actions, responsive variants, keyboard paths, empty states, and every alternate entry point. A static grep for buttons alone is insufficient.

Give each control/workflow/state a stable coverage ID. Record:

```text
ID | surface/entry route | control/action | preconditions | relevant states
   | user intent | expected visible outcome | expected persisted/backend outcome
   | forbidden side effects | test IDs | browser/build/data identity
   | evidence | result | defect IDs | retest result
```

Every control needs a reason to exist and a demonstrated outcome. For repeated rows, exercise every distinct behavior and representative first/middle/last and edge-case rows; do not confuse clicking one device's View button with validating all device/file mappings.

Build explicit state-transition coverage: empty, loading, clean/saved, dirty/unsaved, invalid, validating, queued, generating, cancelled/interrupted, succeeded, failed, stale, conflicting revision, engine unavailable, missing topology, unsupported target, and any implemented apply/verify/recovery states. Include passive UI components such as badges and warnings, not just buttons. Add single-device restart review, accepted/restarting, stopped-node recovery, booting, fresh-ready, conflicting/busy, failed, and interrupted/unknown outcomes from §7.13.

Track meaningful combinations of lab identity, design revision, generation identity, target selection, browser session, and asynchronous state. Cover every enumerated supported control and transition; use boundary partitions and pairwise combinations for the broader matrix, plus targeted higher-order races for risky interactions. Do not claim every possible input combination was exhausted.

Allowed results: `PASS`, `FAIL`, `BLOCKED`, `NOT RUN`, and `NOT APPLICABLE — evidence/reason`. An unsupported feature's **refusal workflow** still needs a passing test. Never count BLOCKED, NOT RUN, or a skipped platform as a pass, shrink the denominator to hide failures, or call a presence check end-to-end coverage.

## 5. What counts as proof

Use four distinct test layers and label evidence accordingly:

1. **Unit/component:** transformations, state vocabulary, validation, serialization, mappings, DOM helpers.
2. **Real-app integration:** actual FastAPI app on scratch state with the pinned netlab engine; deterministic fault injection where appropriate.
3. **Real-browser end-to-end:** the actual rebuilt, installed manager on the development VM, using the normal UI and real backend/engine for success paths.
4. **Live NOS verification:** for implemented device-affecting workflows, the newly required individual-device restart, or to prove non-mutation; actual intended devices, not their Linux container shells. Restart additionally needs host/container and dataplane-link evidence, not NOS output alone.

A fixture manager is useful but cannot replace the real installed-product run. Mocked success responses cannot establish engine, persistence, download, or device correctness. Controlled network interception is appropriate for error/race tests; label it as fault injection rather than live service evidence.

For a user action, prove the chain that applies:

**visible control → real interaction → correct request/target/revision → correct service result → correct persisted artifact/state → accurate visible feedback → survives reload/reconnect.**

Also prove negative effects did not occur. Planning must not change NOS configuration, deploy/destroy containers, rewrite topology, change management addresses, or commit/push Git files.

Use real browser clicks, typing, keyboard navigation, menus, and file selection for the acceptance path. Do not call production handlers directly, manually toggle `disabled`, use forced clicks through overlays, or mutate state through DevTools and claim the UI worked. API/CLI setup is allowed for documented fixtures and cleanup, not as a substitute for the interaction under test.

Use the existing Playwright language/framework where practical. Prefer accessible role/label locators and condition-based assertions. Add stable test IDs only where needed. Avoid arbitrary sleeps and retries that conceal races. A flaky test that passes on rerun remains a problem until diagnosed. Capture unexpected console errors, unhandled rejections, request failures, application errors, screenshots, and targeted traces. Expected injected failures must be identified and asserted, not globally suppressed.

Inspect screenshots and actual interaction behavior. Merely taking a screenshot is not a visual review. Automated accessibility checks also require keyboard/focus and usability review. Do not call an automated accessibility pass proof of complete accessibility compliance.

## 6. High-priority probes from the inspected source

These are **test hypotheses**, not claims of browser-confirmed bugs. Re-check the current implementation and reproduce or close each with evidence. They are starting points, not the full campaign.

1. **Advanced-to-guided data loss.** `designIntentFromForm` rebuilt `intent.addressing` from three visible pools. Try an otherwise-valid design with custom pools, `vrf_loopback`, `router_id`, additional pool properties, and advanced per-node/link settings. Change one unrelated guided field. Verify all unrelated semantic data survives save, reload, export, and generation.
2. **Multiple route reflectors and node-specific BGP state.** The guided form represented a single reflector selection. Import a supported multi-reflector design and per-node AS/options, then edit unrelated fields. Never silently collapse a richer advanced design to the simple form's representational limits.
3. **Validation of what is actually on screen.** Leave malformed or half-typed JSON in Advanced, then click Check, Save, Generate, or Export without a preparatory blur. `designOnAdvancedChange` previously retained the last parsed object after a parse error. Prove the UI cannot validate or act on old intent while appearing to accept the current text.
4. **Unsaved Generate/Export semantics.** The inspected Generate handler sent the saved revision rather than the draft. Change a value and immediately generate/download. The product must either explicitly save-and-generate, ask how to proceed, or clearly require saving; never silently generate old content under a new-looking form.
5. **Cross-lab asynchronous contamination.** Delay save, import, validation, renumber, clear, plan-load, and file-preview responses from lab A; navigate to B before they return. No A result may replace B's form, errors, badge, dialog, draft, download target, or future request identity.
6. **Same-lab, different-generation races.** Return requests out of order while generating again or opening different results/files. A lab-ID check alone does not prove generation/revision correctness.
7. **Polling failures and stale success.** The inspected polling catch stopped watching silently. Disconnect mid-generation, return malformed/failed responses, then restore connectivity. Require visible uncertainty and a usable recovery path, not a frozen “Generating” or an old green success.
8. **Draft conflict and storage failure.** Inspect stale-draft discard behavior, quota errors, unavailable storage, and multiple tabs. Never silently destroy the user's only copy to resolve a revision conflict. Preserve/download recoverable text and offer a clear reconciliation path.
9. **History usefulness and retention.** The inspected history was largely a status list and file actions selected the newest generation. After a failed generation or Remove design, prove retained results remain unambiguously identifiable and retrievable through the promised workflow. Older files must never masquerade as current intent.
10. **Falsy/default coercion and hidden-field mutations.** Probe zero, blank, invalid numeric strings, IPv4-only/IPv6-only, toggling a module off/on, switching roles, and unsupported nodes. Invalid values must not silently become defaults; legitimate values and advanced settings must not disappear unnoticed.

## 7. Execute the full workflow matrix

### 7.1 Entry, navigation, loading, and identity

Exercise the Design tab, Tools shortcuts, direct/deep links, reload, back/forward, switching tabs, switching labs, and opening a second browser tab. Start with no lab, no topology, no design, a saved design, failed history, an unavailable engine, and a removed or renamed lab.

No stale previous-lab content while loading, unexplained blank panels, trapped navigation, duplicate listeners, incorrect breadcrumbs, or controls targeting a lab other than the one shown. Verify initial loading failure has a reachable retry and does not require a hard refresh. Navigate away during every asynchronous action and return both before and after it finishes.

### 7.2 Guided inputs and conditional settings

Exercise every addressing input, family toggle, prefix-length control, module selector, common protocol field, gateway selector, node role, exclusion control, and reflector selector. Inspect every conditional section when shown, hidden, re-enabled, or restored from saved intent.

Use valid boundaries, invalid ranges, empty values, whitespace, pasted content, long permitted names, and irrelevant disabled fields. Verify which values are preserved, cleared, or validated and make that behavior intentional. Global settings must not erase valid per-node overrides. A host or excluded/unsupported device must not silently become a router or reflector.

Confirm error messages identify the exact field/device, explain a repair, remain visible, and clear when corrected. Correct inputs must not be rejected merely because a hidden unrelated control contains a stale default. Visible field changes must reach the plan and generated configuration, not just browser state.

### 7.3 Advanced editor and round-trip integrity

Exercise valid rich documents, malformed JSON, incomplete typing, wrong root types, invalid schemas, unknown/refused fields, deep nesting, oversize input, and duplicate-key behavior. Ensure duplicate/conflicting semantic fields are not silently accepted by a permissive parser.

Test guided → advanced → guided → save → reload → export → import → regenerate. Compare normalized semantic intent, including custom addressing, node/link overrides, VLANs, VRFs, modules, interface mappings, and explicit assignments. Only an intentional edit may change its owned fields. Allocation-ledger changes must follow their own documented rules.

Typing, selection, caret position, scroll, and editor content must not be overwritten by polling or background refresh. Preserve raw invalid edits for recovery; do not substitute an older valid object invisibly. Check input/change/blur ordering with immediate button clicks and keyboard activation.

### 7.4 Saving, drafts, conflicts, and persistence

Test first save, unchanged save, edited save, failed validation, request timeout before and after server commit, duplicate submission, 409 conflicts, and a successful save followed by a lost response. Reconcile uncertain outcomes from the backend instead of blindly repeating destructive operations.

Verify per-lab drafts across navigation and reload, browser storage failure, stale tabs, two separate sessions, manager restart, and design removal. Unsaved work must not leak between labs or disappear during import, clear, failed save, or generation. No false “saved” label before durable persistence; no “No design yet” after a confirmed saved design merely because no plan exists.

### 7.5 Generating, cancelling, failing, and recovering

Generate from each supported input path. Inspect button disabling, repeated clicks, immediate cancellation, running cancellation, completion/cancel races, regeneration after failure, engine unavailable/incompatible, malformed output, timeout, controlled disk errors, manager restart, and a second lab competing for engine capacity.

UI progress must match actual state. Do not invent percentage completion. Cancellation acknowledgement must not claim the worker stopped before it did. Failed jobs need actionable error detail and retained useful results; no unending spinner, undisclosed polling failure, orphan process, stale lock, or duplicate generation.

Verify immutable input and artifact identities. Edit the design or change topology during generation; the result must remain tied to the inputs actually used, and stale results must be marked as such. A repeat with unchanged semantic inputs should preserve the expected allocations and semantic outputs.

### 7.6 Addressing, routing, mappings, and capability presentation

Compare form intent, saved intent, calculated plan, compatibility data, and generated device text. Check IPv4-only, IPv6-only, dual-stack, loopbacks, point-to-point/shared links, explicit addresses, automatic pools, allocation boundaries/exhaustion, per-VRF overlap, management overlap, duplicate IDs, and renumbering.

Use nonsequential explicit ports, parallel links, reordered nodes/links, renamed nodes, inherited Containerlab settings, hosts, excluded targets, and each baseline platform. Containerlab endpoint, NOS interface, neighbor, address, ASN, area, VRF, VLAN, and AF must remain associated with the correct identity.

For every currently exposed module and important subfeature, test a valid supported case and the applicable unsupported or missing-prerequisite case. This includes the implemented paths for OSPFv2/v3, BGP, IS-IS, EIGRP, RIPv2/RIPng, DHCP/DHCPv6, BFD, VLAN/VRF, LAG/LACP/MLAG, STP, VRRP/anycast, VXLAN, GRE/WireGuard, routing policy/filtering/static routes/redistribution/default origination, MPLS/LU/VPN/6PE/EVPN, and SR-MPLS/SRv6.

Do not infer that every catalog item is implemented on every image. Use the real schema, exact profile/image, dependencies, and capability ledger. A correctly refused unsupported request is a tested refusal, not protocol support. “Generated” must not be presented as “applied,” “verified on this image,” or working forwarding. Supported compound configurations need interaction tests, not only one checkbox at a time.

### 7.7 Plans, previews, warnings, and history

Inspect every summary, table, badge, expansion, warning, compatibility cell, neighbor list, protocol note, renumbering display, and history action. Exercise empty, sparse, dense, long, failed, interrupted, stale, and partially excluded results.

The user must know which lab/design/generation is shown, whether it is current, what succeeded, and what remains unverified. Avoid truncated critical identifiers or values that cannot be recovered. Old successful generations must not override newer failures or imply an active design still exists after removal.

Open different files and historical results rapidly, while generating and while switching labs. Handle missing/corrupt/pruned artifacts and bounded-history rollover. Retention promises must be usable through the UI; add a focused retrieval/navigation affordance when necessary to complete that existing promise, not an unrelated history subsystem.

### 7.8 Downloads, import, and export

Click each actual download/export entry point and intercept the browser download event. Read the downloaded bytes. Verify filename, nonempty content, file type, selected lab/generation/device, module ordering, manifest identity, checksums, archive paths, and appropriate secret exclusions. A link with the right `href` is not a download test.

Round-trip valid JSON/YAML intent through import/export. Test cancelling selection, reselecting the same file, malformed/empty/oversized files, wrong schemas, YAML aliases, disallowed executable fields, Unicode/long filenames, stale revisions, missing nodes/interfaces, and import over unsaved changes. Failure must preserve the previous valid design and recoverable draft.

Export with unsaved changes must clearly state which version is exported. Browser download errors must not silently open an unexplained error tab. Generated fragments, intent exports, backups, and restore-grade candidates must remain distinct and cannot be mislabeled to satisfy another workflow.

### 7.9 Renumber, clear, destructive confirmation, and cleanup

Exercise both confirmation and cancellation, Escape, focus return, duplicate clicks, stale review state, unsaved edits, concurrent generation, network loss, and lab switching while dialogs are open.

Renumber must explain that it resets the allocation ledger, what changes now versus next generation, and that it does not itself configure devices. Clear must explain exactly which design, drafts, history, and files remain or disappear. Preserve anything the dialog promises to retain and keep it usable afterwards. Cancel must cause no mutation.

Test lab removal and Start fresh only on designated campaign data. Verify associated design artifacts are cleaned up according to policy without removing another lab's data. Do not silently alter the existing application's destructive-action scope.

### 7.10 Errors, stale data, and recovery journeys

Inject reachable 400/403/404/409/413/422/500/503-class failures as applicable, failed fetches, delayed and out-of-order responses, unavailable services, corrupt artifacts, stale revisions, and engine incompatibility. Use actual response contracts, not invented codes as an excuse to change APIs.

For each error verify: accurate explanation; no false success; user work retained; the affected control becomes usable again; a next action is visible; and recovery succeeds without restarting the whole browser. Prefer durable inline/dialog feedback for consequential failures over an easily missed toast. No swallowed exceptions or infinite automatic retries.

### 7.11 Any implemented apply/verify/recovery workflow

First establish whether this capability actually exists. If absent, verify the UI accurately says preview/download only and cannot reach a hidden apply path. Do not add unsafe application as part of cosmetic QA.

If present, test target selection, unsupported targets, native preview/diff, acknowledgement, immutable review binding, readiness, pre-change backup, protected management, pending edits, cancellation, progress, partial failure, verification, rollback, restart reconciliation, and user-visible per-node outcomes.

Execute through the UI against the real baseline devices. Verify actual NOS configuration and applicable adjacencies/routes/reachability; a 200 response or green badge is insufficient. Test repeated apply/no-op, modify, remove managed state, and preservation of unrelated manual configuration. Never send generated fragments into whole-config restore to take a shortcut. Confirmed-commit/session ownership and recovery timers must retain their existing safety contracts.

### 7.12 Adjacent-workflow regression

After repairs touching shared code, exercise topology builder, map-only editing, deploy/redeploy/start/stop, discovery/readiness, browser terminals, capture, backups, per-device/ZIP downloads, snapshot restore, Git Save progress/Latest/checkpoints, profile credentials, diagnostics, and navigation back to Design.

Use before/after evidence. A Design tab fix that damages another tab, changes a normal deploy into automatic provisioning, or expands Git export to unrelated files is a regression. Trace underlying causes across boundaries and fix them; do not declare shared failures out of scope merely because they appear outside the Design tab.

## 7.13 Required new feature — individual-device restart with Containerlab VS Code parity

**This is an explicit implementation requirement, not merely a QA probe or a future feature to document.** Add **Restart device** to the manager and include it in this entire repair-and-acceptance campaign. The user wants to restart one device in an existing lab as they can through the Containerlab VS Code extension. Deliver working UI, backend, restricted host execution, state reconciliation, tests, and evidence. Do not mark the feature N/A because it was not present before this assignment.

### A. Establish the reference behavior; use the correct lifecycle operation

The prompt author's source review found the following reference at `srl-labs/vscode-containerlab` commit `6df8e9629a0dfca625d162498aa976d49845a342` (the package declares version `0.26.3`):

- `src/commands/nodeActions.ts`: `restartNode` calls `runTopologyNodeLifecycleAction("restart", node)`. It resolves the topology node name from `rootNodeName`, then `name_short`, then `name`; requires the selected lab's topology path; and supplies `--node <nodeName>`.
- `src/commands/clabCommand.ts`: the command arguments combine the action, configured runtime, node flag, and topology path. For Docker, its equivalent is:

```bash
containerlab restart -r docker --node <exact-topology-node-name> -t <trusted-topology-path>
```

Containerlab documents this as a lifecycle-aware stop/start that parks and restores dataplane interfaces. A stopped node takes the start/restore path. An omitted `--node` selects the entire lab. Its documented limits include non-veth links, root-namespace nodes, auto-remove, multi-container nodes, and shared container network namespaces. Re-check these details against the installed CLI and the selected extension revision before implementation; record the versions and behavior tested.

**Use the native node-scoped Containerlab restart operation. Do not substitute plain `docker restart`, an SSH `reboot`/NOS reboot, destroy+deploy, redeploy, or a whole-lab restart.** These are not interchangeable acceptance paths. Do not bypass link preservation by manually reconstructing Containerlab wiring. Preserve native behavior rather than implementing a second lifecycle engine.

Behavioral parity means matching node selection, lifecycle, wiring recovery, and restart semantics. Present it through the manager's own UI, review, permissions, and job conventions; do not copy an extension security boundary or remove the manager's established safeguards for visual similarity.

### B. Product scope and discoverability

Make this a normal **device lifecycle action**, usable whether or not a lab has a netlab design. A missing netlab engine, unsupported routing module, absent NOS backup driver, or failed SSH login must not by itself disable a valid Containerlab restart. Restarting an unresponsive device is a primary use case.

Expose one shared action through:

1. The topology map's existing device right-click/context menu.
2. The existing per-device actions in the Devices view or device rail/card, following the actual UI structure.

Both entry points must use the same eligibility, target identity, review, execution, and feedback logic. Make the non-map path keyboard accessible. Do not create a competing management page, add unrelated stop/pause/rebuild features, or change what the existing lab-wide Restart action means.

Label the node action **Restart device** or an equally unambiguous existing product term. Name the exact device and lab in the review and job output. Clearly separate it from Restart lab, Redeploy, Reset, and Apply configuration. Reuse the product's reviewed operation dialog; one deliberate confirmation is sufficient unless an existing safety contract requires more. Cancel means no operation and no device mutation.

The review must explain that the chosen device will be interrupted, its sessions/traffic may drop, and unsaved configuration may not survive. It must not claim that unrelated traffic cannot be affected: neighboring adjacencies or transit paths can depend on that device even though those other containers are not restarted.

Do not silently save running configuration, create/push a Git snapshot, reset configuration, restore a backup, or reapply network intent as part of Restart. Preserve whatever the native lifecycle and the image's existing persistence mechanism do. An optional suggestion to use an existing save workflow is not permission to make saving an implicit side effect or prerequisite. A configuration backup and saving startup configuration are different operations.

### C. Restricted backend execution and exact single-node targeting

Trace and extend the current lifecycle path: `lab_operations.py`, `host_operations.py`, gateway/protocol definitions, capability responses, preview/review binding, job storage, discovery/readiness, UI actions, installer/helper refresh, and associated tests. At the inspected manager ref `0cac864e2efed3e7b21973277763db8a1f2eda09`, the host helper's lifecycle builder was lab-scoped and its options allowlist did not include a node selector. Check current code rather than assuming the UI can safely pass a new flag through unchanged.

Keep the manager container unprivileged and without a Docker socket. Use the existing structured SSH gateway and restricted host helper. Preserve its fixed-argv/no-shell, trusted-path, same-release, output-scrubbing, and stdlib-only host-code conventions. An installed CLI upgrade needed on this development VM is already authorized; do not solve an old CLI by granting the product arbitrary host commands.

Design a typed single-device request. The server resolves the selected manager lab/node to its trusted topology, runtime, literal topology node name, and current container identity. Never trust a browser-provided command, path, runtime override, arbitrary container ID, or ambiguous display label as authority.

At review and again before mutation:

- Verify that the node belongs to that deployed lab and that the lab is associated with the intended trusted topology; handle configured name/prefix overrides deliberately.
- Bind the review to the specific node, lab, topology revision and deployment/container identity. Refuse an approval after a destroy/redeploy, identity substitution, or relevant topology change; do not retarget silently.
- Require exactly one nonempty, valid selector for this single-device action. Reject absent/null/blank selectors, arrays, duplicate selectors, comma-separated node lists, option-like input, and anything that could broaden scope. Preserve legitimate names using safe literal arguments and verified topology lookup, not shell escaping guesses.
- Construct exactly one `--node` argument and one resolved node value. Assert this invariant in backend and host-helper tests. A missing selector must fail closed; it must never fall through to the pre-existing lab-wide `restart` path.
- Populate the review's affected-device list with only the selected device; do not merely add `--node` to a preview that still announces the whole lab.

Discover the installed CLI's `restart` and node-selection support and relevant node limitations. Use capability-aware explanations for unsupported targets or versions. Refresh capabilities after upgrades/helper changes. If a deployed lab cannot be associated safely with its topology/runtime, explain the missing information and refuse without mutation. Do not guess from a similarly named lab or use a whole-lab fallback.

For absent, removed, paused, auto-remove, shared-network, root-namespace, multi-container, or otherwise unsupported states, verify native eligibility and show the precise result. Do not quietly unpause, recreate, widen scope, or invent support. A stopped deployed single node must follow the reference's supported start/restore behavior rather than being blocked just because its container is not running.

### D. Jobs, concurrency, uncertain outcomes, and readiness

Integrate with the existing operation guards and persisted jobs. Do not race with deployment/destruction, snapshot restore, configuration apply, Git capture, backups, or another conflicting node operation. Preserve current conservative serialization until narrower locking is justified and tested; do not introduce a new queue framework just for Restart. Known active manager-owned confirmed-commit/recovery transactions must not be silently interrupted. Do not require successful NOS SSH as a blanket precondition for recovery via restart.

Disable duplicate actions immediately while submission is in flight and deduplicate repeated requests on the backend. Treat two tabs, two entry points, and repeated confirmation clicks as the same concurrency problem. If the helper channel or browser loses the response, the outcome is unknown until reconciled; do not automatically run Restart again. Keep an operation/request identity and enough execution/state evidence for safe reconciliation. Do not claim exactly-once execution merely because the frontend disabled its button.

Keep runtime operation completion separate from device readiness:

```text
Review → request accepted/queued → restarting → container running / NOS booting
       → fresh readiness proof → ready
```

These are conceptual states to integrate into the existing vocabulary, not a mandate for a new independent state machine. Expose failed, interrupted/unknown, and not-ready-with-diagnostic outcomes too. A successful CLI exit is not proof that the NOS can accept commands.

Invalidate the target's prior readiness, automatic login-test success, and active-session assumptions when a restart is accepted. A restart may keep the same container ID and complete between discovery polls; do not depend solely on seeing an intermediate stopped state. Use an explicit restart/boot epoch or equivalent current-runtime evidence, and reject delayed readiness results from before that epoch. Handle restarts initiated externally through VS Code/CLI without stale permanent green status as far as the existing discovery data allows.

Trigger timely discovery and fresh readiness probing, with image-appropriate bounded budgets and useful diagnostics. Junos and XR boot duration must not be confused with HTTP request duration. A device without a NOS driver may be reported as container running/SSH availability unknown, not falsely NOS-verified. Preserve old failure information as history while identifying what is happening now.

Other devices keep their own state, sessions, and readiness checks. Aggregate lab counts and topology statuses must reflect the targeted restart without treating the entire lab as destroyed or deployed again. Keep the selected lab/device stable as the UI refreshes.

Existing terminals for the target must show disconnection and a usable reconnect path; never replay previously typed commands on reconnect. Invalidate target-specific capture handles as necessary and require fresh interface/runtime resolution for new capture sessions, without tearing down unrelated capture sessions. Distinguish closing a progress dialog from cancelling an operation: once native stop/start has begun, do not pretend dismissing the dialog cancels it or terminate it mid-transition without a proven safe recovery contract.

### E. Network-design and configuration invariants

Restart must work for labs with no design, valid/stale/failed designs, unsaved browser drafts, and unavailable netlab engines. It must not mutate intent, allocation ledgers, generated artifacts, topology YAML, annotations, credentials, management addressing, image selections, port mappings, Git history, or saved progress as an added side effect.

Do not automatically regenerate or apply netlab configurations after restart. Preserve historical generation/application evidence, but do not reuse an old live-verification badge as evidence of post-restart convergence. Where the product reports current device health, mark it unknown/booting until freshly checked; do not label immutable design artifacts stale solely because a container restarted when their inputs did not change.

Test persistence with a deliberately saved marker and an unsaved-only marker where the NOS supports that distinction. Record actual results per image and reference route. Never promise universal preservation of unsaved running configuration or silently add configuration saving to make a persistence test pass. Distinguish expected image behavior from integration defects.

### F. Mandatory parity, isolation, and failure tests

Extend the campaign inventory with stable `NODE-RESTART-*` coverage IDs. Add unit/helper/API tests, real browser tests, and live-device evidence. Register new offline tests in the actual explicit CI lists. At minimum:

| Test | Evidence required |
|---|---|
| Map menu and Devices/rail action | Real clicks on each entry point; same exact target, eligibility, review, job, and visible recovery |
| Cancel before confirmation | No helper mutation, unchanged target runtime, no configuration/save side effects |
| One running target | Native scoped command, observed restart epoch, fresh readiness, functioning NOS session afterwards |
| One stopped deployed target | Reference-compatible start/restore and recovered dataplane interfaces |
| SSH-unresponsive or booting target | Recovery action is not incorrectly gated by login readiness; honest bounded outcome |
| Missing/invalid/cross-lab node or unsafe selector | Server/helper rejection before execution; never all-node fallback |
| Stale review after redeploy/rename/substitution | Approval rejected; the newly resolved device is not restarted under stale consent |
| Duplicate clicks/tabs and conflicting operations | No duplicate disruptive work; clear busy/reconciliation behavior and restored controls |
| Browser/helper disconnect, timeout, manager restart | Persisted job history, no blind replay, truthful unknown/failure and successful reconciliation |
| Delayed readiness response or missed down interval | Old probe cannot mark the restarted device ready; fresh epoch-aware proof is required |
| Old CLI, helper mismatch, unsupported topology/node | Precise error or disabled reason; no Docker/SSH/redeploy workaround disguised as parity |
| Netlab and adjacent workflows | Design drafts, plans, files, Git, backup/restore, map and lifecycle behavior remain correct |

Run live restart testing sequentially against **each of the four existing baseline images**, exactly one instance of each, retaining the resource constraints in §12. Exercise both UI entry points across the set. For every image compare against the same native command used by the extension from an equivalent baseline. When the extension UI is available, perform at least one actual extension-originated restart and document its version; if only the source/CLI reference is exercised, state that distinction rather than inventing a VS Code UI run.

Capture before/after container IDs and start epochs, selected and non-selected device uptimes, link endpoints, dataplane interface presence, management reachability, and relevant configuration/adjacency/traffic evidence. The intended target should restart; unrelated containers must retain their identities/start epochs and must not receive lifecycle commands. Do not use a Docker restart counter alone as the oracle. Do not require Linux interface indices or transient handles to remain numerically identical if the native operation legitimately changes them; prove endpoint mapping and usable wiring instead.

In the square, verify traffic that crosses the target recovers and traffic on a path not depending on it continues where topology permits. Neighbors may legitimately lose adjacencies to the restarting target; that is not proof they were restarted. Confirm IPv4/IPv6 reachability and relevant routing restoration only when the pre-restart lab configuration and image support those checks. For a blank lab, use an explicit minimal test configuration and record it.

For each baseline image prove at least a running-node restart and the supported stopped-node recovery path, then a repeat restart after recovery to catch leaked lifecycle/parking state. Verify map/rail counts, terminal reconnection, and a new capture where supported. Use fixtures for broad timing permutations, not scores of gratuitous reboots of heavy NOS images. Record actual command failures or image limitations as such, investigate them, and never relabel an unexecuted scenario a pass.

### G. Delivery and acceptance integration

Implement in coherent tested chunks: reference/capability/target contract; restricted node lifecycle path; shared UI and readiness/recovery integration; live parity and adverse tests. Adapt chunk boundaries to existing code; avoid exposing an incomplete destructive action. Use the same Fable orchestration, task-appropriate agents, unrestricted development-VM authority, and tested **+0.0.1 / commit / push / remote verification** rules as the rest of this campaign.

Independent high-risk review must cover selector fail-closed behavior, helper permissions, stale identity, duplicates/replay, locking, and readiness epochs before final acceptance. Both clean final acceptance passes must include Restart device, the repaired restart bug reproducers, and adjacent netlab workflows on the same final build. A defect in this feature invalidates a clean pass just like a netlab UI defect.

Add a compact parity record to the campaign evidence: extension ref/version; Containerlab version/runtime; exact reference command; supported state matrix; per-image results; deliberate manager-UI differences such as review/readiness reporting; and any blocked case. The final report must explicitly state **Implemented: individual-device restart**, its UI paths, validation and remaining limits. Source review or a clickable button alone does not fulfill this requirement.

## 8. Visual, interaction, and accessibility quality

Conduct a deliberate novice-user walkthrough before consulting source for the happy path. Ask of each screen: What can I do here? What should I do next? What is saved? What will change? Which devices are affected? What went wrong? How do I recover? Repair unnecessary confusion, not just thrown exceptions. This is an agent-led usability review, not a substitute for claiming actual student user research.

Test ordinary typing, paste, mouse, keyboard-only operation, touch-sized interaction, and zoom. Inspect visual hierarchy, spacing, labels, terminology, field grouping, primary/secondary/destructive action emphasis, table density, empty states, and progress/error placement. No ambiguous duplicate actions, unlabeled icons, misleading “ready” labels, unexplained disabled controls, or essential instructions available only on hover.

Use desktop and constrained sizes: 1920×1080, 1366×768, approximately 1024×768 and 768×1024, and 390×844 CSS pixels. Add the actual breakpoints and 200% zoom. Test every supported theme rather than adding a new theme. Allow deliberate inner scrolling for wide technical tables/configuration, but not clipped controls, inaccessible dialogs, or unexplained whole-page horizontal overflow. A shell overflow is not permission to hide a netlab usability defect.

Run the complete primary browser suite in Chromium and core workflows in Firefox and WebKit where installable on the VM. Record actual browser versions. Do not claim a Linux WebKit run tested a physical iPhone or a branded browser/OS you did not use. Install missing test dependencies where feasible; a genuinely unavailable browser remains an explicit coverage gap.

For every menu/dialog verify focus entry, focus containment when appropriate, keyboard order, Escape behavior, close/cancel controls, background interaction, scroll locking, return to the invoking control, and narrow-screen sizing. Check forms for accessible names, associated validation messages, required-state communication, focus visibility, and a sensible route to the first error. Ensure dynamic progress/errors are announced without excessive repetition.

Inspect labels and semantics for repeated per-device controls, tables/headings, code previews, and statuses. Do not convey important meaning by color alone. Use automated accessibility scanning with targeted manual/agent-driven keyboard and visual checks. Fix identified actionable issues; do not suppress scanner rules or exclude the whole feature to create a green report.

Preserve the product's existing architecture, visual conventions, CSP, and accessibility contracts. Make focused UI improvements; no framework migration, wholesale redesign, vendor-bundle hand edits, or removal of useful information just to make screenshots cleaner.

## 9. Stress, race, longevity, and performance passes

Use repeatable, seeded sequences and record the seeds. Include at least:

- 25 repetitions of the core edit → save → generate → inspect → download → reload loop, including transitions between two distinct lab identities. Compilation-only labs can share no running NOS resources.
- 20 repetitions of each repaired high-risk race, with controlled variations in response order and delay. A single lucky pass does not close a race defect.
- 100 mixed navigation/dialog/edit actions in one browser session, checking active request counts, listeners, polling, console errors, rendering stability, and retained drafts.
- A 30-minute mixed-use/idle-return observation while performing other campaign work, including background-tab return and network recovery. Actually run it during this assignment; do not promise future monitoring.

These are minimum empirical probes, not proof of exhaustive timing coverage or a replacement for deterministic regression tests. Bound expensive device-changing repetitions separately and justify the count; do not repeatedly reboot heavy NOS images when the relevant state race exists in the UI/backend.

Use empty, typical, and larger synthetic lab records for render/generation testing, without deploying dozens of heavy routers. Include long permitted identifiers, many interfaces/rows, large generated files, and enough generations to exercise the actual retention limit and its boundary. Test resource limits on both sides, without causing unbounded memory/disk use.

Measure interaction responsiveness separately from compiler/device work. Capture timings for tab entry, typing, module toggles, save acknowledgement, generation progress updates, file preview, and history rendering. Establish practical baseline-informed budgets and explain regressions. The UI should acknowledge a click promptly and stay usable while slower work proceeds; do not hide latency with fabricated progress or caching that shows the wrong revision.

Inspect growing requests, timers, event listeners, DOM nodes, memory, jobs, temporary directories, and generation artifacts. Stop hidden-page polling where appropriate without breaking recovery. Use evidence of a leak or performance regression, not arbitrary optimization, to choose repairs.

## 10. Security and data-integrity tests tied to UI actions

Test untrusted text in allowed labels, device names, errors, previews, filenames, and imported intent. Rendering must not execute HTML/JavaScript or expose private paths, credentials, keys, or other labs' data. Use harmless test markers and synthetic credentials, not real secrets in public evidence.

Exercise cross-lab/generation/file identifiers, encoded traversal, malformed requests, refused executable netlab settings, and missing/stale confirmation tokens where applicable. Browser controls and server checks must agree; disabling a button alone is not authorization or validation. Do not broaden accepted input, shell execution, file permissions, or privileged host access as an expedient repair.

The real compiler, not a mocked response, must retain its data-only input boundary, private per-job work area, timeout/cancellation behavior, and no-device-write guarantee. Preserve immutable artifacts and integrity verification. Broken checksums must yield an honest recoverable failure, not silently regenerate a different file under an approved identity.

Review evidence before committing it. Browser traces, HAR, screenshots, downloads, logs, and test configuration can contain secrets. Keep private raw evidence outside Git; commit only sanitized artifacts and indexes, with useful reproducible details. Never remove the evidence needed to diagnose an unresolved defect while cleaning disk space.

## 11. Defect handling and root-cause repair

For each finding record:

```text
Bug ID and severity | affected coverage IDs | build/browser/lab identity
Exact setup and steps | expected result | observed result | reproducibility
Screenshot/trace/log/artifact evidence | data/device/security impact
Root cause | files changed | regression test | deployed build
Author retest | independent retest | final disposition
```

Severity guides order, not whether a valid defect matters:

- **P0:** wrong-lab/device mutation, serious data/credential exposure or loss, unsafe application/recovery.
- **P1:** broken core task, silent semantic data loss, false success, inaccessible required control, unrecoverable state.
- **P2:** meaningful workflow, validation, accessibility, race, error/recovery, or performance defect.
- **P3:** reproducible visual, copy, feedback, or interaction polish that materially reduces clarity or consistency.

Fix all reproducible actionable in-scope findings, including P3 polish. Do not automatically defer something as “cosmetic.” Equally, do not invent defects to meet a quota or relabel a correct designed limitation as a bug. Explain disputed expectations and use observable requirements to resolve them.

For every confirmed bug:

1. Preserve the smallest reproducer and evidence. Add a failing automated regression where feasible.
2. Trace the root cause through UI, state, API, engine, and persistence as needed. Fix the correct layer.
3. Test the original failure, neighboring inputs/states, and the same defect class elsewhere.
4. Rebuild/deploy the real app and repeat the original user path, including reload and artifact verification.
5. Have an independent agent verify high-risk repairs and all proposed bug closures during acceptance.

Do not paper over defects with longer sleeps, forced clicks, blanket catches, unconditional reloads, silent defaults, clearing user data, disabling checks, reducing capabilities, hardcoded successful results, or deleting failing tests. Do not auto-accept visual snapshots after a regression. Expected-output changes require a justified behavior improvement, not convenient test appeasement.

Do not build a vast test framework before repairing obvious blockers. Alternate useful coverage expansion with small verified fixes. Parallel agents may investigate different areas, but must not overwrite each other's fixes or independently rebuild the shared runtime.

## 12. Live environment and test resources

Preserve the four-image interoperability baseline, one of each:

| Image | Containerlab kind |
|---|---|
| `n24l/ceos:4.35.0F` | `arista_ceos` |
| `n24l/cjunosevolved:26.2R1.7-EVO` | `juniper_cjunosevolved` |
| `n24l/vjunos-switch:23.2R1.14` | `juniper_vjunosswitch` |
| `n24l/cisco_xrv9k:24.3.1` | `cisco_xrv9k` |

Reuse or repair the existing square acceptance lab and its tools after inspecting actual state. Do not silently substitute XRd for XRv9k or vJunos Evolved for cJunosEvolved. Verify the correct NOS is ready, not merely that its container runs. Use direct NOS SSH for required independent read-back.

No duplicate heavy labs are needed for cross-lab UI tests: use lightweight/scratch lab records or serialize physical-lab work. Preserve runtime evidence when a device fails to boot; diagnose and repair the development setup before declaring live validation unavailable. Resources, platform limitations, and unfinished product capabilities are distinct categories.

Keep the existing shipped security boundaries, device identities, credential precedence, operation locking, restore semantics, and secret scrubbing. Leave telemetry/Grafana retired. Do not change the student guide in this campaign; update focused technical, maintenance, validation, changelog, and handoff documentation instead.

## 13. Incremental execution and checkpointing

Work in these phases, with small tested repairs throughout rather than one enormous final diff:

**A — Baseline and map.** Verify runtime/source identity, baseline tests, feature scope, control inventory, state model, and risk charters. Preserve the current usable build.

**B — Core journeys and data safety.** Attack draft/save/generate semantics, advanced/guided preservation, cross-lab identity, download correctness, and obvious blockers first.

**B2 — Required single-device restart.** Implement §7.13 through the native Containerlab lifecycle, exact-target restricted helper, shared device actions, readiness and recovery integration. Test platform parity and protect all current workflows. Run non-conflicting netlab investigations in parallel; do not leave this requirement until after acceptance.

**C — Full surface and adverse conditions.** Exercise every inventoried control, conditional state, error path, history/import/export/destructive action, supported module path, applicable apply workflow, and the new Restart device workflow.

**D — UX quality and stress.** Perform novice-task, keyboard, visual, responsive, cross-browser, race, persistence, and longevity passes. Fix the resulting issues rather than merely collecting screenshots.

**E — Independent acceptance.** Re-run coverage and adjacent regressions against the final installed build; complete both independent clean passes described below.

For every coherent completed code-change chunk:

1. Review and test the intended changes, including a regression for each fixed bug.
2. Increment the **current patch version by exactly +0.0.1** using the repository's `deploy/set-release.py` tooling. Never assume the old starting version is current.
3. Update required version markers, cache-busted assets, changelog, validation records, and pickup notes using repository conventions.
4. Run relevant Python, JavaScript, static, release, browser, and live checks. Rebuild the manager and refresh matching helpers as required; confirm the browser is using the new assets.
5. Commit only the intended files, push the working branch, and verify the expected remote commit exists. Check relevant CI results and fix campaign-caused failures. No force-push or automatic merge into main without authorization.
6. Record version/commit, deployed identity, fixed bugs, coverage added, actual tests, remaining failures, effective agent routing, and next exact action.

Do not batch the entire campaign into one unpushed change. Do not create fake release bumps for individual clicks or reruns; checkpoint coherent tested repairs. Preserve intentionally untracked/local files and any required Git-account context. Never run blanket staging without reviewing the paths.

Use current repository commands, not invented equivalents. The existing conventions include:

```bash
# From clab-backup-ui, using the prepared environment:
PATH="$PWD/.venv/bin:$PATH" .venv/bin/python -m unittest discover -s tests -t tests
node --test tests/*.js

# From repository root:
python3 deploy/verify-release.py
git diff --check
```

Read current instructions for browser commands, explicit CI registration, helper refresh, build tools, and installed-product health checks. Register new tests in CI; a test file that never runs is not ongoing regression protection. Keep opt-in live tests clearly separated from offline CI requirements.

## 14. Acceptance gates — do not stop early

The campaign is complete only when all of these gates are satisfied:

1. **Inventory closure:** every implemented netlab surface plus the new individual-device restart surfaces, controls, conditional components, and enumerated supported state transitions is accounted for with evidence. No unexplained gaps, presence-only “passes,” or unsupported-feature inflation.
2. **Workflow closure:** all implemented core user journeys succeed through the real UI with correct backend/persisted outcomes, meaningful downloads, and reload/recovery proof. Individual-device restart is implemented and validated against the reference lifecycle on the four baseline images, with the single-target, stopped-node, link-recovery, configuration-persistence, fresh-readiness, and failure evidence in §7.13. Unsupported native cases remain explicit and cannot be counted as successful restarts. Platform configuration application is live-verified only where actually implemented and supported.
3. **Defect closure:** zero known unresolved actionable P0/P1/P2/P3 netlab or individual-device-restart defects in the tested scope. Every closed defect has reproduction and repair evidence; disputed/non-defect outcomes have a reason. Genuine external blockers remain BLOCKED and prevent an unqualified completion claim.
4. **Integrity closure:** no silent draft loss, unintended advanced-field loss, wrong-lab/generation data, stale approval, misleading success, secret exposure, or unintended device/topology/Git mutation in the tested paths.
5. **UX closure:** every action has clear feedback, disabled states explain prerequisites, errors have recovery paths, and required tasks are usable by keyboard and at tested sizes. Visual polish is reviewed rather than inferred from no console errors.
6. **Regression closure:** existing manager functionality and safety contracts remain intact. Tests are not weakened; new regressions run in CI. The installed image/helpers/assets correspond to the intended source.
7. **Repeated clean acceptance:** two consecutive clean acceptance passes against the same final application build and test-suite revision, led by independent reviewers. Pass one follows the coverage map with fresh state; pass two uses fresh browser contexts, warm/returned sessions, different action order, and adversarial state transitions. Both include core journeys, the new Restart device workflow, known-bug reproducers, downloads/persistence, and adverse cases; restart evidence must match the final build and preserve its single-node boundary. A new failure resets clean-pass counting after repair; there must not be an untested code change after the final pass.
8. **Delivery closure:** coherent patches are committed, pushed, and verified; evidence and pickup records are accurate; the development product is left usable with no abandoned fault injection, unknown pending device transaction, or misleading success report.

Do not declare the campaign complete because tests hit a numerical target or because a reviewer found no issue in a brief look. The repetition counts are floors; the coverage and defect gates decide completion.

If execution is interrupted by an actual context/usage/tool limit, finish the safe current step, preserve user work and evidence, checkpoint coherent tested changes, mark remaining coverage honestly, and leave exact continuation instructions. Do not relabel an interrupted campaign “complete.” Do not stop voluntarily after writing the plan or tell the owner to perform routine authorized testing instead.

## 15. Final report

Provide an evidence-backed engineering handoff, not a congratulatory summary:

- Source/branch, installed release/image/helpers/assets, engine and browser versions, and verified remote commits.
- What was tested: counts for surfaces, controls, workflows and transitions, with PASS/FAIL/BLOCKED/NOT RUN/N/A separated and the denominator defined.
- Defects found by severity and repaired behavior, with root cause, regression test, build, and independent retest references.
- Important before/after UI evidence, actual download/persistence checks, and live NOS evidence where applicable.
- The delivered individual-device restart action, both entry points, reference extension/CLI versions and command, per-image parity, non-target isolation, link recovery, startup/running configuration behavior, readiness/session recovery, and any unsupported native cases.
- Cross-browser, responsive, accessibility, stress, latency, interruption/recovery, and adjacent-regression results.
- Honest implemented-versus-unavailable capabilities and any unresolved external limitation; never equate generated with applied.
- Exact reproduction/test commands, evidence locations, and proof of the two clean acceptance passes.
- **Intentionally removed functionality: None.** Explain any targeted UX change; telemetry/Grafana remains retired.

Use a precise conclusion such as “No known unresolved defects within the enumerated and tested scope” only if the evidence supports it. Do not claim every possible interaction, real user, browser, or platform has been proven flawless.

**Begin now with runtime verification and parallel reconnaissance, then implement the required single-device restart and test and repair continuously. Do not wait for approval of a plan. The assignment is to deliver the new device action and make the netlab experience reliable, understandable, and difficult to break—not merely to describe how someone else could build or test them.**

---

## Source anchors for the prompt author’s preliminary review

These anchors establish why the targeted probes are included. They are not evidence that Claude has already executed the new campaign. Inspect current code before relying on historical observations.

Repository ref inspected: `0cac864e2efed3e7b21973277763db8a1f2eda09`.

- `docs/netlab-integration/PICKUP.md`: initial implementation milestones, previous baseline, VM and routing observations.
- `docs/NETWORK-DESIGN.md`: implemented Design workflow, intent/persistence/API and generation-only boundary.
- `app/static/network-design.js` under `clab-backup-ui/`: `designIntentFromForm`, `designFormFromIntent`, `designLoadPlan`, polling, rendering, saving, generation, import/export, destructive dialogs, and file preview.
- `clab-backup-ui/app/network_design.py`: generation/service state and non-device-mutating compiler boundary.
- `docs/netlab-integration/evidence/browser-design-ui.md`: prior fixture-browser checks; some checks assert presence or link identity rather than complete user outcomes.

Primary browser-testing references, checked when drafting; use documentation matching the installed test framework:

- https://playwright.dev/docs/best-practices
- https://playwright.dev/docs/accessibility-testing

The campaign requirements, repetition counts, priorities, and acceptance gates above are requirements for this assignment, not claims that an external standard mandates them.


### Additional source anchors: individual-device restart

Reviewed for this amendment on September 27, 2026; these are source/documentation findings, not a live test of the user's VM. Re-verify the installed software and current checkout during execution.

- Extension ref: `6df8e9629a0dfca625d162498aa976d49845a342`; `package.json` reports `0.26.3`.
- `src/commands/nodeActions.ts`: selected-node name/path resolution and `restart` with `--node`.
- `src/commands/clabCommand.ts`: runtime, topology and command argument construction.
- Containerlab's restart command documentation: lifecycle-aware interface handling, stopped-node behavior, selector scope and supported-node limits.
- Manager ref: `0cac864e2efed3e7b21973277763db8a1f2eda09`; `clab-backup-ui/app/host_operations.py`, particularly `plan` and its lifecycle/options validation, as the existing extension point to examine.

```text
https://github.com/srl-labs/vscode-containerlab/blob/6df8e9629a0dfca625d162498aa976d49845a342/src/commands/nodeActions.ts
https://github.com/srl-labs/vscode-containerlab/blob/6df8e9629a0dfca625d162498aa976d49845a342/src/commands/clabCommand.ts
https://github.com/srl-labs/vscode-containerlab/blob/6df8e9629a0dfca625d162498aa976d49845a342/package.json
https://containerlab.dev/cmd/restart/
https://github.com/ArchRuger/CLAB-BACKUP-WORKER-v2/blob/0cac864e2efed3e7b21973277763db8a1f2eda09/clab-backup-ui/app/host_operations.py
```
