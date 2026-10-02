---
name: multi-platform-restore
description: "Replace running configuration on four NOS images (cEOS, cJunosEvolved, vJunos-switch, XRv9k): branch, PR, lab, where to pick up"
metadata: 
  node_type: memory
  type: project
  originSessionId: a286c708-b3d0-4ce8-85af-d1412fb8ae33
  modified: 2026-09-21T00:38:31.585Z
---

Work stream started 2026-09-20: *Replace running configuration* for the exact images n24l/ceos:4.35.0F, n24l/cjunosevolved:26.2R1.7-EVO, n24l/vjunos-switch:23.2R1.14, n24l/cisco_xrv9k:24.3.1, one patch release per image chunk, on branch `claude/multi-platform-restore` (ArchRuger/CLAB-BACKUP-WORKER-v2): PR #47 (1.30.27) and PR #48 (1.30.28–1.30.30) were both merged by the user on 2026-09-21: the stream is in `main`. Releases pushed 2026-09-21: 1.30.27 `3c5d954` (cEOS + driver contract + Junos identity/confirmation fixes), 1.30.28 `af036c9` (Evolved through the product, backup digests, evidence hardening after an audit). 1.30.29 `4d35a9b` (Cisco IOS XR driver with the held arming session, all four kinds restorable, all-four and mixed runs, interruption measured). 1.30.30 `11e5104` closed the stream: persistence across a normal NOS restart proven on all four, the dev VM runs `clab-backup:1.30.30`, all acceptance rows have evidence; the open points that could not be produced are named in `evidence/MATRIX.md`.

**Read `docs/multi-platform-restore/PICKUP.md` first**, then `README.md` and `evidence/MATRIX.md` there. The acceptance lab `restore-square` (one node per image, routed square, 172.20.20.101–104) is deployed from `/srv/containerlab-node-manager/projects/restore-square/` and must stay the single lab for this work; tools are in `docs/multi-platform-restore/tools/`. Raw transcripts live in `~/research/multi-platform-restore/raw/` (outside Git).

**Why:** the user asked for full live proof per image, agent routing by model (scout=Haiku, builder=Sonnet, reviewer=Opus, QA=Sonnet, lead=Fable), one shared lab, and honest PASS/FAIL/NOT RUN reporting.

**How to apply:** one operator per node and one for the manager at a time; never docker-restart a clab node ([[readiness-only-via-ssh]]); the user's `.claude/` routing files are their own uncommitted work: do not commit them; the square lab's Git saves are local commits in `~/labs/CLAB-MNGR-DEV-LLM` and were deliberately not pushed; deliver through the PR ([[user-pr-workflow]]). Known non-obvious facts: IOS XR lets only the arming CLI session confirm a `commit replace confirmed` (driver must hold that session, never confirm inline); Junos `commit check` confirms a pending commit; vJunos-switch answers SSH ~10 min before its FPC forwards.
