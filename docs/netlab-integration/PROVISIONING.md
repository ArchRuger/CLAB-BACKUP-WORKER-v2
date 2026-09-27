# Provisioning contract: applying a generated plan to devices

The design of milestone D, written and reviewed on paper before its implementation. It refines decisions
D4.2 to D4.5 of [DECISIONS.md](DECISIONS.md). Nothing here replaces *Apply to running lab* (`restore.py`):
a generated fragment is never a whole-configuration candidate, and the two features keep their own job
lists, drivers and words. The first draft was reviewed by the Opus `risk-reviewer` (2026-09-27); its
seven must-fix findings (the stale rule that could never fire, Junos presence containers left behind by
leaf deletes, negated statements, a preview that omitted the removals, the ledger's restart consistency,
the IOS XR timer unit, and the filter dropping Junos presence blocks) and its should-fix items are folded
in below, each marked *(review)*. §7 records what was verified on the real devices.

## 1. What is applied, and what never is

A generation holds netlab's per-device fragments in order (`initial`, then the modules). They are merge
fragments written for a fresh device. Before anything reaches a device, `design_provision.prepare(kind,
fragments)` turns them into one *candidate* and a list of the *protected settings it left out*, each with
its module and reason:

| Never applied | Why | Platform shapes |
|---|---|---|
| The management interface's own configuration (any statement but the LLDP-off below) | management stays containerlab's | EOS `interface Management…`; Junos `interfaces { fxp0 / re0:mgmt-0 {…} }`; IOS XR `interface MgmtEth…`, `vrf clab-mgmt`, `router static > vrf clab-mgmt` |
| `hostname` / `host-name` | the device already carries its containerlab name; a change breaks prompts and terminals | EOS `hostname`, Junos `system { host-name }`, IOS XR `hostname` |
| AAA, users, logging targets, DNS servers, SSH/telnet/API servers | credentials and access stay the manager's | EOS `aaa`, `username`, `logging`, `management api…`; Junos `system { login, services, syslog, name-server, root-authentication }`; IOS XR `username`, `aaa`, `ssh server`, `telnet`, `netconf`, `grpc`, `xml agent`, `line` |
| Default routes toward management | | EOS `ip route 0.0.0.0/0 …`, `ipv6 route ::/0 …`; IOS XR `router static > vrf clab-mgmt` |
| MAC addresses on interfaces | runtime identity, disruptive | EOS `mac-address` |
| The cEOS `normalize` file | netlab's pre-deploy interface reset (`shutdown` and MACs) | whole file |
| Junos `delete: <hierarchy>;` tags | they wipe a whole stanza, manual statements included; removal is the ledger's job (§3), except for whole owned policy objects (§3, S2) | every `delete:` line |
| Static host mappings | not design intent, keeps the owned set small | EOS `ip host`, `ipv6 host`; Junos `static-host-mapping`; IOS XR `domain ipv4/ipv6 host` |

Kept on purpose *(review S9)*: netlab's LLDP-off on the management interface where the image accepts it
(Junos `protocols lldp interface <mgmt> { disable; }`, IOS XR's global `lldp / no management enable`),
because dropping it would enable LLDP on the shared management network; on cEOSLab 4.35.0F the EOS form
(`no lldp transmit` / `no lldp receive` under `interface Management0`) is refused by the device (`% Invalid
input`, verified through the driver on 2026-09-27), so the whole management block is left out there and
`lldp run` therefore also covers the management port on cEOS: recorded as an image limit; `ip routing`, `ipv6 unicast-routing`, `lldp run`; Junos
presence blocks such as `interface lo0.0 { }` (meaningful syntax: only a block the filter itself emptied
is pruned *(review M7)*); IOS XR `domain lookup disable`. An EOS `service routing protocols model` line in a
fragment is refused (it needs a reload; the lab image already runs multi-agent).

The preview shows the protected settings by name so the student knows what was not sent.

## 2. The transaction, per platform

Every platform stages *removals then the candidate* in the NOS's own transaction on top of the running
configuration (a merge, never a replace), reads the whole would-be configuration from inside it, arms the
NOS's timed recovery, proves management with a fresh connection, confirms, and reads the device back. The
review is the same transaction, aborted instead of armed *(review M4)*: the reviewed bytes are the applied
bytes. Mechanics and the identity of "our" pending change come from the restore drivers, which proved them
live:

| | Arista cEOS | Junos (cJunosEvolved, vJunos-switch) | Cisco IOS XR (XRv9k) |
|---|---|---|---|
| Open | `configure session <name>` (a copy of running) | `configure exclusive` (after the shared candidate was found clean) | `configure exclusive` |
| Session name | `clabdsg-<8 hex>` per node: never the review token, never the restore's `clabmgr-` shape *(review S8)* | commit comment `clabdsg-<8 hex>` (≤ 40 chars) | one held session per node |
| Removals (§3) | `default <line>` for negated lines, `no <line>` otherwise, inside the parent block, children first | `delete <path>` at the highest created ancestor | `no <line>` from a per-statement table, children first; `shutdown` is never re-applied |
| Merge | `copy terminal: session-config` + Ctrl-D (merges; verified) | `load merge terminal` + Ctrl-D | the candidate entered line by line (`restore_iosxr._paste`) |
| Would-be configuration (ownership source) | `show session-config` (verified: running-config form, device defaults included) | `show \| display set` inside the candidate | `show configuration merge` (verified: running-config form with the usual header) |
| Desired set (the candidate alone, device-rendered) *(review M1)* | a throwaway session: `rollback clean-config`, paste, `show session-config`, `abort`; desired = that − the clean base (verified: the clean base is readable) | `configure private` + `load override terminal` + `show \| display set` + `rollback 0` (verified on vJunos-switch) | a plain `configure`, the lines, `show configuration` (the target buffer holds exactly them; verified), `abort` |
| Display diff | `show session-config diffs` | `show \| compare` | the target buffer (`show configuration`) for additions; removals from §3 (`show configuration changes diff` shows a merge as a full replacement and misleads; verified) *(review S7)* |
| Validate | any `% ` line while loading rejects | `commit check` **only at apply time**, never in a preview (it confirms anybody's pending change) *(review S5)* | any non-warning `% ` line while entering rejects |
| No-op | `would_be == before` and no removals: nothing is armed *(review S7)* | same | same |
| Arm | `commit timer HH:MM:SS` | `commit confirmed <min> comment <name>` | `commit confirmed minutes <N>` on the kept session; armed evidence: `Client: commit-confirm` in `show configuration sessions detail` from the fresh connection *(review M6)* |
| Ours? | `Session with pending commit timer: <name>` | commit entry 0 comment = name and `rollback pending` | `Client: commit-confirm` and this process holds the arming session |
| Confirm (fresh connection first) | `configure session <name> commit`, then `write memory` (it also saves the student's other unsaved changes: said in the review) | `commit check` (confirms; the shared candidate untouched) | `commit` on the held session |
| Persistence | `write memory` after confirmation | the commit is persistent | the commit is persistent |
| Abort of a preview | `abort` (verified: no session left) | `rollback 0`, `exit` (a private candidate dies with the session) | `abort` (verified: no session row left); a dropped connection leaves a row for minutes: the review refuses on it like the restore does |

Refusals before anything is sent (asked at review, repeated at apply): a pending change of anybody's on
the node (EOS timer, Junos `rollback pending`, IOS XR `commit-confirm` client), somebody's uncommitted
edits in the shared Junos candidate, another IOS XR configuration session or exclusive lock, an orphaned
`clabdsg-` session of ours (aborted first, never one of another name; the restore's `clabmgr-` cleanup and
ours never touch each other's sessions *(review S5)*), the node not ready (SSH login not answered),
credentials missing, the device blocked or unsupported in the generation, an IOS XR data port still
`preconfigure` (not live), and drift (§4). The review itself runs under `operation_busy` *(review S5)*.

## 3. Ownership, removal and conflicts

The manager owns exactly what its own commits added. Ownership is computed the same way on every platform,
as set differences between device snapshots in the platform's *ownership form* (EOS and IOS XR: running-
config lines with their parents, `restore_compare.indented_statements`; Junos: `display set` statements,
`restore_compare.set_lines` minus the `[edit]` banner), never from a fragment alone and never by parsing a
NOS diff *(review M5)*. Volatile lines are excluded as `restore_compare` documents (Junos `version`, `last-
changed`; EOS/XR `!` banners and timestamps; the XR `show configuration merge` header through
`restore_iosxr.strip_generated_header`) *(review S4)*.

For one device and one generation, inside the transaction:

- `before`: the running configuration read at the start, inside the lock on Junos and IOS XR; on EOS,
  which has no lock, re-read immediately before `commit timer` and compared *(review S4)*;
- `desired`: the candidate alone, rendered by the device on an empty base (§2 row "Desired set") minus
  that base *(review M1)*; the parsed candidate text is only a fallback where the device cannot render it;
- `owned`: the ledger entry for the device (empty at first), plus its *created ancestors* (see below);
- `stale = (owned − desired) ∩ before` *(review M1)*: what the manager put there, does not want any more,
  and is still on the device (an *Apply to running lab* may have removed it already; a `no`/`delete` of
  an absent statement can fail the load);
- removals are staged first (§2), then the candidate is merged;
- `would_be`: the whole configuration read inside the transaction after both;
- `added = would_be − before`, `removed = before − would_be`;
- `conflicts = removed − owned`, plus additions beside an unowned sibling inside an *exclusive hierarchy*
  (a per-platform list: interface address families, where two addresses would both stay on Junos and a
  manual address would be supplemented rather than replaced; EOS `no bgp default ipv4-unicast` under a
  `router bgp` holding manual neighbours; Junos group-level `export`) *(review S1)*;
- the *expected changes* of a first apply are named, not counted as conflicts: IOS XR data ports ship
  `shutdown`, so the design's `no shutdown` removes an unowned `shutdown` line (verified on the lab XRv9k);
  admin state on a design interface is listed as expected and is never re-applied on removal *(review S3)*.

**Created ancestors** *(review M2)*: every path prefix of an `added` statement that no `before` statement
starts with (on Junos the `set protocols bgp group X neighbor Y` container is not a statement while it has
children and appears as one when its last leaf goes; on EOS and IOS XR the parent line is a statement). They
are recorded with the owned set. Removal happens at the *highest created ancestor whose current subtree is
entirely owned and stale*: one `delete protocols bgp group ibgp-peers-ipv4 neighbor 10.255.0.4`, one
`no neighbor 10.255.0.4` under `router bgp 65000`, one `no router ospf 1` when the whole process is owned
and stale; otherwise only the owned stale leaves go. A leaf whose inverse has a side effect on unowned
statements (`switchport` back on an interface that carries manual addresses) is a conflict, not a silent
removal *(review M3)*. Statements that appear only in `after` under a created ancestor (EOS `max-lsa 12000`,
verified) become owned with it, so the container can be removed later.

**Identity changes** *(review M4)*: a changed BGP AS or OSPF process id is a removal of the old container
when it is entirely owned (EOS refuses a second `router bgp`), otherwise a named conflict.

**Order-sensitive objects** *(review S2)*: Junos `policy-statement` and `route-filter-list`, IOS XR
`route-policy`, `prefix-set`, `community-set`, EOS access lists are *whole owned objects*: when an object is
entirely owned it is replaced whole (on Junos exactly the fragment's own `delete: <object>;` is kept for
it; on EOS/XR the object is removed and re-entered), when it holds unowned lines it is a conflict; the
verification is order-aware (`restore_compare.ordered_blocks_differ` and a Junos term-order check), because
`load merge` appends new terms after an existing `term default { then reject; }`.

Conflicts block the apply with the statements named, unless the student made the explicit, reviewed
decision *Take over these settings* for that device; the token then carries the take-over list and the
apply refuses a body whose list differs *(review S6)*; the overwritten statements become owned. A
conflict is never resolved by the whole-configuration replacement.

**The ledger** lives on the lab record under the private key `network_ownership`
(`{node: {generation_id, applied_at, statements: [...], ancestors: [...], pending: {...}}}`) *(review M5)*:

- before arming, the job persists per device `added`, `desired`, the removals and the created ancestors;
- the owned set `owned' = (owned ∩ after) ∪ (added ∩ after)` and the ancestors are written **in the same
  store update** as the device's `applied`/`verified` outcome, both in the settle path and in the restart
  recheck; nothing is written to the ledger for `rolled_back`, `failed` or `unchanged`;
- an `uncertain` device keeps a *pending* ledger entry (the persisted `added`) that blocks the next review
  of that device until a read-back resolves it (present → owned; absent → dropped);
- a stale owned container kept because a manual child sits under it is its own reported state
  (`kept_manual`), not a verification failure.

## 4. Review token, drift and the apply job

`POST /api/labs/{id}/design/generations/{gid}/review` with `{targets}`, under `operation_busy`: for each
target the service connects (direct node SSH, existing credential precedence), refuses on the conditions
of §2, runs the whole transaction of §3 and aborts it, and returns per device: reachable, protected
settings left out, the device's diff (masked with `restore.mask_line`), added/stale/removed/conflicts
counts and samples, the expected changes, the removal commands it will send, and the compatibility rows.
The token (32 hex, single use, 10 minutes, checked once at submit *(review O1)*) binds the generation id,
the targets, the intent revision, the topology and mapping digests, each device's `before` digest and the
take-over list.

`POST /api/labs/{id}/design/apply` with `{token, confirm_minutes, request_id}`: guarded by
`operation_busy` (the new busy family `DESIGN_APPLY_BUSY`), the Runner's single job, a fresh discovery, and
idempotent by `request_id`. Flow, mirroring `restore.py`:

1. preflight (lab, VM identity, node availability);
2. mandatory pre-change backup of the live targets through the Runner (`source='design-pre'`), kept on the
   apply job; a device whose backup failed is not changed;
3. per device on the node pool (endpoint groups, per-node session name; the recovery deadline starts at
   arming, and the pre-arm steps are bounded *(review O1)*): reconnect, take `before` again and compare its
   digest with the review's (drift refuses the device: "the configuration changed since you reviewed it"),
   stage removals and candidate, read `would_be`, check `added`/`removed` against the review's, persist the
   pre-arm ledger fields, arm (or record a no-op without arming);
4. settle as the restore does: fresh connection, confirm only under our name, read back, `rolled_back` only
   when the `before` snapshot is read back, otherwise `uncertain`; IOS XR confirms on the held session; a
   manager restart marks in-flight devices `interrupted` and rechecks them at start (stages `connecting`,
   `applying`, `confirming`);
5. verification: semantic read-back (every `desired` statement present, every stale statement and every
   removed ancestor gone, ordered objects in order), the ledger written with the outcome (§3), then
   control-plane evidence where the plan expects it (OSPF neighbours, BGP sessions, IS-IS adjacencies as
   parsed `show` output, informational in this milestone);
6. post-change backup (`source='design-post'`) for the record, and a finalisation that sets the job's status
   from the per-device outcomes: `succeeded`, `partial`, `failed`, `needs_attention`, `interrupted`; a
   healthy-looking label never hides a failed or unverified device.

Per-device outcomes and words: `verified`, `applied_unverified`, `verify_mismatch`, `kept_manual`, `failed`
(not changed, with the reason), `rolled_back`, `uncertain`, `interrupted`, `ineligible`, `drifted`,
`conflict`, `no_op`.

No lab-wide atomicity is promised; the job document says what happened to each device and what to do
next (the pre-change backup is restorable through *Apply to running lab* for any device).

## 5. What the page shows

An **Apply to devices…** action on the plan card opens the review: the targets with their state, the
protected settings left out, each device's diff and expected changes, the removals, the conflicts (with
the take-over choice), the timed-recovery minutes, and the acknowledgement; then the live progress per
device (the restore dialog's shape: stages, outcomes, recovery), and afterwards the ledger of owned
statements per device under Advanced.

## 6. Order of work and evidence

cEOS first (boots in a minute; its session transaction is proven), then Junos (both kinds share the
driver; cJunosEvolved is the `vptx` stand-in and must be proven on the image), then IOS XR (held-session
confirmation). Each platform: driver with fake-channel tests, the service path with the real app on scratch
state, then the live proof on `restore-square`: create → apply → verify → re-apply (no-op) → modify (a link
prefix, a removed BGP peer) → remove (the module dropped) → verify cleanup, with unrelated manual
configuration surviving, plus an unconfirmed apply left to the device's timer and a manager restart inside
the recovery window. The devices currently run containerlab's startup configurations (no configuration A),
so the first applies meet no manual conflicts; a take-over case is staged deliberately afterwards. Evidence
goes to `evidence/` and the ledger's live column: `evidence/live-apply-ceos.md` (ten steps including the
take-over, the timer expiry and the restart inside the window), `evidence/live-apply-junos.md` (both kinds,
five steps) and `evidence/live-apply-iosxr.md` (the held-session path). §8 lists what those runs changed.

## 7. Live facts gathered while writing this (`restore-square`, 2026-09-27)

Probed with `docs/multi-platform-restore/tools/nodecli.py`, inside transactions that were aborted (`show
configuration sessions detail` empty afterwards on EOS and IOS XR):

- **cEOS 4.35.0F:** `configure session <name>` then `copy terminal: session-config` with a fragment (an
  interface block and a `router ospf 7` block, Ctrl-D) **merges**: `show session-config diffs` printed only
  the added lines under their unindented parent context, header `--- system:/running-config` /
  `+++ session:/<name>-session-config`; `show session-config` prints the whole would-be configuration in
  `show running-config` form, and the device's own defaults are already in it (`max-lsa 12000` under the new
  OSPF process); `rollback clean-config` inside a session gives a readable clean base (interfaces present and
  empty, `interface Management0` empty, `no ip routing`, the model and spanning-tree lines); `abort` leaves
  nothing.
- **IOS XR 24.3.1 (XRv9k):** in `configure`, after `router ospf 7 / router-id …`, `show configuration`
  prints exactly the entered lines (the target buffer), `show configuration merge` prints the whole would-be
  configuration in running-config form with the `!! Building configuration`, version and last-change
  header, and `show configuration changes diff` prints the *entire* running configuration as removed with
  the target as added (a replacement view, unusable as a merge diff); `abort` leaves no session row. The
  data ports ship `shutdown` (`show running-config interface GigabitEthernet0/0/0/0`); management is
  `interface MgmtEth0/RP0/CPU0/0` with `vrf clab-mgmt`, `router static > vrf clab-mgmt` default routes and
  `ssh server vrf clab-mgmt`, all protected by the filter.
- **Junos (vJunos-switch 23.2R1.14):** `configure private` + `load merge terminal` loads netlab's fragment
  shape (the semicolon-less `router-id` included); `show | display set` inside the candidate renders it with
  its presence lines; a leaf `delete` leaves the presence container behind (the M2 case the ancestor rule
  handles); `load override terminal` works in a private candidate without a commit, so the device renders the
  desired set; `rollback 0` clears it. Details: [evidence/junos-transaction-facts.md](evidence/junos-transaction-facts.md).

## 8. What the live proof changed (2026-09-27)

Rules and fixes that came out of the runs in `evidence/live-apply-*.md`; each has a unit test in
`tests/test_design_ownership.py` or `tests/test_design_apply.py` and was then proven again live.

- **EOS BGP neighbours are one object.** Per-line negation (`no neighbor X activate` inside an address family,
  then `no neighbor X remote-as …`) left explicit `no neighbor X activate` lines in the running configuration.
  When every line of a neighbour (process level and address families) is stale, the plan emits one
  `no neighbor X`; a neighbour with a manual line under it is still removed leaf by leaf.
- **EOS `no address-family F` keeps the family's `network` statements** (the device moves them to the process
  level). A family removed whole has its `network` statements removed by name first.
- **A container kept for a manual child is not a verification failure.** `verify()` takes the kept list; the
  device says "N setting(s) stayed because manual configuration sits under them".
- **An all-no-op apply is a success**, worded "Every selected device already matched the plan; nothing was
  changed." (it had failed as "none of the selected devices is running").
- **Junos created ancestors are the device's own blocks.** The word prefixes of a set statement include
  keyword-only levels (`set protocols bgp group X neighbor`) that Junos cannot `delete`; the driver returns the
  hierarchical `show` of the would-be configuration and `design_ownership.junos_blocks` limits the ancestors to
  its blocks (the `X.N {` interface shorthand becomes `X` and `X unit N`). A ledger written earlier is filtered
  the same way at the next review.
- **What the design puts back under a removed container is not a leftover**, and a container the same apply
  removes and re-creates stays owned (`_record_applied`).
- **IOS XR negations.** `show configuration merge` never prints `no shutdown` or `no management enable`: a port's
  `shutdown` that vanishes under an interface the design configures is an expected change, and a typed
  negation in the desired set (the target buffer echoes it) is verified as the absence of its positive form,
  both in the read-back and in the recovery loop's "matches the reviewed result" test.
- **IOS XR held session.** The driver's client entry point keeps the arming connection in its own `_HELD`
  table under the design's session name and returns `held: True`; the service closes every other connection
  and never that one. After a manager restart nobody can confirm the trial: the recheck keeps the persisted
  deadline and waits for the device's own timer before reading the node back, instead of one immediate pass.
- **IOS XR refuses a BGP AS change in one commit** ("BGP is still in process of unconfiguration for instance
  default"): the apply fails cleanly with the device's own `!!%` reasons appended (`show configuration failed`,
  reasons only, never the statements); the identity change is two applies (drop the module, then add it with
  the new AS) rather than a two-commit transaction with two recovery timers.
- **IOS XR removals and candidate are one paste**: the depth tracking of `_paste` must see both, or a candidate
  line typed after a removal that ended inside a submode would land in that submode (found by the fake-channel
  tests, `tests/test_design_iosxr.py`).
- **The interrupted job says what the read-back came to** ("Read back afterwards: ceos applied and verified"
  or "… undone by the device") instead of a blanket "undone".
- **`send-community` is not a secret.** The restore's masker redacted `neighbor X send-community standard
  extended large` in every review; `snmp-server community` stays redacted.
- **cEOSLab refuses `no lldp transmit` / `no lldp receive` under `Management0`** (lines 8 and 9 of the first
  candidate): the whole management interface block is left out and named among the protected settings.

### Fourth review pass (Opus `risk-reviewer`, after the live proof)

Three must-fix and six should-fix findings, all applied and pinned:

- the held IOS XR session is now released on every path that does not confirm (`DesignApply._release`: a
  mismatch, a foreign pending change, an expired timer, an unknown outcome), and `design_iosxr.pending()` prefers
  the caller's own session name over another held entry for the same node;
- a refused IOS XR commit puts the device's `!!%` reasons into the job in the manager's fixed words only
  (`FAILURE_PHRASES`: "BGP was still being removed: change the AS in two applies …", "it refers to an object the
  device does not have yet", "something it removes is still in use", else "the device refused the commit on
  semantic grounds"), never the device's text;
- a pending ledger entry (an `uncertain` outcome) is settled by the next review's read-back (`_resolve_pending`:
  desired present → the added statements become owned; absent → dropped), so a device is never blocked for good;
- a plan is applied only while it is the plan of the lab's current design and topology (`_current_plan` at review
  and at submit: intent revision and topology digest), and the page disables *Apply* for a stale plan;
- a change armed without the review's confirmation of what was staged (a lost session, a restart before the arming
  was recorded) is compared with the review's would-be digest before it is confirmed; anything else is left to the
  device's timer;
- `guard_idle` also refuses while a design apply or a restore is busy on *any* lab (the Runner would refuse the
  pre-change backup), and a refused post-change backup is said on the job;
- the provisioning filter also leaves out Junos `root-authentication` in its block form, `radius-server`,
  `tacplus-server`, `authentication-order`, `management-instance`, the `mgmt_junos` routing instance, and EOS
  `tacacs-server`, `radius-server`, `snmp-server`; protected statements are masked before they reach the browser;
- EOS `neighbor interface …` (unnumbered) and `neighbor default …` are not peers named `interface`/`default`;
- the acknowledgement is unticked on every new review, capped samples say "… and N more", a take-over says how
  many manual settings it covers.

