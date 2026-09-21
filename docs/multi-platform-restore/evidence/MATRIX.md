# Evidence matrix

One row per acceptance check and image. **PASS / FAIL / BLOCKED / NOT RUN.** "Build" is the manager
build that produced the evidence; a row proven on an earlier build is rerun when a later change
touches its path. Layers: *product* = through the running manager's API or browser; *driver* = the
driver module called directly against the node; *device* = raw CLI through `tools/nodecli.py`;
*unit* = scripted fake device or fake connector. Raw transcripts are outside Git
(`~/research/multi-platform-restore/raw/`); the files named here are sanitized.

Images: cEOS `n24l/ceos:4.35.0F`, cJunosEvolved `n24l/cjunosevolved:26.2R1.7-EVO`, vJunos-switch
`n24l/vjunos-switch:23.2R1.14`, XRv9k `n24l/cisco_xrv9k:24.3.1` (IDs and reported NOS versions in
[PICKUP](../PICKUP.md)).

## How to read the builds

Several working-tree builds carried the release number 1.30.27. `-wt1` = deployed 2026-09-20 23:30 UTC (first cEOS
build); `-wt2` = 2026-09-21 00:16 UTC (token identity, `commit check` confirmation, orphan cleanup, submit probe; a
rebuild at 00:21 changed one sentence of the page). From `18-*` on every evidence file names its build itself
(`build`: running image id, container start, checkout commit, number of uncommitted application files), because an
independent audit of this matrix (`PICKUP.md`, "Evidence audit") found that prose was the only place the builds were told
apart. The same audit is why the newer files embed the devices' own answers (`tools/readback.py`: booleans, counts and boot
identity, never configuration text) and an independent whole-configuration comparison; where an older row rests on raw
transcripts outside Git or on the manager's own report, the row says so.

## A. Complete replacement through the product

| Check | cEOS 4.35.0F | cJunosEvolved 26.2R1.7-EVO | vJunos-switch 23.2R1.14 | XRv9k 24.3.1 |
|---|---|---|---|---|
| A1 configuration A (interfaces, loopback, OSPF, static route, prefix list), data plane, boot identity | PASS reachability and boot identity `00-square-baseline.json`; that A itself is active: `readback` inside `53-*`…`57-*` (markers + whole-configuration comparison with the saved files) | PASS same | PASS same | reachability PASS `00-…json`; configuration NOT RUN |
| A2 A saved through the manager's normal workflow, restore-grade artifact, integrity | PASS: backups `64bb697e…`, `177b0f23…` and the *Save progress* saves `9d5906d`, `366c21f` were real restore sources (rows A4, A7). Integrity: Git and folder sources are checked per file against the manifest (size, SHA-256) at restore time; a backup is checked against the digest the runner recorded when it stored it (since this release; older backups carry none). Both are unit-tested with tampered files (`test_restore.py`), the pipeline with real Ansible (`test_app.py`); no live tamper test was run | PASS same | PASS same | NOT RUN |
| A3 drift to B active: a value modified, a statement removed, B-only stanzas added | PASS: `device_readback_before` says B in `53-*` (markers for all three kinds of drift) | PASS `54-*`, `55-*`, `57-*` readback before; driver layer `30-evo-driver-live.json` | PASS `54-*`, `55-*` readback before; driver layer `20-vjunos-driver-live.json` | NOT RUN |
| A4 restore A from the running UI, every source type the page offers | PASS folder source `14-ceos-browser-desktop.json`, `-narrow.json`, `53-*`; commit-pinned Git-version source (the row's View dialog) `54-browser-git-version-source-three.json`; backup source (API only) `10-*`, `13-*` | PASS folder `31-*`, `55-*`; Git version `54-*`; backup (API) `56-*`, `57-*` | PASS folder `21-*`, `55-*`; Git version `54-*`; backup (API) `56-*` | NOT RUN |
| A5 independent readback through a fresh device connection; whole configuration compared | PASS `53-*`, `54-*`: markers (value restored, statement back, B-only gone) and `tools/readback.py`'s own comparator against the saved files: 0 missing, 0 extra; the manager's `verified` 0/0 agrees. Earlier runs (`10-*`, `14-*`): manager report plus raw transcripts outside Git | PASS `54-*`…`57-*` same; `57-*` reports the one tolerated difference (the synthesised root-authentication) | PASS `54-*`…`56-*` same | NOT RUN |
| A6 management reconnects, links recover, no NOS restart; measured interruption | PASS no restart: boot identity before/after in `53-*`, `54-*` (cEOS: age of PID 1; `show version` Uptime is not a boot identity there). Interruption `16-interruption-ceos.json` (`-wt2`): 0 of the 0.2 s probes lost on management, the cEOS–cJunosEvolved edge and a remote loopback. **Not yet measured:** the edge to XRv9k, a path that transits cEOS, loss outside the first/last reply (tool rewritten, rerun owed) | PASS no restart `54-*`…`57-*`. Interruption `16-…-cjunosevolved.json`: 0 lost on management, the cEOS edge and its loopback; same limits, rerun owed | PASS no restart `54-*`…`56-*`. Interruption `16-…-vjunos-switch.json`: 0 lost on management and one two-hop path; its own edges were not probed, rerun owed | NOT RUN |
| A7 repeat cycle, A onto A, post-restore backup as a source, nothing pending, nonselected nodes unchanged | PASS `12-ceos-a7-1…3` (`-wt1`); nonselected: `53-browser-nonselected-unchanged.json` (two nodes drifted, only cEOS restored, vJunos-switch read back on B, the job lists one device) | PASS through the product `56-junos-a7-A-onto-A.json` (`no_op` true, verified, nothing pending), `56-…-restore-from-post-restore-backup.json`; driver layer `30-*` | PASS `56-*` both files; bystander in `53-*`; driver layer `20-*` | NOT RUN |

The drift changes a description, a static route, a prefix list and a VLAN. A restore that changes addressing or
routing on a probed path interrupts it by as much as that change does.

## B. Failure handling and recovery

| Check | cEOS | cJunosEvolved | vJunos-switch | XRv9k |
|---|---|---|---|---|
| B1 invalid syntax / commit rejection | PASS driver+device `12-ceos-b1-invalid-candidate.json` (`-wt1`; the candidates and the device's words are in raw transcripts only) | unit PASS; live in progress (QA wave two) | unit PASS; live in progress | NOT RUN |
| B2 missing / truncated / wrong-format / legacy artifact, integrity mismatch | PASS driver `12-ceos-b2-…json`; legacy rows through the product `57-*` (the evening's first backup: cEOS and XRv9k listed with "no restore data"); unit PASS incl. tampered files | unit PASS | unit PASS | NOT RUN |
| B3 unreachable node / rejected credentials, at the review and at application | review: PASS `12-ceos-b3-…json` (`-wt1`); application and credentials: unit PASS, live in progress (QA wave two) | live in progress | live in progress | NOT RUN |
| B4 management lost after arming: timer observed independently, read-back by the manager, later restore works | PASS `17-02-check2-…json` (`-wt2`): armed under the job token, EOS reverted at +126 s (seen through `docker exec … Cli`), the manager read B back → `rolled_back`, no own session left pending, recovery restore verified. `12-ceos-b4-*` (`-wt1`) kept: its attempts found the orphaned-session defect | PASS `17-04-check4-…attempt4…json`: rollback time from the device's commit log, manager waited and said `rolled_back`; recovery `17-04-…-recovery-…json` | PASS `17-05-check5-…json` + recovery | NOT RUN |
| B5 manager restart during a restore; SSH loss after activation | PASS `17-03-check3-…json` (`-wt2`): target settled by the restart re-check, job recomputed ("Checked after a manager restart."), nothing re-applied | PASS `17-06-check6-…json`: SSH left reachable; after the restart the pending change was found under the job's own token, confirmed and `verified` | unit PASS (shared restart logic; the Junos mechanism is the one proven on Evolved) | NOT RUN |
| B6 foreign session / candidate / pending confirmation; double submit; contention | PASS `12-ceos-b6a…` (the restore in it was a no-op), `13-ceos-orphan-cleanup-restore.json` (own orphan aborted, foreign one kept, during a restore that changed configuration), `13-ceos-submit-refused-foreign-timer.json` (HTTP 409, nothing started), double submit `10-*`, backup contention `12-ceos-b7-…json`; Save and lab-operation contention in progress | driver layer PASS `30-*`; at the API: in progress (QA wave two) | driver layer PASS `20-*`; at the API: in progress | NOT RUN |
| B7 applied / verified / mismatched / rolled back / uncertain told apart, API and page | unit PASS; real `rolled_back` jobs rendered in the browser `58-browser-rolled-back-job-1…3.json`; a real `verify_mismatch`: in progress | same files (job 2) | same files (job 3) | NOT RUN |

## C. Persistence, browser, mixed platforms

| Check | Result |
|---|---|
| C1 confirmed restore survives a controlled NOS restart | **NOT RUN** (tool `tools/persistence_check.py` written, not run) |
| C2 real browser against the deployed manager and the real nodes | PASS: fresh assets, device-type labels, selection, acknowledgement refused without the tick, Space and Enter by keyboard, progress, **reopen from the banner while running** (`54-*`, `55-*`: the Junos restores last long enough; on cEOS the job is over first and the check is recorded as not exercised), reload mid-job, result, both backups under Details; a disabled row with its reason `18-browser-disabled-row-unsupported-platform.json`; restore → backup from the page → restore again in one session at 390 px for both Junos images `55-*`; the tools count a check that could not be exercised as "n/a", never as a pass. At 390 px the Progress tab itself is 431 px wide before any dialog; the restore dialogs fit and add nothing |
| C3 all four nodes from one saved state | NOT RUN (XRv9k is not restorable in this release) |
| C4 mixed selection with one controlled failure | NOT RUN |
