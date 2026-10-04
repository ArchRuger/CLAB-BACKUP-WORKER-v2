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
| 2. Inventory, design round, Opus review | In progress |
| 3. The two reproduced defects of section 6.1 as their own commit | Not started |
| 4. Folder model | Not started |
| 5. Header control, save, load, lab states | Not started |
| 6. Drawers, first save, Progress tab removal | Not started |
| 7. Fixture pass, "try to get blocked" pass, live pass | Not started |
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

## 5. How to resume

1. `git fetch`, check out the branch, read section 2 and the newest commits.
2. Re-run the baseline commands in `CLAUDE.md` "Commands" before changing code.
3. Continue at the first step of section 2 that is not done; `DESIGN.md` holds the decisions, and
   `INVENTORY.md` the acceptance lists.
