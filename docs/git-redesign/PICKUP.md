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
| 6. Drawers, first save, Progress tab removal | **Done and pushed** (tip `7e95817`; on the merged tree: 2537 Python tests, 725 browser tests, `check_fixture.py` 262 ok). S11 (`2e7b8d5` to `32f03cf`): the fifteen items closed, the tab and its code deleted, old addresses open the chip panel (`tests/test_save_router_ui.js`), the rewording, `tools/integration/evidence_pass.py` (118 states, 348 assertions, clean at 1440x900 and 390x844 in the author's run). Amendment K of `docs/redesign/DESIGN-SPEC-ADDENDUM.md` is written. |
| 7. Fixture pass, "try to get blocked" pass, live pass | **Running since 2026-10-04 18:50 UTC, ten workers, each in its own worktree under `~/projects/clab-wt/` cut from `2578f22` (branches `slice/<name>`, local only); their briefs are in `briefs/`:** `qa-1440`, `qa-1280`, `qa-760`, `qa-390` (the fixture pass per width: evidence and FINDINGS.md under `evidence/<width>/`; `brief-qa.md` is the 1440 one, the others differ in width, height and ports 8176/8181/8186); `review-final` is the read-only tree of the fourth `risk-reviewer` pass (helper H8, H9, S1d; the save's catch-up and the mandatory head; the integration's backend changes; the deleted functions); `l2-live` (`brief-l2.md`: the live pass through the browser on dev2, groups A to D; the operator rebuilt the manager from its worktree); `r2-refusals` (`brief-r2.md`: REFUSALS.md section E, then the "try to get blocked" pass in the fixture, findings under `evidence/blocked/`); `p2-parity` (`brief-p2.md`: CAPABILITIES.md on the finished tree); `d4-docs` (`brief-d4.md`: the guides against the finished page); `t1-tools` (`brief-t1.md`: the Playwright regression tools and the guide screenshots, README.md and TOUR.md). When each reports: cherry-pick its commits (one owner per file, so no conflicts are expected), answer the risk review in REVIEW.md section 7, route every finding marked "blocks the goal" or "wrong" to a fix (the page: a `clab-fable-specialist` or `clab-ui-builder` in a fresh worktree; the helper: its author's route, `clab-opus-specialist`), rerun `evidence_pass.py` for the widths a fix touches, and run the "try to get blocked" pass on dev2 once the live pass has freed the labs. |
| 8. Documentation, release, pull request | The guides are rewritten (D1 to D3) and being checked against the finished page (D4). Still to do by the lead, after every worker has stopped: CLAUDE.md (the three changed invariants of PROMPT section 8, the new scripts and modules in the architecture notes, the routing rows for saving and loading); `python3 deploy/set-release.py 1.31.0`; the three history sections (CHANGELOG, VALIDATION with unit, fixture, CI and live evidence kept apart, `agent instructions.md`); `verify-release.py`, the link check, both suites; one pull request with the description PROMPT section 12 prescribes (what changed; the owner decisions as implemented; the folder model in ten lines; every helper change with its review; every rewritten test and why; what was validated where; which models ran which slices; anything open, among it the lead's deviation that a save first fast-forwards the VM copy, DESIGN.md section 6). Remove the worktrees and local slice branches at the very end. |

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
