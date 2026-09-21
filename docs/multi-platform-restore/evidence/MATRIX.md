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

## A. Complete replacement through the product

Build `1.30.27-wt2` is the working tree of release 1.30.27 as deployed on 2026-09-21 00:20 UTC (token
identity, `commit check` confirmation, orphan cleanup, submit probe); `-wt1` is the first 1.30.27 build
(2026-09-20 23:30 UTC), before the two reviews' fixes. Rows proven only on `-wt1` say so.

| Check | cEOS 4.35.0F | cJunosEvolved 26.2R1.7-EVO | vJunos-switch 23.2R1.14 | XRv9k 24.3.1 |
|---|---|---|---|---|
| A1 configuration A, data plane, boot identity | PASS `00-square-baseline.json` | PASS same | PASS same | PASS same |
| A2 A saved through the manager, restore-grade artifact, integrity | PASS backup `64bb697e…` (`.eoscfg`, byte-identical to the backup file: `test_app.py`) and Git save `9d5906d` (manifest sha256 checked by `decoded_snapshot`) | PASS `.jcfg`, same two saves | PASS `.jcfg`, same two saves | NOT RUN (no artifact yet) |
| A3 drift to B active (modify, remove, add) | PASS `lab/drift/ceos-B.cli`, device readback | PASS `lab/drift/cjunosevolved-B.cli`, `30-evo-driver-live.json` step 2 | PASS `lab/drift/vjunos-switch-B.cli`, `20-vjunos-driver-live.json` step 2 | NOT RUN |
| A4 restore A from the running UI | PASS browser, Saved versions row (folder source): `14-ceos-browser-desktop.json` 22/22, `14-ceos-browser-narrow.json` 22/22; API backup source `10-…json`, `13-…json` | PASS browser `31-evo-browser-desktop.json` 22/22; API backup source `16-interruption-cjunosevolved.json` | PASS browser `21-vjunos-browser-tablet.json` 22/22; API backup source `16-interruption-vjunos-switch.json` | NOT RUN |
| A5 independent readback: value restored, A statement back, B-only gone; whole-configuration comparison | PASS `nodecli` readback after every run above; manager `verified` 0 missing / 0 extra | PASS same | PASS same | NOT RUN |
| A6 management reconnects, square recovers, no NOS reboot; measured interruption | PASS `16-interruption-ceos.json`: 0 probes lost at 0.2 s on management, the directly connected edge and a remote loopback; longest gap 0.4 s; uptime and kernel boot id unchanged (`12-ceos-acceptance.md` A7.4) | PASS `16-interruption-cjunosevolved.json`: 0 lost, longest gap 0.26 s; `System booted` unchanged | PASS `16-interruption-vjunos-switch.json`: 0 lost, longest gap 0.21 s; `System booted` unchanged | NOT RUN |
| A7 repeat cycle, A onto A, post-restore backup as a source, nothing left pending, other nodes unchanged | PASS `12-ceos-a7-1…`, `-a7-2…` (no-op is armed and confirmed like any change), `-a7-3…`; build `-wt1`, repeated implicitly by six more cycles on `-wt2` | PASS driver layer `30-evo-driver-live.json` (A onto A, nothing pending); product: three cycles on `-wt2` | PASS driver layer `20-vjunos-driver-live.json`; product: three cycles on `-wt2` | NOT RUN |

The drift used for A6 changes a description, a static route, a prefix list and a VLAN. A restore that
changes addressing or routing on the probed path interrupts it by as much as that change does; the
measurement says that the replacement transaction itself costs nothing on these three platforms.

Source types: the page offers a saved Git version and a repository folder (the Saved versions rows apply the
folder's `latest`); the backup source is API-only. Folder source: PASS on all three (browser runs above).
Backup source: PASS on all three (API). **Saved Git version (commit + path) source: NOT RUN yet.**

## B. Failure handling and recovery

| Check | cEOS | cJunosEvolved | vJunos-switch | XRv9k |
|---|---|---|---|---|
| B1 invalid syntax / commit rejection: no false success, nothing partial, session cleaned | PASS driver+device `12-ceos-b1-invalid-candidate.json` (`-wt1`) | unit PASS; live NOT RUN | unit PASS; live NOT RUN | NOT RUN |
| B2 missing / truncated / wrong-format / legacy artifact refused before any device is touched | PASS driver `12-ceos-b2-…json`; unit PASS | unit PASS (`test_restore.py`, `test_restore_junos.py`, `test_restore_compare.py`) | unit PASS | NOT RUN |
| B3 unreachable node at the review step | PASS product `12-ceos-b3-preflight-unreachable.json` (`-wt1`) | NOT RUN | NOT RUN | NOT RUN |
| B4 management lost before confirmation: timer observed independently, state read back by the manager, later restore works | PASS product+device `12-ceos-b4-attempt5-armed-rolled-back-success.json` (+ event log, + recovery restore); attempts 1–4 are kept: they found the orphaned-session defect. Build `-wt1`; **rerun on the final build owed** | device: unconfirmed `commit confirmed 2` rolled back by itself twice, up to 35 s late, no reboot (`evo-live-facts.md` §5); product NOT RUN | device: observed (`PICKUP`); product NOT RUN | NOT RUN |
| B5 manager restart during an in-flight restore | PASS product+device `12-ceos-b5-manager-restart-rolled-back.json` (`-wt1`: target settled to `rolled_back` by the restart re-check; the job stayed `interrupted`, fixed since, unit-tested); **rerun on the final build owed** | NOT RUN | NOT RUN | NOT RUN |
| B6 foreign uncommitted session / candidate preserved; another user's pending confirmation never confirmed; double submit; contention | PASS `12-ceos-b6a…` (foreign session untouched), `13-ceos-orphan-cleanup-restore.json` (own orphan aborted, foreign one kept, `-wt2`), `12-ceos-b6b-preflight…` + `13-ceos-submit-refused-foreign-timer.json` (HTTP 409, nothing started, `-wt2`; it was HTTP 200 on `-wt1`: `12-ceos-b6b-submit-not-refused-DEFECT.json`), double submit `10-…json`, contention `12-ceos-b7-contention.json` | PASS driver layer `30-evo-driver-live.json`: foreign token refused, bystander's uncommitted edit preserved and never activated, foreign pending change refused and left to roll back, dropped exclusive session leaves nothing | PASS driver layer `20-vjunos-driver-live.json`, same 25 steps | NOT RUN |
| B7 verification fails after application: applied / verified / mismatched / rolled back / uncertain told apart | unit PASS (`test_restore.py`) | unit PASS | unit PASS | NOT RUN |

## C. Persistence, browser, mixed platforms

| Check | Result |
|---|---|
| C1 confirmed restore survives a controlled device restart | **NOT RUN** (all four). cEOS: running == startup after every restore (`show running-config diffs` empty), which is the precondition, not the proof |
| C2 browser: fresh assets, eligibility, selection, acknowledgement by keyboard, progress, reopen from the banner, reload mid-job, result, details | PASS cEOS (1366 px, 390 px), vJunos-switch (768 px), cJunosEvolved (1366 px), 22 checks each. At 390 px the manager's Progress tab itself is 431 px wide before any dialog (its lab list; the project's own verification covers 1366 px and up); the restore dialogs fit and add nothing |
| C3 all four nodes restored from one saved state | NOT RUN (needs XRv9k) |
| C4 mixed selection with one controlled failure | NOT RUN |
