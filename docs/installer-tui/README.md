# Slate Ops installer TUI (INSTALLER-TUI-B1)

A full-screen, keyboard-first front end for `bash deploy/install.sh`, built with Textual
and layered over the existing installer. The plain numbered menu remains and is still
the fallback.

| File | What it is |
|---|---|
| [PICKUP.md](PICKUP.md) | Branch, state, tests actually run, open defects, next command |
| [PARITY.md](PARITY.md) | Every plain-installer action and option mapped to its TUI screen, callable and tests |
| [VALIDATION.md](VALIDATION.md) | What was verified and how (unit, fixture, headless, PTY, live dev VM) |
| [HANDOFF.md](HANDOFF.md) | Integration notes for the release owner: CI lines, docs to update, release actions |
| [snapshots/](snapshots/) | Scrubbed screenshots rendered from the fixture (invented account, host and status) |
| [tools/](tools/) | Fixture app, snapshot renderer, fixture checkout builder, PTY checks |

## Launch

```bash
bash "$HOME/projects/clab-manager/deploy/install.sh"              # full screen when set up, else plain
bash "$HOME/projects/clab-manager/deploy/install.sh" --setup-tui  # one-time: pinned packages for this account
bash "$HOME/projects/clab-manager/deploy/install.sh" --tui        # full screen (sets itself up if needed)
bash "$HOME/projects/clab-manager/deploy/install.sh" --plain      # the plain numbered menu
```

`--git` and `--advanced` keep their meaning in both modes.

## The installer lock

One mutating installer run per VM, plain or full-screen, from any account: an advisory `flock` on
`/run/lock/clab-node-manager-installer.lock` (`/tmp` when `/run/lock` is not writable), shared by both
installers through `installer_tui/core.py`. The directory is world-writable, so the lock never follows a
symlink and refuses a file that is not a regular file or cannot be opened: the installer then changes
nothing and prints the exact `sudo rm -f <path>` that clears it. Code that runs with root privileges (the
lock is taken by the unprivileged installer, which refuses to run as root) removes such a file itself and
replaces a lock file owned by an unprivileged account with a root-owned one, which that account cannot
delete from the sticky directory; it never replaces a lock that is held. `/run/lock` is cleared at every
boot, so on a VM with several accounts the name can still be planted before the first run after a boot: the
result is a refusal with the removal command, never a half-run installer.

## Code

| Module | Needs Textual | Role |
|---|---|---|
| `deploy/install-manager.py` | no | Plain menu and the shared plan: `Options`, `Step`, `install_steps`, `action_steps`, `plan_lines`; mode selection in `main()` |
| `deploy/installer_tui/bootstrap.py` | no | Hash-verified wheel install into a private `--without-pip` venv; launch |
| `deploy/installer_tui/core.py` | no | Step processes (own process group, `sudo -n`, streamed inert output), installer lock, run record |
| `deploy/installer_tui/engine.py` | no | Runs an action's phases, terminal handoffs, recovery choices, stop-after-step, hang-up |
| `deploy/installer_tui/probes.py` | no | Read-only, bounded dashboard status checks |
| `deploy/installer_tui/sanitize.py` | no | Control-sequence and markup-safe output lines |
| `deploy/installer_tui/theme.py` | yes | Slate Ops tokens, badges, glyphs, stylesheet |
| `deploy/installer_tui/app.py` | yes | Screens: dashboard, settings, review, run with recovery, result, help |
| `deploy/installer_tui/requirements.lock` | — | Pinned, hashed pure-Python wheels (Textual and its dependencies) |
