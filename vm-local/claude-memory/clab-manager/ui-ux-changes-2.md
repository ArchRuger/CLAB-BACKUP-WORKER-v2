---
name: ui-ux-changes-2
description: "2026-10-02 stream on claude/ui-ux-changes-2 (worktree clab-manager-1.30.42, PR #60): the developer's fresh-install walk as a student, ten items as releases 1.30.52–1.30.57; where the records are, the numbering decision, the VM leftovers"
metadata:
  node_type: memory
  type: project
  originSessionId: f37a5ea5-b834-493a-a45a-4361af46e540
  modified: 2026-10-02T20:36:30.351Z
---

Stream started 2026-10-02 from the developer's email *Ui/Ux Changes 2* (`Ui_Ux Changes 2.eml`, untracked in the
worktree root, nine screenshots). Branch `claude/ui-ux-changes-2` cut from `origin/main` at 1.30.50; **PR #60** to
ArchRuger/CLAB-BACKUP-WORKER-v2. Releases 1.30.52 (items 1, 9), 1.30.53 (3, 4), 1.30.54 (2), 1.30.55 (5, 6, 7),
1.30.56 (8), 1.30.57 (10). The netlab stream's uncommitted 1.30.51 was set aside as a local WIP commit on
`claude/netlab-integration` (`git reset --soft HEAD~1` restores it; never pushed), which is why this stream starts at
1.30.52. Records: `docs/ui-ux-changes-2/PICKUP.md` (state, plan, evidence index), `CHECKLIST.md` (the ten items with
status), `FINAL-REPORT.md`, `evidence/`, `tools/` (one Playwright or API check per item).

**Why:** the next agent must not re-derive the base, the numbering or where the proof lives.

**How to apply:** read the pickup file first. Facts that cost time: the editor's image/version joining, label options,
Apply step and view-mode menu are upstream in the pinned `@containerlab/clab-ui` 0.3.2 and are changed only through
`clab-backup-ui/lab-builder/patches.mjs` (build-time, anchored, applied by `build.mjs`; Node 24 in `~/.local/node24`);
the Docker build cache and superseded `clab-backup:<version>` images fill the root filesystem after a few `--no-cache`
rebuilds (`docker builder prune -af` and remove old tags; the exited `restore-square` NOS containers hold ~18 GB of
writable layers and are the maintainer's); Playwright tools that open the topology browser click tree files with a DOM
click (the dialog intercepts pointer events); the readiness monitor's automatic login test runs right after a device
becomes ready, so a tool must wait for an idle job queue before a backup or a destroy. VM leftovers of this stream:
the lab folder `uiux2-prev-200859` (kept: the preview tool's default lab) under `/srv/containerlab-node-manager/projects`,
a Git registration `uiux2-tests/uiux2-bk-203408` and two local commits `6455fc6`, `386ba9c` in
`~/labs/CLAB-MNGR-DEV-LLM` (not pushed; the checkout was already one commit ahead before). Related: [[netlab-ui-qa-campaign]], [[dev2-host-environment]],
[[user-pr-workflow]].
