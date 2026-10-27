# T07: live acceptance of topology editing (browser to file to runtime), 2026-10-27

Evidence class: live (real containerlab 0.79.0, real cEOS 4.35.0F, real vSRX 23.2R2.21, real manager 1.31.6 at
commit 973668e on http://127.0.0.1:8081, the real helper over SSH). Browser: Playwright Chromium 153.0.8010.12,
headless, 1440x900 (steps 1 to 10, 12) and 390x844 (step 11). Operator: `clab-ui-qa`. No repository source was
edited. Memory (`free -g` available): 23 GB at start, 15 GB at the end (limit 8 GB).

Lab `camp-topo` (id `df60f69c61404cff902882eeb8176ebd`), file `/srv/containerlab-node-manager/projects/camp-topo/camp-topo.clab.yml`,
created 02:52:04 UTC, deployed in 20.8 s with `sudo containerlab deploy`, SSH answered on both cEOS at 02:52:36,
imported through Manager > Labs found on the VM > preview > Add lab at 02:56:08.
Lab `camp-topo-2` (id `f567d448e50640d595cbffb6c99d4b11`), built the student way, never deployed.

Final state left behind: `camp-topo` running with ceos1, ceos2, host1, fw1, host2 and links
`ceos1:eth1-ceos2:eth1`, `host1:eth1-ceos2:eth3`, `ceos1:eth4-ceos2:eth4`; plan "nothing to apply"; `camp-topo-2` stopped with host1, host2,
host3 (saved, never deployed, 0 containers). Not touched: `parity`, `camp-vsrx`, `git-redesign*`.

## Per-kind reconcile facts (what `containerlab apply` did to a running node)

Source: the apply job output (`GET /api/operations/<id>`) plus container ids and `StartedAt` from `docker inspect`.

| Kind | Change to a running node | containerlab's own line | Result |
|---|---|---|---|
| `arista_ceos` | link added (step 3), link end removed (step 4), link added (extra) | `Node will be restarted to apply link change node=ceos1 change="added link"` / `"deleted endpoint"` | restarted in place: SAME container id, `StartedAt` moved (ceos1 02:52:05 to 03:02:19, 03:13:37, 03:44:15); links restored (`Restored link ... interface=eth1`); 1.5 to 2 s each; unsaved running-config LOST (`Ethernet1 description` set live, gone after restart), saved startup-config KEPT (`write memory` description survived) |
| `arista_ceos` | an unrelated device added (host2, step 11) | nothing | not restarted, ids and `StartedAt` unchanged |
| `juniper_vsrx` | link end removed (step 4: `fw1:eth1`) | `Node will be recreated to apply link change since its kind does not declare live link support; if the NOS detects hot-plugged interfaces, set link-apply-mode: live on the node to avoid the recreation node=fw1 change="deleted endpoint"` | RECREATED: id `3e013f0e...` to `0081afe3...`; fresh boot (Junos booted 03:14:03, SSH after about 2 min 20 s); configuration LOST (`set system login message T07-PERSIST-CHECK`, committed 03:10:08, absent after) |
| `juniper_vsrx` | created together with its link (step 3) | `Creating node fw1`, `Created link: fw1:eth1 (ge-0/0/0)` | created, no restart; the alias `ge-0/0/0` is accepted for `eth1` |
| `linux` | link added to a running host | `Applying link change without node lifecycle action node=host1 change="added link"` | no restart, id unchanged (`7ecc56a8...` from 03:02:18 to the end) |

Container ids and start times around each apply:

| Apply | ceos1 (`a30ac9b3...`) | ceos2 (`1bc009fa...`) | host1 | fw1 | host2 |
|---|---|---|---|---|---|
| deploy 02:52 | 02:52:05.18 | 02:52:05.09 | | | |
| step 3, 03:02:17 (job `ee3f121d`, 4.2 s) | same id, restarted 03:02:19.95 | same id, restarted 03:02:21.30 | created `7ecc56a8...` 03:02:18.44 | created `3e013f0e...` 03:02:18.52 | |
| step 4, 03:13:34 (job `73ecbff1`, 4.8 s) | same id, restarted 03:13:37.77 | same id, restarted 03:13:39.01 | same, not restarted | RECREATED `0081afe3...` 03:13:36.20 | |
| step 8, 03:21:33 and 03:25:46 (failed parse) | unchanged | unchanged | unchanged | unchanged | |
| step 9, 03:28:13 (failed pull) | unchanged | unchanged | unchanged | unchanged | |
| step 11, 03:39:57 (job `25adac3b`, 1.0 s) | unchanged | unchanged | unchanged | unchanged | created `7828a7c1...` |
| extra, 03:44:13 (job `5adc3d6d`, 3.7 s) | same id, restarted 03:44:15.01 | same id, restarted 03:44:16.38 | unchanged | unchanged | unchanged |

## Acceptance table

PASS = the expected result was observed. Times are UTC. "Review" and "dialog" texts are quoted from the page.

| Step | Expected | Observed | Evidence | Result |
|---|---|---|---|---|
| 1 | Edit topology... beside Edit map with titles; mirrors in Lab actions > Advanced options and Tools > Map card; bar names the lab, Back to lab, the running line | `#topology-edit` (title "Devices and links, saved to the lab file on the VM; applying is a separate step") beside `#map-edit` (title "Positions and drawing, kept in the manager"); mirrors `#menu-topology-edit` (Advanced options) and `#tools-topology-edit`; the mirrors carry an empty title while enabled and "Wait for the current operation to finish" while disabled. Builder bar: "Back to lab", "Editing camp-topo", pill "Saved on the VM", line "This lab is running on the VM (2 devices). Saving changes the file and the map, not the devices; applying is a separate step." | `s1-edit-topology-bar.png` | PASS |
| 2 | Add linux host1 + link, vSRX fw1 + link; save review shows diff, "running devices" sentence, no removed devices; file, annotations, recovery copy; dialog and pill; still 2 containers | Palette names: host1 automatic, vSRX came as `srx1` and was renamed `fw1` in the Node Editor (Apply). Review 02:59:23: "This lab has 2 running devices. Saving replaces the topology file and the map layout on the VM; the devices are not changed. Applying the changes is a separate, reviewed step."; diff +host1 +fw1 +2 links; no removed-devices sentence. Confirmed 02:59:25 (job `be719aaa`, 0.3 s). File sha `8ccb99c1...` to `8b8bf117...`; `.annotations.json` created (ceos1 0,0; ceos2 160,0; host1 -40,-100; fw1 200,-140); recovery copy `.clab-manager-history/camp-topo.clab.yml.7f050e5d...` has sha `8ccb99c1...` (the old file; root 0600 in a root 0700 folder, read with sudo). Dialog: "Saved to the VM. The running lab is unchanged until you apply the changes." with only "Copy output" and "Back to lab and review changes...". Pill "Saved on the VM · not applied"; bar line "fw1, host1 to create · ceos1, ceos2 to restart · 2 links to connect". `containerlab inspect --name camp-topo`: 2 containers, ids unchanged | `s2-save-review.png`, `s2-save-output.png` | PASS (see U1, U2) |
| 3 | Back to lab and review changes... opens the apply review once, hash loses `review=apply`; plan lists creates, links, restarted rows with limit sentences; apply; four containers; veth; Ethernet2 connected; ids; vSRX boot; manager 4 devices, notice gone, positions kept | `#builder-review` (an `<a>`) opened the lab page and the review (hash `#lab=...&view=topology`). Plan: Create fw1, host1; Restart ceos1, ceos2 ("added link"); Links ceos1:eth2--host1:eth1, ceos2:eth2--fw1:eth1; command `"/usr/bin/containerlab" "apply" "-t" ... "--name" "camp-topo"`. No limit sentence under the cEOS rows (cEOS has no entry in `RESTART_KNOWN_LIMITS`) and no "Back up these devices first". Applied 03:02:17, job done 03:02:22 (4.2 s). `docker ps`: 4 containers; `host1 ip -br link`: `eth1@if136 UP`; ceos1 and ceos2 `Et2 connected`. ids: see table (cEOS restarted in place). vSRX: Junos booted 03:02:45, the manager's own SSH check was `ready` for fw1 at 03:05:04, `ge-0/0/0 up up` seen at 03:09:20 (the exact first appearance was not measured, only "present by 6.6 min"). Manager: 4 devices (`updated` 03:02:22.6), event `topology.registered` "Lab definition refreshed after apply" at 03:02:22.60, plan from `apply-plan` empty, no banner, map document ceos1 0,0 / ceos2 160,0 / host1 -40,-100 / fw1 200,-140 | `s3-apply-review.png`; job output | PASS (U3) |
| 4 | Move host1 link to ceos2:eth3, remove fw1 link; deployed save names what changed; apply plan lists ends; fw1/ceos2 fate; `inspect interfaces` agrees; vSRX config kept? | Editor: right-click an edge > Delete Link; a new link made after deleting the old one picked `host1:eth1`/`ceos2:eth3`. Save review: "This lab has 4 running devices..."; diff -2 links +1 link. Apply review (03:13:30): Back up these devices first: fw1 (its configuration is lost when it restarts or is recreated); Restart (2) ceos1, ceos2 "deleted endpoint"; Recreate (1) fw1 "deleted endpoint" with "A recreated device boots from its image again: configuration not saved is lost."; Links to connect ceos2:eth3--host1:eth1; Link ends to disconnect ceos1:eth2, ceos2:eth2, fw1:eth1 (host1's old end is not listed). Job 03:13:34 to 03:13:39. `containerlab inspect interfaces`: ceos1 eth0 eth1; ceos2 eth0 eth1 eth3; fw1 eth0; host1 eth0 eth1 = the file. fw1 recreated, login message gone after the new boot | `s4-apply-review-recreate.png` | PASS |
| 5 | Reopen: pill "Saved on the VM", positions kept, no false 409 | Reopen 03:15:22: pill "Saved on the VM", the VM annotations and the manager document hold the same four positions, no response >= 400, no console error | scripted run | PASS |
| 6 | Undo, Ctrl+Z, Back to lab without saving: hash unchanged, no helper job | host2 added, Undo button removed it (focus moved to Redo), host3 added, Ctrl+Z removed it, pill back to "Saved on the VM". sha256 of file and annotations identical before and after (`2eb6201a...`, `c895c151...`); `GET /api/operations` list md5 identical; requests on open were only `read`, `parse-yaml`, `image-check` (no `preview`, no `confirm`) | scripted run | PASS |
| 7 | Stale revision: refused with the stale sentence, nothing written, dialog offers both choices | Opened 03:16:29, `# touched` appended 03:16:33 (sha `4a69a468...`), device added, Save: `POST /api/operations/preview` 409 "The topology changed on the VM after it was opened. Open it again before saving." Dialog "Not saved to the VM": "Nothing on the VM was changed. Your draft is kept in this browser." buttons Close, Open the VM version, Review the differences... File sha unchanged, no job. "Review the differences..." showed a review whose diff drops `# touched`. Reopening the page then showed the old-draft dialog "Your draft and the VM file differ" with focus on "Continue my draft" and the buttons Download my draft / Continue my draft / Start from the VM version | `s7-stale-save.png` | PASS |
| 8 | Invalid endpoint and reuse: check names them; containerlab's own refusal in the apply job; fix | YAML panel, Problems: "Warning Line 21: `ceos1:eth1` is already used by the link on line 19." and "Error Line 22: the link endpoint `nosuch` is not a device in topology.nodes." ("Checked against containerlab 0.79.0"). Save is not blocked and the save review does not mention the findings. After the save the bar said "What applying would change could not be checked: Unable to find node nosuch."; Lab actions > Apply topology changes... showed "containerlab could not plan this change: Unable to find node nosuch." with "Apply anyway"; the job (03:21:33, `a0a6ef6e`) failed exit 1: `ERROR  Unable to find node nosuch.` Reuse only (saved 03:25:28): "could not be checked: Duplicate endpoint ceos1:eth1."; the job (03:25:46, `86deb79b`) failed exit 1: `ERROR  Duplicate endpoint ceos1:eth1  /  duplicate endpoint ceos1:eth1.` Containers untouched; the lab showed "Needs attention" and "Updating the lab from its topology file did not finish." with Details, View output, Try again, Dismiss. Fix saved 03:27:14: "Saved on the VM. The running lab already matches the file: there is nothing to apply." | `s8-yaml-check.png` | PASS |
| 9 | Missing image: review warns; apply fails for that device, others keep running; notice shows the plan again; remove, save, apply succeeds | `bad1` (`n24l/no-such-image:1.0`) added in the YAML panel. Editor: "Error: n24l/no-such-image:1.0 is not on the VM and no registry offers it...". Save review: "Images needing attention (1) ... The deploy fails for bad1." Apply review (Create (1) bad1) has no image warning (U4). Job 03:28:13 failed exit 1 in 1 s: `Failed to pull image image=docker.io/n24l/no-such-image:1.0 ... pull access denied`; no partial container, the four ids and `StartedAt` unchanged, `apply-plan` still lists `added: [bad1]`. The lab page showed the failure banner first; after Dismiss the notice "The topology file differs from the running lab." with Review changes... appeared. Removing bad1 (03:29:52): "The running lab already matches the file: there is nothing to apply", so no second apply job was needed or possible; success = the plan is empty | `s9-save-review-image.png` | PASS (U4, U5) |
| 10 | Undeployed camp-topo-2: "This lab is not deployed."; no deployed sentences; toast; Start lab = existing deploy review | Home > Open the lab builder > New lab... (name, folder `/srv/containerlab-node-manager/projects`), two linux hosts, link, Save to the VM... (publish, 03:34:42): "Saved as .../camp-topo-2.clab.yml. It is not running yet." with Add to My labs without starting / Deploy now. Added through Manager > Deploy a new lab > folder > file > Add to My labs without starting (03:36:14). Topology tab: "This lab is not running." + Start lab; Edit topology... line "This lab is not deployed."; save review has no "running devices" sentence; output "camp-topo-2 is in My labs. It is not running: adding a lab never starts its devices." with Deploy now / Go to My labs; toast "My labs now shows the saved topology of camp-topo-2."; Start lab opened "Start camp-topo-2?" (`containerlab deploy -t ... --name camp-topo-2`), cancelled; 0 containers | `s10-undeployed-save.png` | PASS |
| 11 | 390 px: More reaches both entries; bar wraps; both reviews usable by keyboard alone | `.map-edit-group` hidden, `#map-more-button` lists Edit map and Edit topology...; no horizontal overflow (page 390 = viewport). Bar wraps to 164 px (name truncated to "Editing camp-t..."). Keyboard only: Tab to More, Enter, ArrowDown, Enter; YAML panel Ctrl+A, paste, Ctrl+Enter; Tab to Save changes to the VM..., Enter; dialog 372 px wide with no horizontal scroll, Tab to Save changes, Enter; Tab to Back to lab and review changes..., Enter opened the apply review once; also Lab actions (Enter, ArrowDown) > Apply topology changes... > Tab to Apply changes > Enter; host2 created 03:39:57. First focus in each dialog is the close button | `s11-390-more.png`, `s11-390-apply-review.png` | PASS (U6) |
| 12 | Two tabs, edit both, save one: the other refused (which sentence) | Two separate browser contexts (separate drafts): A saved (03:42:26), B's Save got `preview` 409 "The topology changed on the VM after it was opened. Open it again before saving." and the same Not saved to the VM dialog as step 7: the STALE sentence. If both tabs had added the identical device (`host3`, first attempt 03:40:49) B's 409 produced no dialog: the page recognised the VM now held its content and showed "Saved on the VM". Two tabs in ONE context (shared draft): after A's edit, tab B shows pill "Last change not kept in this browser" and an overlay "This draft was changed in another tab. Reload this page to continue with the newer version, or download the version shown here first. Editing is paused..." with Download this version / Reload, and Save is disabled: the DRAFT-CONFLICT overlay | `s12-two-tabs-draft-conflict.png` | PASS (U7) |

## Unexpected or worth the lead's attention (U)

- U1 (low) The editor wrote the vSRX link as `fw1:ge-0/0/0` (the catalog's pattern) and the linux image as
  `ghcr.io/srl-labs/network-multitool` without `:latest`, not `fw1:eth1` and `...:latest` as the assignment text
  assumed. containerlab 0.79.0 accepted the alias (`Created link: fw1:eth1 (ge-0/0/0)`).
- U2 (low) A device added through the YAML panel has no annotation, so it lands at (0,0), on top of ceos1 (host2
  after step 11). Devices added from the palette keep their drop position.
- U3 (info) The apply review shows no limit sentence for cEOS rows, and "Back up these devices first" lists only
  fw1, yet a cEOS restart discards unsaved running-configuration (proved above). Only the generic "Configuration
  changes you have not saved are lost." covers it. A `RESTART_KNOWN_LIMITS` entry for `arista_ceos` ("restarted in
  place by containerlab; the running configuration is reloaded from the startup configuration, so unsaved
  changes are lost, saved ones stay") would make the cEOS fact visible. The step-4 vSRX review was correct: it
  listed fw1 as Recreate with the first-boot sentence.
- U4 (low) The save review carries the image check ("Images needing attention"), the apply review does not; a
  missing image only fails inside the job (pull access denied, 1 s).
- U5 (low) After a failed apply the lab page shows only the failure banner; the "topology file differs" notice
  with Review changes... appears after Dismiss.
- U6 (cosmetic) At 390 the bar truncates the lab name ("Editing camp-t..."). The palette-over-canvas limit (V11)
  was not re-tested.
- U7 (cosmetic) At 1440 the draft-conflict overlay's centred text runs under the palette panel and its sentence
  is cut ("Reload this page to conti...").
- U8 (process) The manager's single operation guard blocked this lab from other labs' jobs: the import returned 409
  "Wait for the lab operation to finish." for 3 minutes (parity restore job 02:53 to 02:56), the Edit topology
  button read "Wait for the current operation to finish" (02:57), and preview returned 409 "Wait for the current lab
  operation to finish." twice (design apply job of another worker). By design (`operation_busy`), but it also
  reaches the Edit topology entry of an unrelated lab. Three further attempts showed neither a review nor an
  error within 20 to 40 s (confirm 03:12:09, confirm 03:38:05, a Save at 03:41:18): no job was created, a retry
  worked; the cause was not captured (the busy guard is the likely one, unverified). Not reproduced on demand.
- U9 (info, known) 409 on `POST /api/operations/read` of `<file>.annotations.json` on the first open of a lab that
  has none (two console errors); `host1` (linux) shows "Unmapped"; the vSRX container stays Docker-`unhealthy`
  while the manager and SSH both say ready (also on `camp-vsrx`).
- U10 (info) The apply plan's "Link ends to disconnect" omitted host1's old end when its peer ceos1:eth2 was
  removed; containerlab removed it with the peer (`ceos2:eth3 -- host1:eth1` then connected cleanly).

## Method notes

Scripts and notes: `/tmp/claude-1000/-home-archtop-projects-clab-manager/8c727c84-a148-42fb-b8ff-25a6638ec02a/scratchpad/t07/`
(`lib.py`, `bl.py` builder helpers, `p01..p49.py`, `notes.txt`). The builder was driven by dragging palette
templates, Shift+click for links, right-click > Delete Link for edges, the YAML panel for text edits. The VM-side
checks used `docker inspect`, `sha256sum`, `sudo containerlab inspect`, SSH (cEOS admin/admin, vSRX admin/admin@123)
and `GET /api/operations/<job id>` for containerlab's output. Not done: Firefox, 760 px, the cJunos/vJunos/XRv9k kinds,
a vSRX restart without recreate (containerlab chose recreate at apply; a `containerlab restart --node` of vSRX was not run).
