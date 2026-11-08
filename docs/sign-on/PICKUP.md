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
| Build | done | eleven slice workflows (`signon-slice`), merged with pull request 80 (BUILD.md 5) |
| Tools and fixture (S11), documentation (S12) | done | merged with pull request 80 |
| Integration, hotfix, full verification, release | done | pull request 80 (integration), 81 (the hotfix), 82 (1.31.9, which carried the code and fixed CI), then release 1.32.0: `clab-backup-ui/VALIDATION.md` 1.32.0 |

Released as 1.32.0 (2026-11-02); the live VM pass ran the same day on the development VM and its fixes are 1.32.1
(`clab-backup-ui/VALIDATION.md` 1.32.1). The open points are in section 3.

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

## 3. Open after the live VM pass (1.32.1)

The VM pass of item 6 ran on 2026-11-02 (`clab-backup-ui/VALIDATION.md` 1.32.1): the upgrade from 1.31.7 through the
installer, the firewall and SSH drop-in, a provided certificate, container-source sign-ins, the browser against the
live manager and every feature under sign-on. What it found is fixed in 1.32.1 (`docs/CHANGELOG.md`). Open, none of it
blocking:

1. **Renewal happens before the guard** (unchanged from 1.32.0): move `touch` behind the guard's checks.
2. **Admin create and reset hash outside the verify bound** (unchanged).
3. **A console-only IPv6 VM** is warned, not refused, by `setup-firewall.sh` (unchanged).
4. **`export MANAGER_IMAGE=`** is read by the firewall but not by `recreate-manager.sh` and `manager-recover-admin.sh`
   (unchanged).
5. **The People page** goes straight to sign-in on a 401 and loses an open dialog's text (unchanged).
6. **The other banners keep the narrow-width defect** the session banner had: at 760 px and narrower a `.banner` with a
   bare `div` or `p` child gets a 320 px flex basis as its height (`#home-banner` measured 732 px). A general
   `.banner > div, .banner > p { flex: none }` inside the `<=760` block is the candidate fix; it needs measuring against
   `#lab-banner` (collapsed too), the confirm banner and the home notice.
7. **Request-time events carry the actor `-`**: `job.queued` (`runner.submit`), `capture.launch` and `git.connect` are
   written while a request is in hand but pass no actor (DESIGN.md 10.3 asks for one where a request is in hand).
8. **The forced change accepts the administrator-set password unchanged** (no same-as-current check on
   `POST /api/session/password`; the voluntary dialog has one in `account.js`). The design does not state the rule;
   decide and write it.
9. **Small contract gaps seen live**: `GET /api/audit` ignores a `since` that is not a date (answers the whole log);
   `PATCH /api/users/{name}` accepts `"yes"` as `disabled` (Pydantic lax mode; `StrictBool` would refuse it);
   `POST /api/users` lowercases an uppercase name instead of refusing it (the pages lowercase anyway); `invalid_role`
   and the house 422 body are missing from DESIGN.md 7.4; a password of 12 spaces is accepted (DESIGN.md 4.3 reads as
   if it were refused).
10. **The last-administrator refusal is unreachable through sequential requests**: `self_change` fires first and the
    caller is always another active admin; only a concurrent mutual demotion reaches `last_admin` (unit evidence only).
11. **Not run on the VM**: *Start fresh* on the shared development manager (it would drop the owner's lab records);
    the `UI_PORT=8081` upgrade variant; a second physical machine as a source; the idle and absolute session limits;
    the console protocol's ticket; the full-screen installer front end (the plain menu was driven).
12. **Housekeeping on dev2 after the pass**: `tls/names` still holds `manager.example.test` (a SAN of the current
    self-signed certificate; remove the file and run `setup-tls.sh --renew` to drop it), the recovery administrator
    `recov1` was deactivated, the shared accounts stay (`vmadmin`, `vmadmin2`, `student1`).

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
