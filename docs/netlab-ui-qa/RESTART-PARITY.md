# Restart device: parity record

The compact record the campaign asks for: what the reference does, what the manager does, where they
deliberately differ, and what was proven live on which build. Per-image results are appended as the
live runs complete; a case that was not run says so.

## Reference

| Item | Value |
|---|---|
| Extension | `srl-labs/vscode-containerlab` commit `6df8e9629a0dfca625d162498aa976d49845a342`, `package.json` version **0.26.3** (source fetched 2026-09-27; the extension UI itself was not run in this campaign, see "Deliberate differences") |
| Reference command | `src/commands/nodeActions.ts` → `runTopologyNodeLifecycleAction("restart", node)` resolves the node name as `rootNodeName` → `name_short` → `name`, needs the lab's topology path, and runs `ClabCommand("restart").run(["--node", nodeName])`; `src/commands/clabCommand.ts` builds `containerlab restart -r <runtime, default docker> --node <node> -t <topology path>` |
| Containerlab on the VM | **0.79.0** (commit `5ae50094a`, 2026-08-21), runtime Docker 29.8.1; `containerlab restart --help` offers `-n/--node` (repeatable or comma-separated), `-t/--topo`, `--name`, `-r/--runtime` |
| Documented semantics | `docs/cmd/restart.md` + `start.md`: a lifecycle-aware stop+start; for running nodes containerlab parks the dataplane interfaces before the stop and restores them on start; for already stopped nodes it performs the start/restore phase; without `--node` every node of the lab is restarted. Limitations: only veth dataplane links, no root-namespace nodes, no `auto-remove` nodes, single-container nodes only, no `network-mode: container:<…>` users or providers |

## What the manager runs

The helper (`app/host_operations.py`, installed on the VM as the sudoers helper `clab-manager-operate`)
builds, for the new action `restart-node`:

```text
/usr/bin/containerlab restart -t <trusted topology path> --name <deployed lab name> --node <topology node>
```

Exactly one `--node`, carrying the literal topology node name the manager resolved from its own node
record and verified against the topology file on the VM; the container that node must be
(`<prefix>-<lab>-<node>`) is bound into the review together with its container id and state, so a
redeploy, start or stop between review and run is refused at run time. A request without a valid
selector (absent, blank, a list, `a,b`, `--node`, an unknown node, a node of another lab) is refused
before any command is built and can never reach the lab-wide `restart`.

## Deliberate differences from the extension

| Extension | Manager | Why |
|---|---|---|
| Runs as the VS Code user on the host with whatever containerlab rights that user has | Runs through the structured SSH gateway and the restricted sudoers helper, inside the trusted lab roots, under the one host lock, same-release checked | The manager's standing boundary: no Docker socket, no shell, fixed argv |
| No confirmation; the node name comes from the tree item | A reviewed operation: the review names the device and the lab, what drops (its CLI sessions and traffic through it, neighbours' adjacencies to it), that nothing is saved, backed up, reset or reapplied, and lists that one device as affected; one confirmation | The product's safety contract for every lab command |
| `-r docker` is passed explicitly (from the extension setting) | No `-r`: containerlab's default runtime, the same runtime whose `inspect` produced the container identity bound into the review | Passing a runtime the manager did not verify would be a second source of truth; on this VM the default is Docker and the resulting command is otherwise the extension's |
| Passes `-t <topology>` only | Also `--name <lab>` when the installed `restart` offers it (as every other lifecycle action of the manager does) | A lab deployed under a name other than the topology's `name` is addressed the way the manager addresses it everywhere |
| The extension has no cancel for a running node restart; closing its output channel changes nothing | The same: the operation output window can be closed while the job runs (the job continues and stays in the operation history); there is no cancel button, so closing is never mistaken for cancelling, and the job's outcome reaches the banner and history either way | containerlab offers no safe mid-transition stop |
| Reports success when the command exits | Also looks at the container again a moment after a successful command: an image that exits right after starting (vJunos-switch) makes the job fail with the reason, not succeed | A successful CLI exit is not a running device either |
| Reports success when the command exits | Reports the exit code, containerlab's own log, the number of `Restored link` lines, then drops the device's proven login: the device reads *Restarting*, then *Starting*, and *Ready* only when it answers `show version` again (a probe from before the restart is discarded by the readiness epoch) | A successful CLI exit is not a booted NOS |

## Findings from the mechanism probes (host1, containerlab CLI, 2026-09-27 13:32–13:34 UTC)

- **Running node, reference command** (`containerlab restart -r docker --node host1 -t …`): 0.3 s; the
  container kept its id (`27bd5e30d351…`), got a new `StartedAt`, `RestartCount` stayed 0 (Docker's
  counter counts restart-policy restarts only, so it is no oracle); `eth1@if159` and `eth2@if162` came
  back with the same peer indexes; the four other containers kept id, `StartedAt` and pid. Output:
  `Restored link node=host1 interface=eth1`, `… interface=eth2`.
- **Stopped with `containerlab stop --node host1`, then `restart --node`**: the stop parked both links;
  inspect showed `exited`, `Exited (137) Less than a second ago`; the restart took the start/restore path
  and restored both links (same peers).
- **Stopped with `docker stop` (outside containerlab), then `restart --node`**: the container came back
  (exit 0) **without** `eth1`/`eth2` and no `Restored link` line; the veth pairs had been destroyed with
  the container's namespace, taking the neighbours' ends with them (`vjunos-switch:eth3` and `ceos:eth3`
  were gone). This is the documented limitation; the manager's review warns about it for a stopped
  device and the job message says `no links restored` in that case. The lab was repaired with
  `containerlab tools veth create` (both pairs) and, on vJunos-switch, the tap redirect for the recreated
  `eth3` was re-added by hand; cEOS picked the recreated `eth3` up as `Et3 connected` on its own.
- **Status line for health-checked containers**: containerlab's `inspect` reports `status: "healthy"`
  (not `Up N minutes`) for vJunos-switch and XRv9k, so the manager's uptime hint for restarts done
  outside the manager applies only to containers without a health check (cEOS, cJunosEvolved, host1
  here); the others are caught only by a state change discovery sees, or by *Test logins*.

## Supported-state matrix (native behaviour, as observed or documented)

| Target state | Native result | Manager |
|---|---|---|
| running | stop, park links, start, restore links | offered; review lists the device as `running` |
| exited after `containerlab stop` / the extension's *Stop node* / the manager's *Stop devices* | start, restore parked links | offered; review carries the start/restore warning |
| exited after `docker stop` | start; no links to restore | offered with the same warning; job message `no links restored (…redeploy…)` |
| absent (destroyed, not in `inspect`) | — | refused by the helper (`is not deployed in lab …`) and greyed out in the UI (`… is not deployed on the VM`) |
| running, image that cannot start twice (**vJunos-switch 23.2R1.14**) | `containerlab restart --node` exits 0; the container starts and exits 0.2 s later with exit code 1: the vrnetlab launcher renames `init.conf` to `juniper.conf` on the first start and fails with `FileNotFoundError: init.conf` on any later start (`/launch.py` lines 60–110 of the image). The extension's command behaves the same. Only a redeploy recreates the node | the review carries the known limit for this kind; the job looks at the container again after the command and reports **failed** with the state, the runtime's status line and the way out (Redeploy lab), instead of a success that the device list then contradicts |
| running, image whose launcher boots a fresh disk on the first restart (**XRv9k 24.3.1**) | `containerlab restart --node` exits 0, the container keeps its id and its links are restored, the device comes back `Ready`, but with its factory configuration: `/launch.py` chooses the VM disk by sorted file name and a second copy of the pristine image sorts first after the first start (QA-017) | offered; the review names the limit (back up first, *Replace running configuration* afterwards); the job reads `succeeded` because nothing the manager can see went wrong |
| running, a neighbour's container exited (any image; worst for VM images) | `containerlab restart --node` exits 0 and restores only the links whose other end still exists (`Restored link` per link); the link to the exited neighbour stays missing; a vrnetlab launcher then waits for its provisioned interfaces and never starts the VM (XRv9k, 16:01 UTC: `waiting for provisioned interfaces to appear…`, *Starting* for good) | offered; the review names the neighbour and both cases (a neighbour stopped with `containerlab stop` keeps its ends parked and the link comes back, proven on cEOS/host1 16:49 UTC: `3 links restored`; one that exited on its own or was `docker stop`ped took the link with it) and says to start it first; the job reads `n of m links restored (no link to …: not running, its link was gone; …)` when fewer came back (QA-018) |
| paused | not run in this campaign | offered (state shown in the review); result would be containerlab's own |
| root-namespace / auto-remove / multi-container / `network-mode: container:` | refused by containerlab (documented) | offered; the job fails with containerlab's own reason (no such node in this lab) |

## Per-image results

Filled in from `evidence/restart/*.json` as each run completes (build, entry point, before/after ids and
start times, links restored, readiness timestamps, traffic probe).

| Image | Build | Running (map) | Running (Devices, keyboard) | Stopped → restart | Repeat after recovery | Notes |
|---|---|---|---|---|---|---|
| `n24l/ceos:4.35.0F` | 1.30.47 working tree (commit pending), containerlab 0.79.0, Chromium 153.0.8010.12 | PASS 13:41:52 UTC: job exit 0, `3 links restored`, id `e0c7880e10fb` kept, StartedAt 13:10:08 → 13:41:53, the other four containers unchanged (id, StartedAt, pid); device read *Restarting*, then *Starting* (booting) at 13:41:54, *Ready* at 13:42:15 with a fresh check (13:42:14 > job end) | PASS 13:42:21: Devices tab → Details (Enter) → Tab to *Restart device…* → Enter; same review, same evidence; StartedAt → 13:42:22, Ready 13:42:44 | PASS: `containerlab stop --node ceos` (exited, rail read *Unavailable*), menu item enabled, review carried the start/restore warning and `exited`; job `3 links restored`, StartedAt → 13:43:24, Ready 13:43:52 | The Devices run is the repeat after recovery (map run recovered first): no leaked parking state, links `eth1@if153 eth2@if156 eth3@if172` identical across all three runs | Traffic (cJunosEvolved → cEOS lo `10.255.0.1` vs → XRv9k lo `10.255.0.4` every ~7 s, `evidence/restart/ceos-traffic-from-cjunosevolved.jsonl`): the crossing path lost 100 % during each restart and recovered; the other path never lost a packet. cEOS boots in ~20 s here. The lab's network design (revision `c80a6c72…`, updated 02:53 UTC, 9 generations) and its Git binding were unchanged after the three restarts (read from `/api/labs/<id>/design` at 13:47 UTC). 66 checks, 0 failed (`evidence/restart/ceos-2026-09-27T134146+0000.json`, 11 screenshots) |
| `n24l/cjunosevolved:26.2R1.7-EVO` | first run 1.30.47 working tree before the review fixes (13:44–14:17 UTC); **second run on the reviewed build 14:20–14:40 UTC: 51 checks, 50 passed** (`evidence/restart/cjunosevolved-2026-09-27T142051+0000.json`): map restart 14:20:55 (21 s), *Ready* 14:28:19; the Devices restart issued 7 s after that readiness (14:28:26, 68 s) booted normally this time, *Ready* 14:38:17 (8.7 min); same id, 2 links restored each time, others untouched, design untouched; traffic (cEOS → cJunosEvolved lo vs → XRv9k lo, `cjunosevolved-run2-traffic-from-ceos.jsonl`): the crossing path was lost from 14:21 until the second boot finished and recovered at 14:39, the other path never lost a round. The one failed check was the capture dialog's port mapping (QA-013, a pre-existing bug fixed after this run). The first run's stalled second boot therefore did not recur; it stays recorded as an image hazard seen once (UEFI/GRUB stall) | PASS 13:44:56: job exit 0 in 20 s, `2 links restored` (`eth4@if154`, `eth5@if158`, the container-side names of `et-0/0/0`, `et-0/0/1`), id `edc84f99ebdb` kept, StartedAt 13:10:08 → 13:45:16, the other four untouched; *Restarting* → *Starting* 13:45:17 → *Ready* 13:51:59 (fresh check). A browser CLI opened before the restart showed *Disconnected*, offered Reconnect, reconnected once the device was Ready, and replayed nothing | Restart executed correctly 13:52:10 (68 s: the launcher's graceful EVO shutdown), StartedAt → 13:53:18, links back, others untouched, design untouched — but the NOS did **not** accept a login within the 780 s budget: the container log shows the launcher's usual ~5.3 min interface wait (counter 60), the VM launched 13:59:03 and then sat in UEFI/GRUB for over 10 minutes (no `login:` line before the next stop at 14:08:52; the third boot then says *Coming back from an uncontrolled reboot, will recreate /data!*). Recorded as an image boot stall after a restart issued seconds after readiness; repeated on the reviewed build with a 1200 s budget (see the second run) | PASS: `containerlab stop --node cjunosevolved` (exited), review with the start/restore warning, job 14:08:52 `2 links restored`, StartedAt → 14:08:53, *Ready* 14:16:21 (launcher wait to 14:14:12, VM boot done 14:15:27, 42 s) | The stopped-path run is a repeat after the second restart; the second run repeats map → Devices back to back | Traffic (cEOS → cJunosEvolved lo `10.255.0.2` vs → XRv9k lo `10.255.0.4`): the other path never lost more than a single 2-packet round (6 rounds at 50 %, none at 100 %); the crossing path stayed lost from 13:45 until the probe ended at 14:17, consistent with the stalled second boot (the first boot's 11 s of readiness before the second restart left no time for OSPF to re-form). Capture right after the first readiness: the dialog listed interfaces but said the diagram ports `et-0/0/0`, `et-0/0/1` were not found; 30 minutes later `/api/capture/targets` lists `eth4`, `eth5` for the container (open: QA-013). 73 checks, 3 failed (`evidence/restart/cjunosevolved-2026-09-27T134447+0000.json`) **Final build (20:13 UTC, `cjunosevolved-2026-09-27T201300+0000.json`): 27/27** from the map after the VM had hung following the 18:45 redeploy (guest soft lockups, no login for 35 min): the restart through the product brought it back, job 20:13:05–20:13:34, `2 links restored`, *Ready* 20:20:35, configuration A reapplied at 20:21. |
| `n24l/vjunos-switch:23.2R1.14` | 1.30.47 working tree (usability batch deployed 14:45 UTC, before the outcome check existed) | **Restart executed, device lost:** job 14:47:19 exit 0 in 30 s, `3 links restored`, id `ec830d4fa6c4` kept, StartedAt → 14:47:49, then the container exited with code 1 at 14:47:49.7: the vrnetlab launcher fails on `open("init.conf")` (renamed to `juniper.conf` on the first start). The other four containers were untouched. The device read *Unavailable*; the browser CLI showed *Disconnected* and Reconnect refused because the device was not running; the capture dialog found no running device. On that build the job still read *succeeded* (QA-014, fixed since: the job now fails with the reason) | Executed on the exited container at 15:13:41 (start path): exit 0, `no links restored`, the container exited again at 15:13:42 | not reached (the device could not run) | not reached | The neighbours' ends of the three links were gone afterwards (`evidence/restart/vjunos-neighbours-after-exit.txt`), as after a `docker stop`; the lab was destroyed and redeployed at 15:15 UTC to continue. A rerun on the final build must show the review's known-limit warning and the failed job **Rerun on the fixed build (15:53 UTC, `vjunos-switch-2026-09-27T155300+0000.json`, 26 checks, 7 failed as the image dictates):** the review carried the known limit (API preview of the same build, `preview-warnings-1553.json`), the job ended *failed* in 11 s with "its container is exited (Exited (1) 2 seconds ago) right after starting. Known limit of the vJunos-switch image … Redeploy the lab", the other four containers untouched, the device *Unavailable*; no false success. |
| `n24l/cisco_xrv9k:24.3.1` | 1.30.47 working tree (deployed 15:16 UTC), containerlab 0.79.0, Chromium 153.0.8010.12 (`evidence/restart/xrv9k-2026-09-27T152910+0000.json`, 75 checks, 0 failed) | PASS 15:29:19 UTC: job 9 s, exit 0, `2 links restored`, id `423cb69b2f23` kept, pid 2553491 → 2609157, the other four untouched; *Restarting*, then *Starting* from 15:29:29, *Ready* 15:40:37 (11.2 min); design, plans, Git binding and deployment time untouched; the browser CLI showed the disconnection, Reconnect gave a fresh session with nothing replayed; a new capture resolved the device's interfaces | PASS 15:40:52: Devices tab → Details → Tab to *Restart device…* → Enter; job 6 s, `2 links restored`, same id, *Ready* 15:45:59 (5.1 min) | PASS: `containerlab stop --node xrv9k` at 15:46:06 (exited, no links), the menu item enabled, the review carried the start/restore warning and `exited`; job 15:46:44–15:46:47, `2 links restored`, same id, *Ready* 15:51:54 (5.1 min) | 15:59–16:22: configuration A reapplied on the factory-fresh fourth boot, one restart from the map (job 16:00:44, exit 0, `1 link restored`, same id); the VM never booted because vJunos-switch was exited and the `eth1` link could not be restored (QA-018), so the read-back was impossible; the disks show the fifth start chained on the fourth boot's overlay (the configuration applied after the first restart stays on the disk the later boots use). On the redeployed lab and the final build (1.30.48): restart 1 at 16:50 (27/27, the review named the limit) lost configuration A again (read-back 17:02: no Loopback0); a second and third restart at 17:04 and 17:09 (52/52, map and Devices) came back *Ready* in ~5 min each. Later-restart persistence with a verified configuration: **proven on the final build**: configuration A applied at 17:17:43 and read back on the device (Loopback0 present) before the restart; one restart from the map at 17:19 (record `xrv9k-2026-09-27T171848+0000.json` (27/27, the review named the limit; job 17:18:53–17:19:26, `2 links restored`, *Ready* 17:24:27)); read-back at 17:25: `interface Loopback0 … ipv4 address 10.255.0.4`, OSPF FULL with 10.255.0.3 and 10.255.0.1, Loopback0 Up; the disk listing shows the boot chained a new overlay on the previous one (`…-overlay-overlay-overlay-overlay.qcow2` on `…-overlay-overlay-overlay.qcow2`). So only the first restart after a deploy loses the configuration; what is configured after it survives the next restarts. | **The first restart lost the device's configuration** (QA-017): configuration A had been committed at 15:26:25; after the 15:29 restart the device came back *Ready* with no Loopback0, both GigabitEthernet interfaces shut down and no OSPF; the independent probe (cEOS → 10.255.0.4, `xrv9k-traffic-from-ceos.jsonl`) lost the path at 15:29:22 and never saw it again through all three restarts. Mechanism, read in the container: `/launch.py` picks the VM disk by `sorted(os.listdir('/'))`; the pristine image ships one `.qcow2`, the first boot wrote its overlay, by the second boot a hard link of the pristine disk named `clab-24.3.1.qcow2` sorted first and got a fresh overlay, the third and fourth boots chained on that one. The review of the working tree that became 1.30.48 names this limit; the extension's *Restart node* runs the same command and loses the same configuration |

## Adversarial checks (final build, `host1`, 15:19 UTC)

`tools/check_restart_two_tabs.py` (`evidence/restart/two-tabs-host1-*.json`, `two-tabs-host1-check.log`): 13 of 13.
Two tabs each opened a review for the same device; a double click on *Restart device* created exactly one job
and one restart (same id, one new start time); the other tab's older review was refused at confirm with
"Another lab operation ran after this review. Review the restart again.", its dialog kept the reason inline,
no second job and no second restart followed, Cancel closed it and a fresh review was offered; two
confirmations fired at the same moment started at most one job, the loser reading the busy or stale refusal.
The stale refusal's ordering was fixed in 1.30.50 (QA-020): acceptance pass 4 found that, when the older review was
confirmed while the manager still refreshed its view of the VM after the first job (a window of 5–8 s on the recovered
VM), the tab heard the generic busy message instead; `confirm()` now runs the consent checks before the busy guard. Retested on 1.30.50: 13 of 13 (`two-tabs-host1-2026-09-27T234527+0000.json`).

## Configuration persistence across a restart (final build)

- **cEOS** (`evidence/restart/ceos-persistence-markers.md`, 15:16–15:17 UTC): a saved marker (`interface
  Loopback99 description restart-saved-marker`, then `write memory`) and a running-only marker (`Loopback98
  … restart-unsaved-marker`) were set over an independent SSH session; before the product-driven restart the
  running configuration held both and the startup configuration the saved one only; after the restart
  (26 checks, 0 failed) the running configuration holds the saved marker only. That is the image's own
  behaviour (cEOS boots from its startup configuration); the manager saved nothing on the student's behalf,
  as the review says.
- **cJunosEvolved, XRv9k** (committed configuration only; there is no running-only state to lose): the routed
  configuration A, committed before the runs, was in force again after every restart — the traffic probes'
  recovery of the crossing path and the neighbours' adjacencies are the evidence.
- **vJunos-switch:** not applicable: the container cannot start again (above).
