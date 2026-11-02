# Tools that talk HTTP to the manager, under sign-on

Every tool below `docs/*/tools` that calls the manager (found with `grep -rlE '/api/|urlopen|page\.goto|8081|8090|curl'`)
and what sign-on did to it. The manager answers HTTPS only and every `/api/` route needs a session, so a tool is in one
of four states:

1. **Works through the fixture**: it runs against `docs/redesign/tools/fixture_manager.py`, which signs every request
   in (below). Nothing changed in the tool.
2. **Migrated**: it talks to a live manager and now uses `docs/sign-on/tools/manager_http.py`.
3. **Needs the helper**: it talks to a live manager over plain `http://` with no sign-in and was not migrated in this
   slice (why, below). Until it is, it gets `401` or a redirect from a real manager.
4. **Not a client**: the search matched text, an in-process call or something that never reaches the manager.

Counts: 40 work through the fixture, 19 migrated, 54 need the helper, 9 are not clients.

## The fixture (`docs/redesign/tools/fixture_manager.py`)

```
FIXTURE_DATA=$(mktemp -d) clab-backup-ui/.venv/bin/python docs/redesign/tools/fixture_manager.py --port 8090 \
    [--signed-out | --role operator] [--credentials-file PATH]
```

* On a fresh data directory it completes the first-run setup through the real routes (`POST /api/setup` with the code in
  `<data>/setup-code`), then creates an operator with `POST /api/users` and completes that account's forced password
  change. The accounts are the administrator `admin` and the operator `student`, each with its own random password for
  this run (`secrets.token_urlsafe(24)`, 32 characters). **The run prints both passwords** (they are valid only for this
  scratch data directory), and `--credentials-file PATH` also writes them as JSON, mode 0600:
  `{"admin": {"name", "password"}, "operator": {"name", "password"}}`. No password is written into the repository.
  With `--keep` and existing users the fixture replaces those two accounts' passwords in-process, because a random
  password cannot be known to the earlier run.
* **Default: signed in.** The app is served behind a fixture-only ASGI wrapper (`FixtureWrapper`) that adds the fixture
  administrator's `clab_session` cookie to every request, HTTP or WebSocket, that carries none. The Playwright checks
  written before sign-on therefore run unchanged. A session the wrapper holds that ended another way (a sign-out in a
  check) is replaced at the next request.
* `--signed-out`: the wrapper adds nothing; sign in through the real pages or `POST /api/session` with the printed
  credentials. `--role operator`: the wrapper signs requests in as `student`.
* The fixture's control channel is always reachable and always signed as the administrator, in every mode:
  `/fixture/state`, `/fixture/switch`, `/fixture/action` (the scripted VM, unchanged) and the wrapper's own routes:
  * `POST /__fixture/expire` `{"name": "student", "reason": "idle"}` ends that user's sessions through
    `app.state.sessions.end_user(name, reason)` and answers `{"ended": n}`; the wrapper does not sign that user in again
    until `POST /__fixture/revive` `{"name": ...}`.
  * `GET /__fixture/requests` lists the requests the app saw as `"METHOD /path"`, in order, with `counts`; `POST
    /__fixture/requests/reset` clears the list. A check counts requests (for example the polls after a session ended) with it.
* Nothing of this is in `app/`; `tests/test_fixture_signon.py` fails if `app/` ever contains `__fixture` or `FIXTURE_DATA`.

`docs/sign-on/tools/run_regression.sh <port>` starts the fixture with a fresh `FIXTURE_DATA`, runs `verify_after.py` and
`student_workflow.py` against it and exits non-zero when either fails.

## The helper (`docs/sign-on/tools/manager_http.py`)

Standard library only.

```python
import sys; sys.path.insert(0, 'docs/sign-on/tools')
from manager_http import Manager, playwright_context
manager = Manager('https://127.0.0.1:8443')      # or $MANAGER; --pin / --cafile / $CLAB_PIN / $CLAB_CAFILE
status, answer = manager.get('/api/state')       # signs in with CLAB_USER and CLAB_PASSWORD (or a prompt) on the first request
status, answer = manager.post('/api/discovery/refresh')   # a missing body is sent as {}
context = playwright_context(browser, manager, viewport={'width': 1440, 'height': 900})   # a browser that shares the session
```

* `https://` only. `--pin cert.pem` trusts exactly that certificate without comparing the name (the certificate names the
  VM's addresses and a tool on the VM uses `127.0.0.1`); `--cafile` verifies the chain and the name. With neither, the
  installed `/srv/containerlab-node-manager/tls/cert.pem` is pinned when readable.
* Credentials: `CLAB_USER` and `CLAB_PASSWORD`, else a `getpass` prompt. **There is no option for a user or a password.**
  Nothing prints a password, a cookie or a session id. A cookie jar keeps the session; a `signed_out` 401 signs in once more
  and repeats the request once. No proxy from the environment is used.
* Every request carries the `Origin` of the base URL; every mutating request a non-empty JSON body (`{}` when none).
* `python docs/sign-on/tools/manager_http.py GET /api/state` is the command line; `docs/git-redesign/tools/live/mgr.py` is a
  thin wrapper that keeps the old `mgr.call(method, path, body, timeout)` signature.
* `deploy/scaffold-lab.py` cannot import it (a deploy script stays self-contained), so it carries the same logic in standard
  library code, with `--cafile` and the same environment variables. Its default manager is `https://127.0.0.1:8443`.

## The sign-on check (`docs/sign-on/tools/check_signon.py`)

```
PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers clab-backup-ui/.venv/bin/python docs/sign-on/tools/check_signon.py [--port 8871] [--out DIR] [--viewport 390 ...] [--only NAME ...]
```

Starts its own fixture (`--signed-out`, fresh `FIXTURE_DATA`, a private credentials file it removes afterwards), signs in through the real
pages and stops the fixture. Writes `signon-<width>-<view>.png` screenshots, `report.json` (mode 0600) and the fixture's log with the
passwords removed into `--out` (default `docs/sign-on/evidence/<date>`). At 1440, 1280, 760 and 390 px it exercises: a signed-out visit of
a lab and tab (the `/login` address keeps the fragment, sign-in returns to that tab, the account chip at 1440 and 1280 only); a wrong
password and the Tab order; the open-redirect `next`; the operator's Manager menu (no People, no Diagnostics, VM connection and Manager
settings disabled with *Administrators only*), its keyboard path and the two refused pages; the throttle sentence and countdown; the
People page as the administrator (own-row rules, add a person, the audit table) and a new person's forced change on the sign-in page
(weak password sends nothing, restricted-session answers of the gate, the Current password field after a reload, Sign out from that
view); arrival from another site with a live session; sign-out, `GET /api/state` 401 and Back. Waits are on UI conditions only (no
`networkidle`, no fixed delay). Every response of 400 or more, console error, page error and failed request fails the run unless the
scenario named that exact `(status, method, path)` as expected; a request cancelled by a navigation (`ERR_ABORTED`) is recorded, not failed.
Exit 0 all held, 1 a failure, 2 the check could not run. The countdown's end (30 s) is checked at 1440 and 390 only. This is fixture
evidence: no VM, no TLS, no device. Its machinery is tested without a browser by `clab-backup-ui/tests/test_check_signon.py` (standard
library only).

## What was run when this table was written

Only these, each against the fixture on a scratch `FIXTURE_DATA` (fixture and browser evidence, no VM, no live device):
`run_regression.sh` (`verify_after.py` 107 of 107 checks at each of its three viewports, `student_workflow.py` 45 of 45),
`docs/ui-review-001/tools/check_ui001.py` and `check_ui004.py` (exit 0), and `docs/git-redesign/tools/integration/save_flow.py`,
which stops at the same step (`#save-see` is not visible after the chip is clicked again) on the tree before sign-on as on this
one, so it is not caused by sign-on. The other fixture rows are classified by reading the tool, not by running it. No migrated
live tool was run against a live manager: there is no VM here; their syntax was checked (`py_compile`) and the helper has its own
test (`clab-backup-ui/tests/test_manager_http.py`, against a local HTTPS server with a throw-away certificate).

## Migrated

| Tool | How |
|---|---|
| `docs/git-redesign/tools/live/l1_s10.py` | through `l1lib` / `l2lib` and `mgr.call` (the scenario scripts call no HTTP of their own) |
| `docs/git-redesign/tools/live/l1_s15.py` | through `l1lib` / `l2lib` and `mgr.call` (the scenario scripts call no HTTP of their own) |
| `docs/git-redesign/tools/live/l1_s17_state.py` | through `l1lib` / `l2lib` and `mgr.call` (the scenario scripts call no HTTP of their own) |
| `docs/git-redesign/tools/live/l1lib.py` | through `mgr.call` |
| `docs/git-redesign/tools/live/l2_a4.py` | through `l1lib` / `l2lib` and `mgr.call` (the scenario scripts call no HTTP of their own) |
| `docs/git-redesign/tools/live/l2_a5.py` | through `l1lib` / `l2lib` and `mgr.call` (the scenario scripts call no HTTP of their own) |
| `docs/git-redesign/tools/live/l2_b2.py` | through `l1lib` / `l2lib` and `mgr.call` (the scenario scripts call no HTTP of their own) |
| `docs/git-redesign/tools/live/l2_c5.py` | through `l1lib` / `l2lib` and `mgr.call` (the scenario scripts call no HTTP of their own) |
| `docs/git-redesign/tools/live/l2_c6.py` | through `l1lib` / `l2lib` and `mgr.call` (the scenario scripts call no HTTP of their own) |
| `docs/git-redesign/tools/live/l2_x_c6_second.py` | through `l1lib` / `l2lib` and `mgr.call` (the scenario scripts call no HTTP of their own) |
| `docs/git-redesign/tools/live/l2lib.py` | `BASE` from `mgr`; the browser shares the helper's session (`Session(cookies=…, ignore_https_errors=True)`) |
| `docs/git-redesign/tools/live/l3_2.py` | through `l1lib` / `l2lib` and `mgr.call` (the scenario scripts call no HTTP of their own) |
| `docs/git-redesign/tools/live/mgr.py` | the helper itself behind `call()` |
| `docs/git-redesign/tools/live/repro_first_save.py` | helper session handed to the browser context |
| `docs/multi-platform-restore/tools/browser_restore.py` | helper session handed to the browser context; `--base`, `--cafile`, `--pin` |
| `docs/multi-platform-restore/tools/failure_harness.py` | through `manager_restore.Manager`; `--url`, `--cafile`, `--pin` |
| `docs/multi-platform-restore/tools/manager_restore.py` | `Manager` wraps `manager_http.Manager`; `--url`, `--cafile`, `--pin` |
| `docs/multi-platform-restore/tools/mixed_failure.py` | one signed-in `manager_http.Manager` for `state()` and `restore_job()` |
| `docs/ui-ux-cleanup/tools/isolation_all_four.py` | through `manager_restore.Manager`; `--url`, `--cafile`, `--pin` |

The browser tools among them (`browser_restore.py`, `l2lib.py`, `repro_first_save.py`) take the helper's session as a cookie
for their Chromium context and set `ignore_https_errors`, because Chromium does not know the manager's own certificate.

## Works through the fixture

| Tool | Why |
|---|---|
| `docs/git-redesign/tools/blocked/attack_pending.py` | runs against the fixture (`common.Session` / its own fixture process); the wrapper signs requests in |
| `docs/git-redesign/tools/blocked/blocked.py` | runs against the fixture (`common.Session` / its own fixture process); the wrapper signs requests in |
| `docs/git-redesign/tools/fixture/check_fixture.py` | runs against the fixture (`common.Session` / its own fixture process); the wrapper signs requests in |
| `docs/git-redesign/tools/integration/common.py` | runs against the fixture (`common.Session` / its own fixture process); the wrapper signs requests in |
| `docs/git-redesign/tools/integration/drawers_flow.py` | runs against the fixture (`common.Session` / its own fixture process); the wrapper signs requests in |
| `docs/git-redesign/tools/integration/evidence_pass.py` | runs against the fixture (`common.Session` / its own fixture process); the wrapper signs requests in |
| `docs/git-redesign/tools/integration/load_flow.py` | runs against the fixture (`common.Session` / its own fixture process); the wrapper signs requests in |
| `docs/git-redesign/tools/integration/old_addresses.py` | runs against the fixture (`common.Session` / its own fixture process); the wrapper signs requests in |
| `docs/git-redesign/tools/integration/save_flow.py` | runs against the fixture (`common.Session` / its own fixture process); the wrapper signs requests in |
| `docs/lab-builder/tools/post_save_checks.py` | targets the fixture manager |
| `docs/lab-builder/tools/student_workflow.py` | targets the fixture manager |
| `docs/lab-builder/tools/uiux_email_checks.py` | targets the fixture manager |
| `docs/netlab-integration/tools/check_design_ui.py` | targets the fixture manager |
| `docs/netlab-ui-qa/acceptance/pass-2/tools/adversarial_names.py` | targets the fixture manager |
| `docs/netlab-ui-qa/acceptance/pass-5/tools/check_qa002_more_menu.py` | targets the fixture manager |
| `docs/netlab-ui-qa/acceptance/pass-6/tools/adversarial_design.py` | targets the fixture manager |
| `docs/netlab-ui-qa/acceptance/pass-7/tools/check_more_menu_reasons.py` | targets the fixture manager |
| `docs/netlab-ui-qa/acceptance/pass-8/tools/adversarial_transitions.py` | targets the fixture manager |
| `docs/netlab-ui-qa/tools/check_design_poll_retry.py` | targets the fixture manager |
| `docs/netlab-ui-qa/tools/coverage_run.py` | runs against the fixture (it says it never touches 8081) |
| `docs/netlab-ui-qa/tools/inventory_dom.py` | targets the fixture manager |
| `docs/netlab-ui-qa/tools/probes/design_probes.py` | targets the fixture manager |
| `docs/netlab-ui-qa/tools/stress_design.py` | targets the fixture manager |
| `docs/netlab-ui-qa/tools/usability_scan.py` | runs against the fixture (it says it never touches 8081) |
| `docs/parity-campaign/tools/check_c06.py` | targets the fixture manager |
| `docs/redesign/tools/readme_shots.py` | targets the fixture manager |
| `docs/redesign/tools/verify_after.py` | targets the fixture manager |
| `docs/ui-review-001/tools/check_ui001.py` | targets the fixture manager |
| `docs/ui-review-001/tools/check_ui002a.py` | targets the fixture manager |
| `docs/ui-review-001/tools/check_ui002b.py` | targets the fixture manager |
| `docs/ui-review-001/tools/check_ui003.py` | targets the fixture manager |
| `docs/ui-review-001/tools/check_ui003b.py` | targets the fixture manager |
| `docs/ui-review-001/tools/check_ui004.py` | targets the fixture manager |
| `docs/ui-review-001/tools/check_ui005.py` | targets the fixture manager |
| `docs/ui-review-001/tools/check_ui006.py` | targets the fixture manager |
| `docs/ui-review-001/tools/check_ui007ab.py` | targets the fixture manager |
| `docs/ui-review-001/tools/check_ui007c.py` | targets the fixture manager |
| `docs/ui-review-001/tools/check_ui008a.py` | targets the fixture manager |
| `docs/ui-review-001/tools/check_ui008b.py` | targets the fixture manager |
| `docs/ui-ux-cleanup/tools/check_lab_builder_yaml.py` | targets the fixture manager |

A tool in this group that is pointed at a live manager instead of the fixture is in the next group.

## Needs the helper, and why it was not migrated here

| Tool | Why |
|---|---|
| `docs/netlab-integration/tools/check_design_apply_ui.py` | a live-manager tool (plain `http://` address, no sign-in) |
| `docs/netlab-integration/tools/check_design_export_ui.py` | a live-manager tool (plain `http://` address, no sign-in) |
| `docs/netlab-integration/tools/check_design_live.py` | a live-manager tool (plain `http://` address, no sign-in) |
| `docs/netlab-ui-qa/acceptance/pass-2/tools/api_previews.py` | a live-manager tool (plain `http://` address, no sign-in) |
| `docs/netlab-ui-qa/acceptance/pass-2/tools/capture_dialog_ports.py` | a live-manager tool (plain `http://` address, no sign-in) |
| `docs/netlab-ui-qa/acceptance/pass-4/tools/adversarial_restart_preview.py` | a live-manager tool (plain `http://` address, no sign-in) |
| `docs/netlab-ui-qa/acceptance/pass-6/tools/previews_refusals.py` | a live-manager tool (plain `http://` address, no sign-in) |
| `docs/netlab-ui-qa/acceptance/pass-8/tools/live_transitions.py` | a live-manager tool (plain `http://` address, no sign-in) |
| `docs/netlab-ui-qa/acceptance/pass-8/tools/previews_refusals.py` | a live-manager tool (plain `http://` address, no sign-in) |
| `docs/netlab-ui-qa/tools/check_restart_device.py` | a live-manager tool (plain `http://` address, no sign-in) |
| `docs/netlab-ui-qa/tools/check_restart_neighbour.py` | a live-manager tool (plain `http://` address, no sign-in) |
| `docs/netlab-ui-qa/tools/check_restart_two_tabs.py` | a live-manager tool (plain `http://` address, no sign-in) |
| `docs/redesign/tools/audit_current.py` | a live-manager tool (plain `http://` address, no sign-in) |
| `docs/redesign/tools/audit_menus.py` | a live-manager tool (plain `http://` address, no sign-in) |
| `docs/redesign/tools/audit_rest.py` | a live-manager tool (plain `http://` address, no sign-in) |
| `docs/redesign/tools/verify_stage1.py` | a live-manager tool (plain `http://` address, no sign-in) |
| `docs/save-location-fix/tools/b0_legacy_recovery.py` | live tool; its address and calls come from `qa_lib.py` |
| `docs/save-location-fix/tools/b1_b2_saves.py` | live tool; its address and calls come from `qa_lib.py` |
| `docs/save-location-fix/tools/b3_unchanged_cancel.py` | live tool; its address and calls come from `qa_lib.py` |
| `docs/save-location-fix/tools/b4_checkpoints_baseline.py` | live tool; its address and calls come from `qa_lib.py` |
| `docs/save-location-fix/tools/b5_faults.py` | live tool; its address and calls come from `qa_lib.py` |
| `docs/save-location-fix/tools/b6_discovery.py` | live tool; its address and calls come from `qa_lib.py` |
| `docs/save-location-fix/tools/b7_apply.py` | live tool; its address and calls come from `qa_lib.py` |
| `docs/save-location-fix/tools/b7_restore_submit.py` | live tool; its address and calls come from `qa_lib.py` |
| `docs/save-location-fix/tools/b7_stale_invalid.py` | live tool; its address and calls come from `qa_lib.py` |
| `docs/save-location-fix/tools/b8_after_apply.py` | live tool; its address and calls come from `qa_lib.py` |
| `docs/save-location-fix/tools/c1_prepare.py` | live tool; its address and calls come from `qa_lib.py` |
| `docs/save-location-fix/tools/c1_resume.py` | live tool; its address and calls come from `qa_lib.py` |
| `docs/save-location-fix/tools/c6_save_and_seed.py` | live tool; its address and calls come from `qa_lib.py` |
| `docs/save-location-fix/tools/c8_rejections.py` | live tool; its address and calls come from `qa_lib.py` |
| `docs/save-location-fix/tools/c_apply.py` | live tool; its address and calls come from `qa_lib.py` |
| `docs/save-location-fix/tools/qa_lib.py` | the shared library of its campaign: its `BASE` and `api()`/`fetch` are the one place to change for every tool that imports it |
| `docs/save-location-fix/tools/repro_apply_manifest.py` | live tool; its address and calls come from `qa_lib.py` |
| `docs/save-location-fix/tools/repro_nested_latest.py` | live tool; its address and calls come from `qa_lib.py` |
| `docs/student-quick-start/tools/capture_scenario_a.py` | live tool; address and calls from `qs_lib.py` |
| `docs/student-quick-start/tools/capture_scenario_b.py` | live tool; address and calls from `qs_lib.py` |
| `docs/student-quick-start/tools/qs_lib.py` | the shared library of its campaign: its `BASE` and `api()`/`fetch` are the one place to change for every tool that imports it |
| `docs/student-quick-start/tools/qs_ui.py` | live tool; address and calls from `qs_lib.py` |
| `docs/student-quick-start/tools/reset_scenario_a.sh` | shell script that runs `curl` against `http://127.0.0.1:8081` |
| `docs/student-quick-start/tools/reset_scenario_b.sh` | shell script that runs `curl` against `http://127.0.0.1:8081` |
| `docs/technical-audit/tools/check_release_1_30_39.py` | a live-manager tool (plain `http://` address, no sign-in) |
| `docs/technical-audit/tools/check_release_1_30_42.py` | a live-manager tool (plain `http://` address, no sign-in) |
| `docs/technical-audit/tools/fresh_install_vm.py` | drives a test VM over SSH and runs `curl http://127.0.0.1:8081/api/…` there |
| `docs/ui-ux-changes-2/tools/check_backup_topology.py` | a live-manager tool (plain `http://` address, no sign-in) |
| `docs/ui-ux-changes-2/tools/check_hide_lab.py` | a live-manager tool (plain `http://` address, no sign-in) |
| `docs/ui-ux-changes-2/tools/check_image_availability.py` | a live-manager tool (plain `http://` address, no sign-in) |
| `docs/ui-ux-changes-2/tools/check_image_fields.py` | a live-manager tool (plain `http://` address, no sign-in) |
| `docs/ui-ux-changes-2/tools/check_labels.py` | a live-manager tool (plain `http://` address, no sign-in) |
| `docs/ui-ux-changes-2/tools/check_preview.py` | a live-manager tool (plain `http://` address, no sign-in) |
| `docs/ui-ux-changes-2/tools/installer_lock_repro.py` | a live-manager tool (plain `http://` address, no sign-in) |
| `docs/ui-ux-cleanup/tools/check_release_1_30_36.py` | a live-manager tool (plain `http://` address, no sign-in) |
| `docs/ui-ux-cleanup/tools/check_release_1_30_37_a.py` | a live-manager tool (plain `http://` address, no sign-in) |
| `docs/ui-ux-cleanup/tools/live_1_30_37_b.py` | a live-manager tool (plain `http://` address, no sign-in) |
| `docs/uiux-email-2026-10-03/tools/live_lib.py` | the shared library of its campaign: its `BASE` and `api()`/`fetch` are the one place to change for every tool that imports it |

These are the per-campaign acceptance and audit scripts of earlier work. Each was written against one live lab on one VM
(`restore-square`, `link-basics`, a named test VM), records its result in its campaign folder, and cannot be run from a
development checkout without that VM. Moving them without being able to run them would change what they test
unseen, and the brief for this slice named the live tools of the routing table (`git-redesign/tools/live`,
`integration`, `multi-platform-restore`) and no others. The change for each is small and mechanical:

* a tool that calls `urllib` or `httpx`: build one `Manager(os.environ.get('MANAGER', 'https://127.0.0.1:8443'))` and call
  `manager.get/post/...` (the answer is `(status, parsed JSON)`);
* a Playwright tool: `playwright_context(browser, manager, viewport=...)` in place of `browser.new_context(...)`, and the
  base URL from the same variable;
* a `curl` script: add `--cacert /srv/containerlab-node-manager/tls/cert.pem`, sign in once with `-c jar` and
  `POST /api/session`, and send `-b jar` and `-H "Origin: https://127.0.0.1:8443"` on every call (read the password from the
  environment, never from the command line);
* the shared libraries (`qa_lib.py`, `qs_lib.py`, `live_lib.py`) are the one place to change for every tool that imports them.

## Not clients of the manager

| Tool | What it is |
|---|---|
| `docs/git-redesign/tools/fixture/fixture_control.py` | the fixture's own `/fixture/*` routes (they are the control channel and stay reachable in every mode) |
| `docs/git-redesign/tools/fixture/fixture_scenarios.py` | seeds the fixture in-process through the `client` that `fixture_manager.build` passes (the admin session of the fixture) |
| `docs/git-redesign/tools/inventory/outcomes_ad.py` | a text inventory that names routes in sentences; no request |
| `docs/installer-tui/tools/snapshots.py` | a fake installer screen that prints the string `http://127.0.0.1:8081/`; no request is made |
| `docs/maintenance-audit/tools/check_external_links.py` | checks external documentation links; never calls the manager |
| `docs/redesign/tools/fixture_manager.py` | the fixture itself (this slice) |
| `docs/sign-on/tools/manager_http.py` | the helper |
| `docs/sign-on/tools/run_regression.sh` | starts the fixture and runs two fixture checks |
| `docs/uiux-email-2026-10-03/tools/live8_lib.py` | a page-side `fetch` helper used through `live_lib` |
