# Validation record — INSTALLER-TUI-B1

Everything below ran on the dev VM `dev2` (Ubuntu 24.04, Python 3.12.3, Textual 8.2.8 from the
pinned lock) on 2026-10-03, unless a row says otherwise. Evidence types are kept apart:
**unit** (stdlib, fakes), **headless** (Textual `run_test`, fixture data), **fixture-PTY** (real tmux
pseudo-terminal, real sudo and signals, fake helpers from `tools/make_fixture.py`), **live** (the real
checkout and real helpers on the VM). Nothing here claims CI, a desktop client, a Windows terminal or
a real GitHub login.

## Automated suites

| Suite | Interpreter | Result | Type |
|---|---|---|---|
| `test_install_manager.py` (58 existing + 83 new) | system `python3`, both discover modes | 141 OK | unit |
| `test_install_tui_core.py` | system `python3`, both discover modes (also with ResourceWarnings as errors) | 165 OK | unit (real subprocesses with tiny scripts, real `venv --without-pip`) |
| `test_install_tui_app.py` (118) | TUI venv python, both discover modes; also a fresh venv from `pip install --no-deps --require-hashes -r requirements.lock` with `INSTALLER_TUI_REQUIRED=1` (the proposed CI stage) | 118 OK, about 65 s | headless |
| `test_install_tui_app.py` | system `python3` (no Textual) | skipped cleanly; with `INSTALLER_TUI_REQUIRED=1` it fails loudly | — |
| `test_check_install.py`, `test_apt_lock.py`, `test_release_consistency.py` | system `python3` | OK | unit (unchanged files, regression) |
| Baseline before any change | see PICKUP | 323 pre-venv deploy tests, 1721 app tests (1 skip), 389 browser tests, all OK | — |
| `tools/pty_check.py` (hangup, stop, flood, interrupt, lock) | system `python3` driving tmux | 36/36 PASS ([evidence/pty-check.txt](evidence/pty-check.txt)) | fixture-PTY |
| `verify-release.py`, `bash -n deploy/install.sh`, `git diff --check`, `check_links.py` | system `python3` | OK | static |

## Live runs on dev2 (real checkout, real helpers)

| # | Scenario | What was observed |
|---|---|---|
| L1 | `--setup-tui` | 9 pinned wheels downloaded, SHA-256 verified, unpacked into `~/.local/share/clab-node-manager/installer-tui/py312-<lock digest>/`; second call says already set up and downloads nothing |
| L2 | First install through the TUI (manager not installed) | Admin phase used cached sudo; prerequisites piped; the launcher was handed the real terminal for the first-time clab-discovery password (typed at `setup-password.sh`'s own prompt), then built the image in that terminal; the dashboard came back |
| L3 | Stalled image pull | The Wireshark `docker pull` stalled (~4 KB/s). SIGINT to the step's process group (the mechanism of the new Interrupt action; this session predated the key binding) ended it through sudo; the phase failed truthfully with completed work kept; Retry repeated only that phase and completed |
| L4 | Git setup cancelled at its own `sudo -v` prompt | Exit status 2 reported; recovery offered Retry / Finish without it / Return; result **PARTIAL** with Manager READY reported separately from Git ATTENTION; summary printed to scrollback; exit 0 |
| L5 | `sudo -v` refused (`verifypw=all` on this VM) and cancelled with Ctrl+C | Terminal handed over, Ctrl+C, explicit exit status, Enter returned to recovery; Return → **STOPPED**, nothing claimed |
| L6 | Health check (Check installation) | `check-install.sh --json` ran with streamed progress; 32 PASS · 3 WARN · 0 FAIL · 2 SKIP shown; Finish exit status 2 (same as the plain report) |
| L7 | Update with a sentinel lab (`dev2-sentinel`, alpine) and Advanced settings → Git later | Launcher ran **piped** inside the dashboard (password already set); COMPLETED; sentinel container ID and start time unchanged; `.env` and `state.key` hashes unchanged; data files retained. A second update later (L9) also left the sentinel unchanged |
| L8 | Second invocation while a run holds the lock | Another TUI showed "Installer busy" with holder pid/account/start; the plain menu printed the same message and returned to its menu |
| L9 | Real dpkg lock held by a test process (`fcntl.lockf` on `/var/lib/dpkg/lock-frontend`) with `curl` removed via `dpkg -r --force-depends` so the helper must install | Lock signature detected; holder pid shown from `apt_lock.py --show`; Wait for lock paused the APT timers; `s` ended the wait with SIGINT ("Cancelled; any paused timer was restored", timers active again); Wait again + releasing the holder → wait returned → only the prerequisites phase retried and reinstalled curl; stop-after-step ended the run STOPPED with no later phase |
| L10 | Disposable account `tuiprobe` (password sudo, no NOPASSWD) | Non-TTY rejected; auto mode without provisioning printed the `Plain menu:` hint; `--tui` with downloads blocked failed clearly (exit 1, nothing left behind); real `--tui` provisioning; admin phase handed to sudo's prompt; `sudo -K` from another session mid-run → next phase handed back to sudo instead of prompting over the screen; fixture auth signature → Authenticate, retry; fixture Git cancelled then retried → COMPLETED |
| L11 | Clean Ubuntu 24.04 container without `python3-venv` | `python3 -m venv` with pip fails; `--without-pip` works (the bootstrap's path) |

## Fixture-PTY scenarios (`tools/pty_check.py`)

Hang-up: killing the tmux session mid-phase let the active piped phase finish, started no later phase,
recorded `interrupted` with "terminal disconnected", released the lock and left no process. Stop after
step, a 200 000-line flood with hostile escapes (bounded log with an explicit "earlier N lines not
shown" marker; OSC title never reached the terminal; markup literal), confirmed interrupt + retry, and
package-lock recovery all passed.

## Independent reviews

| Review | Model | Outcome |
|---|---|---|
| Terminal/process and privilege safety (commit `5ec3207`) | Opus 5.5, read-only | No critical/high. 3 medium (second SIGINT during a lock wait, a phase repeated after a hang-up during a recovery wait, umask-dependent lock file) and 10 low findings: all fixed except the `apt_lock.py` signal window, proposed to A in [HANDOFF.md](HANDOFF.md) |
| Visual and keyboard usability | Opus 5.5, read-only, fixture runs in tmux (truecolor, 256, NO_COLOR, ASCII, 80x24, too small) | 19 defects + polish. Fixed: invisible focus on warning buttons (one unique focus treatment now), flat recovery buttons, a stray Tab stop, frozen retry timer, interrupt confirmation that could hit a later phase, locale-based ASCII fallback (decided in `install.sh`; render-time ASCII filter), 256-colour palette, mis-styled View output button, hidden lock command and clipped buttons at 80x24, unscrolled output on failure, phase highlight not following the run, missing Inspect output, clipped footers and help, review warning below the fold, status badge width, phase label truncation, settings and result polish, wrapped scrollback summary. Follow-up: dialogs now have their own key footer, and the System status is focusable (up/down choose a component, its complete status shows in Details, Enter reviews the fixing action), so nothing truncated at 80 columns is unreadable |

## Not verified

- A desktop terminal client (Windows Terminal, PuTTY, macOS Terminal) — only tmux on the VM and
  headless snapshots.
- A real GitHub device login (no account available to this worker); Git handoff verified up to its
  own prompts and cancellation, plus fixture success.
- CI: the proposed stages in [HANDOFF.md](HANDOFF.md) have not run in GitHub Actions.
- Resume after reconnect does not exist; a hang-up during a *terminal handoff* stops that child as in
  the plain installer.
