# Installer parity: plain menu and full-screen installer (Slate Ops)

Every installer action and option, the TUI control that carries it, the callable behind it, and the test that
holds it. The plain menu (`deploy/install-manager.py`) is the reference; the full-screen installer
(`deploy/installer_tui/`) reuses its plan, helper commands and recovery rules (`action_steps`, `install_steps`,
`plan_lines`, `Options`) and decides only how each phase meets the terminal (`engine.py`).

Test columns: `IM` = `clab-backup-ui/tests/test_install_manager.py` (existing, named exactly),
`CORE` = `clab-backup-ui/tests/test_install_tui_core.py`, `APP` = `clab-backup-ui/tests/test_install_tui_app.py`.
CORE and APP names marked "(planned)" describe intent and are not yet written. The invariant audit this was meant to
follow (`invariants-report.md`) was not available when this page was written; rows come from the current code.

## 1. Entry and flags

| Entry | Behaviour | Callable | Tests |
|---|---|---|---|
| `bash deploy/install.sh` | Refuses root; runs `install-manager.py` with the system Python | `install.sh`; `install-manager.py:main` | existing: `test_install_manager.py` loads `main` |
| (no flag), interactive | Auto selection: TUI when `TERM` is usable and the private environment is ready, else plain with a one-line reason | `main`, `tui_available`, `bootstrap.ready` | CORE: auto selection and reason text (planned) |
| `--tui` | Provisions the pinned packages if needed, then runs the TUI; if it cannot start, stops with an explanation and changes nothing (no plain fallback) | `main`, `bootstrap.provision`, `run_tui` | CORE: `--tui` provisions then stops on failure (planned) |
| `--plain` | Plain numbered menu, no extra packages | `main` (mutually exclusive with `--tui`, `--setup-tui`) | `MainLoopTests.*` |
| `--setup-tui` | Verifies and unpacks pinned wheels into `~/.local/share/clab-node-manager/installer-tui/`; runs before the tty check; changes nothing else; no installer lock | `bootstrap.provision` | CORE: provision with fake fetcher, bad SHA-256, unsafe wheel path, no root, no partial ready marker (planned) |
| `--git` | Plain: Git setup directly, under the installer lock, exit status is Git's. With `--tui --git`: TUI opens the Git review screen | `main`, `git_setup`, `run_tui` extra flags | `test_git_setup_menu_item_exits_only_once_it_succeeds` (menu form); CORE: `--git` takes the lock (planned) |
| `--advanced` | Plain: every question restored. TUI: Install/update opens Advanced settings first, then the plan | `ask_install_options`; `SlateOps.open_action` (`start_action='advanced'`) | `test_advanced_flag_is_threaded_into_install`, `test_advanced_install_asks_every_question_in_order`; APP: advanced opens settings before review (planned) |
| Not interactive / root / `clab-discovery` | `ValueError`, exit 1 | `main` | existing: `test_environment_keeps_real_owner_not_shell_tokens_or_sudo_user` (environment only); CORE: refusals (planned) |
| Fallback rule | The TUI exits 75 only before any change (no tty, import failure, crash before a run started); the auto path then prints `Plain menu: ...` and continues plain; any other status is final | `launch.py`, `app.main`, `main` (`TUI_UNAVAILABLE`) | APP: 75 only when no run started; status of a crash after a run is 1 (planned) |
| Ctrl+C while the TUI runs | The waiting parent ignores it; the TUI owns it | `bootstrap.launch` | CORE: launch survives KeyboardInterrupt (planned) |

## 2. Menu actions

| Plain item | TUI screen / control | Underlying callable | Tests |
|---|---|---|---|
| 1 Install or update manager, then set up Git | Dashboard "Install / update" -> ReviewScreen (plan + phases, one Start) -> RunScreen -> ResultScreen | `install`, `install_steps`, `plan_lines`; `engine.Run` | `test_standard_install_skips_every_question_and_runs_git_setup_unconditionally`, `test_standard_plan_starts_without_a_confirmation`; APP: install review lists the same plan lines (planned) |
| 2 Git setup / repair only | Dashboard "Git setup / repair" -> ReviewScreen -> Start; terminal handed over | `git_setup`, `git_command`, `action_steps('git')` | `test_git_cancellation_keeps_manager_and_does_not_use_sudo`, `test_git_setup_menu_item_exits_only_once_it_succeeds` |
| 3 VS Code / Containerlab access | Dashboard "VS Code / Containerlab access" -> ReviewScreen -> Start | `engineer_access`, `engineer_command`, `action_steps('engineer')` | `test_engineer_access_menu_item_exits_after_success` |
| 4 Browser Wireshark stack only | Dashboard "Browser Wireshark stack" -> ReviewScreen -> Start | `capture_stack`, `stack_command`, `action_steps('capture')` | `test_stack_menu_item_reinstalls_the_capture_stack_without_a_rebuild`, `test_stacks_menu_item_exits_after_success` |
| 5 Check running installation | Dashboard "Check installation" (starts at once, read-only) -> RunScreen -> ResultScreen with the findings table | `health_report`, `health_command`; `engine.HealthRun` (`check-install.sh --json`) | `test_full_health_report_keeps_owner_and_preserves_attention_exit`, `test_health_report_menu_item_exits_only_once_it_passes`; `test_check_install.py` (`--json` mode); CORE: HealthRun parses the structured report (planned) |
| (advanced only) | Dashboard "Advanced settings" -> SettingsScreen | `Options`, `ask_install_options` | APP: settings round trip (planned) |
| 6 Exit | Dashboard "Exit" or Ctrl+Q (asks first while a phase runs) | `main` returns 0; `SlateOps.action_request_quit` | `test_exit_menu_item_returns_zero_immediately`; APP: quit while running asks (planned) |

## 3. Install phases and how each meets the terminal in the TUI

The plain menu runs every phase on the real terminal except the package step (tee, to spot the lock signature).
The TUI runs a phase piped with `sudo -n` (`core.noninteractive`, `core.StepProcess`) unless it needs the terminal.

| Phase key | Helper (same argv in both modes) | Plain | TUI | Tests |
|---|---|---|---|---|
| `admin` | `sudo -v` | `command_step`, terminal | `engine._authenticate`: cached credentials (`credentials_cached`) need no prompt; otherwise the screen is suspended and `sudo -v` gets the terminal | `test_step_retry_does_not_repeat_prior_steps`; CORE: cached credentials skip the handoff (planned) |
| `settings` | `copy_env` (only when a previous `.env` was chosen) | in process, outside `phase()` | in process; failure offers retry/return; contents never shown | `test_env_copy_is_byte_exact_and_never_overwrites`, `test_default_env_choice_*` |
| `prereqs` | `install-prerequisites.sh --docker --containerlab [--repair-install-media]` | tee, lock signature scanned | piped, `sudo -n`, lock signature scanned (`StepProcess.saw_lock`) | `test_command_step_flags_the_dpkg_lock_signature`, `test_command_step_does_not_flag_an_unrelated_failure`; CORE: signature split across chunks (planned) |
| `launch` | `start-manager.sh --manager-only [--enable-operations]` | terminal | piped with `sudo -n` when the `clab-discovery` password exists (`sudo -n passwd -S`); on first setup the whole launcher gets the terminal (password, then image build) | `test_wireshark_and_grafana_stacks_are_standard_phases_between_launch_and_verification`; CORE: password check picks piped vs handoff (planned) |
| `capture` | `setup-capture.sh` | terminal | piped, `sudo -n` | same test as above |
| `verify` | `check_manager` (container, version, HTTP) | `sudo -v`, then checks | `_authenticate`, then `check_manager(sudo=('sudo','-n'))` | `test_health_uses_actual_container_bind_and_port`, `test_health_requires_running_compose_service`, `test_health_rejects_stale_image_before_http`, `test_wrong_http_version_does_not_report_success`, `test_health_prints_no_state_content`, `test_unexpected_container_command_is_rejected`, `test_compose_checks_target_local_rootful_daemon` |
| `engineer` (only when selected) | `setup-engineer-access.sh --owner USER` | terminal | piped, `sudo -n`; reconnect note kept in the result | `test_advanced_install_asks_every_question_in_order` |
| `lazydocker` (post, optional) | `setup_lazydocker` | in process | in process, output as inert text; a failure is `Skipped`, never fails the install | `LazydockerTests.*` (all) |
| `git` (post) | `setup-git.sh` | terminal (always, after the summary) | suspended screen, terminal handed over; hidden when "Git later" was chosen | `test_standard_install_skips_every_question_and_runs_git_setup_unconditionally`, `test_advanced_install_runs_git_setup_when_chosen_from_next_step_menu` |

Step numbering is `n/6` with engineer access, `n/5` without (`install_steps`). Phase order, titles and hidden
steps come from `install_steps`; the TUI never reorders them.

## 4. Advanced choices and their TUI controls

| Plain question | Options field | TUI control (SettingsScreen) | Rule | Tests |
|---|---|---|---|---|
| Manager bind/port: defaults, copy `.env`, back | `env_source` | "Manager bind/port settings" radio + path input; "Existing `.env` retained" text when one exists; Start disabled for a symlinked `.env` | absolute, regular, not a symlink, at most 64 KiB; contents never shown | `test_default_env_choice_refuses_a_symlinked_env`; APP: path validation errors (planned) |
| Lab operation access | `operations` `'1'`/`'2'` | "Lab operation access" radio | `'1'` adds `--enable-operations` | `test_advanced_install_asks_every_question_in_order` |
| VS Code / Containerlab access | `engineer` | radio, disabled unless operations is `'1'` | `Options` forces `'2'` otherwise | same test; APP: engineer disabled with discovery-only (planned) |
| Back up and disable obsolete installation-media APT entries | `repair` | checkbox | adds `--repair-install-media` | same test; CORE: `prerequisites_command` flag (planned) |
| Proceed with this plan? (y/N) | none | ReviewScreen Start / Cancel | Cancel changes nothing | `test_declined_advanced_plan_runs_no_commands_and_copies_no_settings` |
| Next step: Git now / later | `git_now` | "After the manager is ready" radio on the settings screen | decides whether the `git` step is visible | `test_advanced_install_runs_git_setup_when_chosen_from_next_step_menu`; APP: Git later hides the step (planned) |
| (standard path) no questions | `Options()` | "Standard defaults" button resets the form | defaults: retain `.env`, operations on, engineer on, repair on, Git now | `test_standard_install_skips_every_question_and_runs_git_setup_unconditionally` |

Intentional presentation difference: in the plain menu the advanced "Next step" (Git now or later) is asked after the
manager is ready; in the TUI it is chosen before Start, because nothing may ask a question mid-run on the dashboard.
The outcome is the same: the `git` step runs or is skipped, after the manager phases, never changing their result.

## 5. Recovery choices

| Failure | Plain menu | TUI recovery panel (RunScreen) | Callable | Tests |
|---|---|---|---|---|
| Generic step failure | Retry this step / Return to menu, keep completed work | "Retry phase" / "Return, keep work" (plus "Output") | `phase`; `engine.Run._phase`, `Failure('command')` | `test_step_retry_does_not_repeat_prior_steps`, `test_cancelled_step_returns_without_advancing`, `test_phase_without_env_falls_back_to_the_generic_recovery_menu` |
| Package lock (dpkg/apt signature) | 1 wait here, 2 retry now, 3 return; holder report, restart hint and copyable command shown | "Wait for lock" / "Retry phase" / "Check again" / "Return, keep work"; same holder, hint and command | `lock_recovery`, `lock_free`, `lock_holder_text`, `lock_wait_command`; `engine._recover`, `_lock_wait` | `PackageLockRecoveryTests.*` (all, eleven tests); CORE: lock failure offers four choices, wait is stopped with SIGINT only (planned) |
| Sudo needs a password again (piped step) | not applicable: sudo prompts on the terminal | "Authenticate, retry" (terminal handoff to `sudo -v`) / "Return, keep work" | `Failure('auth')`; `_authenticate(force=True)` | CORE: `saw_auth` signature gives the auth choices (planned) |
| Verification failure | Retry / Return | "Retry phase" / "Return, keep work" | `Failure('verify')` | `test_health_*` (as in section 3) |
| Settings copy failure | Retry / Return | "Retry phase" / "Return, keep work" | `Failure('settings')` | `test_env_copy_is_byte_exact_and_never_overwrites` |
| Git did not finish (in an install) | install continues; prints "Git setup is incomplete"; resume from the menu | "Retry phase" / "Finish without it" / "Return, keep work"; the manager outcome is unchanged | `git_setup`; `Failure('git')`, `SKIP` | `test_git_cancellation_keeps_manager_and_does_not_use_sudo`; CORE: skipped Git leaves the run `partial`, not `failed` (planned) |
| Git did not finish (Git action alone) | returns to the menu | "Retry phase" / "Return, keep work" | `action_steps('git')` | APP: Git-only has no skip choice (planned) |
| Terminal could not be handed over | not applicable | `Failure('handoff')`, retry or return | `Bridge.handoff` | APP: handoff with no suspend support (planned) |

## 6. Result and exit semantics

| Situation | Plain | TUI | Tests |
|---|---|---|---|
| Install, engineer, stacks succeed | prints completion, exits 0 | ResultScreen "Completed"; Finish exits 0 and prints the plain summary to scrollback | `test_successful_install_exits_zero_without_reprompting_the_setup_menu`, `test_engineer_access_menu_item_exits_after_success`, `test_stacks_menu_item_exits_after_success`; APP: Finish prints the summary (planned) |
| Failure or cancel | returns to the Setup menu | ResultScreen "Failed"/"Stopped"; "Back to dashboard" returns; Finish exits 1 (failed) or 0 (returned, stopped, partial) | `test_cancelled_install_returns_to_the_setup_menu_instead_of_exiting`; CORE: `exit_status` per outcome (planned) |
| Git alone | exits 0 only when Git succeeded | Finish exits with Git's own status | `test_git_setup_menu_item_exits_only_once_it_succeeds` |
| Health check | exits 0 only when it passes (1 FAIL, 2 WARN/SKIP stay on the menu) | ResultScreen findings; Finish exits 0 for pass or attention, 1 only when no structured report came back | `test_health_report_menu_item_exits_only_once_it_passes`; APP: health result table (planned) |
| Ctrl+C / Ctrl+Q | `Setup stopped...` exit 1; steps already finished are kept | asks before quitting a running phase; "Stop after this phase, then quit"; summary printed; status 130 if no run decided otherwise | APP: quit dialog (planned) |
| Terminal lost (SIGHUP) / SIGTERM | not handled specially | active phase finishes, nothing later starts, nothing is asked, exit 1 | CORE: `Run.disconnect` stops after the active phase (planned) |
| Run record | none | metadata-only JSON under `$XDG_STATE_HOME/clab-node-manager` (no output, no settings values) | CORE: record has no output text, private mode (planned) |

## 7. Documented intentional differences

| Difference | Why | Where |
|---|---|---|
| Piped TUI steps use `sudo -n`; an expired credential becomes the "Authenticate, retry" choice | sudo must never open `/dev/tty` and prompt over the screen | `core.noninteractive`, `engine._command` |
| Credential check is `sudo -n -v`, then `sudo -n true` | `-v` is refused under `verifypw=all` when any rule needs a password although a NOPASSWD rule lets commands run | `engine.credentials_cached` |
| Health check uses `check-install.sh --json`; exit codes unchanged (0, 1, 2) | structured findings for the results table; progress lines still stream | `engine.HealthRun`; `check_install.py` |
| Plain mode now takes the installer lock for mutating items (1 to 4 and `--git`) | one mutating run per VM whichever front end or account starts it; health and `--setup-tui` take none | `installer_lock`, `core.InstallerLock`, `main` |
| One Start on a plan screen, even on the standard path | the TUI shows the plan before running; the standard path still asks no questions, only Start | `ReviewScreen`; plain prints the plan and starts |
| Git now/later chosen before Start (section 4) | no question mid-run | `SettingsScreen`, `Options.git_now` |
| Lock wait uses `sudo -n` after authentication and ends with SIGINT | APT timers are restored only on SIGINT; never SIGTERM or SIGKILL | `engine._lock_wait`, `Run.cancel_lock_wait` |
| `--git` alone stays plain; the TUI Git screen needs `--tui --git` | `main` selects the TUI only when `--git` is absent or `--tui` is given | `main` |

## 8. Gaps still open

| Gap | Note |
|---|---|
| CORE and APP test files are planned, not yet written | every "(planned)" row above |
| Health Finish exit status: the TUI exits 0 for a WARN or FAIL report, plain exits with the report's status | `app.exit_status` has no health case; decide and test before relying on the TUI status in scripts |
| `exit_status` treats `partial`, `returned` and `stopped` as 0 | plain returns to the menu instead of exiting; confirm this is the wanted scripted behaviour |
| `--git` alone does not open the TUI | possibly surprising next to `--tui`, `--advanced`; kept as is |
| Advanced `Proceed with this plan?` has no separate confirm in the TUI | Start on the review screen is the single confirmation for both paths |
| Textual rendering is not covered by system-Python tests | APP tests need either a stubbed Textual or the private environment; screens are checked by the snapshot tool in `docs/installer-tui/tools/` |
| Real sudo, the apt lock, Docker and the network are never exercised by tests | fake `sudo` and fake helper scripts in temp dirs only |
