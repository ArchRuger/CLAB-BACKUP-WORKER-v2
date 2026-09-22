# Final acceptance replay — Scenario B (build your own lab and keep it in Git)

Agent simulation (this was not a human student session): Claude agent acting as
mock student, replaying the guide's steps verbatim against a live manager and
lab VM, verifying independently after the guide's own steps.

PDF under test: `docs/student-quick-start/evidence/qa/guide-under-test.pdf`
SHA-256 `e53aa7b9af2f2542a7dd40b7e0b056dca1612586f3ff509f2b7bf03a2a1d475d` (verified
before use). Read with `pdftotext -layout`; figures viewed with `pdftoppm`
only where the text alone left a UI detail ambiguous (none needed here).

Manager: `http://127.0.0.1:8081` (release 1.30.35). Substitutions per
assignment: repository created in B5 is `my-network-labs-qa2` (in place of
`my-network-labs`), used everywhere the PDF says `my-network-labs`, including
VM folder paths. GitHub CLI already authenticated as `pruger-dev` (the
student account). Browser: Playwright/Chromium, one fresh context for the
whole scenario (viewport 1366×900). Device CLI: the manager's browser
terminal (Open CLI). VM terminal steps (B5's `gh repo create`, B7's publish,
B10's `git clone`) run as `clabllm` on this machine, labelled "Where to run
it: on the lab VM" per the PDF.

Start: 20:09:20. End: 20:25:41. Total: ~16 minutes.

## Step-by-step

| Step | Result | Finding |
|---|---|---|
| B1 New lab in builder | Pass — dialog matched Figure B.1 exactly (name, Two devices/one link, Arista cEOS n24l/ceos:4.35.0F, VM folder); draft opened with ceos1/ceos2, "Draft · kept in this browser only · not on the VM yet" | — |
| B2 Draw and check topology | Pass — Node Editor renamed both nodes, set Management IPv4 172.20.20.21/.22 (Basic tab re-checked before Apply, as instructed); canvas text note added; View YAML matched the PDF's YAML verbatim (kind arista_ceos, image n24l/ceos:4.35.0F, one link r1:eth1–r2:eth1) | — |
| B3 Save to the VM and deploy | Pass — "Save my-first-lab to the VM?" review showed the exact folder/path and YAML; "✔ Save lab to the VM succeeded"; "Start my-first-lab?" review confirmed; builder did not navigate, returned via "← My labs" | — |
| B4 Bring the link up | Pass — both devices Ready; r1/r2 configured (`ip routing`, `no switchport`, addresses); ping 10.0.0.2 succeeded | — |
| B5 Create repository on GitHub | Pass — `gh repo create my-network-labs-qa2 --private --add-readme` created the repo; `gh api` confirms private, branch `main`, README.md present | — |
| B6 Connect repository and save | Pass — destination line exactly "my-first-lab saves to my-network-labs-qa2 › my-first-lab › latest/"; review listed all 4 files "added"; after upload `gh api` shows exactly `manifest.json, r1.cfg, r1.eoscfg, r2.cfg, r2.eoscfg` under `my-first-lab/latest/`, no topology file yet | — |
| B7 Publish the topology files | Pass — `~/labs/my-network-labs-qa2` existed already (created at B6); `cp` + README + `git add/commit/push`; `git status -sb` reported exactly `## main...origin/main` (clean) | — |
| B8 Check GitHub | Pass on GitHub (`gh api` tree shows `my-first-lab/{README.md,my-first-lab.clab.yml,my-first-lab.clab.yml.annotations.json,latest/}`); in-product browser initially showed **should-fix** below | **Should-fix**: immediately after B7's out-of-band VM `git push`, clicking Progress › Saved versions › **Browse the repository…** in the still-open manager tab showed only the `latest` folder — not the four items the PDF says appear "side by side" (`README.md`, `my-first-lab.clab.yml`, `my-first-lab.clab.yml.annotations.json`, `latest`). A full page reload (`final-b8c/d`) then showed all four exactly as described. The manager appears to cache the connected folder's file tree from when the lab was registered (B6) and does not refresh it after a push made outside the manager (via direct VM git, as B7 instructs); the PDF gives no hint a reload might be needed. Not blocking — GitHub itself and the reloaded manager view both confirm the guide's substantive claim. |
| B9 Change, save, checkpoint | Pass — r2's loopback added; review showed only `r2.cfg`/`r2.eoscfg` changed; checkpoint `link-up` created and uploaded; `gh api` confirms `my-first-lab/checkpoints/link-up/` exists, `my-first-lab/latest/r2.cfg` has the new Loopback0, no nested `latest/latest`, and exactly two new "Save my-first-lab progress" commits above "my-first-lab: topology and map" | — |
| B10 Destroy, remove, rebuild from Git | Pass — "Destroy my-first-lab?" review verbatim, confirmed, lab "Stopped"; "Remove … from this manager?" review verbatim, confirmed, lab gone from My labs; `git clone` into `/srv/containerlab-node-manager/projects/my-network-labs-qa2` succeeded; deploy browser listed both the original `my-first-lab` and the clone at top level (as warned); File location field read exactly `/srv/containerlab-node-manager/projects/my-network-labs-qa2/my-first-lab/my-first-lab.clab.yml` (contains `my-network-labs-qa2`, checked before deploying); redeployed, both devices Ready, map/annotation text intact from Git; reconnect reused the existing registration with no special message; Latest applied, ping succeeded, r2's Loopback0 10.255.0.2/32 back | — |

## Remote evidence (GitHub, read-only `gh api`/`gh repo`)

- `pruger-dev/my-network-labs-qa2`: private, default branch `main`.
- Commit history (newest first): `Save my-first-lab progress` (link-up
  checkpoint), `Save my-first-lab progress` (B9 save), `my-first-lab: topology
  and map` (B7), `Save my-first-lab progress` (B6), `Initial commit`.
- `my-first-lab/latest/` and `my-first-lab/checkpoints/link-up/` each hold
  `manifest.json, r1.cfg, r1.eoscfg, r2.cfg, r2.eoscfg`; `my-first-lab/`
  additionally holds `README.md`, `my-first-lab.clab.yml`,
  `my-first-lab.clab.yml.annotations.json` after B7.
- No `my-first-lab/latest/latest` path exists at any point.

## Findings summary

- Blocking: none.
- Should-fix: B8 — the manager's in-product repository browser can show a
  stale (pre-push) file listing right after topology/map files are published
  by a direct VM `git push` (as B7 instructs), until the page is reloaded.
  The PDF's B8 text does not mention this; a student following it literally
  in one continuous session could see only "latest" and wrongly conclude the
  publish failed.
- Cosmetic: none beyond A's.

## Limitations

- Agent simulation, not a human student session.
- Browser tooling (Playwright/Chromium) was available and used throughout;
  no gap to record.
- B8's finding was isolated to one reload; it was not re-tested with a
  shorter/longer wait-without-reload to bound exactly how long the stale
  listing persists — recorded as observed, not exhaustively characterized.

Lab left running at the end: `my-first-lab`, Running, 2 of 2 devices ready
(alongside Scenario A's `link-basics`, also left running).
