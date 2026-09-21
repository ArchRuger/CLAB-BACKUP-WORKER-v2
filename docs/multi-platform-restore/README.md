# Replace running configuration: platforms, semantics and acceptance record

What *Replace running configuration* does on each supported network operating system, which exact
images it was proven on, how it recovers, and how to rerun the proof. The student-facing description
is in [GIT-PROGRESS](../GIT-PROGRESS.md) and [LAB-OPERATIONS](../LAB-OPERATIONS.md); the work log and
the state of the acceptance lab are in [PICKUP](PICKUP.md). This file is a dated acceptance record:
it claims support only for what was run, on the images named here.

## What "replace" means

The saved configuration becomes the active one, and anything configured after the save is removed.
A paste or a merge of saved commands over the current configuration is not a restore. Every driver
therefore uses the NOS's own whole-configuration transaction, arms the NOS's own timed recovery before
management can be lost, and the manager confirms from a **fresh** SSH connection (which is the proof
that management survived). Devices are not rebooted. Nodes are applied one after another: there is no
atomicity across nodes, and a mixed result is reported per node.

| | Junos (cJunosEvolved, vJunos-switch) | Arista cEOS | Cisco IOS XR (XRv9k) |
|---|---|---|---|
| Restore artifact | `show configuration` (hierarchical), `.jcfg`, format `junos-hierarchical`: a second capture | `show running-config`, `.eoscfg`, format `eos-running-config`: the backup's own text, one capture | `show running-config`, `.xrcfg`, format `iosxr-running-config`: the backup's own text, one capture |
| Replacement | `configure exclusive`, `load override terminal` | `configure session <token>`, `rollback clean-config`, `copy terminal: session-config` | `configure exclusive`, the saved configuration entered into the (empty) target configuration, then `commit replace …` |
| Review diff | `show \| compare` | `show session-config diffs` | `show configuration changes diff` (`show commit changes diff` is a merge preview and misleads) |
| Validation | `commit check` | the session commit itself; any `% ` line during the load rejects the candidate | per line while entering; any `% ` line that is not a warning rejects the candidate; the commit itself |
| Timed recovery | `commit confirmed <minutes> comment <token>` | `commit timer HH:MM:SS` | `commit replace confirmed minutes <N>`: replacement and timer in one native command |
| Confirmation | from a fresh connection: `commit check` (confirms without committing the shared candidate), then `rollback pending` must be gone | from a fresh connection: `configure session <token> commit` | **only the CLI session that armed the change can confirm it** (proven three ways). The driver keeps that session, the service proves management with a fresh connection, and only then `commit` is sent on the kept session |
| Persistence | the commit is persistent | `write memory` after the confirmation (EOS does not autosave on commit); reported per node as saved / not saved | the commit is persistent |
| Pending-change detection and identity | entry 0 of `show system commit`: its comment line (the token) and `rollback pending` | `Session with pending commit timer: <name>` in `show configuration sessions detail` | an extra session with `Client: commit-confirm` in `show configuration sessions detail`; ours when this manager process holds the arming session to that node |
| What else blocks a restore | somebody's uncommitted edits in the shared candidate | nothing (sessions are isolated) | another open configuration session or an exclusive lock |
| Base-configuration prerequisite | none | none on 4.35.0F (the stock containerlab startup configuration is enough) | none |

Limits that are known and accepted:

- Junos needs `system root-authentication` for `commit check` and `commit confirmed`. When the saved
  configuration has none (the cJunosEvolved lab image ships without it), the driver adds one from the
  first login `encrypted-password` of the same saved configuration. In a lab image that is the only
  login; in a multi-user configuration it is not necessarily a superuser's. The added statement is
  reported per node and is the one tolerated difference in the Junos comparison.
- Junos has one shared candidate. A restore does not start while somebody's uncommitted changes sit
  in it (the review names the reason); it never discards them. On EOS a restore works in its own
  session and other sessions are left alone.
- While a change waits for confirmation, a `commit check` or `commit` by anybody confirms it (Junos),
  so do not use a node's CLI during the undo window of a restore.
- IOS XR: a saved configuration that contains a `banner` is refused before the device is touched (delimited
  banner bodies are not entered yet). Because only the arming session can confirm, a manager restart during the
  undo window always ends in the device undoing the change; the read-back then reports it.
- IOS XR turns away SSH connections that follow each other too quickly. The service looks at a node over one
  connection and retries a refused connection three times before anything is sent.

## Outcomes the manager reports per node

`verified` (replaced, confirmed, and a fresh capture equals the saved state; after A onto A the device reports
no change and the node is still `verified`), `verify_mismatch`
(replaced, but differences remain: counted and sampled with secrets masked), `applied_unverified`
(replaced, the follow-up capture did not run), `failed` (not changed: the driver refused or the node
rejected the candidate and the candidate was discarded, or the node could not be reached before
anything was sent), `rolled_back` (the change was not confirmed and the manager **read the previous
configuration back**), `uncertain` (the manager could not establish what is active), `ineligible`,
`interrupted`. `rollback_expected` exists only on jobs stored by releases before 1.30.27.

The manager keeps trying to reconnect and confirm for the whole recovery window (and 90 s beyond:
Junos was seen rolling back 35 s late). It confirms a pending change only when the node shows it
under this job's token; "something is pending" proves nothing about whose it is. After a manager
restart the same read-back runs for every node that was mid-change; nothing is re-applied, and the
job then states what was found.

## Desired-state comparison and its exclusions

Nothing is normalised away except what is listed here.

- **Junos** compares `display set` statements (each carries its whole path). Excluded: `#` comment
  lines, `set version …`, `… last-changed …` timestamps, and `set system root-authentication …`
  (the driver may have to synthesise it; see PICKUP).
- **IOS XR** compares running-config lines together with their parents, like EOS. Excluded: `!` and `!!` lines
  (the capture's banner: "Building configuration", version, last-change time), the timestamp line and the
  final `end`. A route-policy or an access list whose lines only changed order is reported as a difference.
- **EOS** compares running-config lines together with their parents (`interface Ethernet1 >
  description …`), so a statement under another parent is a different statement. Excluded: `!`
  comment lines (the capture's command/device banner and separators) and the final `end`. An ACL,
  route-map or prefix-list whose entries only changed order is reported as a difference.

## The acceptance lab

[`lab/restore-square.clab.yml`](lab/restore-square.clab.yml): one node of each image in a square of
routed /31 edges with OSPF area 0 and loopbacks; "configuration A" is in
[`lab/base-configs/`](lab/base-configs/), the drift to "configuration B" (one value changed, one A
statement removed, B-only stanzas added) in [`lab/drift/`](lab/drift/). Image identities and the NOS
versions the devices report are in PICKUP.

Tools (all in [`tools/`](tools/); all but `manager_restore.py` need `clab-backup-ui/.venv/bin/python`):

| Tool | Purpose |
|---|---|
| `nodecli.py` | Independent device CLI with transcripts kept outside Git. Acceptance readbacks never go through the code under test. |
| `square_check.py` | Every edge pinged in both directions, loopback mesh, and each NOS's own boot identity (a container's uptime says nothing about a virtual router inside it). |
| `manager_restore.py` | Drives the running manager's real API: preflight, restore, idempotent double submit, job timeline; writes a committable evidence file. |
| `browser_restore.py` | The student's path in a real browser (Playwright) against the running manager and the real nodes: Saved versions, review, acknowledgement by keyboard, progress, reopen from the banner, reload, result; desktop and narrow viewports. |
| `readback.py` | The devices' own answer, sanitized for Git: is A or B active (one marker per kind of drift), is anything awaiting confirmation, is a manager session left over, the NOS boot identity. Booleans only. `manager_restore.py --readback` and `browser_restore.py` embed it before and after a run, together with the identity of the build that was running. |
| `interruption.py` | 0.2 s probes on management and data-plane paths around one manager restore that really changes configuration; lost probes and the longest gap. |
| `persistence_check.py` | Restart the NOS the normal way (Junos `request system reboot`, IOS XR `reload`, cEOS `containerlab restart --node`), prove from the NOS that it restarted, wait for management and both edges, compare the configuration independently. A containerlab redeploy is not a restart. |
| `mixed_failure.py` | All four nodes selected, a foreign timed change armed mid-job on the node applied last: three verified, one "not changed", job `partial`, the foreign change left alone, recovery afterwards. |
| `driver_junos_live.py` | Driver-layer proof of `restore_junos.py` on a real Junos node: token identity, `commit check` confirmation, the refusals that protect other people's edits and pending changes, a dropped session, no reboot. |

Rerun one platform: apply the drift file with `nodecli.py <node> --file lab/drift/<node>-B.cli`, take a
manager backup while A is active (`manager_restore.py --backup-now`, before drifting), then
`manager_restore.py --backup <job> --nodes <node> --evidence evidence/<name>.json`, then
`nodecli.py` readback and `square_check.py`.

## Evidence matrix

PASS / FAIL / BLOCKED / NOT RUN, with the manager build that produced the evidence. Static analysis,
unit tests and fixtures support these live checks; they do not replace them.

See [`evidence/MATRIX.md`](evidence/MATRIX.md).
