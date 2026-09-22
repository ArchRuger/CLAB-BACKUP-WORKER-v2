# Student quick start: validation record

What was actually executed for the guide, by whom (an agent, never a human study), on which build, with the evidence
paths. Newest chunk first. The final section names the exact PDF (SHA-256) that was inspected page by page.

## Chunk 3 — the delivered PDF, its inspection and the independent replays (release 1.30.35, 2026-09-22)

- **Delivered file:** `Containerlab_Node_Manager_Student_Quick_Start.pdf`, 20 pages, US Letter,
  **SHA-256 `9f42d9399acb32378f58c6ea40ef3e1f260da844f70329cc5f335255a540d394`**, built with `build.sh` from
  `source/guide.md` (byline "tested with manager release 1.30.35"), `source/style.css` and `screenshots/spec.json`
  (24 composed figures from the raw captures of the two executed scenarios). `tools/inspect_pdf.py`: all five fonts
  embedded (DejaVu Sans/Bold/Oblique, Mono/Mono-Oblique), nine bookmarks, every table-of-contents link resolves, no
  placeholder text, no U+FFFD, no empty page.
- **Page-by-page inspection** (the lead, on the `pdftoppm` renders of this exact file, every one of the 20 pages):
  screenshots and callouts legible, no text over images, no clipped table, captions with their figures, running
  headers and "Page N of 20" on every page, scenario sections start on a new page; the only white space is the end
  of the two pages before a scenario break and the end of the last page. Fixes applied during the inspection before
  the final build: the given-box table header, three captions, and four recrops (a fragment of the canvas note, a
  too-wide terminal, two dialogs with a stray top edge).
- **Independent review** (Opus `clab-ui-reviewer`, read-only, on the draft): four blocking findings, all one root
  cause — the guide named the author's GitHub account where it meant the student's; resolved by stating in "What you
  have been given" that the lab VM's GitHub login is the student's account (`pruger-dev` in the guide, "read your own
  account name"), plus the lab-VM terminal row; ten should-fix items (exact status texts, timings, the "5 files" count,
  the `.cfg`/`.eoscfg`/`manifest.json` wording, the byline) and the length cuts — all applied.
- **Replay 1** (Sonnet `clab-ui-qa`, an agent simulation of the student, NOT a human study), on the draft PDF
  `1b9656058c87a8bc50c1f3234dc4f755628d2899cb48e8c5b0d61f502a2f9878`, from the reset starting states
  (`tools/reset_scenario_a.sh netlab-course-qa`, `tools/reset_scenario_b.sh my-network-labs-qa`), fresh browser
  contexts, using only the PDF (repository names substituted: `netlab-course-qa`, `my-network-labs-qa`): **A1–A11 and
  B1–B10 all PASS**; one should-fix (B7's `~/labs/<repo>` checkout is created by B6 — a sentence was added), cosmetic:
  the reference rows' order, the builder opening in the same tab (both worded now). Remote evidence: `netlab-course-qa`
  commits `135e811`, `37f2452`, `e2353ce`; `my-network-labs-qa` `ae0bc47`, `be0a10c`, `6aa091a`, `43f02d6`; no
  `latest/latest`; checkpoints distinct from Latest; the B10 redeploy path contained `my-network-labs-qa`. Files:
  `evidence/qa/qa-replay-a.md`, `qa-replay-b.md`, `qa-replay.json`, `qa-a*/qa-b*.png`.
- **Replay 2 (final acceptance)** on the delivered file (`e53aa7…`), from the reset starting states with the
  repositories `netlab-course-qa2` and `my-network-labs-qa2`, on the manager image `clab-backup:1.30.35`:
  **A1–A11 and B1–B10 all PASS** (Scenario A about 12 minutes, Scenario B about 16 minutes of agent time). No blocking
  finding. One should-fix: at B8 the manager's *Browse the repository…* showed the tree from before the terminal push
  of B7 until the page was reloaded; two cosmetic notes (the Progress tab's own *Create checkpoint…* button works as
  well as the header menu; a ping sent within a second of "Configuration replaced" can still succeed before the fault
  shows). Remote evidence and screenshots: `evidence/qa/final-replay-a.md`, `final-replay-b.md`, `final-replay.json`,
  `final-a*/final-b*.png`; the replayed file is kept as `evidence/qa/guide-under-test.pdf`.
- **Delta between the replayed file and the delivered file:** after replay 2 two sentences were added and nothing else
  changed — B8 now says to reload the page if the listing still shows only `latest/`, and A10 says "after a few
  seconds" before the ping fails. The three affected pages (10, 16, 17) were re-rendered and inspected; the page count
  and every other page are unchanged (`build.sh` reports the new SHA-256 above). No step, control or expected result
  changed, so the replay was not repeated for the two sentences.

## Chunk 2 — Scenario B executed and recorded (release 1.30.34, 2026-09-22)

- **Build under test:** manager image `clab-backup:1.30.33` (commit `cf7bc5d`) on `clab-llm-dev2`, helpers 1.30.33.
- **Starting state:** Scenario A's lab `link-basics` running and connected (left alone); no `my-first-lab` anywhere;
  the private repository `pruger-dev/my-network-labs` (created with `gh repo create --private --add-readme` in an
  earlier attempt of the same authoring session; the final run found it existing).
- **Method:** `tools/capture_scenario_b.py` (same conventions as A); device readbacks with `tools/eos.py`; remote trees
  with `gh api`; the owner-side Git commands run as the ordinary VM account and captured as a transcript. Agent
  simulation of the student, not a human study.

| Step | UI action | Result observed | Evidence |
|---|---|---|---|
| B1 | Open the lab builder › New lab… (my-first-lab, Two devices one link, Arista cEOS, projects folder) › Create draft | Editor with ceos1/ceos2 and one link; "Draft · kept in this browser only · not on the VM yet" | `raw/b1-*.png` |
| B2 | Edit Node ×2 (names r1/r2, image n24l/ceos 4.35.0F, Management IPv4 .21/.22), Add Text, View YAML | YAML with both images `n24l/ceos:4.35.0F` and `mgmt-ipv4` | `raw/b2-*.png`, `examples/my-first-lab/` |
| B3 | Save to the VM… › Save lab; Deploy or add this lab… › Deploy lab › Start lab | "Save my-first-lab to the VM?", "✔ Save lab to the VM succeeded", "Saved on the VM"; files on the VM; builder page stays (← My labs) | `raw/b3-*.png`, `ls -la` in the log |
| B4 | Wait for Ready; CLI on r1/r2 (ip routing, no switchport, addresses); ping | Ready after 40.7 s; ping 3/3 | `raw/b4-*.png`, SSH |
| B5 | `gh repo create pruger-dev/my-network-labs --private --add-readme` | Repository private, branch main (creation in an earlier attempt; HTTP 422 "already exists" in the final run) | log step 5 |
| B6 | Connect a repository by URL (folder my-first-lab) › Save progress › Upload these changes | "my-first-lab saves to my-network-labs › my-first-lab › latest/"; job synced; remote `my-first-lab/latest/*`, no topology file | `raw/b6-*.png`, tree |
| B7 | Terminal on the VM: copy topology+map, README, git add/commit/push | Clean tree; remote holds topology, map, README beside latest/ | transcript, `raw/b7-terminal-transcript.png` (rendered transcript) |
| B8 | Saved versions › Browse the repository… | Lists README.md, my-first-lab.clab.yml, .annotations.json, latest/ | `raw/b8-*.png`, `examples/my-first-lab/remote-tree.txt` |
| B9 | r2 Loopback0; Save progress; Create checkpoint… link-up | Review lists only r2.cfg/r2.eoscfg changed; checkpoint present; no latest/latest | `raw/b9-*.png`, tree |
| B10 | Destroy lab… › Remove from this manager… › `git clone` into the trusted root › Deploy from `my-network-labs/my-first-lab` › Connect by URL › Latest › Apply to running lab… | Path field and `vm_project_path` under `projects/my-network-labs/`; Ready after 46.8 s; both verified in 12 s; addresses, Loopback0 and ping back; binding `my-first-lab` | `raw/b10-*.png`, SSH, API |

- **Re-execution:** the first run of B10 had deployed the original `projects/my-first-lab` folder (the tree locator matched
  the root-level folder of the same name); step 10 was re-run with a scoped locator and assertions on the path and on
  `vm_project_path`, after the original folder had been moved to `projects-archive-2026-09-22/my-first-lab.original`
  (an authoring step; the guide tells the student to check the path in the *Topology file* dialog instead).
- **Not yet done:** PDF inspection, independent QA replay (fresh repository name for B5), Opus review.

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
