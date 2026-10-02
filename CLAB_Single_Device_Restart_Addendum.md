# Claude Code addendum: implement single-device restart; preserve the full netlab QA campaign

This addendum supplements `CLAB_Netlab_Relentless_UI_UX_QA_Campaign.md` when that campaign is already underway. It is incorporated into `CLAB_Netlab_Relentless_UI_UX_QA_Campaign_v2.md`; do not execute it as a second independent workstream if you already read revision 2.

The owner explicitly authorizes this additional feature. Keep the full relentless netlab UI/UX repair campaign, Fable 5.1 orchestration, task-appropriate agents, unrestricted isolated development VM with bypass permissions already enabled, no existing-functionality regressions, and tested +0.0.1 commit/push/verified-remote checkpoints. Do not restart the whole audit from scratch; preserve existing progress and add this feature to the coverage inventory and final acceptance gates.

Implement, deploy, and validate the feature below even if absent at baseline. This explicit requirement overrides the campaign's “test existing implementation only” boundary solely for individual-device restart. It does not authorize unrelated feature expansion or relaxing shipped permissions and reviews. All requirements below are additive.

## Required new feature — individual-device restart with Containerlab VS Code parity

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


## Integrate into the existing campaign

Add implementation chunks for the selector/capability contract, restricted helper path, shared UI and readiness/recovery, then live parity and adverse cases. Both final clean acceptance passes must include this feature on the same final build. Include restart defects in the same P0–P3 ledger; no unresolved actionable restart defect may be excluded from completion merely because it is not a netlab compiler defect.

The final report must state what was delivered, where the user clicks, the actual extension/CLI versions and reference command tested, per-image results, single-target/link preservation evidence, persistence and boot-readiness results, commits, and any genuine limitation. A button that calls the wrong restart mechanism is not parity; a CLI exit without fresh readiness/link evidence is not complete validation.

Continue the existing campaign now. Implement and prove this addition without dropping any previous requirement.


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
