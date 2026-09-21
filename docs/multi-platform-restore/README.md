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
| Restore artifact | `show configuration` (hierarchical), `.jcfg`, format `junos-hierarchical` | `show running-config`, `.eoscfg`, format `eos-running-config` | NOT YET SUPPORTED in this record |
| Replacement | `configure exclusive`, `load override terminal` | `configure session <token>`, `rollback clean-config`, `copy terminal: session-config` | |
| Review diff | `show \| compare` | `show session-config diffs` | |
| Validation | `commit check` | the session commit itself; any `% ` line during the load rejects the candidate | |
| Timed recovery | `commit confirmed <minutes> comment <token>` | `commit timer HH:MM:SS` | |
| Confirmation (fresh connection) | `commit check` (confirms without committing the shared candidate), then `rollback pending` must be gone | `configure session <token> commit` | |
| Persistence | the commit is persistent | `write memory` after the confirmation (EOS does not autosave on commit); reported per node as saved / not saved | |
| Pending-change detection and identity | entry 0 of `show system commit`: its comment line (the token) and `rollback pending` | `Session with pending commit timer: <name>` in `show configuration sessions detail` | |
| Base-configuration prerequisite | none | none on 4.35.0F (the stock containerlab startup configuration is enough) | |

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

## Outcomes the manager reports per node

`verified` (replaced, confirmed, and a fresh capture equals the saved state), `verify_mismatch`
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
| `driver_junos_live.py` | Driver-layer proof of `restore_junos.py` on a real Junos node: token identity, `commit check` confirmation, the refusals that protect other people's edits and pending changes, a dropped session, no reboot. |

Rerun one platform: apply the drift file with `nodecli.py <node> --file lab/drift/<node>-B.cli`, take a
manager backup while A is active (`manager_restore.py --backup-now`, before drifting), then
`manager_restore.py --backup <job> --nodes <node> --evidence evidence/<name>.json`, then
`nodecli.py` readback and `square_check.py`.

## Evidence matrix

PASS / FAIL / BLOCKED / NOT RUN, with the manager build that produced the evidence. Static analysis,
unit tests and fixtures support these live checks; they do not replace them.

See [`evidence/MATRIX.md`](evidence/MATRIX.md).
