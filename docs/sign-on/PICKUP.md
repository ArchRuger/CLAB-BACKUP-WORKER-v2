# Sign-on and internet-exposure hardening: pickup

The state of the work stream for the next session. First written 2026-11-01 by the lead of the first
session; rewritten 2026-11-01 by the lead of the second session. Verify Git before trusting any line:
`git log --oneline -12` on `claude/sign-on-and-hardening`, `git worktree list`, and `git branch --list 'signon/*'`.

## 1. Where the work stands

| Step | Status | Evidence |
|---|---|---|
| Owner's task and decisions | done | `PROMPT.md` (D1 local accounts, D2 Admin + Operator with shared labs, D3 an Internet-exposed, auto-scanned VM) |
| Read-only inventory | done | `INVENTORY.md` (file:line to `fac28de`, 1.31.8) |
| Designs | done | `DESIGN.md` (accounts, sessions, gate, roles, throttling, bootstrap, audit, tickets; section 16 is the contract between build slices), `UI.md` (the pages; 3.2 is the `session.js` contract), `EXPOSURE.md` (TLS, redirect, firewall, SSH, installer, health check; 6.1 is the probe contract) |
| Lead's rulings | done | `RECONCILIATION.md` 1-5, applied to the three designs |
| Opus design review | done | `REVIEW.md`: `risk-reviewer` and `clab-ui-reviewer` (40 findings, 8 merged), two Opus refuters per finding (30 stand, U16 refuted), the lead's answers |
| Answers applied and checked | done | each document amended by a `clab-fable-designer`, checked by a read-only reviewer, misses fixed; then a cross-document check (21 contradictions, all resolved by the documents' precedence). Final design: commit `a9e3608` |
| Build plan | done | `BUILD.md`: 15 slices, ownership, contracts index, acceptance checks |
| Build | **in progress** | eleven slice workflows (`signon-slice`), one worktree each, base `a9e3608` (BUILD.md 5) |
| Tools and fixture (S11), documentation (S12) | not started | after the code slices are integrated |
| Integration, full verification, release 1.32.0, pull request | not started | section 3 |

The release is still 1.31.8. No VM, browser or live-device validation has happened. No Docker daemon is
available in the cloud session, so no image was built.

## 2. What binds

The amended `DESIGN.md`, `UI.md` and `EXPOSURE.md` (with `REVIEW.md`'s answers, which win where they
differ) are the behaviour; `BUILD.md` is the plan. The list of decisions the first session kept here is
superseded by them; the largest changes since: the forced password change lives on the sign-in page
(REVIEW R1); `UI_TLS` is dropped and uvicorn serves TLS with `--no-proxy-headers` (RECONCILIATION 4); the
gate keeps a user index and never takes `store.lock` (R4); the throttle is three levels with familiar
sources (R5, R6); scrypt runs in its own executor (R7); failed sign-ins go to `audit-failures.jsonl`,
summed per minute (R8); a session renews only on acts of the person (R9); sign-out ends the browser's
capture sessions and the capture owner identity is per person (R10 and the lead's addendum); the health
check keeps every check through read-only probes (R16).

## 3. Next steps, in order

1. **Collect the eleven slice workflows.** Each returns `{builds, rounds, open}`: the builders'
   hand-backs, every verification round (test runs, the Opus attack, the area reviewer's findings) and
   the problems still open after the fix rounds. A slice with open must-fix problems gets one more fix
   pass (`resumeFromRunId`, or a direct fixer) before it is merged.
2. **Integrate.** Merge each `signon/<slice>` branch into `claude/sign-on-and-hardening` with
   `git merge --no-ff` (the files are disjoint by BUILD.md 2), `core` first. Then the lead's files: the
   new test files in `.github/workflows/release-check.yml` (Python with `-p`, browser files on the one
   `node --test` line, new `deploy/*.sh` in the `bash -n` loop), `login.html`, `setup.html` and
   `users.html` in `deploy/verify-release.py` FIELDS, the new security files in
   `.claude/rules/routing-privileged-paths.md` (REVIEW R19). Run the full Python and browser suites on the
   merged tree and fix the cross-slice breaks (`test_page_load_ui.js`, the label-map case of
   `test_audit.py`, the redirect's import of `app/headers.py`).
3. **S11 tools and fixture**, then **S12 documentation** (BUILD.md 4), each through the same
   `signon-slice` workflow on a new worktree from the integrated commit.
4. **Verify the whole branch:** `/clab-review-changes` on the branch diff; `check_signon.py` and the
   existing Playwright checks through the fixture at 1440, 1280, 760 and 390 px.
5. **Release** (`clab-release` skill): `python3 deploy/set-release.py 1.32.0`; CHANGELOG, VALIDATION
   (what was run, by kind) and the handoff section of `agent instructions.md`; the `CLAUDE.md` invariant of
   DESIGN 14 and the routing-table row; amendment M of `docs/redesign/DESIGN-SPEC-ADDENDUM.md`; then the
   pull request through the GitHub MCP tools.

## 4. The workflow runs of the second session

Kept for `resumeFromRunId` while this session's transcript exists (scripts under the session's
`workflows/scripts/`):

| Slice | Run |
|---|---|
| core (S1a, S1b, S2) | `wf_4c964bc6-662` (its script is the shared `signon-slice` script) |
| probe (S3) | `wf_1c0bc87c-9f5` |
| tls (S4) | `wf_78f7c2bf-029` |
| doors (S5a) | `wf_ecd687ff-9e3` |
| installer (S5b) | `wf_41aee6b8-00a` |
| health (S6) | `wf_91c0b2a0-cd1` |
| pages (S7) | `wf_4e3db82a-112` |
| appsession (S8) | `wf_812b6c17-b4c` |
| people (S9) | `wf_d7213814-3cc` |
| features (S10a) | `wf_48d5d2fd-2f4` |
| standalone (S10b) | `wf_389d5451-9c1` |

A new session cannot resume these runs: it reads each worktree's commits instead (`git log
a9e3608..signon/<slice>`), and reruns the verification with `/clab-slice-verify` or the `signon-slice`
script from `docs/sign-on/BUILD.md` 4.

## 5. Environment notes

- This cloud environment reaches `pypi.org`: `python3 -m venv .venv && .venv/bin/pip install -r
  requirements.txt httpx` works. Node is 22 (the editor bundle needs 24; this stream does not touch it).
  No Docker daemon: `docker compose config` works, a build or `up` does not.
- Four CPUs: a workflow runs at most two agents at once, so independent work goes into parallel
  workflows, not one big one.
- The session runs as root; the test of the installer lock that assumed a non-root account is fixed on
  this branch (`7d871bc`, cherry-picked from `claude/elegant-newton-tuulux`).
- The GitHub proxy rejects `gh pr`/`gh issue`; use the GitHub MCP tools or `gh api` REST calls.
