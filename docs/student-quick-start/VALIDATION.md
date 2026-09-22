# Student quick start: validation record

What was actually executed for the guide, by whom (an agent, never a human study), on which build, with the evidence
paths. Newest chunk first. The final section names the exact PDF (SHA-256) that was inspected page by page.

## Chunk 1 — Scenario A executed and recorded (release 1.30.33, 2026-09-22)

- **Build under test:** manager image `clab-backup:1.30.32` on `clab-llm-dev2` (`/api/state` 1.30.32), containerlab
  0.79, host helpers refreshed from the working tree of this chunk (`host_git.py` with the identity fix). Devices
  `n24l/ceos:4.35.0F`.
- **Starting state (documented, reproducible with `tools/reset_scenario_a.sh`):** My labs empty, VM connected, VM Git
  registry empty, `link-basics` staged under `/srv/containerlab-node-manager/projects/`, the student's private copy
  `pruger-dev/netlab-course-student` made from the `pruger-dev/netlab-course` template.
- **Method:** `tools/capture_scenario_a.py` (Playwright, Chromium 1366×900 at device scale 2) drove every student action
  through the real pages; device facts read back over direct SSH with `tools/eos.py`; remote trees read with `gh api`.
  This is an agent simulation of the student, not a human usability study.

| Step | UI action | Result observed | Evidence |
|---|---|---|---|
| A1 | Open Home | "No labs yet", Deploy and Build boxes | `raw/a1-home-full.png` |
| A2 | Choose a file on the lab VM… › projects › link-basics › ◇ link-basics.clab.yml › Deploy lab › Start lab | Review "Start link-basics?", confirm "Start lab", lab page opens | `raw/a2-*.png` |
| A3 | Wait on the Devices tab | "Starting lab", "0 of 2 devices ready" → both "Ready" after 38 s | `raw/a3-*.png`, `scenario-a.json` |
| A4 | Topology tab; Open CLI on r1; show commands | Terminal "Connected"; Et1 `connected`, no address yet | `raw/a4-*.png`, SSH readback |
| A5 | Progress › Connect a repository by URL (folder `link-basics/work`) › Connect repository | "link-basics saves to netlab-course-student › link-basics/work › latest/"; reference rows Starting state / Final state (instructor) / Troubleshooting scenario 01 | `raw/a5-*.png` |
| A6 | Starting state › Apply to running lab… › Replace configurations | Both "Configuration replaced and verified", 12 s; ping 10.0.0.2 succeeds; binding still `link-basics/work` | `raw/a6-*.png`, SSH, API |
| A7 | r1 CLI: Loopback0 10.255.0.1/32, write memory | Readback shows Loopback0 | `raw/a7-*.png`, SSH |
| A8 | Save progress › Upload these changes | Job `synced`, commit `7d3c233`; remote `link-basics/work/latest/{manifest.json,r1.cfg,r2.cfg,r1.eoscfg,r2.eoscfg}` | `raw/a8-*.png`, `gh api` tree |
| A9 | Create checkpoint… `loopback-added`; r2 Loopback0; Save progress again | Commits `da05d70`, `cf244a0`; Latest updated in place, checkpoint keeps the old r2.cfg, no `latest/latest` | `raw/a9-*.png`, tree listing |
| A10 | Troubleshooting scenario 01 › Apply; then Latest › Apply | Ping fails / Et1 `notconnect`; then ping and loopbacks back; binding unchanged | `raw/a10-*.png`, SSH, API |
| A11 | New browser context: Home card, Progress, Lab actions ▾, Destroy review (cancelled) | "Running", "2 of 2 devices ready", "Last saved …"; menu and review texts recorded | `raw/a11-*.png` |

- **Defect found and fixed on the way:** *Connect a repository by URL* failed with "This VM account has no Git commit
  identity yet" because the GitHub account `pruger-dev` has no display name (see `docs/CHANGELOG.md` 1.30.33). After
  the helper refresh the connection registered the checkout with `user.name pruger-dev` and the noreply address.
- **Not yet done:** Scenario B, the composed PDF and its inspection, the independent QA replay, a rebuilt image.
