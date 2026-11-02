---
paths:
  - "clab-backup-ui/app/host_*.py"
  - "deploy/clab-manager-gateway"
  - "deploy/setup-*.sh"
  - "clab-backup-ui/app/store.py"
  - "clab-backup-ui/app/main.py"
  - "clab-backup-ui/app/allowed_hosts.py"
  - "clab-backup-ui/app/capture_service.py"
  - "clab-backup-ui/app/capture_sessions.py"
  - "clab-backup-ui/app/lab_operations.py"
  - "clab-backup-ui/app/git_places.py"
  - "clab-backup-ui/app/git_progress.py"
  - "clab-backup-ui/app/discovery.py"
  - "clab-backup-ui/app/sessions.py"
  - "clab-backup-ui/app/accounts.py"
  - "clab-backup-ui/app/origin.py"
  - "clab-backup-ui/app/headers.py"
  - "clab-backup-ui/app/recover.py"
  - "clab-backup-ui/app/redirect.py"
  - "clab-backup-ui/app/probe.py"
  - "deploy/setup_tls.py"
  - "deploy/manager-recover-admin.sh"
---

# Routing: the privileged paths (this rule loaded because you touched one)

The VM helper boundary (a helper or one of its manager-side clients), the Store, the shared busy guard
`operation_busy`, the folder rule `colliding()` that `git_places.py` keeps equal to the helper's, the
same-origin guard, the session gate and the sign-on modules (accounts, sessions, origin, headers, the
recovery and the read-only probes), the redirect listener, the TLS tool or the capture service is in front
of you.
Read `CLAUDE.md` "VM boundary and data" and "Side stack" first, then the handoff sections the routing
table names for the area.

- **Builder.** The lead, `clab-fable-specialist` or `clab-opus-specialist`; `clab-backend-engineer`
  only for a change the lead specified line by line. Never `mechanical-editor` or `clab-ui-builder`.
- **Reviewer, before the change is called done.** `risk-reviewer` on the diff, through
  `/clab-review-changes` or a direct delegation that includes the diff. Its must-fix findings are
  answered in the change, not waved through.
- **Never without the owner.** The gateway's three request names, each helper's option whitelist,
  trusted roots, review digests, the single host lock, the removed `write` mode, password-only VM
  login, the pinned host key, the manager without a Docker socket, `HostCheck` as the outermost layer.
  Helper `VERSION` moves only through `deploy/set-release.py`.
- **Tests that must stay green.** `test_gateway_whitelist.py`, `test_gateway_preflight.py`,
  `test_helper_preflight.py`, `test_host_git.py`, `test_lab_operations.py`, `test_vm_files.py`,
  `test_app.py`, `test_capture.py`, `test_capture_sessions.py`, `test_capture_proxy.py`, and for sign-on
  `test_session.py`, `test_users.py`, `test_password.py`, `test_audit.py`, `test_setup.py`,
  `test_ticket_binding.py`, `test_socket_session.py`, `test_redirect.py`, `test_probe.py`, `test_setup_tls.py`.
