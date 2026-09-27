# Relentless netlab UI/UX QA campaign and Restart device: final report

Campaign of 2026-09-27 on `claude/netlab-integration`, from release 1.30.47 (`3194ec4`) to **release 1.30.48**
(`b4329d3`, PR #56, CI green). The assignment was the owner's `CLAB_Netlab_Relentless_UI_UX_QA_Campaign_v2.md`
with the folded-in `CLAB_Single_Device_Restart_Addendum.md`. Companion records in this folder: `PICKUP.md`
(state), `DEFECTS.md` (ledger), `RESTART-PARITY.md` (parity record), `EVIDENCE.md` (index), `COVERAGE.md` /
`coverage.json` (inventory and results), `probes-report.md`, `usability-report.md`, `evidence/stress/REPORT.md`,
`acceptance/` (the two independent passes).

## Implemented: individual-device restart

**Restart device** restarts one device of a deployed lab through containerlab's own node-scoped restart, the
operation the Containerlab VS Code extension's *Restart node* runs (extension source at `6df8e96`, 0.26.3:
`nodeActions.ts` → `clabCommand.ts` → `containerlab restart --node`). Nothing is substituted: no `docker restart`,
no SSH or NOS reboot, no destroy/redeploy.

- **Command on the VM** (built by the sudoers helper, fixed argv, no shell):
  `containerlab restart -t <topology file> --name <lab> --node <device>`, exactly one `--node`.
- **UI paths**: right-click a device on the lab map → *Restart device…*; Devices view or the device panel →
  *Details* → *Restart device…* (keyboard reachable: Tab to the button, Enter). Both open the same review, which
  names the device and the lab, lists that one device as affected, says that its CLI sessions and traffic through
  it drop and that neighbours lose their adjacencies to it, that nothing is saved, backed up, reset or reapplied,
  and names the image's known limits (below). The confirm button is the destructive *Restart device*; Cancel and
  Escape return focus to what opened the review. The lab-wide action is now *Restart all devices…* with the same
  vocabulary.
- **Exact-target validation**: the helper (`host_operations.py`, action `restart-node`) accepts one literal node
  name (`[A-Za-z0-9_][A-Za-z0-9_.-]{0,119}`) and the container it must be (`<prefix>-<lab>-<node>`,
  `<lab>-<node>` or `<node>`), refuses every other shape (a list, `a,b`, an option-like value, an unknown or
  other-lab node, any option), builds exactly one `--node` and binds the container's id and state into the review
  digest, so a redeploy, start or stop between review and run is refused. The manager resolves the page's device
  against the topology file on the VM, refuses page-supplied selectors and paths, takes the review stamp under its
  first lock and refuses a confirmation once another lifecycle operation ran after the review or the device no
  longer resolves to the same container. There is no fallback to the lab-wide restart.
- **Readiness and session recovery**: the readiness monitor has an epoch (`forget()`); a login probe that began
  before the restart was accepted can never mark the device ready; the device reads *Restarting* while the job
  runs, then *Starting* until a fresh login and `show version` prove it, and the lab header names it. The browser
  CLI shows the disconnection and offers *Reconnect*, which gives a fresh session with nothing replayed; a new
  capture resolves the restarted device's interfaces. A device restarted outside the manager (VS Code, CLI) is
  re-checked when the runtime's status line shows an uptime younger than its last proof.
- **Outcome honesty**: the job message counts the links containerlab restored (`3 links restored`, `2 of 3 links
  restored (no link to host1 …)`, `no links restored (…redeploy…)`); a container that exits right after starting
  makes the job *failed* with the state, the runtime's status line, the known limit and *Redeploy the lab*.

### Per-image results (one instance of each baseline image, lab `restore-square`, containerlab 0.79.0)

| Image | Result | Evidence |
|---|---|---|
| `n24l/ceos:4.35.0F` | PASS. Map, Devices (keyboard) and stopped→restart paths; same container id, 3 links restored each time, *Ready* in ~20 s; CLI reconnect, new capture, design and Git binding untouched. 66/66 on the 1.30.47 working tree, **78/78 on the final build** (no known-limit note for this image). Saved configuration survives, running-only changes do not, nothing is saved by the manager (persistence markers). | `evidence/restart/ceos-2026-09-27T164553+0000.json`, `ceos-2026-09-27T134146+0000.json` |
| `n24l/cjunosevolved:26.2R1.7-EVO` | PASS. Two restarts of one container, 2 links restored each, *Ready* after 7.4 and 8.7 min (its launcher waits ~5 min for its interfaces before starting the VM); the path through it recovered after each boot. 50/51 on the reviewed 1.30.47 tree (the one failure was the capture port mapping, QA-013, fixed and proven on the other images), **27/27 on the final build** (20:13 UTC: the VM had hung after the last redeploy and the product's restart brought it back; *Ready* after 7.5 min, configuration A reapplied). | `cjunosevolved-2026-09-27T142051+0000.json`, `cjunosevolved-2026-09-27T201300+0000.json`, traffic `cjunosevolved-run2-traffic-from-ceos.jsonl` |
| `n24l/vjunos-switch:23.2R1.14` | **Known limit, reported honestly.** The image's launcher renames `init.conf` on the first start and fails without it, so its container cannot start a second time: `containerlab restart --node` exits 0 and the container exits 0.2 s later. The review names the limit before the student confirms; the job ends *failed* with the reason and *Redeploy the lab* (QA-014). Proven twice (14:47 on the tree without the outcome check: a false success, fixed; 15:53 on the fixed tree: the failed job). On the final build the note is verified through the API preview and the review text, not by running it. | `vjunos-switch-2026-09-27T155300+0000.json`, `preview-warnings-1553.json` |
| `n24l/cisco_xrv9k:24.3.1` | PASS with a **known limit**: three restarts of one container (map, Devices, stopped→restart), 2 links restored each, *Ready* after 11.2 / 5.1 / 5.1 min, 75/75 on the 1.30.47 tree and 27/27 + 52/52 + 27/27 on the final build. The first restart after a deploy boots the VM from a fresh disk (the launcher picks its disk by sorted file name; a second copy of the pristine image sorts first after the first start), so the device comes back *Ready* with its factory configuration (QA-017); a configuration applied after that first restart survives the next ones (proven: Loopback0 and OSPF FULL after the 17:19 restart). The review names the limit. | `xrv9k-2026-09-27T152910+0000.json`, `…T165016…`, `…T170416…`, `…T171848…`, `xrv9k-traffic-from-ceos.jsonl` |
| `host1` (Linux, `network-multitool`) | PASS: the adversarial two-tabs check (a double click makes one job; an older tab's review is refused after the restart; two simultaneous confirmations start at most one job) 13/13, three times. | `two-tabs-host1-*.json` |

### Restart limits found and named in the product

1. vJunos-switch cannot start its container a second time (above).
2. XRv9k's first restart after a deploy loses the device's configuration (above); back up first, *Replace
   running configuration* afterwards.
3. A restart restores only the links whose other end still exists: a neighbour stopped by the manager, the
   extension or `containerlab stop` keeps its ends parked and the link comes back (proven: `3 links restored`);
   a neighbour that exited on its own or was `docker stop`ped took the link with it, the job says `n of m links
   restored`, and the restarted device waits for the missing interface before it boots: cEOS for the five minutes
   containerlab's `CLAB_INTFS` gives it, a vrnetlab VM for good (proven on XRv9k, stuck at *Starting*, and on
   cEOS, *Ready* after the timeout). The review names the neighbour and both cases (QA-018).
4. Not exercised: a paused container; root-namespace, auto-remove, multi-container and `network-mode:
   container:` nodes (containerlab refuses them; the job would fail with containerlab's own reason).

## Versions and commands tested

- Manager 1.30.48 (`clab-backup:1.30.48`), helpers 1.30.48; the same working tree at 1.30.47 for the earlier live
  runs (13:37, 14:45 and 15:16 UTC builds). Dev VM `clab-llm-dev2`: Docker 29.8.1, containerlab 0.79.0
  (`restart --node` present), Python 3.12.3, Node 18 (system) / 24 (editor bundle only). Browser evidence:
  Chromium 153.0.8010.12 through Playwright 1.63.0 (Firefox 155.0 for the usability review; WebKit could not launch).
  Engine: the pinned `netlab==26.9`. Extension reference: `6df8e96` (0.26.3).
- Suites on the final tree: `python -m unittest discover -s tests -t tests` → 1701 OK (1 skipped);
  `node --test tests/*.js` → 379 pass; `deploy/verify-release.py` and `check_links.py` clean; CI runs
  36339238311 and 36339241324 green.
- Live tools (all in `tools/`): `check_restart_device.py` (both entry points, stopped path, terminal reconnect,
  new capture, design non-mutation, the known-limit note per image), `check_restart_two_tabs.py`,
  `check_restart_neighbour.py` (both stop modes), `traffic_probe.py`, `persistence_markers.py`; fixture tools:
  `coverage_run.py`, `probes/design_probes.py`, `check_design_poll_retry.py`, `stress_design.py`,
  `usability_scan.py`, `inventory_dom.py`; plus `docs/netlab-integration/tools/check_design_ui.py`.

## The Design tab: what was found and repaired

- **Inventory**: 123 rows (`COVERAGE.md`), 17 transitions, three sources compared. **Coverage closure** on the
  final tree: **112 PASS, 0 FAIL, 8 BLOCKED, 3 NOT RUN** (below).
- **Defects** (`DEFECTS.md`, every one with a regression test): QA-001…QA-018 (P1: QA-003, QA-004, QA-006,
  QA-007, QA-014, QA-017, QA-018; the rest P2/P3), U-01…U-21 from the independent usability review, RD-001…RD-004
  from the pre-release Opus reviews. Highlights: guided edits no longer drop pool keys or reflectors; invalid
  Advanced text blocks Save/Check/Generate and stays on screen; Generate saves first; a save answered after a lab
  switch lands nowhere; polls retry five times then say *Plan progress unknown*; History › View opens any earlier
  plan; a BGP AS of 0 is refused; an older design answer never paints over a newer one (QA-015); names follow
  netlab's 16-character identifier rule at Save (QA-016); every dialog is named and returns focus; the More menu
  never opens off screen; Capture traffic… recognises Junos and IOS XR ports (QA-013).
- **Probes** (`probes-report.md`): all ten §6 hypotheses reproduced, fixed, and their bug-side checks now fail.
- **Stress, race, longevity** (`evidence/stress/REPORT.md`): core loop ×25, 100 mixed actions, 30 minutes idle
  with a flat DOM, the 20-generation retention boundary, 20/20 cross-lab race replays clean; the out-of-order
  poll race and the identifier limit found and fixed; two observations recorded unchanged (generation time near
  the cap, the heartbeat's rate in a hidden tab).

## Intentionally removed functionality: None

No capability was removed. The lab-wide *Restart devices* was renamed *Restart all devices…* and keeps its
behaviour. Three UI-review-001 browser tools (`check_ui005/007c/008a`) fail identically on the untouched HEAD and
are recorded as tooling debt (TOOL-001), not touched.

## BLOCKED and NOT RUN, named

- Coverage rows BLOCKED (need a reachable device behind the Apply review; each cites the 1.30.45–1.30.47 live
  record that covers it): ND-APPLY-007, -008, -012, -013, -014, -017, ND-ERROR-007, ND-PLAN-009. NOT RUN
  (covered by named unit tests): ND-APPLY-016, ND-GENERATE-005, ND-PLAN-004.
- Not run live: the extension's own UI (its source and the identical command were exercised); a paused
  container; WebKit; vJunos-switch on the final build (API preview and review text only, by design); the stopped→restart
  and Devices-view paths on cJunosEvolved on the final build (only the map path ran there, after its VM hung).
- Not rebuilt: the browser Wireshark stack (unchanged in this release).

## Acceptance passes

Two independent clean passes on the same final build (1.30.48, `b4329d3`), run one after the other by fresh
agents with no knowledge of this session, following the same script (static, unit, fixture, live, ledger
spot-checks):

1. **Pass 1, Sonnet** (`acceptance/PASS-1-sonnet.md`, evidence `acceptance/pass-1/`, 19:29–20:11 UTC): **CLEAN**.
   Static clean; Python 1701 OK, browser 379; `check_design_ui` 29/29, poll retry 9/9, stress race 80/80 and bulk
   43/43, coverage 112/0/8/3, probes run; live: cEOS 78/78 with the traffic probe's loss windows lining up with the
   four restarts and zero loss on the other path, two-tabs 13/13, neighbour (parked case) 20/20, both known-limit
   previews verbatim, XRv9k 27/27 with the configuration loss on the first restart after the redeploy reproduced,
   configuration A reapplied and read back; seven regression tests rerun singly. Its one finding (F1): three of the
   probe script's own "bug present" assertions were stale (P7 read the wrong element, P8 the wrong moment, P10 left
   invalid values before its final Save), not product regressions; corrected afterwards and re-verified
   (`probes-report.md`, corrections section).
2. **Pass 2, Opus** (`acceptance/PASS-2-opus.md`, evidence `acceptance/pass-2/`, 20:22–20:49 UTC): **NOT CLEAN**, four
   findings, everything else passed (static, Python 1701, browser 379, `check_design_ui` 29/29, poll retry 9/9, stress
   80/80 and 43/43, coverage 112/0/8/3 row for row, its own QA-012/QA-016 API check 16/16, cEOS 78/78, two-tabs 13/13,
   neighbour 20/20, previews and three refusals 20/20, a read-only QA-013 check 8/8, XRv9k 27/27 with the configuration
   surviving this later restart; eight regression tests broken on purpose and seen failing). The findings: **F-1** trailing
   whitespace in three evidence files of the release commit (fixed; the staged tree is now checked); **F-2** during every
   XRv9k restart the device read a red credentials failure for 1.5–4.5 minutes before *Ready*, because IOS XR answers SSH
   before it accepts logins (**QA-019**, a real P2, fixed with a login grace window after a manager-driven restart, start
   or deploy); **F-3** the committed probe script's three stale assertions (already corrected, TOOL-003); **F-4** two
   live-check assertions that could not fail, one of which is how F-2 slipped through (TOOL-002, fixed).
3. Because a product change followed, the gate "two clean passes on the same final build" restarted on **1.30.49**
   (QA-019 retested live first: XRv9k `booting → ready` with no `failed` state, `xrv9k-2026-09-27T205833+0000.json`).
   The two passes on 1.30.49 are taken after the 1.30.49 commit and recorded in the evidence commit that follows:
   `acceptance/PASS-3-*.md` and `PASS-4-*.md`.
