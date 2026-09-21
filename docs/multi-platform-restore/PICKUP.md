# Multi-platform restore: pickup file

*Replace running configuration* for four exact images: cEOS 4.35.0F, cJunosEvolved 26.2R1.7-EVO,
vJunos-switch 23.2R1.14 and XRv9k 24.3.1. Read this file first; update it before a compaction or a
handoff. Raw device captures stay outside Git (`~/research/multi-platform-restore/`); only sanitized
evidence is referenced here.

## Plan (chunks)

1. Routing and environment preflight, the square lab, vJunos-switch baseline. **Done** (no code release: read-only baseline).
2. cEOS 4.35.0F: prerequisites, capture and restore path, UI, positive and failure tests. **Done: release 1.30.27, commit `3c5d954`, pushed 2026-09-21, draft PR #47.** Owed on the final build and running as a QA agent: B4/B5 rerun, the saved-Git-version source, Evolved and vJunos-switch product-level B4/B5, the root-authentication synthesis through the product (evidence `17-*`).
3. cJunosEvolved 26.2R1.7-EVO: find the real gap, same acceptance checks.
4. XRv9k 24.3.1: implementation and the same acceptance checks.
5. All-four integration, mixed-platform restore from the running UI, final regression.

Each finished code chunk is one patch release (`deploy/set-release.py`), committed and pushed on
`claude/multi-platform-restore` (branched from `main` at `e4f466a`, release 1.30.26).

## Routing preflight (2026-09-20, Claude Code 2.1.278)

Resolved models were read from the session's transcript metadata
(`~/.claude/projects/<project>/<session>/subagents/agent-*.jsonl`, field `message.model`, joined
with `agent-*.meta.json` `agentType`), not from what a worker said about itself.

| Role | Expected | Configured | Observed | Result |
|---|---|---|---|---|
| Main session | `claude-fable-5-1` | project `model: claude-fable-5-1` | `claude-fable-5-1` on every assistant turn, no fallback model seen | PASS |
| `clab-ui-scout` | haiku | `model: haiku` | `claude-haiku-4-5-20251001` | PASS |
| `clab-ui-builder` | sonnet | `model: sonnet` | `claude-sonnet-5` | PASS |
| `clab-ui-reviewer` | opus | `model: opus` | `claude-opus-5` | PASS |
| `clab-ui-qa` | sonnet | `model: sonnet` | `claude-sonnet-5` | PASS |
| Unassigned subagent (`general-purpose`) | sonnet | project env `CLAUDE_CODE_SUBAGENT_MODEL=sonnet`, `…_FORCE=0` | `claude-sonnet-5` | PASS |
| `clab-ui-escalation` (optional) | fable, if it exists | not defined anywhere | — | nothing to preserve |
| Agent teams | unchanged | `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=0` | `0` in the session environment | PASS |

Precedence seen: there is no managed settings file and no `.claude/settings.local.json`. The user
file `~/.claude/settings.json` still says `CLAUDE_CODE_SUBAGENT_MODEL=claude-fable-5-1` and
`availableModels: ["claude-fable-5-1"]`; the project file overrides both in this checkout (the
session environment shows `sonnet`, and Haiku, Sonnet and Opus workers all ran). Outside this
project the user file still forces Fable subagents; that file was left alone.

The four `clab-ui-*` definitions and `.claude/rules/clab-ui-routing.md` were widened from UI-only
to full-stack work (descriptions; Bash for scout and reviewer; Write and Edit for QA tooling; live
checks allowed when the lead assigns the lab). Tool-list changes load at the next session start.

## Environment (checked, not assumed)

- Host `clab-llm-dev2`: 28 vCPU, 67 GiB RAM (52 free before the lab), 28 GiB disk free, `/dev/kvm`
  present, Docker, containerlab 0.79.0, passwordless sudo, Node 18 (so no lab-builder bundle rebuild here).
- Source: `main` = `e4f466a` = release 1.30.26.
- Deployed before this work: manager `clab-backup:1.30.17` on TCP 8081 (host network), helpers 1.30.17.
  Present in source but not deployed: 1.30.18–1.30.26. Upgrade to the source release: see the log below.
- Restore history in the live store: six manager-run restores on cJunosEvolved nodes of `l10-evpn`,
  all `verified`. The Evolved path is therefore not simply broken; chunk 3 finds the real gap.

## Lab

- Topology: `docs/multi-platform-restore/lab/restore-square.clab.yml`, deployed from
  `/srv/containerlab-node-manager/projects/restore-square/` (a trusted lab root) on 2026-09-20.
- `ceos eth1 ↔ et-0/0/0 cjunosevolved et-0/0/1 ↔ ge-0/0/0 vjunos-switch ge-0/0/1 ↔ Gi0/0/0/0 xrv9k Gi0/0/0/1 ↔ eth2 ceos`
  (containerlab mapped these to cjunosevolved eth4/eth5, vjunos-switch eth1/eth2, xrv9k eth1/eth2).
- Management 172.20.20.101–104 in that order; routed /31 edges 10.0.12/23/34/41.0, loopbacks
  10.255.0.1–4, OSPF area 0.

| Node | Kind | Image | Image ID (= repo digest) |
|---|---|---|---|
| ceos | `arista_ceos` | `n24l/ceos:4.35.0F` | `sha256:47b251291ce6…1f1007` |
| cjunosevolved | `juniper_cjunosevolved` | `n24l/cjunosevolved:26.2R1.7-EVO` | `sha256:d1dfc8bc6fa2…569455` |
| vjunos-switch | `juniper_vjunosswitch` | `n24l/vjunos-switch:23.2R1.14` | `sha256:12832fcba163…f71d62` |
| xrv9k | `cisco_xrv9k` | `n24l/cisco_xrv9k:24.3.1` | `sha256:1409cf12e4b5…dd9d2b` |

NOS versions reported inside the devices (2026-09-20): ceos `4.35.0F-44178984.4350F (engineering build)`, i686;
cjunosevolved `Junos: 26.2R1.7-EVO`, model ptx10001-36mr, hostname `HOSTNAME`; vjunos-switch `Junos: 23.2R1.14`, model
ex9214; xrv9k `Cisco IOS XR Software, Version 24.3.1`. Boot times on this VM: cEOS about 1 min, cJunosEvolved
login after about 8 min, XRv9k "Startup complete in 0:10:37" with its GigabitEthernet ports two minutes later (until
then their configuration sits under `interface preconfigure`), vJunos-switch login after about 17 min and **FPC 0
online only after about 26 min** (it restarted itself once as an "unresponsive board"): SSH readiness long precedes
the data plane there. Baseline health: `evidence/00-square-baseline.json` (all four edges both ways, full loopback mesh).

## Findings so far

- Backend gate: `restore_junos.SUPPORTED_KINDS` via `restore.py` `map_targets` and the `sources`
  route; browser wording in `restore.js` ("Only Junos devices can be updated this way for now.").
- A saved node without a restore artifact is skipped silently in `resolve_source` (no row, no
  reason); only `restore_capable_nodes` hints at it. Needs a visible compatibility outcome.
- Static review (Opus) of the Junos driver for Evolved, to settle live: commit judged by one
  `commit complete` substring; root-shell prompt regex is csh-shaped; one immediate reconnect
  attempt after the armed commit; `pending_rollback_shell` is not wired (interrupted restores).
- Only restore-capable captures today: Junos kinds (`inventory.py` `restore` command → `.jcfg`).
  EOS and IOS XR have no restore artifact yet.

- Deployed state after `start-manager.sh --manager-only` (2026-09-20 22:18 UTC): manager image
  `clab-backup:1.30.26`, `/api/state` version 1.30.26, `restore.js?v=1.30.26`, all three helpers
  1.30.26. The square is imported into the running manager as lab `904a35a79dc3…` (four nodes, correct kinds).
- `rollback_expected` is worded in the UI as "Rolled back — unchanged" / "returned to its previous
  configuration": a claim nobody verified. It has to become a checked outcome.

### cEOS 4.35.0F live facts (raw transcripts: `~/research/multi-platform-restore/raw/*ceos*`)

- No base-config prerequisite: `configure session` offers `commit timer` and `rollback clean-config`
  on the stock containerlab startup configuration. "Enable commit-based sessions" is not needed.
- A session starts as a copy of the running configuration, so pasting into it only merges.
  True replacement = `configure session N` → `rollback clean-config` → `copy terminal: session-config`
  + candidate + Ctrl-D. Proven: the B-only VLAN and static route were removed, the changed
  description restored, the removed prefix list returned; `show session-config diffs` is the review
  diff and is empty for a no-op.
- A bad line prints `% Invalid input at line N` yet still "Copy completed successfully": any `% `
  line is a rejection. Multi-line banners load; the candidate's trailing `end` does not leave the
  session (it does when pasted line by line, which leaves the session `pending`).
- `commit timer 00:02:00` then no confirmation: EOS reverted to B by itself at expiry, uptime kept
  counting (no reboot). Observed, not assumed. Confirmation from a fresh connection:
  `configure session N commit`. `show configuration sessions detail` shows
  `Session with pending commit timer: N` while armed.
- "Autosave to startup-config on commit is disabled": persistence needs `write memory` after the confirmation.
- `?` help leaves the partial command on the line; a following newline executes it. Do not probe with `?` + newline.

### cJunosEvolved 26.2R1.7-EVO first facts

- `show version`: Hostname `HOSTNAME`, Model ptx10001-36mr, Junos 26.2R1.7-EVO; boot identity from
  `show system uptime` ("System booted: …").
- No `system root-authentication` in the deployed configuration, and an ordinary `commit and-quit`
  of configuration A **succeeded** (only an OSPF licence warning). This contradicts the 1.28.0 handoff
  note ("rejects every real commit"); settle in chunk 3 whether the synthesis path is still needed.
- Edge ceos↔cjunosevolved: OSPF Full, ping both ways.

### Code so far (uncommitted)

- `app/restore_shell.py`: shared `Shell`, `RestoreError`, `open_shell`, `close_channel`; the Junos
  driver now subclasses it (names unchanged, 29 restore tests pass).
- Builder (Sonnet) owns `app/restore_eos.py` + `tests/test_restore_eos.py`, from the live facts above.
- Driver contract being introduced: `apply_candidate(client, candidate, confirm_minutes) → {diff,
  no_op, handle}`, `confirm(client, handle)`, `pending(client)`, `capture(client)`, `validate_candidate(text)`.

### vJunos-switch 23.2R1.14 baseline (chunk 1, manager 1.30.26, before any code change)

- Normal backup → both Junos nodes got a `.jcfg` artifact; cEOS and XRv9k got none, and the preflight dropped
  them silently (no row, no reason).
- A→B drift (`lab/drift/vjunos-switch-B.cli`), restore A from the backup source through the API: 39 s,
  `verified`, 0 missing / 0 extra. Independent readback: description back, deleted static route back, B-only prefix
  list and VLAN gone; `show system commit` shows `commit confirmed, rollback in 5mins` then the confirmation 3 s
  later; boot time unchanged; square healthy (`evidence/01-vjunos-baseline-square-after.json`).
- Live facts: while a confirmation is pending, entry 0 of `show system commit` is followed by a line
  `rollback pending`; older entries keep their "commit confirmed" text for good. An unconfirmed
  `commit confirmed 2` rolled back by itself (`by root via other`), observed. **`commit check` from a fresh session
  confirms a pending commit** (still active after the window) and does NOT activate another session's uncommitted
  edits, unlike the plain `commit` the driver uses today. Pending decision for the driver, with the Evolved evidence.

### Junos confirmation: what the live evidence says (both Junos images)

- Today's driver confirms with `configure` + plain `commit`. Proven on Evolved (`evidence/evo-live-facts.md` §4):
  that **activates another session's uncommitted edit** sitting in the shared candidate. Defect.
- `commit check` from a fresh session confirms a pending `commit confirmed` (documented Junos behaviour; observed
  on vJunos-switch with a 5-minute window and on Evolved) and leaves a foreign uncommitted edit uncommitted.
  `configure private` is refused while the shared candidate is modified (`error: shared configuration database
  modified`), so it is not an option. Direction: confirm with `commit check`, then prove with `show system commit`
  that `rollback pending` is gone; never fall back to a plain `commit`.
- Leaving configuration mode while a foreign edit is in the candidate asks
  `Exit with uncommitted changes? [yes,no] (yes)`: not a CLI prompt, so the driver must answer it (`yes` leaves the
  other user's candidate as it is). `enter_config`'s `rollback 0` DISCARDS such a foreign candidate: decide with
  the Opus review whether to refuse instead.
- Evolved: `commit check` and `commit confirmed` reject a configuration without `system root-authentication`
  ("Missing mandatory statement"), a bare `commit` only warns. The synthesis in the driver is still needed; only
  its comment was imprecise. Login lands in the CLI (`admin@HOSTNAME>`), prompts match the driver's patterns.

### Independent risk review of the service changes (Opus, 2026-09-20) and what was done

Accepted and fixed in the working tree, each with a regression test: (1) Junos had no identity for its armed
change, so after a lost session the manager refused to confirm its own change and then said "not changed" →
`commit confirmed N comment <token>`; `show system commit` prints the comment under entry 0 before
`rollback pending` (proven on vJunos-switch; **still to prove on Evolved**); `_settle` confirms by token only, never
because "something is pending". (2) Junos confirmation is now `commit check` + proof that `rollback pending` is gone
(it clears at once: proven on vJunos-switch), the exit question is answered, and the driver looks at the shared
candidate from a plain session first and **refuses** when somebody's uncommitted edits are there; no shared
`configure` + `rollback 0` fallback any more. (3) `mask_line` cut EOS lines after the type token and left the hash:
now everything after the first secret keyword is dropped. (6) only connectivity-shaped errors are retried for the
window. (7) the restart re-check says what it checked (`verified` only after a comparison) and recomputes the job
(`_finalize(prefix='Checked after a manager restart. ')`). (8) no driver → never "converged". (9) EOS: one capture;
the artifact is the backup text (`runner.py`), test delegated (`tests/test_app.py`).
Rejected: (5) *Remove lab* during a restore is already refused by `get_lab()` → `operation_busy` (pinned by a test).

Live driver-layer proof of the rewritten Junos driver on vJunos-switch: `tools/driver_junos_live.py` →
`evidence/20-vjunos-driver-live.json` (running in the background when this was written).

### Second Opus review (of the Evolved evidence) and the driver-layer proofs (2026-09-21)

- The review was written against the driver before its rewrite; its blocker (plain `commit` confirmation) and the
  pending-parse point were already fixed. Taken from it: `recovery_grace` 90 s (Evolved rolled back 35 s late), a
  commit answer with both "complete" and an error line is `SessionLost` (read back, never "not changed"; hardening,
  no lab image prints per-RE output), the evidence file's "fragile timer" conclusion was wrong (it was `commit
  check` confirming) and was corrected in place, the synthesis limitation is in the README.
- Disagreement settled by evidence: the risk review wanted the driver to refuse when somebody's uncommitted edits
  exist, the Evolved review wanted it to keep discarding them (fearing our own crashed session would block a node
  for good). A dropped `configure exclusive` session leaves nothing in the candidate on BOTH images, so the driver
  refuses, as the task's "preserve unrelated edits" demands. The same reason is shown at the review step through
  the optional driver hook `blocked()`.
- `tools/driver_junos_live.py`, 25 steps, ALL OK on cJunosEvolved (`evidence/30-evo-driver-live.json`) and 21 steps
  ALL OK on vJunos-switch before the dropped-session steps were added (rerun with them: `20-vjunos-driver-live.json`).
- Found by QA on cEOS (B4 attempts 2 and 4): a restore whose SSH died before `commit timer` left its session
  `pending` on the device; EOS keeps five. Fixed: `restore_eos.cleanup_shell` (own names only), called at the start
  of an apply and when a lost session is settled. **Live proof still owed** once QA releases the node.

### Work in flight (2026-09-20 about 23:35 UTC)

- Workflow `multi-platform-restore-tracks` (run `wf_135f5f79-c0a`): XR track (builder on node xrv9k: live facts →
  `app/restore_iosxr.py` + test + `evidence/xr-live-facts.md`, then Opus review), Evolved track (QA on node
  cjunosevolved: `evidence/evo-live-facts.md`, then Opus decides the Junos driver changes), UI track (builder:
  `restore.js`, `git-places.js` + tests, then QA verification).
- QA agent: cEOS acceptance matrix A7 + B1–B7 on node ceos and the running manager → `evidence/12-ceos-*`.
  It may `docker restart` the manager; **do not rebuild the manager until it reports**.
- Builder agent: `tests/test_restore_compare.py`.
- Lead-owned and done in the working tree: `restore_shell.py` (+`SessionLost`), `restore_compare.py`,
  `restore_drivers.py` (contract + registry), `restore.py` (driver-based eligibility, unusable/legacy rows with
  reasons, foreign-pending refusal at preflight, reconnect+confirm retried for the whole window, read-back
  settlement `rolled_back`/`uncertain`, restart re-check via `RestoreService.start()`), `inventory.py` (EOS
  `.eoscfg` artifact), Junos driver contract functions and the fixed pending probe, `verify-release.py` history dir.
- Found live and fixed: `terminal width 32767` makes cEOS close the channel in the driver's read loop; the driver
  uses `terminal width 500`.
- cEOS through the manager (build 1.30.27 working tree): restore A over B `verified` in 7 s, double submit returned
  the same job, independent readback clean, running == startup, no session pending, uptime unbroken
  (`evidence/10-ceos-restore-A-over-B.json`, `evidence/11-ceos-square-after.json`).

## Verified tests

- Baseline before any change: `test_restore*.py` 29 passed; `test_restore_ui.js` 4 passed (unit).
- Live acceptance matrix: nothing run yet.

## Evidence audit of 1.30.27 (2026-09-21, workflow `evidence-matrix-audit`, 15 QA auditors + an Opus critic)

Every audited PASS came back "partly": the facts held, the committed evidence was weaker than the matrix wording.
Themes, and what was done (tools changed in the working tree, **not yet exercised live**: the nodes and the manager were busy):
- No evidence file named its build (`-wt1`/`-wt2` existed only in prose) → `manager_restore.build_identity()` (running
  image id, container start, git head, dirty count) is embedded by `manager_restore.py`, `browser_restore.py`, `interruption.py`.
- Independent readbacks lived only in raw transcripts, and "0 missing / 0 extra" was only ever computed by the manager →
  `tools/readback.py` (booleans, counts, boot identity; `--saved DIR` recomputes the whole-configuration comparison with
  its own comparator against the repository checkout) is embedded before/after by the three tools above.
- `driver_junos_live.py` judged the device with the driver's own capture and the application's comparator → now through
  `nodecli` + `readback.statements`, with the product's verdict as a cross-check; steps timestamped; both boot readings.
- `interruption.py` threw the restore record away, had no boot identity, could not see loss before the first reply, and
  every probe started at cEOS → rewritten: restore record inline, readback before/after, both edges of the restored
  node from the neighbour's side, one transit path that crosses it (CLI pings at 1 s where the source is not cEOS).
- `browser_restore.py`: vacuous checks (disabled-row over an empty set, reopen-or-ended, `collapsed[:0]`), graded "the
  newest job" → tri-state checks ("n/a" is never a pass), the job id comes from the page's own POST, `--drift` makes the
  run prove B before / A after / `no_op` false, `--via view` reaches the commit-pinned Git-version source (the row's View
  dialog), `--expect-disabled N`, `--again` (backup from the page, then a second restore in the same session),
  `--show-job ID` (renders a stored job: the real `rolled_back`/`uncertain` badges), static-asset failures are errors.
- Product gap closed: the backup source had no integrity check at all → the runner records `sha256`/`restore_sha256`
  when it stores a capture, `captured_snapshot` refuses a file that no longer matches (captures older than that carry
  no digest and are taken as they are); tests for backup, folder and Git sources; pinned in the real-Ansible pipeline test.
- Unit gap closed: restart re-check with the job's own token (confirms, verified, nothing re-applied) and with a
  foreign/unknown pending change (never confirms, `uncertain`).
- Overclaims to correct in MATRIX/README/VALIDATION with the next release: A7 "three cycles" without files for the two
  Junos images; A4's backup-source cells citing files that do not name a source; A6's boot identity cited from files that
  lack it; C2 "eligibility" (never exercised); `driver_junos_live.py`'s "independent" docstring; VALIDATION's browser
  bullet reading as if the commit-pinned source had been exercised; README recovery paragraph not naming the platforms.

**Live runs still owed for the three claimed platforms** (after the QA run `17-*` and with the new tools): per Junos image
A7 through the product (restore over B, A onto A, post-restore backup as a source), B1 (a `commit check` rejection) at
the driver layer, B3 at application time, wrong credentials at review and at application, B6 at the API (foreign pending →
409, bystander's edit → ineligible + 409); once on any platform: Save-vs-restore and lab-operation-vs-restore contention,
a real `verify_mismatch`, the real `rolled_back`/`uncertain` jobs rendered in the browser; browser: `--via view` per
platform, 390 px for the Junos images, `--again`, a disabled row (`--expect-disabled`), "nonselected nodes unchanged"
(drift two, restore one, read the other back on B).

## State on 2026-09-21 about 02:30 UTC (working tree on top of `3c5d954`, nothing of it committed yet)

**Deployed:** working-tree build of 1.30.27, image `sha256:845bcd0d…`, started 02:23 UTC (it contains a mid-rework snapshot of
`restore_iosxr.py`: redeploy when the XR builder reports). Every evidence file from `18-*` on names its build.

**XRv9k is integrated and works through the product.** Registered in `restore_drivers.DRIVERS`, `.xrcfg` artifact in
`inventory.py` (one capture), CI line added, 179+ restore tests. Live: restore A over B `verified` in 13 s
(`40-xr-restore-A-over-B.json`); all four from one saved state through the browser, 28 checks, reopen from the banner
while running, independent 0/0 comparison on all four, no restart (`50-all-four-browser-desktop.json`); mixed run with
one controlled failure: three verified, xrv9k "not changed" because a foreign trial was pending, job `partial`, the
foreign change rolled back by itself, recovery verified (`51-*`), and what the page shows for it (`52-*`).
Design fact: on IOS XR only the arming CLI session can confirm → `HOLDS_SESSION`/`release(token)` in the contract;
the service keeps the client after a successful apply, proves management with a fresh connection, confirms on the
kept session, always releases. Second Opus review of the driver: could not break "no early / no foreign confirm, no
leaks"; found F1 (release leaves our session row → `blocked()` refuses the next restore for minutes), F2 (a failing
fresh connection in `confirm` destroys the only session that can confirm), F3 (a test contradicting the no-op
evidence), F4–F7 minor. **A builder is fixing these on node xrv9k (driver layer) right now.** Live fact for F1:
`end` in the arming session with the trial outstanding asks "Do you wish to exit? [no]:" and, answered yes, rolls back at once.

**Done for the three earlier platforms since the audit** (all with device readbacks embedded): disabled row in the
browser, both reasons (`18-*`: unsupported platform on the older build, legacy save on the new one; the legacy save is
local commit `b8534ad`); nonselected nodes unchanged (`53-*`); commit-pinned Git-version source from the browser
(`54-*`); 390 px for both Junos images with restore → backup from the page → restore (`55-*`); Junos A7 through the
product: A onto A `no_op` true, restore from a post-restore backup (`56-*`); root-authentication synthesised through
the product from the evening's first backup (`57-*`); the three real `rolled_back` jobs rendered in the browser
(`58-*`). QA run `17-*` on the earlier build: Git-version source via API, cEOS B4/B5, Evolved and vJunos-switch B4,
Evolved B5 with identity surviving a manager restart — all PASS; its check 7 was blocked by a device fact now recorded
in `evo-live-facts.md` (a commit that REMOVES root-authentication is refused; a node that never had it only warns).

**Code since `3c5d954`:** digests for stored captures (`runner.py`, `git_progress.captured_snapshot`), one SSH
connection per node for the review + bounded connect retry (IOS XR refuses rapid connections), rejected credentials
as their own reason (backend + page), a failed device shows its reason beside the badge, undone devices counted apart
in the result sentence, interrupted-job message, restart re-check tests, Junos docstrings, `test_restore_compare`
registry tests for XR. Tools: `readback.py`, `interruption.py` (rewritten, **not rerun yet**), `browser_restore.py`
(rewritten), `mixed_failure.py`, `persistence_check.py` (**not run yet**), build identity in every evidence file,
cEOS boot identity = age of PID 1 (`show version` Uptime is not one).

**Running:** builder (XR review fixes, node xrv9k), QA wave two (`19-*`: B3 at application, credentials, Junos B6 at the
API, contention with Save and lab operations, a real `verify_mismatch`, Junos B1; plus `tools/failure_harness.py`),
docs-auditor (guides for IOS XR).

**Release plan:** 1.30.28 = chunk 3 (everything above that is not XR-specific, after QA wave two), 1.30.29 = chunk 4 (XR
driver + registration + inventory + CI + evidence `40-*`, `xr-live-facts.md`), 1.30.30 = chunk 5 (all-four, mixed,
persistence, final matrix). Split by reverse-applying the XR-only hunks for the first commit.

## Exact next action

1. CI for `3c5d954` is green (push and pull-request runs, 2026-09-21). Collect the QA agent's
   `evidence/17-acceptance-final-build.md`; fix what it finds (next patch release) and update `evidence/MATRIX.md`.
   Prepared in the working tree for the XR release, not committed: `inventory.py` XR artifact (`.xrcfg`, one capture)
   pinned in `test_app.py`; `tools/persistence_check.py` (restart the NOS the normal way, compare, prove the restart).
2. Chunk 4, XRv9k: a builder is reworking `app/restore_iosxr.py` onto the held-session contract (`HOLDS_SESSION`,
   `release(token)`; the service side is already in `restore.py` and tested) with the Opus review's findings. Then the
   lead's integration: `inventory.py` (`restore`/`restore_format: iosxr-running-config`/`restore_suffix: xrcfg`; the
   backup text is the artifact, one capture), `restore_drivers.DRIVERS`, the CI line for `test_restore_iosxr.py`,
   `restore.js` needs nothing (labels and `.xrcfg` are there), guides and README's XR column; Opus re-review; QA matrix
   on xrv9k through the product; re-link the lab's Git save with all four nodes (`PUT /api/labs/<id>/git`, after
   dismissing the un-uploaded save) and make a new local save.
3. Chunk 5: all four from one saved state through the browser; a mixed selection with one controlled failure;
   persistence across a controlled NOS restart on all four, in parallel (Junos `request system reboot`, XR `reload`,
   cEOS: `sudo containerlab restart -t <topology> --node ceos`, which containerlab 0.79 describes as a node restart
   with a seamless data plane; verify the links afterwards; never `docker restart` a clab node); final regression; leave the square
   healthy and the manager on the final build.
4. The user's `.claude/` routing files are uncommitted on purpose (their own configuration). The square lab's Git
   save (`9d5906d` in `~/labs/CLAB-MNGR-DEV-LLM`, one commit ahead of origin) is local and was deliberately not uploaded.
