# QA replay — Scenario A ("use a lab your instructor gave you")

**This was an agent simulation** of a first-time student, driven entirely from the PDF
`guide-under-test.pdf` (SHA-256 `1b9656058c87a8bc50c1f3234dc4f755628d2899cb48e8c5b0d61f502a2f9878`,
pages 1-14 for Scenario A). No source under `docs/student-quick-start/source/`, no capture
script and no other guide was read to fill a gap. Browser steps used Playwright (Chromium,
headless, 1366x900, one fresh `BrowserContext` for the whole scenario) against
`http://127.0.0.1:8081`; the device CLI was the manager's in-browser terminal, driven with
keyboard input like a student. A few checks marked "independent verification" additionally
used direct SSH (`tools/eos.py`) or `gh api` against GitHub — never as a stand-in for what the
page itself showed.

Substitution used throughout (per task assignment): repository
`https://github.com/pruger-dev/netlab-course-qa.git` in place of the guide's
`netlab-course-student.git`.

## Steps

| Step | Result | Finding |
|---|---|---|
| A1 Open the manager | PASS | Home matches Figure A.1 exactly: Deploy/Build boxes, "No labs yet". `qa-a1-home.png` |
| A2 Deploy the lab | PASS | Folder browser and Topology file dialog matched Figure A.2a exactly; "Start link-basics?" review matched Figure A.2b. One tooling note: the confirm `<dialog>` renders earlier in DOM order than the panel behind it, so a naive `body.inner_text()[-N:]` slice can miss it — not a product issue. `qa-a2-topology-dialog.png`, `qa-a2b-start-review.png` |
| A3 Wait for devices ready | PASS | 0/2 → 2/2 in 35s (well under the guide's "one to two minutes"). Matches Figure A.3a/A.3b. `qa-a3a-starting.png`, `qa-a3b-ready.png` |
| A4 Look around from the CLI | PASS | `show version` reported "Arista cEOSLab"; `show interfaces status` showed Et1 `connected`; `show ip interface brief` listed only Management0 — exactly the guide's expected result. `qa-a4-terminal-shows.png` |
| A5 Connect your repository | PASS | Dialog matched Figure A.5a with the substituted URL; after connecting, destination line read exactly "link-basics saves to netlab-course-qa › link-basics/work › latest/" and all three instructor/reference rows appeared with the documented actions. Cosmetic: the three rows rendered in the order Troubleshooting/Final/Starting, the guide's sentence lists them Starting/Final/Troubleshooting — order only, all three present with 5 files each. `qa-a5c-progress-connected.png` |
| A6 Load the starting configuration | PASS | Review titled "Replace running configuration", source line "Source: Starting state · netlab-course-qa › link-basics/reference/start/latest · saved … · 48d44dc454", both devices "6 differences". After confirming, both reported "Replaced and verified"; `ping 10.0.0.2` from r1 succeeded (5/5, 0% loss). `qa-a6a-review.png`, `qa-a6b-replaced.png` |
| A7 Make a change on r1 | PASS | Loopback0 10.255.0.1/32 configured and read back exactly as shown in the guide; r2 untouched. `qa-a7-loopback.png` |
| A8 Save your progress | PASS | Review before uploading listed all four files `added` as expected; after "Upload these changes" the Progress tab read "Saved to Git just now" and Latest showed "netlab-course-qa › link-basics/work › latest · Saved just now · 5 files". Independently verified on GitHub: commit `135e811` adds exactly `manifest.json, r1.cfg, r1.eoscfg, r2.cfg, r2.eoscfg` under `link-basics/work/latest/`. `qa-a8a-review.png`, `qa-a8b-uploaded.png` |
| A9 Checkpoint, then r2's loopback | PASS | Checkpoint "loopback-added" created and uploaded (commit `37f2452`); second save after r2's loopback showed only `r2.cfg changed`/`r2.eoscfg changed` (commit `e2353ce`). Independently verified: no `latest/latest` nesting; `link-basics/work/latest/r2.cfg` contains the Loopback0 stanza while `link-basics/work/checkpoints/loopback-added/r2.cfg` does not. `qa-a9c-checkpoint-uploaded.png`, `qa-a9g-second-save-uploaded.png` |
| A10 Break it, then recover | PASS | Applying "Troubleshooting scenario 01" (source `.../reference/broken-01/latest`, commit `e2353cecab`) broke the link: `ping 10.0.0.2` from r1 showed 100% loss and `show interfaces status` showed Et1 `notconnect`, exactly as documented. Applying the lab's own Latest (source line "work · netlab-course-qa › link-basics/work/latest") restored connectivity: ping succeeded again and both loopbacks were present. Independent SSH check on r1 (172.20.20.11) and r2 (172.20.20.12) confirmed both `Loopback0` addresses and both `Ethernet1` addresses after recovery. `qa-a10c-r1-broken.png`, `qa-a10f-r1-recovered.png` |
| A11 Next time you open this lab | PASS | Reopening the manager (new page in the same context) showed the Home card exactly as Figure A.11a describes (Running · 2 of 2 devices ready · Last saved N minutes ago · Deployed N minutes ago · Open lab), plus an undocumented but harmless extra field "Last opened N minutes ago". Reopening the lab, Progress still listed Latest and the `loopback-added` checkpoint. Lab actions ▾ matched Figure A.11b exactly, including "Redeploy and clear the lab folder…" which only appears once the menu is scrolled. Destroy lab… review text matched the guide word for word, including "Save progress first"; cancelled without destroying. Remove from this manager… review also matched the guide's paraphrase ("Nothing on the lab VM changes…") word for word; cancelled without removing. `qa-a11a-home-reopened.png`, `qa-a11c-lab-actions-menu.png`, `qa-a11d-destroy-review.png`, `qa-a11e-remove-review.png` |

## Findings

**Blocking:** none.

**Should-fix:**
- None specific to Scenario A's own text. (The one cross-scenario ambiguity — how the VM-side
  checkout the guide's Scenario B step B7 assumes comes to exist — is logged in `qa-replay-b.md`
  since it only surfaces there.)

**Cosmetic:**
- Page 6 (A5 expected result): the guide's sentence lists "Starting state, Final state
  (instructor), Troubleshooting scenario 01" in that order; the manager renders them
  "Troubleshooting scenario 01, Final state (instructor), Starting state". All three rows and
  their actions are present and correct; only the prose order in the guide differs from the UI's
  actual order (looks reverse-registration-order, not alphabetical).
- Page 8 (A7's note about EOS applying config immediately): guide's caution on page 16 that
  "changing something on the Network tab can reset the image back to its suggested name" (a
  Scenario B note) did not reproduce when this agent repeated the same action in Scenario B — see
  `qa-replay-b.md`. Noted here only because it is the closest a Scenario A step comes to touching
  that warning; no impact on Scenario A itself.

## Remote evidence

Repository: `https://github.com/pruger-dev/netlab-course-qa` (private, branch `main`).

- `48d44dc` Initial commit (pre-existing, from the template)
- `135e811` Save link-basics progress — adds `link-basics/work/latest/{manifest.json,r1.cfg,r1.eoscfg,r2.cfg,r2.eoscfg}` (A8)
- `37f2452` Save link-basics progress — checkpoint `link-basics/work/checkpoints/loopback-added/*` (A9)
- `e2353ce` Save link-basics progress — `link-basics/work/latest/{r2.cfg,r2.eoscfg}` updated with r2's loopback (A9)

Confirmed via `gh api repos/pruger-dev/netlab-course-qa/git/trees/main?recursive=1`: no
`latest/latest` path exists anywhere in the tree.

## Timings observed

- Deploy → 2 of 2 devices ready: **35 s** (guide: "one to two minutes", "under a minute" on a
  lightly loaded VM).
- Replace running configuration (Starting state, both devices): reported "Replaced and verified"
  within the same operation-review round trip the guide describes as "within about a dozen
  seconds"; not independently timed to the second in this run.

## Limitations

- The manager's confirmation `<dialog>` elements are inserted earlier in the DOM than the panel
  they cover, which broke a couple of this agent's own tail-slicing text checks (worked around by
  reading the dialog's own locator); this is a tooling detail, not a product finding, and is noted
  in `qa_pw.py`'s pattern of preferring dialog-scoped locators.
- Screenshots are Chromium headless renders at 1366x900; no additional viewport sizes were checked
  for Scenario A (the task did not ask for a responsive sweep).

## PDF followed

SHA-256: `1b9656058c87a8bc50c1f3234dc4f755628d2899cb48e8c5b0d61f502a2f9878`
