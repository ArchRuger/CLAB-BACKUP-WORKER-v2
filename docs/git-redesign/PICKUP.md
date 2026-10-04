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
| 5. Header control, save, load, lab states | **Done and pushed** (tip `77f799f`; on the merged tree: 2536 Python tests, 699 browser tests, `check_fixture.py` 262 ok): every backend, helper and page slice, the helper through S1e (H8, H9), the aligned fixture, the guides, both audits (P1, R1), the live backend pass (L1), the save follow-ups (S3c) and the page integration in a real browser (I1 `cd81fe3` to `306349c`: seams 1 to 16, `tests/test_page_load_ui.js`, the browser scripts under `tools/integration/`). I1's report: every state of PROMPT 5 and every row of 6.2 exercised at 1440x900 except the same-name question, the one-button collision question, a topology-file change and a real load on a lab without a save location; the friction budget met (first save 2 clicks, later save 2, load a lab state 3, change folder 4, lab state 3 plus the name). **Owed:** a `risk-reviewer` pass on S1e (`9b00b43`, `9b8d01a`), S3c (`e0b4cea`: the catch-up, the mandatory `head`, the lock wait, the destination rule) and I1's backend changes in `306349c` and `9e3e6f0` (the unchanged-save rule across labs of one checkout, an upload no longer re-dates uploaded saves, placement refusals recorded as the lab's status). |
| 6. Drawers, first save, Progress tab removal | **Running: S11**, the tab removal, by the I1 worker in the worktree `~/projects/clab-wt/s11-tab` (branch `slice/s11-tab`, local only, cut from `248e21f`); its brief is `briefs/brief-s11.md` (fifteen items to close first, the router, the rewording, the deletions, the evidence script `tools/integration/evidence_pass.py`). Sent after the brief: on the merged tree `folder_flow.py` stops at its refused-placement step (the aligned fixture no longer refuses a placement for `status_problem=operation`; use `hand_commit` or `remote_ahead`) and `drawers_flow.py` fails one check (a just-saved lab state is not listed as `Mine`: script or product, to be found out). When it reports: cherry-pick its commits, both suites, add `tests/test_save_router_ui.js` to the CI list, push; then the lead writes amendment K of `docs/redesign/DESIGN-SPEC-ADDENDUM.md`, a `risk-reviewer` checks the deleted functions, `tools/inventory/fill_outcomes.py` fills REFUSALS.md section E and the rows of CAPABILITIES.md that S11 changed are updated. |
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
