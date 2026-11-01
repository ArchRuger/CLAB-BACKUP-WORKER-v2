# Sign-on and internet-exposure hardening: pickup

The state of the work stream, step by step, for the next session. Written 2026-11-01 by the lead of the
first session. Verify Git before trusting any line here: `git log --oneline -8` on
`claude/sign-on-and-hardening`.

## 1. Where the work stands

| Step | Status | Evidence |
|---|---|---|
| Owner's task and decisions recorded | done | `PROMPT.md` (D1 local accounts, D2 Admin + Operator with shared labs, D3 the threat model: an Internet-exposed, auto-scanned VM) |
| Read-only inventory (guard, every route and socket, store, browser side, deploy, CI) | done | `INVENTORY.md`, 272 lines, file:line to `fac28de` (1.31.8) |
| Design: accounts, sessions, gate, roles, throttling, bootstrap, audit, tickets, tests | drafted, not reviewed | `DESIGN.md`, 1002 lines, 20 sections |
| Design: the pages (sign-in, setup, signed-out handling, account menu, Users and Audit pages, wording, tests) | drafted, not reviewed | `UI.md`, 1011 lines, 13 sections |
| Lead's rulings on every DESIGN/UI disagreement | done | `RECONCILIATION.md` (sections 1-5) |
| Rulings applied to `DESIGN.md`, `UI.md`, `EXPOSURE.md` (section 3 steps 2-3) | done, 2026-11-01, second session | the three documents are the single source; `RECONCILIATION.md` 5 records the two rulings made while applying them; `docs/sign-on/` is a history folder for `verify-release.py` |
| Design: TLS, firewall, installer, health check, recovery script | drafted, not reviewed | `EXPOSURE.md`, 701 lines, 11 sections (uvicorn TLS, self-signed ECDSA certs, redirect-only listener on 8081, ufw and sshd scripts, 13 exposure checks, upgrade decision 7.4) |
| Opus design review (`/clab-design-review`) | **not started** | — |
| Build, verification, release | not started | — |

Branch: `claude/sign-on-and-hardening`, pushed to `origin`. No code was changed; only `docs/sign-on/`.
The release is still 1.31.8. No test, VM, browser or live-device validation of anything in the designs
has happened: the designs cite code by file:line, nothing more.

## 2. The decisions that bind, in one list

From `PROMPT.md`, `DESIGN.md` 18–19 and `RECONCILIATION.md`; read those for the reasons.

1. The invariant "There is no login" in `CLAUDE.md` is replaced by sign-on; `DESIGN.md` 14 holds the
   replacement text, applied at the release step by the lead.
2. Local accounts in `state['users']`, scrypt from the stdlib (`scrypt$n$r$p$salt$hash`, `maxmem` on every
   call, a dummy verify for unknown names, a `BoundedSemaphore(4)`), policy 12–128 chars, deny-list, no
   expiry. Roles `admin` / `operator`; operators see every lab; admin-only: users, audit, VM connection,
   Start fresh, Diagnostics (`/api/debug*`).
3. Sessions in memory only; cookie `clab_session` HttpOnly, SameSite=Strict, Path=/, Secure under TLS
   (`origin.scheme(scope)`: ASGI scheme or `UI_TLS=1`); idle 12 h, absolute 7 d; renewal excludes the 4 s
   poll; sign-in and own password change rotate the id; disable/reset end sessions; `must_change_password`
   makes a restricted session. `/api/state` gains `user:{name, role, must_change_password}`.
4. The gate is a pure ASGI `SessionGate` added on the line before `HostCheck` (which stays outermost);
   one `EXEMPT` constant (`/login`, `/setup`, `login.css`, `login.js`, `setup.js`, `fabric-mark.svg`,
   `POST`+`GET /api/session`, `POST /api/setup`, `GET /api/health` → `{ready:true}`); a page request
   (`GET`/`HEAD` with `Accept: text/html`) gets 302 `/login?next=<path>`, everything else 401 JSON
   `{detail:{code:'signed_out'}}`, sockets close 1008 `signed_out`; `style.css` and every other static file
   are behind the gate. No CSRF token (SameSite=Strict + the existing Origin guard + HostCheck).
5. Throttling: per source 5 free then 30 s doubling to 15 min; per name a fixed 30 s; 429 with
   `retry_after` before any hashing; process-local counters.
6. Bootstrap: setup mode while `users` is empty; a 24-char code in `<DATA_DIR>/setup-code` (0600, read per
   request); `/setup` 404 otherwise; recovery `deploy/manager-recover-admin.sh` → `python -m app.recover`
   writes a `mode=recover` file valid 15 min allowing ONE extra admin; no user is ever reset. Users and
   `audit.jsonl` survive Start fresh.
7. Audit: `audit.jsonl` (admin-only `GET /api/audit`, filters `limit offset event actor outcome since
   address`, row field `source`); `Store.event()` gains `actor`; the guard's `api.request` event names
   actor and source. Never a password, code, session id or hash in any log or response.
8. Terminal ticket tuple carries the session id and the socket compares it. The capture cookie stays,
   set only for signed-in users, cleared on sign-out.
9. Pages: `login.html`/`login.js`/`login.css`, `setup.html`/`setup.js`, `session.js` (shared, loaded after
   `status.js`, its one `location` access inside `sessionGo()`; amendment M of the design-spec addendum),
   `account.js`, `users.html`/`users.js`; account group in the Manager ▾ menu plus `#account-chip`; `next`
   validated by `login.js` (section 15 of `DESIGN.md`); no token in browser storage; no new storage keys.
10. Tests: a `SignedInClient(TestClient)` in `tests/session_fixture.py` signs in through the real routes;
    `create_app` gains no test-only argument; 23 files / 52 `TestClient(` sites change; new files
    `test_session.py`, `test_setup.py`, `test_users.py`, `test_audit.py`, `test_password.py`,
    `test_ticket_binding.py`, `test_login_ui.js`, `test_setup_ui.js`, `test_session_ui.js`, `test_users_ui.js`,
    `test_account_ui.js` — the lead appends them to the CI lists.
11. No secret of this design is ever placed in the container environment (`runner.py:152` passes
    `os.environ` to Ansible).

## 3. Next steps, in order

1. **Read** `PROMPT.md`, `RECONCILIATION.md`, then `DESIGN.md` 2, 6, 7, 9, 19, 20 and `UI.md` 0, 3, 12. Skim
   `INVENTORY.md` for the file:line facts. Do not re-scout.
2. **Apply `RECONCILIATION.md` section 4** (the rulings on `EXPOSURE.md`: `UI_TLS` dropped, HSTS 180 days, `--no-proxy-headers` explicit, the `verify_docs` rule) to `EXPOSURE.md` and `DESIGN.md` 5.6.
3. **Apply the rulings** of `RECONCILIATION.md` to `DESIGN.md` and `UI.md` (a `mechanical-editor` or the
   lead), so that one source remains before review.
4. **Design review.** The project workflow `/clab-design-review` needs the project agent types; in a
   harness that lacks them, run its three phases by hand: `risk-reviewer` and `clab-ui-reviewer` attack
   `docs/sign-on/DESIGN.md`, `UI.md`, `EXPOSURE.md` in parallel (context: "replaces the no-login invariant
   with local accounts, sessions and TLS for an Internet-exposed VM"); two Opus refuters per finding
   (truth, materiality); the answer table goes to `docs/sign-on/REVIEW.md` in the form of
   `docs/git-redesign/REVIEW.md`; every must-fix is answered in the design, not in a reply.
5. **Build** per `DESIGN.md` 16 (build slices and file ownership): one owner per file; the gate, the
   store change, `main.py` wiring and `host_*`-adjacent paths go to `clab-fable-specialist` or
   `clab-opus-specialist` (privileged-paths rule); routine backend to `clab-backend-engineer`; the pages
   to `clab-ui-builder`; the fixture migration to `mechanical-editor` once the fixture exists; installer,
   TLS and health check to `clab-devops-engineer` with `risk-reviewer` on `deploy/setup-*.sh`; docs to
   `docs-auditor`. TDD: tests first in every slice.
6. **Verify**: `/clab-slice-verify` per slice (or the manual equivalent), `/clab-review-changes` on the
   branch diff, the full suites, then the lead bumps the release (`deploy/set-release.py`, minor:
   1.32.0), writes CHANGELOG, VALIDATION and the handoff section, adds the new pages to
   `deploy/verify-release.py` FIELDS (line 40-41) and the new tests to the CI lists, rewrites the
   `CLAUDE.md` invariant, opens the pull request with `gh api repos/…/pulls` (the GitHub proxy blocks
   `gh pr`).

## 4. Open items

- `EXPOSURE.md` is complete; its 18-item attack list (section 10) is the reviewers' entry point. Its
  correction to INVENTORY.md: `start-manager.sh:120` is `:105` on this branch, and uvicorn's
  `--proxy-headers` is on by default today (trusting loopback), not off.
- The scrypt cost (`n=2**15, r=8, p=1`, ~51 ms with `maxmem=64 MiB` on Python 3.13) was measured on the
  design machine, not on `python:3.12-slim`; the build re-measures in CI (`DESIGN.md` 13.4).
- `Dq 2`: `HostCheckTests` send explicit `Host` headers; the httpx cookie jar is host-only, so those tests
  pass `cookies=` explicitly.
- Whether `git_binding` (`owner`, `path`, `push_url`) stays visible to operators (kept; a reviewer may
  contest).

## 5. Environment notes for the next session

- The first session ran in a cloud environment whose network access blocked `pypi.org` and
  `registry.npmjs.org`: the FastAPI application suites could not run there. Use an environment with
  **Trusted** network access and the setup script from the owner's guide "Cloud Environment Setup for
  CLAB Sessions"; verify with `pip3 download --no-deps -d /tmp/probe fastapi` before building.
- Baseline on `fac28de` in that session: `node --test tests/*.js` → 1185 pass, 0 fail; the stdlib Python
  groups of CI (`test_release_consistency`, `test_claude_config`, `test_install_manager`,
  `test_check_*`, `test_recreate_manager`, `test_gateway_whitelist`, `test_git_onboard`) → OK;
  `deploy/verify-release.py` → 1.31.8 verified; `check_links.py` → 0 problems.
- The project agent types under `.claude/agents/` load in a cloud session one turn after the repository
  is registered; before that, route by model (`Agent` with `model: fable|opus|sonnet|haiku`) and have
  each worker load `clab-worker-contract` and its area skill.
- The GitHub proxy rejects `gh pr`/`gh issue` (GraphQL) and tag pushes; use `gh api` REST calls.
