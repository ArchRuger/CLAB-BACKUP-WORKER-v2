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

Released as 1.32.0 (2026-11-02). The evidence is fixture, browser, unit and CI evidence only: no VM, no live device and
no Docker image build has validated sign-on yet. The open points of the release review are in section 3.

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

## 3. Open after the release (1.32.0)

The release step of the earlier plan is done. What the release review left open, none of it blocking:

1. **Renewal happens before the guard.** `SessionGate` renews on a page load or any request with another method before
   the guard decides, so a mutating request the guard then refuses (a same-site page on another port of the VM) still
   resets the idle timer; it never passes the 7-day limit and grants nothing. Move `touch` behind the guard's checks.
2. **Admin create and reset hash outside the verify bound.** `accounts.py` hashes through
   `SCRYPT_EXECUTOR.submit(...).result()` for those two admin routes, which skips `VERIFY_LIMIT` and blocks a shared-pool
   thread while it waits.
3. **An IPv6-only VM run from the console** with `IPV6` other than `yes` in `/etc/default/ufw` is warned, not refused,
   by `setup-firewall.sh` (no SSH session to protect); enabling ufw then drops incoming IPv6, SSH included.
4. **`export MANAGER_IMAGE=`** is read by the firewall (it now accepts the `export ` prefix, as `start-manager.sh`
   does) but not by `recreate-manager.sh` and `manager-recover-admin.sh`; it can only add ports.
5. **The People page** goes straight to sign-in on a 401, so an open Add or Reset dialog loses what was typed (UI.md 5.5
   as written); `account.js` may show "Sign-out did not reach the manager" before going to sign-in.
6. **A VM pass**: install, upgrade from 1.31.x, the firewall and SSH hardening, a provided certificate and a sign-in
   from another machine, none of which a cloud session can run.

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
