# Sign-on build: slices, ownership and contracts

The lead's build plan for the sign-on stream. It answers `DESIGN.md` 16 after the design review
(`REVIEW.md`); where the two differ, this file is the plan the workers follow and `DESIGN.md` is the
behaviour they build. Written 2026-11-01. **Draft:** sections 3 and 4 are completed from the amended design before any slice starts; the base commit is named here when the worktrees are made.

## 1. Every worker

- **Your worktree.** The lead made one Git worktree per slice under `.claude/worktrees/<slice>` on
  branch `signon/<slice>` from the base commit. Work only there (`cd` into it first; every path below is
  relative to it). Commit your slice there with a clear message, as often as you like; never push, never
  switch branches, never touch the main checkout at `/home/user/CLAB-BACKUP-WORKER-v2` except to read.
- **Python.** The worktree has no virtual environment. From `<worktree>/clab-backup-ui` run
  `PATH="/home/user/CLAB-BACKUP-WORKER-v2/clab-backup-ui/.venv/bin:$PATH" python -m unittest discover -s tests -t tests -p <file>`
  (tests import `app` from the working directory, so the worktree's code is what runs). Stdlib-only
  deploy tests run with the system `python3`. Node is 22 (`node --test tests/<file>.js`).
- **Only your files.** The table in section 2 is the ownership: edit no file that another slice owns or
  that no slice owns. If you need a change outside your files, stop and report it as a request to the lead.
- **Test first.** Write the failing test of a behaviour before the code (the `test-driven-development`
  skill). Every behavioural claim of an existing test stays: a pinned label is rewritten, never deleted.
- **Known red in your worktree, not yours to fix:** `test_release_consistency.py` `CiListTests` fails for
  every new test file until the lead adds it to `.github/workflows/release-check.yml` at integration.
  Every other failure is yours.
- **Never** point a test or a `Store` at `/srv/containerlab-node-manager/data`; never print or log a
  password, a setup code, a session id, a cookie value or a hash.
- **Hand back** (your final answer): changed paths, commits, every test command with its exit code, the
  contracts you provide exactly as built, open gaps, and requests to the lead.

## 2. Slices and ownership

| Slice | Builder | Owns (relative to the repository root) | Starts after |
|---|---|---|---|
| S1 core | `clab-fable-specialist` | `clab-backup-ui/app/{accounts,sessions,origin,headers,recover}.py` (new), `app/store.py`, `app/main.py`, `app/allowed_hosts.py`, `app/discovery.py` (the admin dependency on `PUT /api/host` only), `app/diagnostics.py` (the admin dependency only), `app/runner.py` (`secrets_to_hide` only), `tests/session_fixture.py`, `tests/test_{password,session,setup,users,audit,signon_load}.py` (new), `tests/test_manager_reset.py`, then the migration of every `TestClient(` site in the 23 existing test files | base |
| S2 sockets | `clab-opus-specialist` | `app/node_services.py`, `app/capture_sessions.py`, `tests/test_ticket_binding.py`, `tests/test_socket_session.py` (new); after S1 hands over, the socket assertions of `test_nodes.py`, `test_capture_sessions.py`, `test_capture_proxy.py`, `test_capture.py` | S1, same worktree |
| S3 probe and redirect | `clab-opus-specialist` | `app/probe.py`, `app/redirect.py`, `tests/test_probe.py`, `tests/test_redirect.py` (new) | base |
| S4 TLS and container | `clab-fable-specialist` | `deploy/setup-tls.sh`, `deploy/setup_tls.py` (new), `clab-backup-ui/Dockerfile`, `clab-backup-ui/compose.yml`, `deploy/compose.image.yml`, `deploy/start-manager.sh`, `deploy/recreate-manager.sh`, `deploy/verify-release.py` (the `verify_docs` rule only), `tests/test_setup_tls.py` (new), `tests/test_release_consistency.py` | base |
| S5a host doors | `clab-opus-specialist` | `deploy/setup-firewall.sh`, `deploy/setup-ssh-hardening.sh`, `deploy/manager-recover-admin.sh` (new), `tests/test_setup_firewall.py`, `tests/test_setup_ssh_hardening.py`, `tests/test_manager_recover_admin.py` (new) | base |
| S5b installer | `clab-devops-engineer` | `deploy/install-manager.py`, `deploy/install-prerequisites.sh`, `deploy/installer_tui/**`, `tests/test_install_manager.py`, `tests/test_install_tui_*.py` | base |
| S6 health check | `clab-devops-engineer` | `deploy/check_install.py`, `deploy/check_host.py`, `tests/test_check_install.py`, `tests/test_check_host.py` | base |
| S7 exposed pages | `clab-ui-builder` | `app/static/{login.html,login.css,login.js,setup.html,setup.js}` (new), `tests/test_login_ui.js`, `tests/test_setup_ui.js` (new) | base |
| S8 app session | `clab-ui-builder` | `app/static/{session.js,account.js}` (new), `shell.js`, `app.js`, `index.html`, `style.css`, `status.js`, `management.js`, `home.js`, `tests/test_session_ui.js`, `tests/test_account_ui.js` (new), `tests/test_page_load_ui.js`, `tests/test_shell_ui.js`, `tests/test_status_ui.js`, `tests/test_home_ui.js`, and the browser tests of `management.js` | base |
| S9 users page | `clab-ui-builder` | `app/static/{users.html,users.js}` (new), `tests/test_users_ui.js` (new) | base |
| S10a feature scripts | `clab-ui-builder` | `app/static/{operations,network-design,load,restore,git-progress,device-diagnostics,map-tools,device-impairments}.js` and their browser tests | base |
| S10b standalone pages | `clab-ui-builder` | `app/static/{workspace,debug,lab-builder-page,map-editor-page,terminal,capture-session}.js` and `{workspace,debug,lab-builder,map-editor,terminal,capture-session,capture-setup,vm-connection}.html` and their browser tests | base |
| S11 tools and fixture | `clab-ui-qa` | `docs/redesign/tools/fixture_manager.py`, `docs/sign-on/tools/**` (new), the live tools named in section 5 | S1, S7, S8 integrated |
| S12 documentation | `docs-auditor` (two, split by file) | the living guides of `EXPOSURE.md` 8.1 and `DESIGN.md` 12 | code integrated |
| Lead | the lead | `.github/workflows/release-check.yml`, `deploy/verify-release.py` FIELDS, `deploy/set-release.py`, `CLAUDE.md`, `.claude/**`, `docs/redesign/DESIGN-SPEC-ADDENDUM.md`, the release records, `docs/sign-on/{PICKUP,BUILD,REVIEW}.md` | integration |

## 3. Contracts between slices

To be completed from the amended `DESIGN.md` 16 ("Names shared between slices"), `UI.md` 3.2 and
`EXPOSURE.md` 6 and 9 before the build starts.
