---
name: netlab-ui-qa-campaign
description: "2026-09-27 stream on claude/netlab-integration (worktree clab-manager-1.30.42): relentless netlab UI/UX QA campaign plus the authorized Restart device feature (containerlab restart --node parity); 1.30.48, 1.30.49 merged (PRs #56, #57), 1.30.50 cut after the VM crash; read docs/netlab-ui-qa/PICKUP.md first"
metadata:
  node_type: memory
  type: project
  originSessionId: 5248bba7-3cca-409d-b1cd-6742369f6838
  modified: 2026-09-27T16:51:27.292Z
---

Owner's campaign prompt `CLAB_Netlab_Relentless_UI_UX_QA_Campaign_v2.md` (untracked, worktree root; revision 2 folds in
`CLAB_Single_Device_Restart_Addendum.md`): validate/repair every netlab Design-tab workflow AND implement **Restart device**
(one node, native `containerlab restart --node`, VS Code extension 0.26.3 parity, ref `6df8e96`). Started 2026-09-27 on
`claude/netlab-integration` at 1.30.47 (`3194ec4`); release 1.30.48 committed as `b4329d3` and pushed (PR #56, CI green); 1.30.49 committed as `14c2f05` and pushed on 2026-09-27 evening for the second acceptance pass's findings (QA-019: a false credentials failure while IOS XR boots after a restart; the fix is a login grace window keyed on `forget()`'s epoch); campaign workspace `docs/netlab-ui-qa/` (PICKUP, COVERAGE/coverage.json,
DEFECTS QA-001…QA-018 + U-01…U-20 + RD/OBS/TOOL, RESTART-PARITY, EVIDENCE, tools/). PR #55 covered only 1.30.43; PR #56 carries 1.30.44–1.30.48.

**Why:** the pickup file holds the live state (chunks, defects, what was proven on which build); the memory only points there
and keeps the image facts that cost hours to learn.

**How to apply:** read `docs/netlab-ui-qa/PICKUP.md` first. Facts that are not in the code: containerlab 0.79.0 on the dev VM
has `restart --node`; `containerlab inspect` reports `status: "healthy"` (no uptime) for health-checked containers
(vJunos-switch, XRv9k); a `docker stop` of a node destroys both ends of its veths, which is why the product must never
substitute docker. **vJunos-switch 23.2R1.14 cannot restart** (its launcher renames `init.conf`; the container exits; only a
redeploy brings it back). **XRv9k 24.3.1 loses its configuration on the first restart after a deploy** (the launcher picks the
VM disk by sorted file name; a `clab-<ver>.qcow2` hard link sorts first after the first boot → fresh overlay); later restarts
chain on that disk. **A restart with an exited neighbour restores only the links whose other end exists**; a vrnetlab launcher
then waits for its provisioned interfaces and the VM never boots (XRv9k stuck at Starting). Lab `restore-square` was
redeployed 2026-09-27 16:22 UTC with configuration A (`nodecli.py <node> --file docs/multi-platform-restore/lab/base-configs/<node>.cli`);
a redeploy + configuration A takes ~20 min. Never rebuild the manager container while a live Restart device check is
running (a restart marks running jobs interrupted). Three UI-review-001 tools (`check_ui005/007c/008a`) fail on HEAD too
(TOOL-001), not a regression.
Related: [[netlab-integration]], [[multi-platform-restore]], [[dev2-host-environment]].

Late 2026-09-27: PR #57 merged 1.30.49 to main (21:55 UTC). The VM crashed at 21:32 while acceptance pass 3 (Sonnet) ran;
the recovery recipe is in [[dev2-host-environment]]. Pass 4 (Sonnet, on 1.30.49) found QA-020 (a stale second-tab review was
told "Wait for the current lab operation to finish" because `confirm()` consulted the busy guard, held through the executor's
post-job `discovery.refresh()`, before the consent checks) and a wrong charter criterion (a request without `Origin` is
accepted by design: the guard refuses a *mismatched* Origin; never write that criterion again). 1.30.50 fixes QA-020
(consent checks before the guard); the gate (two consecutive clean passes on one build) restarts on it with passes 5 (Sonnet)
and 6 (Opus). The charter for a pass lives in the session scratch (`charter-common.md`); the acceptance reports show its shape.
Tool lesson: the map's device menu is rendered at open time and not refreshed while open; a live tool must wait for the
page's `busy()` to clear before opening it right after a job (OBS-004).
