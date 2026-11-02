# Tools that talk HTTP to the manager, under sign-on

Every tool below `docs/*/tools` that calls the manager and what sign-on did to it. The inventory is every tracked file under a
`tools` folder that this command lists, read one by one (a tool that only imports a library that talks HTTP is a client too):

```
git ls-files docs | grep '/tools/' | grep -vE '\.(png|jpg|json|html|css|txt|svg|md)$' \
  | xargs grep -lE '/api/|urlopen|page\.goto|\.goto\(|8081|8090|8871|curl|MANAGER|\bBASE\b|\.base\b|requests\.|httpx|import (l1lib|l2lib|mgr)|from (l1lib|l2lib|mgr) import'
```

The first version of this table used a narrower pattern (`page\.goto` only) and missed `p.goto(…)`, `s.base`, `BASE` and the scripts that
reach the manager only through `l2lib`; the second pass added them.

The manager answers HTTPS only and every `/api/` route needs a session, so a tool is in one of four states:

1. **Works through the fixture**: it runs against `docs/redesign/tools/fixture_manager.py`, which signs every request
   in (below). Nothing changed in the tool.
2. **Migrated**: it talks to a live manager and now uses `docs/sign-on/tools/manager_http.py`.
3. **Needs the helper**: it talks to a live manager over plain `http://` with no sign-in and was not migrated in this
   slice (why, below). Until it is, it gets `401` or a redirect from a real manager.
4. **Not a client**: the search matched text, an in-process call or something that never reaches the manager.

Counts: 43 work through the fixture, 54 migrated, 55 need the helper, 13 are not clients (165 files; the first version listed 122).

## The fixture (`docs/redesign/tools/fixture_manager.py`)

```
FIXTURE_DATA=$(mktemp -d) clab-backup-ui/.venv/bin/python docs/redesign/tools/fixture_manager.py --port 8090 \
    [--signed-out | --role operator] [--no-vm] [--capture] [--credentials-file PATH]
```

* On a fresh data directory it completes the first-run setup through the real routes (`POST /api/setup` with the code in
  `<data>/setup-code`), then creates an operator with `POST /api/users` and completes that account's forced password
  change. The accounts are the administrator `admin` and the operator `student`, each with its own random password for
  this run (`secrets.token_urlsafe(24)`, 32 characters). **The run prints the account names and the path of the file that
  holds the passwords, never a password** (BUILD.md section 1): the file is `--credentials-file PATH`, else
  `<FIXTURE_DATA>/fixture-credentials.json`, mode 0600, JSON `{"admin": {"name", "password"}, "operator": {"name", "password"}}`.
  No password is written into the repository, a log or a failure message.
  With `--keep` and existing users the fixture replaces those two accounts' passwords in-process, because a random
  password cannot be known to the earlier run.
* **Default: signed in.** The app is served behind a fixture-only ASGI wrapper (`FixtureWrapper`) that adds the fixture
  administrator's `clab_session` cookie to every request, HTTP or WebSocket, that carries none. The Playwright checks
  written before sign-on therefore run unchanged. A session the wrapper holds that ended another way (a sign-out in a
  check) is replaced at the next request.
* `--signed-out`: the wrapper adds nothing; sign in through the real pages or `POST /api/session` with the passwords
  from the credentials file. `--role operator`: the wrapper signs requests in as `student`.
* The fixture's control channel is always reachable and always signed as the administrator, in every mode:
  `/fixture/state`, `/fixture/switch`, `/fixture/action` (the scripted VM, unchanged) and the wrapper's own routes:
  * `POST /__fixture/expire` `{"name": "student", "reason": "idle"}` ends that user's sessions through
    `app.state.sessions.end_user(name, reason)` and answers `{"ended": n}`; the wrapper does not sign that user in again
    until `POST /__fixture/revive` `{"name": ...}`.
  * `GET /__fixture/requests` lists the requests the app saw as `"METHOD /path"`, in order, with `counts`; `POST
    /__fixture/requests/reset` clears the list. A check counts requests (for example the polls after a session ended) with it.
* `--no-vm` removes the lab VM's connection after the seeding (the first-run state; the operator's banner and VM dialog sentences
  are checked against it). `--capture` is the scripted browser-Wireshark stack of the earlier campaign.
* A port that something already listens on is refused at once (`port N on 127.0.0.1 is already in use`), before anything is
  built: a typo must never make a check drive some other server.
* Nothing of this is in `app/`; `tests/test_fixture_signon.py` fails if `app/` ever contains `__fixture` or `FIXTURE_DATA`.

`docs/sign-on/tools/run_regression.sh <port>` starts the fixture with a fresh `FIXTURE_DATA`, runs `verify_after.py` and
`student_workflow.py` against it and exits non-zero when either fails. It refuses a port that is already listening (exit 2,
nothing started) and treats the fixture as up only when `GET /__fixture/requests` answers with the request log, which no
other server does; `check_signon.py` does the same (`port_in_use`, `is_fixture`).

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

* `https://` only. `--pin cert.pem` trusts exactly the **first certificate of the file** (the leaf; a self-signed certificate, or a
  CA-issued `tls/cert.pem`, which holds the full chain, leaf first) and nothing after it: the intermediates and the root in the file are
  not trust anchors, and after the handshake the tool compares the certificate the server presents with the pinned one **byte for
  byte** and closes the connection, before the sign-in, on any difference. A file that starts with a CA (an intermediate, the root, a
  CA bundle) therefore trusts nothing that CA issued, not even the manager's own CA-issued leaf: pin the leaf. A
  leaf-plus-intermediate file works although it holds no self-signed root. The name is not compared (the certificate names the VM's addresses and a tool on the VM uses
  `127.0.0.1`); validity is. `--cafile` verifies the chain and the name. With neither, the installed
  `/srv/containerlab-node-manager/tls/cert.pem` is pinned when readable.
* A browser context (`playwright_context`) ignores certificate errors **only for 127.0.0.1, ::1 and localhost**. Its cookie is a
  full session of `CLAB_USER`; for any other address Chromium keeps verifying the certificate itself (a self-signed remote manager is
  then refused by the browser: trust its certificate in the system store, or run the tool on the VM).
* Credentials: `CLAB_USER` and `CLAB_PASSWORD`, else a `getpass` prompt. **There is no option for a user or a password.**
  Nothing prints a password, a cookie or a session id. A cookie jar keeps the session; a `signed_out` 401 signs in once more
  and repeats the request once. No proxy from the environment is used.
* Every request carries the `Origin` of the base URL; every mutating request a non-empty JSON body (`{}` when none).
* `python docs/sign-on/tools/manager_http.py GET /api/state` is the command line; `docs/git-redesign/tools/live/mgr.py` is a
  thin wrapper that keeps the old `mgr.call(method, path, body, timeout)` signature.
* `deploy/scaffold-lab.py` cannot import it (a deploy script stays self-contained), so it carries the same logic in standard
  library code (the same exact-certificate pin, from `--cafile`, whose alias `--pin` says what it does, or the installed certificate) and the same environment variables. Its default manager is `https://127.0.0.1:8443`.

## The sign-on check (`docs/sign-on/tools/check_signon.py`)

```
PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers clab-backup-ui/.venv/bin/python docs/sign-on/tools/check_signon.py [--port 8871] [--out DIR] [--viewport 390 ...] [--only NAME ...]
```

Starts its own fixture on `--port` (`--signed-out --capture`, fresh `FIXTURE_DATA`, a private credentials file it removes afterwards;
a second fixture with `--no-vm` on `--port`+1 when the operator-and-the-VM scenario runs), signs in through the real pages and stops
the fixtures. Writes `signon-<width>-<view>.png` screenshots, `report.json` (mode 0600) and the fixture's log into `--out` (default
`docs/sign-on/evidence/<date>`). Waits are on UI conditions only (no `networkidle`, no `wait_for_timeout`); the only clock waits are
`until` (polling a count the fixture keeps) and `watch` (a window in which nothing may be sent: 5 or 6 s, longer than the 4 s poll).
Every response of 400 or more, console error, page error and failed request fails the run unless the scenario named that exact
`(status, method, path)` as expected (or blocked that request itself); a request cancelled by a navigation (`ERR_ABORTED`) is
recorded, not failed. Exit 0 all held, 1 a failure, 2 the check could not run (a port that is listening included). This is fixture
evidence: no VM, no TLS, no device. Its machinery is tested without a browser by `clab-backup-ui/tests/test_check_signon.py`
(standard library only).

Coverage of the table of `UI.md` 9.2 (every row has a scenario; the two that are weaker than the row say so):

| UI.md 9.2 row | Scenario | What it asserts beyond the sign-in itself |
|---|---|---|
| Sign-in page, Wrong password, Keyboard (login) | `sign-in and next` | the address keeps lab and tab; the form, the card inside the viewport, no horizontal scroll, focus, Tab order, the wrong-password sentence, the account chip at 1440 and 1280 only |
| Throttling | `throttle` | the sentence, the spoken number kept while the shown one counts, Sign in disabled; the end of the 30 s at 1440 and 390 |
| Open redirect | `open redirect` | `next=//example.org` and `next=/api/state` both land on `/` |
| Forced change | `forced password change` | the change view, the weak password sends nothing, the restricted session's 403 and two 302s, the Current password field after a reload, Sign out from that view |
| Signed in from another site | `cross-site arrival` | the gate sent the browser through `/login` and the form was never shown |
| 401 mid-work | `session ends in a dialog` | the banner is inside `#vm-dialog`; after the first 401 no `GET /api/state` in 6 s; the typed text stays; Try again while signed out keeps the banner; after signing in elsewhere Try again removes it and the polling resumes |
| 401 with a dirty save panel (U9) | `session ends in the save panel` | the panel stays open with `#save-name`'s text, `#session-banner` shows the save-panel text and caption, no navigation, a real click on Try again changes nothing |
| 401 under a running chain (U8) | `session ends under a running operation` | the scripted redeploy's output dialog stops asking after the first 401 (no `GET /api/operations/<id>` in 5 s), asks again after Try again and shows the job's end. The operation is started with the manager's own preview and confirm routes and its output dialog is opened with the page's own `opShowJob`; the review dialogs are covered by `verify_after.py` |
| Sign out (R10, R14) | `sign-out` | with a capture session open: `POST /api/capture/sessions/end-all` before `DELETE /api/session`; the clearing `Set-Cookie` for `clab_session` and for `clab_capture_owner` with `Path=/api/capture`; `/login` without `next`; 401 after; Back shows nothing; and a `DELETE` that never reaches the manager keeps the page, shows *Sign-out did not reach the manager. Try again.* and the polling goes on. The only 401 tolerated is the sign-in page's own `GET /api/session`, so a poll storm after sign-out fails |
| Users page as admin, own row (R12, R2) | `people (administrator)` | the own-row and last-administrator sentences, add / role change (both ways) / reset / deactivate each end in their toast, the audit table shows the operator's failed attempt, a throttled row, the person added, and an em dash (not the text) for a password typed as the name |
| Users page as operator, Keyboard (menu) | `operator` | People and Diagnostics hidden, VM connection and Manager settings disabled with *Administrators only*, ArrowDown skips hidden and disabled items, Escape returns focus, the two refused pages, `GET /api/users` and `/api/audit` 403 |
| Operator and the VM (R13) | `operator and the VM` | on a fixture with no lab VM: no dialog on load, the operator's banner sentence, no Connect button, VM connection… disabled, `openVmDialog()` shows `#vm-operator`, the fixture saw no `PUT /api/host` |
| Terminal pop-up | `terminal pop-up` | **weaker than the row**: the pop-up is opened on a fixture device, the session expires, Connect is answered 401 `signed_out`, the status line reads the sentence and the pop-up stays on `terminal.html`. The fixture has no reachable SSH device, so a *connected* terminal whose socket the manager closes with `signed_out` is not exercised here (that server side is slice S2, which is not in this tree) |
| Student guide | `student guide` | signed out: `302 /login?next=%2Fstudent-guide`; signed in: the PDF; the Help menu shows the entry |
| Screenshots | all | `/login` default and error, the Manager menu (operator), the session banner in a dialog and in the save panel, the users page and its toasts, signed out, the failed sign-out, the terminal and the operator's VM dialog |

Observation recorded in the report notes, not hidden: a sign-out by a browser that never used capture sends
`POST /api/capture/sessions/end-all` and gets 404 (no `clab_capture_owner` cookie), which is a failed request and a console line on
every such sign-out; the sign-out itself goes on.

## What was run when this table was written

Only these, each against the fixture on a scratch `FIXTURE_DATA` (fixture and browser evidence, no VM, no live device):
`check_signon.py` (374 checks at the four widths, none failed, no console error and no unexpected failed request), `run_regression.sh`
(`verify_after.py` 107 of 107 checks at each of its three viewports, `student_workflow.py` 45 of 45; the fixture it started was
confirmed through `/__fixture/requests`), `docs/ui-review-001/tools/check_ui001.py` and `check_ui004.py` (exit 0, from the first
pass of this slice, not rerun after the second), and `docs/git-redesign/tools/integration/save_flow.py`, which stops at the same
step (`#save-see` is not visible after the chip is clicked again) on the tree before sign-on as on this one, so it is not caused by
sign-on (since 1.31.9 it passes: the page opened the chip panel again after **Not now**; see `docs/CHANGELOG.md`). The other fixture rows are classified by reading the tool, not by running it. No migrated live tool was run against a live
manager: there is no VM here; their syntax was checked (`py_compile`) and the helper has its own test
(`clab-backup-ui/tests/test_manager_http.py`, against a local HTTPS server with a throw-away certificate, including a root,
intermediate and two leaves for the pin). The four `s0-fixed` scripts were only byte-compiled.

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
| `docs/git-redesign/tools/live/l2_a1.py` | through `l1lib` / `l2lib` and `mgr.call` (the scenario scripts call no HTTP of their own) |
| `docs/git-redesign/tools/live/l2_a2.py` | through `l1lib` / `l2lib` and `mgr.call` (the scenario scripts call no HTTP of their own) |
| `docs/git-redesign/tools/live/l2_a3.py` | through `l1lib` / `l2lib` and `mgr.call` (the scenario scripts call no HTTP of their own) |
| `docs/git-redesign/tools/live/l2_a3b.py` | through `l1lib` / `l2lib` and `mgr.call` (the scenario scripts call no HTTP of their own) |
| `docs/git-redesign/tools/live/l2_a5b.py` | through `l1lib` / `l2lib` and `mgr.call` (the scenario scripts call no HTTP of their own) |
| `docs/git-redesign/tools/live/l2_b1.py` | through `l1lib` / `l2lib` and `mgr.call` (the scenario scripts call no HTTP of their own) |
| `docs/git-redesign/tools/live/l2_b3.py` | through `l1lib` / `l2lib` and `mgr.call` (the scenario scripts call no HTTP of their own) |
| `docs/git-redesign/tools/live/l2_b4.py` | through `l1lib` / `l2lib` and `mgr.call` (the scenario scripts call no HTTP of their own) |
| `docs/git-redesign/tools/live/l2_b5.py` | through `l1lib` / `l2lib` and `mgr.call` (the scenario scripts call no HTTP of their own) |
| `docs/git-redesign/tools/live/l2_b5b.py` | through `l1lib` / `l2lib` and `mgr.call` (the scenario scripts call no HTTP of their own) |
| `docs/git-redesign/tools/live/l2_c1.py` | through `l1lib` / `l2lib` and `mgr.call` (the scenario scripts call no HTTP of their own) |
| `docs/git-redesign/tools/live/l2_c2.py` | through `l1lib` / `l2lib` and `mgr.call` (the scenario scripts call no HTTP of their own) |
| `docs/git-redesign/tools/live/l2_c3.py` | through `l1lib` / `l2lib` and `mgr.call` (the scenario scripts call no HTTP of their own) |
| `docs/git-redesign/tools/live/l2_c4.py` | through `l1lib` / `l2lib` and `mgr.call` (the scenario scripts call no HTTP of their own) |
| `docs/git-redesign/tools/live/l2_d.py` | through `l1lib` / `l2lib` and `mgr.call` (the scenario scripts call no HTTP of their own) |
| `docs/git-redesign/tools/live/l2_d3.py` | through `l1lib` / `l2lib` and `mgr.call` (the scenario scripts call no HTTP of their own) |
| `docs/git-redesign/tools/live/l2_x_a3_lab_a.py` | through `l1lib` / `l2lib` and `mgr.call` (the scenario scripts call no HTTP of their own) |
| `docs/git-redesign/tools/live/l2_x_a4_finish2.py` | through `l1lib` / `l2lib` and `mgr.call` (the scenario scripts call no HTTP of their own) |
| `docs/git-redesign/tools/live/l2_x_a5_recover.py` | through `l1lib` / `l2lib` and `mgr.call` (the scenario scripts call no HTTP of their own) |
| `docs/git-redesign/tools/live/l2_x_a5_save_after.py` | through `l1lib` / `l2lib` and `mgr.call` (the scenario scripts call no HTTP of their own) |
| `docs/git-redesign/tools/live/l2_x_a5_try3.py` | through `l1lib` / `l2lib` and `mgr.call` (the scenario scripts call no HTTP of their own) |
| `docs/git-redesign/tools/live/l2_x_a5_upl.py` | through `l1lib` / `l2lib` and `mgr.call` (the scenario scripts call no HTTP of their own) |
| `docs/git-redesign/tools/live/l2_x_b5_explore2.py` | through `l1lib` / `l2lib` and `mgr.call` (the scenario scripts call no HTTP of their own) |
| `docs/git-redesign/tools/live/l2_x_c1_explore.py` | through `l1lib` / `l2lib` and `mgr.call` (the scenario scripts call no HTTP of their own) |
| `docs/git-redesign/tools/live/l2_x_c4_finish.py` | through `l1lib` / `l2lib` and `mgr.call` (the scenario scripts call no HTTP of their own) |
| `docs/git-redesign/tools/live/l2_x_c5b.py` | through `l1lib` / `l2lib` and `mgr.call` (the scenario scripts call no HTTP of their own) |
| `docs/git-redesign/tools/live/l2_x_c6_explore.py` | through `l1lib` / `l2lib` and `mgr.call` (the scenario scripts call no HTTP of their own) |
| `docs/git-redesign/tools/live/l2_x_c6_workaround.py` | through `l1lib` / `l2lib` and `mgr.call` (the scenario scripts call no HTTP of their own) |
| `docs/git-redesign/tools/live/l2_x_d_probe.py` | through `l1lib` / `l2lib` and `mgr.call` (the scenario scripts call no HTTP of their own) |
| `docs/git-redesign/tools/live/l2_x_look_b2.py` | through `l1lib` / `l2lib` and `mgr.call` (the scenario scripts call no HTTP of their own) |
| `docs/git-redesign/tools/live/l3_1.py` | through `l1lib` / `l2lib` and `mgr.call` (the scenario scripts call no HTTP of their own) |
| `docs/git-redesign/tools/live/evidence/s0-fixed/scripts/first_save_fixed.py` | dated evidence script, still runnable: `$MANAGER` (default `https://127.0.0.1:8443`) and `manager_http.playwright_context` in place of its `http://127.0.0.1:8081` and bare `new_page` |
| `docs/git-redesign/tools/live/evidence/s0-fixed/scripts/folder_browser_fixed.py` | dated evidence script, still runnable: `$MANAGER` (default `https://127.0.0.1:8443`) and `manager_http.playwright_context` in place of its `http://127.0.0.1:8081` and bare `new_page` |
| `docs/git-redesign/tools/live/evidence/s0-fixed/scripts/folder_browser_lab_b.py` | dated evidence script, still runnable: `$MANAGER` (default `https://127.0.0.1:8443`) and `manager_http.playwright_context` in place of its `http://127.0.0.1:8081` and bare `new_page` |
| `docs/git-redesign/tools/live/evidence/s0-fixed/scripts/next_save.py` | dated evidence script, still runnable: `$MANAGER` (default `https://127.0.0.1:8443`) and `manager_http.playwright_context` in place of its `http://127.0.0.1:8081` and bare `new_page` |
| `docs/git-redesign/tools/live/l2lib.py` | `BASE` from `mgr`; the browser shares the helper's session (`Session(cookies=…, ignore_https_errors=<loopback only>)`) |
| `docs/git-redesign/tools/live/l3_2.py` | through `l1lib` / `l2lib` and `mgr.call` (the scenario scripts call no HTTP of their own) |
| `docs/git-redesign/tools/live/mgr.py` | the helper itself behind `call()` |
| `docs/git-redesign/tools/live/repro_first_save.py` | helper session handed to the browser context |
| `docs/multi-platform-restore/tools/browser_restore.py` | helper session handed to the browser context; `--base`, `--cafile`, `--pin` |
| `docs/multi-platform-restore/tools/failure_harness.py` | through `manager_restore.Manager`; `--url`, `--cafile`, `--pin` |
| `docs/multi-platform-restore/tools/manager_restore.py` | `Manager` wraps `manager_http.Manager`; `--url`, `--cafile`, `--pin` |
| `docs/multi-platform-restore/tools/mixed_failure.py` | one signed-in `manager_http.Manager` for `state()` and `restore_job()` |
| `docs/ui-ux-cleanup/tools/isolation_all_four.py` | through `manager_restore.Manager`; `--url`, `--cafile`, `--pin` |

The browser tools among them (`browser_restore.py`, `l2lib.py`, `repro_first_save.py`, the four `s0-fixed` scripts) take the helper's
session as a cookie for their Chromium context through `playwright_context` (or, in `l2lib.py`, the same rule), which ignores
certificate errors for the loopback addresses only.

## Works through the fixture

| Tool | Why |
|---|---|
| `docs/git-redesign/tools/blocked/attack_labs.py` | runs against the fixture (`common.Session` / its own fixture process); the wrapper signs requests in |
| `docs/git-redesign/tools/blocked/attack_pending.py` | runs against the fixture (`common.Session` / its own fixture process); the wrapper signs requests in |
| `docs/git-redesign/tools/blocked/blocked.py` | runs against the fixture (`common.Session` / its own fixture process); the wrapper signs requests in |
| `docs/git-redesign/tools/fixture/check_fixture.py` | runs against the fixture (`common.Session` / its own fixture process); the wrapper signs requests in |
| `docs/git-redesign/tools/integration/common.py` | runs against the fixture (`common.Session` / its own fixture process); the wrapper signs requests in |
| `docs/git-redesign/tools/integration/drawers_flow.py` | runs against the fixture (`common.Session` / its own fixture process); the wrapper signs requests in |
| `docs/git-redesign/tools/integration/evidence_pass.py` | runs against the fixture (`common.Session` / its own fixture process); the wrapper signs requests in |
| `docs/git-redesign/tools/integration/folder_flow.py` | runs against the fixture (`common.Session` / its own fixture process); the wrapper signs requests in |
| `docs/git-redesign/tools/integration/load_flow.py` | runs against the fixture (`common.Session` / its own fixture process); the wrapper signs requests in |
| `docs/git-redesign/tools/integration/old_addresses.py` | runs against the fixture (`common.Session` / its own fixture process); the wrapper signs requests in |
| `docs/git-redesign/tools/integration/page_fixes.py` | runs against the fixture (`common.Session` / its own fixture process); the wrapper signs requests in |
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
| `docs/save-location-fix/tools/c_lib.py` | the shared library of the C-series of its campaign: it imports `qa_lib.py`, so `qa_lib.py` is the one place to change |
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
| `docs/git-redesign/tools/fixture/fake_git.py` | the fixture's in-process fake GitHub; it serves Git, it never calls the manager |
| `docs/git-redesign/tools/inventory/match_refusals.py` | a source inventory (`git`, `ast`); no request |
| `docs/git-redesign/tools/inventory/outcomes_ad.py` | a text inventory that names routes in sentences; no request |
| `docs/git-redesign/tools/inventory/section9.py` | a text inventory; no request |
| `docs/git-redesign/tools/live/show_version.py` | reads `show version` from a device over SSH (paramiko); no request to the manager |
| `docs/installer-tui/tools/snapshots.py` | a fake installer screen that prints the string `http://127.0.0.1:8081/`; no request is made |
| `docs/maintenance-audit/tools/check_external_links.py` | checks external documentation links; never calls the manager |
| `docs/redesign/tools/fixture_manager.py` | the fixture itself (this slice) |
| `docs/sign-on/tools/manager_http.py` | the helper |
| `docs/sign-on/tools/run_regression.sh` | starts the fixture and runs two fixture checks |
| `docs/uiux-email-2026-10-03/tools/live8_lib.py` | a page-side `fetch` helper used through `live_lib` |
