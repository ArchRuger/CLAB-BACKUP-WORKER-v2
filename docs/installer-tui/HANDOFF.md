# Integration handoff for Worker A — INSTALLER-TUI-B1

Worker B did not touch shared files: release markers, `VERSION`, the three history files,
`.github/workflows/release-check.yml`, `docs/REPOSITORY-MAINTENANCE.md`, `CLAUDE.md`, the living
guides or any helper other than `install-manager.py`. This page lists what A should apply or decide.
Coordination: https://github.com/ArchRuger/CLAB-BACKUP-WORKER-v2/issues/64

## 1. CI (`.github/workflows/release-check.yml`)

Applied (whole-codebase audit finding M-17): both snippets below are in the workflow as written, the
Textual stage right after "Install application test dependencies". They stay here as the rationale.

**a. Stdlib stage** "Check release and helper regression tests" — append after the
`test_install_manager.py` line (system `python3`, no Textual needed):

```yaml
          python3 -m unittest discover -s tests -p test_install_tui_core.py -v
```

**b. New stage** after "Install application test dependencies" (its own venv from the hashed lock, so
the optional TUI tests run instead of skipping; `INSTALLER_TUI_REQUIRED=1` turns a missing Textual
into a failure):

```yaml
      - name: Full-screen installer (Textual) tests
        working-directory: clab-backup-ui
        env:
          INSTALLER_TUI_REQUIRED: '1'
        run: |
          python3 -m venv "$RUNNER_TEMP/installer-tui-venv"
          "$RUNNER_TEMP/installer-tui-venv/bin/python" -m pip install --no-deps --require-hashes -r ../deploy/installer_tui/requirements.lock
          "$RUNNER_TEMP/installer-tui-venv/bin/python" -m unittest discover -s tests -p test_install_tui_app.py -v
```

Headless tests take about 45 s. They never run sudo, helpers or the network (guards in the test file
fail any attempt).

**c.** No new shell script; `bash -n deploy/install.sh` already covers the entry point.

**d.** Not for CI: `docs/installer-tui/tools/pty_check.py` (needs tmux, the VM's sudo and a
provisioned account; fixture helpers) and `tools/snapshots.py` (evidence rendering).

## 2. Proposed documentation changes (A owns these files)

- **`docs/INSTALL.md`**
  - Start section: "`bash deploy/install.sh` opens the full-screen installer when it is set up for
    your account (`--setup-tui`, a one-time download of pinned, hash-verified packages into
    `~/.local/share/clab-node-manager/installer-tui/`), otherwise the plain numbered menu. `--tui`
    sets it up if needed and stops with an explanation if it cannot start; `--plain` always uses the
    plain menu. `--git` and `--advanced` keep their meaning."
  - Replace the sentence at lines 67-69 ("without curses, a desktop browser or extra terminal UI
    packages") with: "The plain menu needs nothing beyond Python's standard library; the full-screen
    installer is optional and uses its own private Python environment."
  - Recovery section: add the full-screen equivalents (Retry phase, Return, keep work; Wait for lock,
    Check again; Authenticate, retry; Finish without it for Git) and the keys `s` (stop after this
    step), `x` (interrupt a stuck step, like Ctrl+C in the plain menu), `f`, `o`, `?`.
  - Note: both front ends now refuse a second concurrent mutating run (installer lock under
    `/run/lock`; not APT's lock).
- **`docs/QUICK-INSTALL.md`**, **`docs/FRESH-VM-GUIDE-V2.md`**, **`README.md`** step 2: one line
  each mentioning `--setup-tui`/`--plain`; their prompt tables describe the plain menu and stay valid.
- **`docs/ARCHITECTURE.md`** module map `deploy/` row: add "`installer_tui/` (optional full-screen
  front end: stdlib bootstrap/core/engine/probes/sanitize, Textual app/theme, hashed
  `requirements.lock`)".
- **`docs/REPOSITORY-MAINTENANCE.md`** CI item 2: name `test_install_tui_core.py`; add the Textual
  stage from 1b. (Done: its CI section lists both.)
- **`CLAUDE.md`** routing row "Installer, health check, engineer access": add
  `docs/installer-tui/` (README, PARITY, PICKUP) and the three test files; note under Commands that
  `test_install_tui_app.py` needs the TUI venv.
- **History files** at release time: CHANGELOG, `clab-backup-ui/VALIDATION.md` (copy the evidence
  types from [VALIDATION.md](VALIDATION.md); live rows are dev2 only) and a short
  `agent instructions.md` section: preserve the plain path, the shared `action_steps`, `sudo -n` only
  on piped steps, terminal handoff for sudo/first password/Git, SIGINT-only lock-wait cancel,
  exit 75 only before any change.
- `verify-release.py` documentation rules: `docs/installer-tui/` names no release except the current
  one inside fixture snapshots (SVG text, not Markdown). If A prefers, add `docs/installer-tui/` to
  the history-file list.

## 3. Proposed helper change (not made; A decides)

`deploy/apt_lock.py --wait --pause-timers`: the independent review found that a SIGINT arriving
while the timers are being stopped (before the `try`) or restarted (inside `finally`) can leave
`apt-daily.timer`/`apt-daily-upgrade.timer` stopped. The TUI now sends at most one SIGINT per wait,
which avoids the double-signal case, but the window in the helper remains (also reachable from the
plain menu with a fast double Ctrl+C). Suggested fix: block SIGINT with `signal.pthread_sigmask`
around the stop and restart calls, or move the stop inside the `try`. A regression test can drive
`wait_for_release` with a fake systemctl and two SIGINTs (as the reviewer did).

## 4. Release actions reserved for A

- One `+0.0.1` release via `deploy/set-release.py` after integrating this branch, then the three
  history sections and `verify-release.py`.
- Main-branch integration and the CI edits above.
- Do not publish images or tags for this change; the manager image is unaffected (the TUI never
  enters it).

## 5. Behaviour A should know before merging

- Plain mode is unchanged except: mutating menu items and `--git` take the installer lock (a Busy or
  unreadable lock prints a message and returns to the menu), and an interactive launch without
  `--plain` prints one `Plain menu: <reason>` line when the TUI is not set up.
- Dashboard status uses read-only `sudo -n` queries only when sudo already runs without a prompt.
- See [PARITY.md](PARITY.md) for every action and option, [VALIDATION.md](VALIDATION.md) for evidence,
  [PICKUP.md](PICKUP.md) for open limitations.
