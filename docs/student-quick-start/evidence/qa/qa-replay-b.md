# QA replay — Scenario B ("build your own lab and keep it in Git")

**This was an agent simulation** of a first-time student, driven entirely from the PDF
`guide-under-test.pdf` (SHA-256 `1b9656058c87a8bc50c1f3234dc4f755628d2899cb48e8c5b0d61f502a2f9878`,
pages 15-24 for Scenario B). No source under `docs/student-quick-start/source/`, no capture
script and no other guide was read to fill a gap; where the PDF did not say how to do something,
that is logged below as a finding, and this agent then worked it out itself only to continue.
Browser steps used Playwright (Chromium, headless, 1366x900, one **fresh** `BrowserContext`
started only after Scenario A's context was closed) against `http://127.0.0.1:8081`. The VM-side
steps (B7 and part of B10) ran as `clabllm` (the guide's "lab VM terminal") with real `git`/`gh`
commands. Independent verification used `gh api` against GitHub and, for device state, SSH via
`tools/eos.py`.

Substitution used throughout (per task assignment): repository `my-network-labs-qa` in place of
the guide's `my-network-labs`, created via `gh repo create my-network-labs-qa --private
--add-readme` exactly as the guide's command line documents (with the substituted name).

## Steps

| Step | Result | Finding |
|---|---|---|
| B1 Start a new lab in the builder | PASS | "Open the lab builder" navigates the *same* tab (not a new one as this agent first assumed); the guide does not say either way. New lab dialog matched Figure B.1 exactly once filled in (name, "Two devices, one link", Arista cEOS · n24l/ceos:4.35.0F, `/srv/containerlab-node-manager/projects`). Draft opened with `ceos1`/`ceos2` and the "Draft · kept in this browser only · not on the VM yet" pill. `qa-b1a-new-lab-filled.png`, `qa-b1b-draft-created.png` |
| B2 Draw and check the topology | PASS | Node Editor tabs use small caps CSS on plain-case DOM text ("Network" not "NETWORK") — a selector detail, not a guide problem. Renamed both nodes, set both management addresses, added the canvas note. Unlike the guide's caution ("changing something on the Network tab can reset the image"), the image/version stayed `n24l/ceos:4.35.0F` in this run after editing the Network tab — the guide's caution did not reproduce, which is a documentation-only mismatch (over-cautious, not wrong) and not a functional bug. View YAML matched the guide's exact expected YAML (kind, image, both mgmt addresses, one link). `qa-b2k-view-yaml.png`, `qa-b2j-canvas-final.png` |
| B3 Save to the VM and deploy | PASS | "Save my-first-lab to the VM?" review showed the exact folder and YAML from Figure B.3; result banner read "✔ Save lab to the VM succeeded" and the pill changed to "Saved on the VM". "Deploy or add this lab…" → Topology file dialog → Deploy lab → "Start my-first-lab?" review → Start lab; builder page did not navigate on its own (matches the guide). `qa-b3a-save-review.png`, `qa-b3f-deployed.png` |
| B4 Bring the link up | PASS | Both devices Ready within 15 s of deploy completing (guide: "around 40 seconds"). Terminal's own header confirmed management address 172.20.20.21 for r1 (matches B2's setting). `ip routing` / `no switchport` / `ip address` sequence on both r1 and r2 worked as documented; `ping 10.0.0.2` from r1 succeeded (5/5). `qa-b4a-r1-configured.png`, `qa-b4b-ping.png` |
| B5 Create your own repository on GitHub | PASS | `gh repo create my-network-labs-qa --private --add-readme` (the guide's exact documented command, with the substituted name) succeeded: private repo, branch `main`, README present. |
| B6 Connect the repository and save progress | PASS | Connect dialog matched Figure B.6a with the substituted URL and folder `my-first-lab`. After connecting, destination line read exactly "my-first-lab saves to my-network-labs-qa › my-first-lab › latest/". First Save progress listed all 4 files `added`; after upload the status read "Saved to Git just now". Independently verified on GitHub: exactly `manifest.json, r1.cfg, r1.eoscfg, r2.cfg, r2.eoscfg` under `my-first-lab/latest/`, **no topology file yet** — matches the guide's stated expected result precisely. `qa-b6a-connect-dialog.png`, `qa-b6d-uploaded.png` |
| B7 Publish the topology files | **Gap, then PASS** | See "Missing step" below: the guide's `cd ~/labs/my-network-labs` (here, `~/labs/my-network-labs-qa`) assumes a checkout that the guide never told the student to create. This agent found it already existed (created automatically by the manager when B6 registered the repository) and used it, exactly as the guide's commands otherwise describe verbatim. `mkdir -p my-first-lab && cp .../my-first-lab.clab.yml* my-first-lab/`, wrote the README verbatim from the guide, then `git add / commit -m "my-first-lab: topology and map" / push`. `git status -sb` printed exactly `## main...origin/main` as the guide's expected result states. |
| B8 Check GitHub | PASS | Progress › Saved versions › "Browse the repository…" showed `README.md`, `my-first-lab.clab.yml`, `my-first-lab.clab.yml.annotations.json` and `latest/` side by side, matching Figure B.8 and the guide's description of "the in-product view of exactly what GitHub holds". `qa-b8a-browse-repo.png` |
| B9 Change, save, and checkpoint again | PASS | After adding r2's Loopback0, Review before uploading listed only `r2.cfg changed`/`r2.eoscfg changed` (r1 untouched), exactly as the guide states. Checkpoint `link-up` created and uploaded. Independently verified on GitHub: `my-first-lab/checkpoints/link-up/*` exists, `my-first-lab/latest/r2.cfg` contains the new Loopback0, and there is **no** nested `latest/latest` anywhere in the tree. `qa-b9b-review.png`, `qa-b9e-checkpoint-uploaded.png` |
| B10 Destroy, remove, and rebuild from Git | PASS | Destroy lab… review text matched the guide word for word ("The running devices are removed from the VM…"). Remove from this manager… review also matched verbatim, including the "Don't offer this lab for import again" checkbox description. `git clone https://github.com/pruger-dev/my-network-labs-qa.git /srv/containerlab-node-manager/projects/my-network-labs-qa` succeeded. Redeploying via the folder browser, both `my-first-lab` (the original) and `my-network-labs-qa` (the clone) were listed at the top level as the guide warns; picked the file **inside the clone** and confirmed "File location on the VM" read `/srv/containerlab-node-manager/projects/my-network-labs-qa/my-first-lab/my-first-lab.clab.yml` — contains `my-network-labs-qa` as required. Deployed; both devices Ready in 15 s, and the Topology tab showed the same map/note as before (annotations came from Git). Reconnecting the same repository/folder produced no special message, just "my-first-lab saves to my-network-labs-qa › my-first-lab › latest/" again. Applying Latest reported "Replaced and verified" for both devices in 12 s (guide: "about 12 seconds"). `ping 10.0.0.2` from r1 succeeded; `show ip interface brief` on r2 showed `Loopback0 10.255.0.2/32`. Independent SSH check on r1 (172.20.20.21) and r2 (172.20.20.22) confirmed the same. `qa-b10g-topology-dialog.png`, `qa-b10m-applied.png`, `qa-b10o-r2-loopback.png` |

## Findings

**Blocking:** none — every step eventually completed and every expected result matched.

**Should-fix:**
- **Page 20, step B7, "Action" block.** The command `cd ~/labs/my-network-labs` (substituted:
  `~/labs/my-network-labs-qa`) is the very first reference to that path anywhere in the guide.
  Nothing before B7 tells the student that connecting a repository in B6 causes the manager to
  clone/register it under `~/labs/<repo-name>` on the VM on the student's behalf. A student
  following the PDF literally would hit `cd: no such file or directory` unless they either guessed
  this mechanism or ran `git clone` themselves first (which then risks a second, divergent checkout
  next to the manager's own one). This agent discovered the directory already existed (verified
  its git remote pointed at the right repo and it was already one commit ahead from B6's save)
  and used it as the guide's commands otherwise describe. A single sentence in B6 or at the top of
  B7 ("connecting a repository registers a working checkout at `~/labs/<repository-name>` on the
  VM; `cd` into it for B7") would close this gap.

**Cosmetic:**
- Page 15/16: the "Network tab resets the image" caution did not reproduce in this run (see B2
  above); harmless over-caution, not a wrong instruction.
- The Node Editor's tab labels are visually upper-case via CSS but the underlying accessible text
  is title-case ("Network", not "NETWORK") — affects test/automation selectors only, invisible to
  a student.

## Remote evidence

Repository: `https://github.com/pruger-dev/my-network-labs-qa` (private, branch `main`).

- `8538f77` Initial commit (from `gh repo create --add-readme`)
- `ae0bc47` Save my-first-lab progress — first save, `my-first-lab/latest/*` (B6)
- `be0a10c` my-first-lab: topology and map — `my-first-lab/{README.md,my-first-lab.clab.yml,my-first-lab.clab.yml.annotations.json}` (B7, pushed from the VM as `clabllm`)
- `6aa091a` Save my-first-lab progress — r2's loopback (B9)
- `43f02d6` Save my-first-lab progress — checkpoint `my-first-lab/checkpoints/link-up/*` (B9)

Confirmed via `gh api repos/pruger-dev/my-network-labs-qa/git/trees/main?recursive=1`: no
`latest/latest` path exists anywhere in the tree; `my-first-lab/latest/r2.cfg` contains
`interface Loopback0` / `10.255.0.2/32` after B9 and again after B10's Apply.

## Timings observed

- Deploy (B3) → 2 of 2 devices ready: **15 s** (guide: "around 40 seconds").
- Redeploy from the clone (B10) → 2 of 2 devices ready: **15 s** (guide: "about 45 seconds").
- Apply Latest after the fresh-checkout redeploy (B10): **12 s** (guide: "about 12 seconds" — exact
  match).

## Limitations

- Same DOM-ordering caveat as Scenario A: confirmation `<dialog>`s can render ahead of the panel
  behind them in document order, which affected a couple of this agent's own tail-sliced text
  checks; not a product issue.
- The lab builder's context-menu and rich-text note editor needed pixel-coordinate clicks in a few
  places (`page.mouse.click`) because the placeholder text node was not reliably matched by
  `get_by_text` after the annotation box first opened; functionally the note was typed and kept
  exactly as intended, confirmed via View YAML and the canvas screenshot.
- No additional viewport sizes were checked beyond 1366x900 (not requested for this task).

## PDF followed

SHA-256: `1b9656058c87a8bc50c1f3234dc4f755628d2899cb48e8c5b0d61f502a2f9878`
