# Git save and load redesign: pickup

The durable state of this work stream. Read it before continuing; ask Git and GitHub for live status.

## 1. The task and the owner's corrections

The task is [PROMPT.md](PROMPT.md), stored verbatim. The approved mockups are in
[reference/](reference/README.md). In the session of 2026-10-04 the owner corrected the prompt:

1. **The work runs on dev2**, not dev1. dev1 is not working and is not involved. This session is its
   own lead: it owns the release, the CI test lists, the commits and the pull request.
2. **The base is `main` at 1.30.60** (`68f24d9`), which is intended. The prompt was written against
   1.30.59; where 1.30.60 changed behaviour the prompt describes, the design says so.
3. **Routing**: the setup kit's agents and skills are all kept and used, and the prompt's section 2 is
   applied on top of them. Fable 5.1 may do build work where necessary. The VM has 70 GB for agents.
4. **Live devices** come from Docker Hub: `n24l/ceos:4.35.0F` (two nodes),
   `n24l/cjunosevolved:26.2R1.7-EVO` and `n24l/cisco_xrv9k:24.3.1`.

## 2. State

Branch `claude/git-save-load-redesign`, cut from `68f24d9`. Steps are those of PROMPT.md section 11.

| Step | State |
|---|---|
| 1. Routing rules, agent definitions, baseline | Done: `e0481a7`. Baseline on 1.30.60: 2223 Python tests OK (2 skipped), 503 browser tests pass, `verify-release.py` and the link check pass. |
| 2. Inventory, design round, Opus review | Done. [INVENTORY.md](INVENTORY.md), [DESIGN.md](DESIGN.md) with three part files under `design/`, and [REVIEW.md](REVIEW.md): 17 findings of the risk reviewer and 44 of the UI reviewer, each answered; DESIGN.md section 7 holds the rulings, and the part files are being revised to them. |
| 3. The two reproduced defects of section 6.1 as their own commit | Done: `bf02e6b` (S0) and its follow-up `a289abe`, both suites green (2371 Python, 509 browser tests), independent review answered (REVIEW.md section 3), and live on dev2: the first save into a repository registered at its top level works, New folder is enabled at the top level, in a lab folder and nested, and a second lab saves inside the first lab's folder ([LIVE-ENV.md](LIVE-ENV.md) section 8, `4e01653`). |
| 4. Folder model | Merged: the helper H1 to H7 with three review rounds answered (S0 `bf02e6b`, S1 `a78a501`, S1b `4e9f586`, S1c `187059a`; REVIEW.md sections 3 to 5), `git_places.py` (S2), the place routes `git_place.py` (S3b `40e4fd7`), the chooser (S10 `3eb07e7`). |
| 5. Header control, save, load, lab states | Merged and pushed (tip `933ff20`; both suites green there: 2532 Python tests, 683 browser tests, `check_fixture.py` 262 ok): every backend, helper and page slice, the helper through S1e (H8 `checkpoint_only`, H9 generated labels), the fixture aligned with the real helper, the guides (D1 to D3), the parity audit (P1), the refusal audit of the backend rows (R1), the live backend pass on dev2 (L1, LIVE-ENV.md section 9) and the save model's follow-ups (S3c: the manager sends `checkpoint_only`, an upload must name the reviewed `head`, the scaffold tool goes through the review, a save first fast-forwards the VM copy when nothing waits, the connection lock waits 10 s, the old destination route applies the bring rule). **Not yet reviewed independently:** S1e (H8, H9) and S3c (the catch-up and the head rule): a `risk-reviewer` pass on commits `9b00b43`, `9b8d01a`, `e0b4cea` is owed before the release. **Running:** I1, the page integration in a real browser, in the worktree `~/projects/clab-wt/i1-integration` (branch `slice/i1-integration`, local only, cut from `b352c28`; its commits so far: `c42ede9`, `7f38c6c`, `c22308a`, `7cf1ec5`). Its brief and the house rules are `briefs/brief-i1.md` and `briefs/brief-ui-common.md`; after the brief it was sent seams 11 to 16 (the codes `settings` and `devices`; the public `moved_from`; refused placements read like the chip, with codes for the helper's place-time sentences; a test that loads every page script in one context; commits made by hand are `busy`; a capture problem that is no device's shows the manager's sentence), all recorded in DESIGN.md 3.6. When it reports: cherry-pick its commits onto the task branch (expect small conflicts in `app/git_progress.py` and `tests/test_git_place.py` with S3c), run both suites, add `tests/test_page_load_ui.js` to the CI browser list, push. |
| 6. Drawers, first save, Progress tab removal | Drawers and first save are merged. **Next after I1:** the tab removal S11, by the same worker in the same worktree (or a fresh `clab-fable-specialist`): `briefs/brief-s11.md` (replace `{WORKTREE}`, `{BRANCH}`, `{BASE}`) holds the fifteen items it must close first (the parity audit's gaps, the refusal audit's F2 to F4, the live pass's page findings), the router for old addresses, the rewording, the deletions and the evidence script the QA pass runs. Then: the lead adds `tests/test_save_router_ui.js` to the CI list, writes the dated amendment K of `docs/redesign/DESIGN-SPEC-ADDENDUM.md`, has a `risk-reviewer` check the list of deleted functions, and reruns `docs/git-redesign/tools/inventory/fill_outcomes.py` for REFUSALS.md section E and P1's column for the rows S11 changed. |
| 7. Fixture pass, "try to get blocked" pass, live pass | The live BACKEND pass is done (L1). Not started: the four-width fixture pass (`briefs/brief-qa.md`, one `clab-ui-qa` per width, ports 8171/8176/8181/8186, evidence under `docs/git-redesign/evidence/<width>/`); the "try to get blocked" pass (a `clab-opus-specialist` that wrote no folder code: the R1 worker knows the refusal inventory; fixture and dev2; REFUSALS.md 9.4 and 9.7 are its attack list); the live pass through the BROWSER on dev2 (rebuild the manager and refresh the Git helper from the tip first; LIVE-ENV.md 9.7 is the state left behind; G1 to G4 of PROMPT 9.6, the friction budget, a second lab record with the same name, Undo right after a load); retaking the guide screenshots that show the old header or the tab (the list is in `briefs/docs-verify-list.md`); one documentation check against the finished page (same file). |
| 8. Documentation, release, pull request | Not started |

## 3. Environment (dev2, discovered 2026-10-04)

- 24 CPUs, 72 GB memory, `/dev/kvm` present, Docker 27.5.1, Node 24.21.0, Claude Code 2.1.289.
- The installed manager and capture stack run 1.30.58 from an earlier install; its data folder is
  `/srv/containerlab-node-manager/data`. No lab was deployed and Git saving was not set up (no Git
  helper installed) when the work started.
- `gh` is logged in as the repository owner with `repo` and `workflow` scope and no `delete_repo`
  scope: scratch repositories created for the live pass stay until the owner deletes them.
- The three device images of section 1 are pulled.

## 4. Assumptions recorded while working

- **Release number**: 1.31.0, because `docs/REPOSITORY-MAINTENANCE.md` makes a compatible feature a
  minor release. Decided at the release step from the then-current `main`.
- **Agent teams** stay off: the flag takes effect only in a new session, so it could not be checked in
  this one. Parallel work uses background subagents and the Workflow tool.
- **External skills** (third-party) stay VM-local and untracked; the 11 project skills are committed.
- **`clab-fable-designer`** was created in this session and an agent definition is only loaded when a
  session starts, so the three design slices ran on `clab-fable-specialist` (the same model, Fable 5.1)
  with the designer's definition as their instructions.
- **Build method**: each slice in its own Git worktree from a named commit, owning the files listed in
  DESIGN.md section 5; the lead merges and runs both suites. Worktrees have no virtual environment of
  their own and use the main checkout's interpreter by path.

## 4a. The live environment

A disposable four-node lab `git-redesign` (two cEOS, cJunosEvolved, XRv9k) and a private scratch
repository are prepared by a VM-operations worker; the facts are in `LIVE-ENV.md` once it reports.

## 5. How to resume

1. `git fetch`, check out the branch, read section 2 and the newest commits.
2. Re-run the baseline commands in `CLAUDE.md` "Commands" before changing code.
3. Continue at the first step of section 2 that is not done; `DESIGN.md` holds the decisions, and
   `INVENTORY.md` the acceptance lists.
