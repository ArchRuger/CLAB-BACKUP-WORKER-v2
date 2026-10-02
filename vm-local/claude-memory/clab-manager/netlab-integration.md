---
name: netlab-integration
description: netlab integration stream (Network design + Apply to devices) on branch claude/netlab-integration in worktree ~/projects/clab-manager-1.30.42; state as of 2026-09-27 and where the records are
metadata:
  type: project
---

Stream started 2026-09-26 from the owner's assignment `CLAB_Netlab_Integration_Claude_Code_Prompt_v2.md` (kept
untracked in the worktree root). Worktree `~/projects/clab-manager-1.30.42`, branch `claude/netlab-integration`,
PR #55 to ArchRuger/CLAB-BACKUP-WORKER-v2. Releases: 1.30.43 (engine, intent, adapter, capabilities),
1.30.44 (Design tab), 1.30.45 = `7bb45af` (milestone D: Apply to devices, all four kinds proven live on restore-square, the deployed product too; committed and pushed 2026-09-27), 1.30.46 = `0439abb` (milestone E: the feature families, IS-IS/VRF/static/policy/VLAN live through the product, guided tables). 1.30.47 = `b3404f8` (milestone F: a plan exported to Git as a reviewed save of kind `design`, the helper's one rule for it, the engine in the health check, `docs/netlab-integration/FINAL-REPORT.md`). Evidence commit `3194ec4` (fresh install of 1.30.47 in a nested VM). Open: the two families outside the schema (GRE plugin allowlist, secret references: DECISIONS D9.8/D9.9), PR #55 merge is the owner's call.

**Why:** the next agent must not rediscover the contract or re-prove the devices.
**How to apply:** read `docs/netlab-integration/PICKUP.md` first, then `PROVISIONING.md` (§8 = what the live
proof changed) and the evidence files `evidence/live-apply-*.md`. The live harness is a scratch `create_app`
(described in PICKUP, not shipped); real backups need `ANSIBLE_COLLECTIONS_PATH=~/.ansible/collections`. The
deployed manager listens on the LAN address http://192.168.132.132:8081 (host network), not 127.0.0.1:8080.
Sonnet workers wrote the fake-channel tests, the apply UI and the records drafts; Opus reviewed; routing is
recorded per chunk in `docs/netlab-integration/TESTS.md` and the handoff. Related: [[multi-platform-restore]]
(the restore drivers the design drivers reuse), [[user-pr-workflow]].
