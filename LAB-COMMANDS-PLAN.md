> Approved by the user and implemented in 1.11.0. See [LAB-OPERATIONS.md](LAB-OPERATIONS.md) for delivered behavior, prerequisites and validation limits. The original proposal is retained below.

# Proposed lab-level Containerlab controls

Scope agreed: lab-level actions only. This document is a proposal; no command
execution or host permissions have been changed. Existing individual node actions,
interface capture, link impairments and image management are outside this change.

Reference checked: upstream VS Code extension package manifest, version 0.26.3,
on 2026-09-10:
https://github.com/srl-labs/vscode-containerlab/blob/main/package.json

## Command coverage

| Area | Planned browser behavior |
|---|---|
| Lifecycle | Deploy, deploy with cleanup, redeploy, redeploy with cleanup, destroy, destroy with cleanup; apply edited topology where the installed version supports it |
| Whole-lab runtime | Start, stop and restart the lab's nodes; inspect the selected lab or all labs |
| Configuration | Containerlab configuration save for the lab, with kind/version support shown; existing manager backups remain available |
| Access | Launch SSH sessions for all supported lab nodes through a session launcher that accommodates browser popup restrictions |
| Files and workspaces | Edit YAML, create a topology, copy its VM path, favorite a lab, import/link a workspace, browse its folder in a new tab, and separately delete an undeployed source YAML |
| Drawing | Existing map viewing plus a topology editor and draw.io horizontal/vertical generation and interactive browser equivalent |
| Lab acquisition | Select an existing VM topology, clone a repository, or select a popular lab; show network/image prerequisites for airgapped hosts |
| Sharing | SSHX and GoTTY session creation, removal, reconnection and link copying; explicitly enabled and dependency/configuration gated |
| SR Linux utilities | fcli views for BGP peers/RIB, IPv4 routes, LLDP, MACs, network instances, subinterfaces and system information, plus a custom query; available only with compatible labs and installed prerequisites |

Editor-specific commands receive browser equivalents; VS Code windows themselves
are not launched. This is the command inventory to track through implementation,
not a claim that all commands are presently supported by Node Manager.

## UI and execution

1. Add a Lab actions menu to the lab header and lab sidebar context menu. Group
   routine lifecycle controls separately from file removal and cleanup variants.
2. Present an operation review showing the selected lab, resolved VM source path,
   affected containers, options and expected consequences. Require confirmation
   for operations that interrupt or remove a deployment or change source files.
3. Add persistent operation records and a live output panel with queued/running/
   succeeded/failed/interrupted states and exit codes. Prevent conflicting lab
   commands, backups and synchronization from running against the same lab.
4. Refresh discovery after completion. Preserve saved manager workspaces when a
   deployment is stopped or destroyed. Existing Remove lab remains manager-only;
   deleting a VM topology is a distinct, clearly named operation.
5. Use the original VM project directory for deployed topologies so relative
   startup configurations, binds and scripts resolve correctly. For manually
   imported YAML with no VM path, require association with a VM project or a
   complete project upload before offering deployment. A YAML snapshot alone is
   not sufficient to reconstruct referenced project files.
6. Keep source YAML editing separate from Apply/redeploy. Validate changes, preserve
   a recoverable original, and show a diff before replacing a VM file. Capabilities
   and options depend on the actual installed Containerlab version.

## Host integration

The existing discovery SSH key is forced to a read-only command. Add a versioned
host operations helper using structured requests, a fixed action registry, validated
paths and bounded options. Extend the existing setup/upgrade entry point to install
and verify this capability, with a deliberate enable step for lab operations.
Retain existing discovery credentials where feasible; do not require unrestricted
SSH shell access or mount the Docker socket in the manager.

Lifecycle support permits privileged work on the host: Containerlab topology files
can reference host mounts and execution hooks. Only trusted project files should
be eligible for deployment. A fixed command registry prevents shell injection; it
does not make an arbitrary topology harmless. Show the actual project selected in
the operation review and scope operations to that lab.

Sharing and remote repository/image downloads must remain opt-in for the airgapped
environment. Missing optional packages or unsupported commands should display a
specific prerequisite rather than a button that only fails after invocation.

## Behavior distinctions to retain

- Stopping nodes retains containers. Destroying a lab removes its deployment.
- Cleanup can remove generated lab-directory contents; confirmation must name the
  affected directory. See https://containerlab.dev/cmd/destroy/.
- Containerlab save uses kind-specific save support and is not equivalent to the
  manager's versioned configuration backup. See https://containerlab.dev/cmd/save/.
- Commands shown by the extension may be absent from an older host binary; detect
  supported flags and provide compatibility feedback, especially for Apply.

## Validation and delivery

Test action selection, request/path validation, confirmation binding, queue conflicts,
stale discovery, output bounds/redaction, disconnect recovery and saved-data retention.
Exercise menu/confirmation/output flows in the browser with synthetic host fixtures.
Verify source ZIP, patches and updated installation/upgrade instructions. Actual
Containerlab lifecycle validation requires a disposable Linux lab; do not use the
user's training deployment as a destructive test target without a specific request.
