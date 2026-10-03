import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch
from urllib.error import URLError

spec = importlib.util.spec_from_file_location('install_manager', Path(__file__).resolve().parents[2] / 'deploy/install-manager.py')
install = importlib.util.module_from_spec(spec)
spec.loader.exec_module(install)


def tui_core():
    return install.tui_package().core


def tui_bootstrap():
    return install.tui_package().bootstrap


def record_run(order):
    """A `run` replacement accepting every keyword `run()` supports (capture, tee)."""
    def record(args, env, capture=False, tee=False):
        order.append(' '.join(args))
        return subprocess.CompletedProcess(args, 0, stdout='')
    return record


class InstallManagerTests(unittest.TestCase):
    def test_compose_checks_target_local_rootful_daemon(self):
        command = install.compose('ps')
        self.assertEqual(command[:5], ['sudo', 'docker', '--host', 'unix:///var/run/docker.sock', 'compose'])

    def test_menu_reprompts_and_uses_explicit_default(self):
        with patch('builtins.input', side_effect=['bad', '']), patch('sys.stdout', new=io.StringIO()):
            self.assertEqual(install.menu('Menu', [('1', 'Install'), ('2', 'Back')], '2'), '2')

    def test_environment_keeps_real_owner_not_shell_tokens_or_sudo_user(self):
        with patch.dict(os.environ, {'SUDO_USER': 'root', 'GH_TOKEN': 'secret', 'GIT_CONFIG_GLOBAL': '/other'}):
            env = install.environment(SimpleNamespace(pw_name='archtop', pw_dir='/home/archtop'))
        self.assertEqual(env['HOME'], '/home/archtop')
        self.assertEqual(env['USER'], 'archtop')
        self.assertNotIn('GH_TOKEN', env)
        self.assertNotIn('SUDO_USER', env)
        self.assertNotIn('GIT_CONFIG_GLOBAL', env)

    def test_health_uses_actual_container_bind_and_port(self):
        for host, expected in [('0.0.0.0', '127.0.0.1'), ('::', '[::1]'),
                               ('10.0.0.5', '10.0.0.5'), ('::1', '[::1]'), ('localhost', '127.0.0.1')]:
            with self.subTest(host=host):
                self.assertEqual(install.health_url(['uvicorn', 'app.main:create_app', '--host', host, '--port', '8099']),
                                 f'http://{expected}:8099/api/state')

    def test_unexpected_container_command_is_rejected(self):
        for cmd in ([], 'uvicorn --port 8081', ['--host', 'example.invalid', '--port', '8081'],
                    ['--host', '127.0.0.1', '--port', '99999'], ['--port']):
            with self.subTest(cmd=cmd), self.assertRaises(ValueError):
                install.health_url(cmd)

    def test_health_requires_running_compose_service(self):
        with patch.object(install, 'output', return_value=''), patch.object(install, 'build_opener') as network:
            with self.assertRaisesRegex(ValueError, 'not running'):
                install.check_manager({}, '1.16.0', 0)
        network.assert_not_called()

    def test_health_rejects_stale_image_before_http(self):
        with patch.object(install, 'output', side_effect=['a' * 64, 'old']), patch.object(install, 'build_opener') as network:
            with self.assertRaisesRegex(ValueError, 'does not match'):
                install.check_manager({}, '1.16.0', 0)
        network.assert_not_called()

    def test_health_prints_no_state_content(self):
        response = SimpleNamespace(status=200, read=lambda limit: json.dumps({'version': '1.16.0', 'labs': 'PRIVATE'}).encode())
        from contextlib import nullcontext
        opener = SimpleNamespace(open=lambda url, timeout: nullcontext(response))
        with patch.object(install, 'output', side_effect=['a' * 64, '1.16.0', '["--host","0.0.0.0","--port","8081"]']), \
                patch.object(install, 'build_opener', return_value=opener), patch('sys.stdout', new=io.StringIO()) as printed:
            install.check_manager({}, '1.16.0', 0)
        self.assertNotIn('PRIVATE', printed.getvalue())
        self.assertIn('checks passed', printed.getvalue())

    def test_wrong_http_version_does_not_report_success(self):
        from contextlib import nullcontext
        response = SimpleNamespace(status=200, read=lambda limit: b'{"version":"old"}')
        opener = SimpleNamespace(open=lambda url, timeout: nullcontext(response))
        with patch.object(install, 'output', side_effect=['a' * 64, '1.16.0', '["--host","0.0.0.0","--port","8081"]']), \
                patch.object(install, 'build_opener', return_value=opener):
            with self.assertRaisesRegex(ValueError, 'did not pass'):
                install.check_manager({}, '1.16.0', 0)

    def test_env_copy_is_byte_exact_and_never_overwrites(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'clab-backup-ui').mkdir()
            old = root / 'old.env'
            content = b'UI_PORT=8099\r\n# keep settings\r\n'
            old.write_bytes(content)
            with patch.object(install, 'SOURCE', root):
                install.copy_env(old)
                target = root / 'clab-backup-ui/.env'
                self.assertEqual(target.read_bytes(), content)
                old.write_bytes(b'new')
                with self.assertRaises(FileExistsError):
                    install.copy_env(old)
                self.assertEqual(target.read_bytes(), content)

    def test_default_env_choice_retains_existing_env_without_a_menu(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'clab-backup-ui').mkdir()
            (root / 'clab-backup-ui/.env').write_text('UI_PORT=9000\n')
            with patch.object(install, 'SOURCE', root), patch.object(install, 'menu') as menu, \
                    patch('sys.stdout', new=io.StringIO()) as printed:
                result = install.default_env_choice()
        self.assertIsNone(result)
        menu.assert_not_called()
        self.assertIn('retained unchanged', printed.getvalue())

    def test_default_env_choice_uses_defaults_when_no_env_exists_without_a_menu(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'clab-backup-ui').mkdir()
            with patch.object(install, 'SOURCE', root), patch.object(install, 'menu') as menu, \
                    patch('sys.stdout', new=io.StringIO()) as printed:
                result = install.default_env_choice()
        self.assertIsNone(result)
        menu.assert_not_called()
        self.assertIn('defaults', printed.getvalue())

    def test_default_env_choice_refuses_a_symlinked_env(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'clab-backup-ui').mkdir()
            other = root / 'elsewhere.env'
            other.write_text('X=1\n')
            os.symlink(other, root / 'clab-backup-ui/.env')
            with patch.object(install, 'SOURCE', root):
                with self.assertRaises(ValueError):
                    install.default_env_choice()

    def test_step_retry_does_not_repeat_prior_steps(self):
        calls = []
        def action():
            calls.append('current')
            if len(calls) == 1:
                raise ValueError('temporary failure')
        with patch.object(install, 'menu', return_value='1'):
            install.phase('Current step', action)
        self.assertEqual(calls, ['current', 'current'])

    def test_cancelled_step_returns_without_advancing(self):
        with patch.object(install, 'menu', return_value='2'), self.assertRaises(install.Cancelled):
            install.phase('Fail', lambda: (_ for _ in ()).throw(ValueError('failure')))

    def test_git_cancellation_keeps_manager_and_does_not_use_sudo(self):
        env = install.environment(SimpleNamespace(pw_name='owner', pw_dir='/home/owner'))
        with patch.object(install, 'run', return_value=subprocess.CompletedProcess([], 2)) as run:
            self.assertEqual(install.git_setup(env), 2)
        self.assertEqual(run.call_args.args[0][0], 'bash')
        self.assertEqual(run.call_args.args[1]['HOME'], '/home/owner')

    def test_full_health_report_keeps_owner_and_preserves_attention_exit(self):
        env = install.environment(SimpleNamespace(pw_name='owner', pw_dir='/home/owner'))
        with patch.object(install, 'run', return_value=subprocess.CompletedProcess([], 2)) as run:
            self.assertEqual(install.health_report(env), 2)
        self.assertEqual(run.call_args.args, (['bash', str(install.SOURCE / 'deploy/check-install.sh')], env))

    def test_standard_install_skips_every_question_and_runs_git_setup_unconditionally(self):
        order = []
        with patch.object(install, 'default_env_choice', return_value=None) as env_choice, \
                patch.object(install, 'menu') as menu, patch.object(install, 'confirm') as confirm, \
                patch.object(install, 'verify_manager'), patch.object(install, 'setup_lazydocker') as lazydocker, \
                patch.object(install, 'git_setup') as git, patch.object(install, 'run', side_effect=record_run(order)):
            install.install({'USER': 'owner', 'HOME': '/home/owner'}, '1.30.35')
        env_choice.assert_called_once()
        menu.assert_not_called()
        confirm.assert_not_called()
        lazydocker.assert_called_once()
        git.assert_called_once()
        # Standard path always sets up engineer access (today's option 1) and the repair flag.
        self.assertTrue(any('setup-engineer-access.sh' in c for c in order))
        self.assertTrue(any('--repair-install-media' in c for c in order))
        self.assertTrue(any('--enable-operations' in c for c in order))

    def test_advanced_install_asks_every_question_in_order(self):
        for chosen in ('1', '2'):
            with self.subTest(engineer=chosen), patch.object(install, 'choose_env_copy', return_value=None), \
                    patch.object(install, 'menu', side_effect=['1', chosen, '2']), \
                    patch.object(install, 'confirm', side_effect=[False, True]), \
                    patch.object(install, 'copy_env'), patch.object(install, 'verify_manager') as verify, \
                    patch.object(install, 'setup_lazydocker'), patch.object(install, 'git_setup') as git, \
                    patch.object(install, 'run', return_value=subprocess.CompletedProcess([], 0)) as run:
                install.install({'USER': 'owner', 'HOME': '/home/owner'}, '1.19.4', advanced=True)
            commands = [call.args[0] for call in run.call_args_list]
            engineer = [c for c in commands if 'setup-engineer-access.sh' in ' '.join(c)]
            git.assert_not_called()  # menu side_effect ends with '2': finish, set up Git later
            if chosen == '1':
                self.assertEqual(engineer, [['sudo', 'bash', str(install.SOURCE / 'deploy/setup-engineer-access.sh'), '--owner', 'owner']])
                launch = next(i for i, c in enumerate(commands) if 'start-manager.sh' in ' '.join(c))
                self.assertGreater(commands.index(engineer[0]), launch)
                verify.assert_called_once()
            else:
                self.assertEqual(engineer, [])

    def test_advanced_install_runs_git_setup_when_chosen_from_next_step_menu(self):
        with patch.object(install, 'choose_env_copy', return_value=None), \
                patch.object(install, 'menu', side_effect=['1', '2', '1']), \
                patch.object(install, 'confirm', side_effect=[False, True]), \
                patch.object(install, 'copy_env'), patch.object(install, 'verify_manager'), \
                patch.object(install, 'setup_lazydocker'), patch.object(install, 'git_setup') as git, \
                patch.object(install, 'run', return_value=subprocess.CompletedProcess([], 0)):
            install.install({'USER': 'owner', 'HOME': '/home/owner'}, '1.19.4', advanced=True)
        git.assert_called_once()

    def test_wireshark_and_grafana_stacks_are_standard_phases_between_launch_and_verification(self):
        # The Grafana/Prometheus telemetry stack was retired: install() no longer runs a
        # separate phase for it (deploy/start-manager.sh cleans up any leftovers itself), so
        # this claims the capture phase only.
        order = []
        with patch.object(install, 'default_env_choice', return_value=None), \
                patch.object(install, 'setup_lazydocker'), patch.object(install, 'git_setup'), \
                patch.object(install, 'verify_manager', side_effect=lambda env, version: order.append('verify')), \
                patch.object(install, 'run', side_effect=record_run(order)):
            install.install({'USER': 'owner', 'HOME': '/home/owner'}, '1.25.0')
        launch = next(i for i, c in enumerate(order) if 'start-manager.sh' in c)
        capture = next(i for i, c in enumerate(order) if 'setup-capture.sh' in c)
        self.assertIn('--manager-only', order[launch], 'the launcher leaves the stack to its own retryable phase')
        self.assertEqual([launch, capture, order.index('verify')], sorted([launch, capture, order.index('verify')]))
        self.assertTrue(order[capture].startswith('sudo env DOCKER_HOST=unix:///var/run/docker.sock bash ' + str(install.SOURCE / 'deploy')))
        self.assertNotIn('--no-recreate', order[capture], 'standalone stack setup recreates the manager itself')
        self.assertFalse(any('setup-telemetry.sh' in c for c in order), 'the Grafana/Prometheus stack was retired')

    def test_stack_menu_reinstalls_the_capture_stack_without_a_rebuild(self):
        commands = []
        with patch.object(install, 'run', side_effect=lambda args, env, capture=False, tee=False: (commands.append(' '.join(args)), subprocess.CompletedProcess(args, 0, stdout=''))[1]):
            install.stacks({'USER': 'owner'})
        self.assertEqual([c for c in commands if 'start-manager.sh' in c], [])
        self.assertTrue(any('setup-capture.sh' in c for c in commands))
        self.assertFalse(any('setup-telemetry.sh' in c for c in commands), 'the Grafana/Prometheus stack was retired')

    def test_declined_advanced_plan_runs_no_commands_and_copies_no_settings(self):
        with patch.object(install, 'choose_env_copy', return_value=None), \
                patch.object(install, 'menu', return_value='1'), \
                patch.object(install, 'confirm', side_effect=[True, False]), \
                patch.object(install, 'run') as run, patch.object(install, 'copy_env') as copy:
            with self.assertRaises(install.Cancelled):
                install.install({'USER': 'owner'}, '1.16.0', advanced=True)
        run.assert_not_called()
        copy.assert_not_called()

    def test_standard_plan_starts_without_a_confirmation(self):
        order = []
        with patch.object(install, 'default_env_choice', return_value=None), patch.object(install, 'confirm') as confirm, \
                patch.object(install, 'verify_manager'), patch.object(install, 'setup_lazydocker'), \
                patch.object(install, 'git_setup'), patch.object(install, 'run', side_effect=record_run(order)):
            install.install({'USER': 'owner', 'HOME': '/home/owner'}, '1.16.0')
        confirm.assert_not_called()
        self.assertTrue(any('install-prerequisites.sh' in c for c in order))


class PackageLockRecoveryTests(unittest.TestCase):
    def test_command_step_flags_the_dpkg_lock_signature(self):
        error_text = ("E: Could not get lock /var/lib/dpkg/lock-frontend. It is held by process 2230 "
                     "(unattended-upgr)\n")
        with patch.object(install, 'run', return_value=subprocess.CompletedProcess([], 100, stdout=error_text)):
            with self.assertRaises(ValueError) as caught:
                install.command_step(['sudo', 'apt-get', 'install', '-y', 'git'], {})
        self.assertTrue(caught.exception.lock_signature)

    def test_command_step_does_not_flag_an_unrelated_failure(self):
        with patch.object(install, 'run', return_value=subprocess.CompletedProcess([], 1, stdout='network unreachable\n')):
            with self.assertRaises(ValueError) as caught:
                install.command_step(['sudo', 'bash', 'x.sh'], {})
        self.assertFalse(caught.exception.lock_signature)

    def test_phase_shows_the_three_option_lock_menu_instead_of_the_generic_recovery(self):
        error = ValueError('boom')
        error.lock_signature = True
        calls = []
        def action():
            calls.append(1)
            if len(calls) == 1:
                raise error
        with patch.object(install, 'lock_recovery', return_value=True) as recovery, patch.object(install, 'menu') as menu:
            install.phase('Prereqs', action, env={'USER': 'owner'})
        recovery.assert_called_once_with({'USER': 'owner'})
        menu.assert_not_called()  # the generic 2-choice Recovery menu never shown
        self.assertEqual(calls, [1, 1])

    def test_phase_returns_to_menu_when_lock_recovery_is_declined(self):
        error = ValueError('boom')
        error.lock_signature = True
        with patch.object(install, 'lock_recovery', return_value=False):
            with self.assertRaises(install.Cancelled):
                install.phase('Prereqs', lambda: (_ for _ in ()).throw(error), env={'USER': 'owner'})

    def test_phase_without_env_falls_back_to_the_generic_recovery_menu(self):
        error = ValueError('boom')
        error.lock_signature = True
        with patch.object(install, 'lock_recovery') as recovery, patch.object(install, 'menu', return_value='2'):
            with self.assertRaises(install.Cancelled):
                install.phase('Prereqs', lambda: (_ for _ in ()).throw(error))
        recovery.assert_not_called()

    def test_lock_recovery_retries_immediately_when_already_free(self):
        with patch.object(install, 'lock_free', return_value=True), patch.object(install, 'menu') as menu:
            self.assertTrue(install.lock_recovery({}))
        menu.assert_not_called()

    def test_lock_recovery_prints_holder_and_copyable_command_then_waits(self):
        printed = io.StringIO()
        with patch.object(install, 'lock_free', return_value=False), \
                patch.object(install, 'lock_holder_text', return_value='Package lock held by pid 2230 (unattended-upgr) on /var/lib/dpkg/lock-frontend.\n'), \
                patch.object(install, 'menu', return_value='1'), \
                patch.object(install, 'run', return_value=subprocess.CompletedProcess([], 0)) as run, \
                patch('sys.stdout', new=printed):
            self.assertTrue(install.lock_recovery({}))
        output_text = printed.getvalue()
        self.assertIn('pid 2230', output_text)
        self.assertIn('Copyable command', output_text)
        copyable_line = next(line for line in output_text.splitlines() if 'Copyable command' in line)
        self.assertNotIn('-n', copyable_line.split())  # the pasted text itself never carries -n
        run.assert_called_once()
        self.assertNotIn('-n', run.call_args.args[0])  # interactive sudo: expired credentials may be typed again
        self.assertEqual(run.call_args.args[0][:2], ['sudo', 'python3'])  # the fd scan needs root
        self.assertIn('--pause-timers', run.call_args.args[0])

    def test_lock_recovery_shows_the_restart_advice_once_with_or_without_a_holder_report(self):
        # The report comes from apt_lock.py --show and already carries the advice; when sudo credentials
        # have expired there is no report, and the installer prints the advice itself. Never twice.
        with_report = io.StringIO()
        report = ('Package lock held by pid 2230 (unattended-upgr) on /var/lib/dpkg/lock-frontend.\n'
                  'Never stop unattended-upgrades.service, kill this process, or delete the lock file: let the current run finish, or wait it out here.\n'
                  'If this appears right after a VM snapshot rollback or a reboot, a normal restart of the VM also clears it.\n')
        with patch.object(install, 'lock_free', return_value=False), patch.object(install, 'lock_holder_text', return_value=report), \
                patch.object(install, 'menu', return_value='3'), patch.object(install, 'run') as run, patch('sys.stdout', new=with_report):
            self.assertFalse(install.lock_recovery({}))
        self.assertEqual(with_report.getvalue().count('snapshot rollback'), 1)
        without = io.StringIO()
        with patch.object(install, 'lock_free', return_value=False), patch.object(install, 'lock_holder_text', return_value=''), \
                patch.object(install, 'menu', return_value='3'), patch.object(install, 'run') as run, patch('sys.stdout', new=without):
            self.assertFalse(install.lock_recovery({}))
        text = without.getvalue()
        self.assertEqual(text.count('snapshot rollback'), 1)
        self.assertIn('restart of the VM', text)
        self.assertIn('every completed setup step is kept', text)
        self.assertLess(text.index('snapshot rollback'), text.index('Copyable command'))
        run.assert_not_called()  # advice only: choice 3 returns to the menu and the installer restarts nothing
        with open(install.__file__) as stream: source = stream.read()
        for forbidden in ("'reboot'", "'shutdown'", "'poweroff'"):
            self.assertNotIn(forbidden, source, 'the installer never restarts the VM')

    def test_lock_recovery_retry_now_skips_the_wait(self):
        with patch.object(install, 'lock_free', return_value=False), patch.object(install, 'lock_holder_text', return_value=''), \
                patch.object(install, 'menu', return_value='2'), patch.object(install, 'run') as run:
            self.assertTrue(install.lock_recovery({}))
        run.assert_not_called()

    def test_lock_recovery_return_to_menu(self):
        with patch.object(install, 'lock_free', return_value=False), patch.object(install, 'lock_holder_text', return_value=''), \
                patch.object(install, 'menu', return_value='3'):
            self.assertFalse(install.lock_recovery({}))

    def test_lock_free_uses_a_zero_timeout_check(self):
        with patch.object(install, 'run', return_value=subprocess.CompletedProcess([], 0)) as run:
            self.assertTrue(install.lock_free({}))
        self.assertIn('--timeout', run.call_args.args[0])
        self.assertIn('0', run.call_args.args[0])


class LazydockerTests(unittest.TestCase):
    def test_arch_mapping(self):
        self.assertEqual(install.lazydocker_arch('x86_64'), 'x86_64')
        self.assertEqual(install.lazydocker_arch('aarch64'), 'arm64')
        self.assertEqual(install.lazydocker_arch('arm64'), 'arm64')
        self.assertEqual(install.lazydocker_arch('armv7l'), 'armv7')
        self.assertEqual(install.lazydocker_arch('armv6l'), 'armv6')
        self.assertIsNone(install.lazydocker_arch('riscv64'))

    def _make_tarball(self, members):
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode='w:gz') as archive:
            for name, content in members:
                data = content.encode()
                info = tarfile.TarInfo(name=name)
                info.size = len(data)
                archive.addfile(info, io.BytesIO(data))
        buffer.seek(0)
        return buffer.read()

    def test_extracts_only_the_exact_lazydocker_member(self):
        tarball = self._make_tarball([('README.md', 'hello'), ('lazydocker', 'BINARY-CONTENT')])
        with tempfile.TemporaryDirectory() as folder:
            destination = Path(folder) / 'lazydocker'
            install.install_lazydocker_binary(tarball, destination)
            self.assertEqual(destination.read_bytes(), b'BINARY-CONTENT')
            self.assertTrue(destination.stat().st_mode & 0o755)

    def test_rejects_a_traversal_or_nested_member_never_the_exact_name(self):
        tarball = self._make_tarball([('../evil', 'x'), ('sub/lazydocker', 'x')])
        with tempfile.TemporaryDirectory() as folder:
            destination = Path(folder) / 'lazydocker'
            with self.assertRaises(ValueError):
                install.install_lazydocker_binary(tarball, destination)
            self.assertFalse(destination.exists())
            self.assertFalse((Path(folder) / 'evil').exists())

    def test_leading_dot_slash_member_is_still_accepted(self):
        tarball = self._make_tarball([('./lazydocker', 'DATA')])
        with tempfile.TemporaryDirectory() as folder:
            destination = Path(folder) / 'lazydocker'
            install.install_lazydocker_binary(tarball, destination)
            self.assertEqual(destination.read_bytes(), b'DATA')

    def test_bashrc_append_is_idempotent_and_touches_only_the_given_home(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            first = install.ensure_local_bin_on_path(home)
            after_first = (home / '.bashrc').read_text()
            second = install.ensure_local_bin_on_path(home)
            after_second = (home / '.bashrc').read_text()
            self.assertTrue(first)
            self.assertFalse(second)
            self.assertEqual(after_first, after_second, 'a second run never duplicates the guarded block')
            self.assertEqual(after_first.count('Added by Containerlab Node Manager setup'), 1)
            self.assertIn('.local/bin', after_first)

    def test_bashrc_append_preserves_existing_content_and_skips_a_pre_existing_path_line(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            (home / '.bashrc').write_text('export PATH="$PATH:$HOME/.local/bin"\nalias ll="ls -la"\n')
            appended = install.ensure_local_bin_on_path(home)
            self.assertFalse(appended)
            text = (home / '.bashrc').read_text()
            self.assertIn('alias ll', text)
            self.assertEqual(text.count('.local/bin'), 1)

    def test_up_to_date_skip_when_installed_version_matches(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'lazydocker'
            path.write_text('#!/bin/sh\n')
            path.chmod(0o755)
            with patch.object(install.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, stdout='Version: 0.23.3\n')):
                self.assertTrue(install.lazydocker_up_to_date(path, '0.23.3', {}))
                self.assertFalse(install.lazydocker_up_to_date(path, '0.24.0', {}))

    def test_up_to_date_false_when_not_installed(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertFalse(install.lazydocker_up_to_date(Path(folder) / 'lazydocker', '0.23.3', {}))

    def test_download_failure_is_a_warning_never_raises_and_never_touches_the_network(self):
        printed = io.StringIO()
        with patch.object(install, 'lazydocker_latest_tag', side_effect=OSError('network unreachable')), \
                patch.object(install, 'download_lazydocker_tarball') as download, \
                patch('sys.stdout', new=printed):
            install.setup_lazydocker({'HOME': '/nonexistent-test-home'})
        download.assert_not_called()
        self.assertIn('skipped', printed.getvalue())

    def test_unsupported_architecture_is_skipped_with_a_warning_and_no_network_call(self):
        with patch.object(install.platform, 'machine', return_value='riscv64'), \
                patch.object(install, 'lazydocker_latest_tag') as tag_fetch, \
                patch('sys.stdout', new=io.StringIO()) as out:
            install.setup_lazydocker({'HOME': '/nonexistent-test-home'})
        tag_fetch.assert_not_called()
        self.assertIn('unsupported', out.getvalue().lower())

    def _checksums_line(self, tarball, filename, digest=None):
        return (digest or hashlib.sha256(tarball).hexdigest()) + '  ' + filename + '\n'

    def test_successful_install_verifies_the_checksum_then_reports_version_and_path(self):
        tarball = self._make_tarball([('lazydocker', 'BIN')])
        filename = install.lazydocker_tarball_filename('v0.23.3', 'x86_64')
        checksums = self._checksums_line(tarball, filename)
        with tempfile.TemporaryDirectory() as folder:
            printed = io.StringIO()
            with patch.object(install, 'lazydocker_arch', return_value='x86_64'), \
                    patch.object(install, 'lazydocker_latest_tag', return_value='v0.23.3'), \
                    patch.object(install, 'download_lazydocker_tarball', return_value=tarball), \
                    patch.object(install, 'download_lazydocker_checksums', return_value=checksums) as checksums_fetch, \
                    patch('sys.stdout', new=printed):
                install.setup_lazydocker({'HOME': folder})
            checksums_fetch.assert_called_once_with('v0.23.3')
            destination = Path(folder) / '.local/bin/lazydocker'
            self.assertEqual(destination.read_bytes(), b'BIN')
            self.assertIn('0.23.3', printed.getvalue())
            home_bashrc = Path(folder) / '.bashrc'
            self.assertIn('.local/bin', home_bashrc.read_text())

    def test_checksum_mismatch_skips_the_install_with_a_warning(self):
        tarball = self._make_tarball([('lazydocker', 'BIN')])
        filename = install.lazydocker_tarball_filename('v0.23.3', 'x86_64')
        wrong_checksums = self._checksums_line(tarball, filename, digest='0' * 64)
        with tempfile.TemporaryDirectory() as folder:
            printed = io.StringIO()
            with patch.object(install, 'lazydocker_arch', return_value='x86_64'), \
                    patch.object(install, 'lazydocker_latest_tag', return_value='v0.23.3'), \
                    patch.object(install, 'download_lazydocker_tarball', return_value=tarball), \
                    patch.object(install, 'download_lazydocker_checksums', return_value=wrong_checksums), \
                    patch('sys.stdout', new=printed):
                install.setup_lazydocker({'HOME': folder})
            destination = Path(folder) / '.local/bin/lazydocker'
            self.assertFalse(destination.exists(), 'a mismatched checksum must never be installed')
            self.assertIn('skipped', printed.getvalue())
            self.assertIn('checksum', printed.getvalue().lower())

    def test_checksum_missing_entry_skips_the_install_with_a_warning(self):
        tarball = self._make_tarball([('lazydocker', 'BIN')])
        # A checksums.txt that exists but never lists this release's filename (for
        # example a differently named platform asset only).
        unrelated = self._checksums_line(tarball, 'lazydocker_0.23.3_Linux_arm64.tar.gz')
        with tempfile.TemporaryDirectory() as folder:
            printed = io.StringIO()
            with patch.object(install, 'lazydocker_arch', return_value='x86_64'), \
                    patch.object(install, 'lazydocker_latest_tag', return_value='v0.23.3'), \
                    patch.object(install, 'download_lazydocker_tarball', return_value=tarball), \
                    patch.object(install, 'download_lazydocker_checksums', return_value=unrelated), \
                    patch('sys.stdout', new=printed):
                install.setup_lazydocker({'HOME': folder})
            destination = Path(folder) / '.local/bin/lazydocker'
            self.assertFalse(destination.exists())
            self.assertIn('skipped', printed.getvalue())

    def test_checksums_file_unavailable_skips_the_install_with_a_warning_never_raises(self):
        tarball = self._make_tarball([('lazydocker', 'BIN')])
        with tempfile.TemporaryDirectory() as folder:
            printed = io.StringIO()
            with patch.object(install, 'lazydocker_arch', return_value='x86_64'), \
                    patch.object(install, 'lazydocker_latest_tag', return_value='v0.23.3'), \
                    patch.object(install, 'download_lazydocker_tarball', return_value=tarball), \
                    patch.object(install, 'download_lazydocker_checksums',
                                side_effect=URLError('HTTP Error 404: Not Found')), \
                    patch.object(install, 'install_lazydocker_binary') as install_binary, \
                    patch('sys.stdout', new=printed):
                install.setup_lazydocker({'HOME': folder})
            install_binary.assert_not_called()
            destination = Path(folder) / '.local/bin/lazydocker'
            self.assertFalse(destination.exists())
            self.assertIn('skipped', printed.getvalue())

    def test_verify_lazydocker_checksum_matches_mismatches_and_missing_entries(self):
        data = b'lazydocker binary content'
        digest = hashlib.sha256(data).hexdigest()
        filename = 'lazydocker_0.23.3_Linux_x86_64.tar.gz'
        self.assertTrue(install.verify_lazydocker_checksum(data, f'{digest}  {filename}\n', filename))
        self.assertTrue(install.verify_lazydocker_checksum(data, f'{digest} *{filename}\n', filename),
                        'the binary-mode "*" marker used by sha256sum must still match')
        self.assertFalse(install.verify_lazydocker_checksum(data, f'{"0" * 64}  {filename}\n', filename))
        self.assertFalse(install.verify_lazydocker_checksum(data, '', filename))
        self.assertFalse(install.verify_lazydocker_checksum(data, f'{digest}  other-file.tar.gz\n', filename))
        # An ambiguous checksums file (two lines for the same filename) is never trusted.
        duplicated = f'{digest}  {filename}\n{"1" * 64}  {filename}\n'
        self.assertFalse(install.verify_lazydocker_checksum(data, duplicated, filename))


class MainLoopTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.object(install, 'source_version', return_value='1.30.35'))
        self.enterContext(patch('os.geteuid', return_value=1000))
        self.enterContext(patch('pwd.getpwuid', return_value=SimpleNamespace(pw_name='owner', pw_dir='/home/owner')))
        self.enterContext(patch('sys.stdin.isatty', return_value=True))
        fake_stdout = io.StringIO()
        self.enterContext(patch.object(fake_stdout, 'isatty', return_value=True))
        self.enterContext(patch('sys.stdout', new=fake_stdout))
        self.out = fake_stdout
        # Deterministic front end and a private installer lock: no real full-screen environment is
        # consulted and nothing under /run/lock is touched (the lock file lives in a temp folder).
        self.tui_available = self.enterContext(patch.object(install, 'tui_available', return_value=(False, 'test')))
        lock_folder = self.enterContext(tempfile.TemporaryDirectory())
        self.lock_path = Path(lock_folder) / 'installer.lock'
        self.installer_lock = self.enterContext(patch.object(
            install, 'installer_lock', side_effect=lambda: tui_core().InstallerLock(self.lock_path)))

    def test_successful_install_exits_zero_without_reprompting_the_setup_menu(self):
        with patch.object(install, 'menu', side_effect=['1']) as menu, patch.object(install, 'install') as do_install:
            code = install.main([])
        self.assertEqual(code, 0)
        do_install.assert_called_once()
        self.assertFalse(do_install.call_args.kwargs.get('advanced'))
        self.assertEqual(menu.call_count, 1)

    def test_advanced_flag_is_threaded_into_install(self):
        with patch.object(install, 'menu', side_effect=['1']), patch.object(install, 'install') as do_install:
            install.main(['--advanced'])
        self.assertTrue(do_install.call_args.kwargs.get('advanced'))

    def test_cancelled_install_returns_to_the_setup_menu_instead_of_exiting(self):
        with patch.object(install, 'menu', side_effect=['1', '6']), \
                patch.object(install, 'install', side_effect=install.Cancelled()):
            code = install.main([])
        self.assertEqual(code, 0)

    def test_git_setup_menu_item_exits_only_once_it_succeeds(self):
        with patch.object(install, 'menu', side_effect=['2', '2']), \
                patch.object(install, 'git_setup', side_effect=[2, 0]) as git:
            code = install.main([])
        self.assertEqual(code, 0)
        self.assertEqual(git.call_count, 2)

    def test_engineer_access_menu_item_exits_after_success(self):
        with patch.object(install, 'menu', side_effect=['3']), patch.object(install, 'phase') as phase:
            code = install.main([])
        self.assertEqual(code, 0)
        phase.assert_called_once()

    def test_stacks_menu_item_exits_after_success(self):
        with patch.object(install, 'menu', side_effect=['4']), patch.object(install, 'stacks') as stacks:
            code = install.main([])
        self.assertEqual(code, 0)
        stacks.assert_called_once()

    def test_health_report_menu_item_exits_only_once_it_passes(self):
        with patch.object(install, 'menu', side_effect=['5', '5']), \
                patch.object(install, 'health_report', side_effect=[2, 0]) as health:
            code = install.main([])
        self.assertEqual(code, 0)
        self.assertEqual(health.call_count, 2)

    def test_exit_menu_item_returns_zero_immediately(self):
        with patch.object(install, 'menu', side_effect=['6']):
            code = install.main([])
        self.assertEqual(code, 0)


class RecordingLock:
    """An installer-lock stand-in that records acquire/release order (optionally refusing as Busy)."""

    def __init__(self, events, busy=None):
        self.events = events
        self.busy = busy

    def acquire(self):
        self.events.append('acquire')
        if self.busy is not None:
            raise self.busy
        return self

    def release(self):
        self.events.append('release')

    def __enter__(self):
        return self.acquire()

    def __exit__(self, *exc):
        self.release()


OWNER = {'USER': 'owner', 'HOME': '/home/owner'}


def busy_error():
    return tui_core().Busy('Another Containerlab Node Manager installer run is active (pid 1). '
                           'Wait for it to finish, then try again.')


class MainFrontEndTests(unittest.TestCase):
    """--tui / --plain / --setup-tui / --git / --advanced routing in main()."""

    def setUp(self):
        MainLoopTests.setUp(self)
        self.launch = self.enterContext(patch.object(tui_bootstrap(), 'launch', return_value=0))
        self.provision = self.enterContext(patch.object(tui_bootstrap(), 'provision', return_value=0))
        self.ready = self.enterContext(patch.object(tui_bootstrap(), 'ready', return_value=True))

    def lines(self):
        return self.out.getvalue().splitlines()

    def test_plain_never_starts_the_tui_even_when_it_is_available(self):
        self.tui_available.return_value = (True, '')
        with patch.object(install, 'run_tui') as run_tui, patch.object(install, 'menu', side_effect=['6']):
            code = install.main(['--plain'])
        self.assertEqual(code, 0)
        run_tui.assert_not_called()
        self.tui_available.assert_not_called()
        self.launch.assert_not_called()
        self.provision.assert_not_called()
        self.assertIn('Containerlab Node Manager 1.30.35 — guided setup', self.out.getvalue())
        self.assertIn('Linux account: owner', self.out.getvalue())
        self.assertFalse([line for line in self.lines() if line.startswith('Plain menu:')])

    def test_auto_mode_with_tui_available_runs_the_tui_and_returns_its_code(self):
        self.tui_available.return_value = (True, '')
        for code in (0, 1, 130):
            with self.subTest(code=code), patch.object(install, 'run_tui', return_value=code) as run_tui, \
                    patch.object(install, 'menu') as menu:
                self.assertEqual(install.main([]), code)
            run_tui.assert_called_once()
            self.assertEqual(run_tui.call_args.args[0]['USER'], 'owner')
            self.assertEqual(run_tui.call_args.args[0]['HOME'], '/home/owner')
            self.assertFalse(run_tui.call_args.args[1].git)
            menu.assert_not_called()
        self.assertFalse([line for line in self.lines() if line.startswith('Plain menu:')])

    def test_auto_mode_unavailable_tui_says_why_and_shows_the_plain_menu(self):
        with patch.object(install, 'run_tui') as run_tui, patch.object(install, 'menu', side_effect=['6']):
            self.assertEqual(install.main([]), 0)
        run_tui.assert_not_called()
        self.assertIn('Plain menu: test.', self.lines())

    def test_auto_mode_tui_exit_75_falls_back_to_the_plain_menu(self):
        self.tui_available.return_value = (True, '')
        with patch.object(install, 'run_tui', return_value=install.TUI_UNAVAILABLE) as run_tui, \
                patch.object(install, 'menu', side_effect=['6']) as menu:
            self.assertEqual(install.main([]), 0)
        self.assertEqual(install.TUI_UNAVAILABLE, 75)
        run_tui.assert_called_once()
        menu.assert_called_once()
        self.assertTrue([line for line in self.lines() if line.startswith('Plain menu:')])
        self.assertIn('guided setup', self.out.getvalue())

    def test_explicit_tui_exit_75_stops_with_plain_advice_and_no_plain_menu(self):
        with patch.object(install, 'run_tui', return_value=75), patch.object(install, 'menu') as menu:
            self.tui_available.return_value = (True, '')
            with self.assertRaisesRegex(ValueError, '--plain'):
                install.main(['--tui'])
        menu.assert_not_called()
        self.assertFalse([line for line in self.lines() if line.startswith('Plain menu:')])

    def test_explicit_tui_returns_the_tui_code_without_provisioning_when_ready(self):
        self.tui_available.return_value = (True, '')
        with patch.object(install, 'run_tui', return_value=3) as run_tui:
            self.assertEqual(install.main(['--tui']), 3)
        run_tui.assert_called_once()
        self.provision.assert_not_called()

    def test_explicit_tui_not_ready_provisions_and_stops_when_it_fails(self):
        self.ready.return_value = False
        self.provision.return_value = 1
        with patch.object(install, 'run_tui') as run_tui, patch.object(install, 'menu') as menu:
            with self.assertRaisesRegex(ValueError, '--plain'):
                install.main(['--tui'])
        self.provision.assert_called_once()
        self.assertEqual(self.provision.call_args.args[0]['USER'], 'owner')
        run_tui.assert_not_called()
        menu.assert_not_called()

    def test_explicit_tui_not_ready_provisions_then_starts_when_it_succeeds(self):
        self.ready.return_value = False
        self.provision.return_value = 0
        self.tui_available.return_value = (True, '')
        with patch.object(install, 'run_tui', return_value=0) as run_tui:
            self.assertEqual(install.main(['--tui']), 0)
        self.provision.assert_called_once()
        run_tui.assert_called_once()

    def test_explicit_tui_that_cannot_start_after_setup_names_the_reason(self):
        self.tui_available.return_value = (False, 'TERM is dumb')
        with patch.object(install, 'run_tui') as run_tui:
            with self.assertRaisesRegex(ValueError, 'TERM is dumb.*--plain'):
                install.main(['--tui'])
        run_tui.assert_not_called()

    def test_setup_tui_provisions_without_a_tty_and_without_reading_the_source_version(self):
        self.provision.return_value = 4
        with patch('sys.stdin.isatty', return_value=False), patch.object(self.out, 'isatty', return_value=False), \
                patch.object(install, 'run_tui') as run_tui, patch.object(install, 'menu') as menu:
            code = install.main(['--setup-tui'])
        self.assertEqual(code, 4)
        self.provision.assert_called_once()
        env = self.provision.call_args.args[0]
        self.assertEqual((env['USER'], env['HOME']), ('owner', '/home/owner'))
        install.source_version.assert_not_called()
        run_tui.assert_not_called()
        menu.assert_not_called()
        self.installer_lock.assert_not_called()

    def test_setup_tui_still_refuses_root_and_clab_discovery(self):
        with patch('os.geteuid', return_value=0):
            with self.assertRaisesRegex(ValueError, 'without sudo'):
                install.main(['--setup-tui'])
        with patch('pwd.getpwuid', return_value=SimpleNamespace(pw_name='clab-discovery', pw_dir='/home/x')):
            with self.assertRaisesRegex(ValueError, 'clab-discovery'):
                install.main(['--setup-tui'])
        self.provision.assert_not_called()

    def test_tui_plain_and_setup_tui_are_mutually_exclusive(self):
        for argv in (['--tui', '--plain'], ['--plain', '--setup-tui'], ['--tui', '--setup-tui']):
            with self.subTest(argv=argv), patch('sys.stderr', new=io.StringIO()) as err:
                with self.assertRaises(SystemExit) as caught:
                    install.main(argv)
            self.assertEqual(caught.exception.code, 2)
            self.assertIn('not allowed with', err.getvalue())
        self.provision.assert_not_called()
        self.launch.assert_not_called()

    def test_git_in_auto_mode_runs_plain_git_setup_under_the_installer_lock(self):
        events = []
        self.tui_available.return_value = (True, '')
        with patch.object(install, 'installer_lock', side_effect=lambda: RecordingLock(events)), \
                patch.object(install, 'git_setup', side_effect=lambda env: (events.append('git'), 5)[1]) as git, \
                patch.object(install, 'run_tui') as run_tui, patch.object(install, 'menu') as menu:
            code = install.main(['--git'])
        self.assertEqual(code, 5)
        self.assertEqual(events, ['acquire', 'git', 'release'])
        git.assert_called_once()
        self.assertEqual(git.call_args.args[0]['USER'], 'owner')
        run_tui.assert_not_called()
        self.tui_available.assert_not_called()
        menu.assert_not_called()
        self.assertIn('guided setup', self.out.getvalue())

    def test_git_returns_the_git_setup_code(self):
        for code in (0, 2):
            with self.subTest(code=code), patch.object(install, 'git_setup', return_value=code):
                self.assertEqual(install.main(['--git', '--plain']), code)

    def test_git_while_another_installer_runs_never_starts_git_setup(self):
        events = []
        with patch.object(install, 'installer_lock', side_effect=lambda: RecordingLock(events, busy_error())), \
                patch.object(install, 'git_setup') as git:
            with self.assertRaisesRegex(ValueError, 'installer run is active'):
                install.main(['--git'])
        git.assert_not_called()

    def test_git_with_tui_passes_the_git_flag_to_the_full_screen_installer(self):
        self.launch.return_value = 0
        with patch.object(install, 'tui_available', return_value=(True, '')):
            self.assertEqual(install.main(['--git', '--tui']), 0)
        self.assertEqual(self.launch.call_args.args[1], ['--git'])
        self.assertEqual(self.launch.call_args.args[0]['USER'], 'owner')

    def test_advanced_in_tui_mode_passes_the_advanced_flag_to_the_full_screen_installer(self):
        self.tui_available.return_value = (True, '')
        for argv, expected in ((['--advanced'], ['--advanced']), (['--tui', '--advanced'], ['--advanced']),
                               (['--tui', '--advanced', '--git'], ['--git', '--advanced']), (['--tui'], [])):
            with self.subTest(argv=argv):
                self.launch.reset_mock()
                install.main(argv)
                self.assertEqual(self.launch.call_args.args[1], expected)

    def test_run_tui_builds_the_extra_flags_from_the_arguments(self):
        env = {'USER': 'owner'}
        for git, advanced, expected in ((False, False, []), (True, False, ['--git']), (False, True, ['--advanced']),
                                        (True, True, ['--git', '--advanced'])):
            with self.subTest(git=git, advanced=advanced):
                self.launch.return_value = 9
                self.assertEqual(install.run_tui(env, SimpleNamespace(git=git, advanced=advanced)), 9)
                self.assertEqual(self.launch.call_args.args, (env, expected))

    def test_advanced_in_plain_mode_is_passed_to_install(self):
        with patch.object(install, 'menu', side_effect=['1']), patch.object(install, 'install') as do_install, \
                patch.object(install, 'run_tui') as run_tui:
            self.assertEqual(install.main(['--plain', '--advanced']), 0)
        self.assertIs(do_install.call_args.kwargs.get('advanced'), True)
        run_tui.assert_not_called()

    def test_busy_installer_lock_prints_its_message_and_returns_to_the_menu(self):
        events = []
        message = str(busy_error())
        with patch.object(install, 'installer_lock', side_effect=lambda: RecordingLock(events, busy_error())), \
                patch.object(install, 'menu', side_effect=['1', '6']) as menu, \
                patch.object(install, 'install') as do_install:
            code = install.main(['--plain'])
        self.assertEqual(code, 0)
        self.assertEqual(menu.call_count, 2)
        do_install.assert_not_called()
        self.assertIn(message, self.lines())
        self.assertEqual(events, ['acquire'], 'a refused lock is never released (it was never held)')

    def test_a_real_lock_held_by_another_run_returns_to_the_menu_for_every_mutating_item(self):
        held = tui_core().InstallerLock(self.lock_path).acquire()
        self.addCleanup(held.release)
        for choice in ('1', '2', '3', '4'):
            with self.subTest(choice=choice), patch.object(install, 'menu', side_effect=[choice, '6']), \
                    patch.object(install, 'install') as do_install, patch.object(install, 'git_setup') as git, \
                    patch.object(install, 'phase') as phase, patch.object(install, 'stacks') as stacks:
                self.assertEqual(install.main(['--plain']), 0)
            for mocked in (do_install, git, phase, stacks):
                mocked.assert_not_called()
        self.assertEqual(self.out.getvalue().count('Another Containerlab Node Manager installer run is active'), 4)

    def test_mutating_menu_items_hold_the_lock_for_the_run_and_release_it_after(self):
        events = []
        def tracked(name, result=None):
            return lambda *args, **kwargs: (events.append(name), result)[1]
        cases = {'1': ('install', 'install'), '2': ('git_setup', 'git'), '3': ('phase', 'phase'), '4': ('stacks', 'stacks')}
        for choice, (attribute, name) in cases.items():
            events.clear()
            with self.subTest(choice=choice), patch.object(install, 'installer_lock', side_effect=lambda: RecordingLock(events)), \
                    patch.object(install, 'menu', side_effect=[choice]), \
                    patch.object(install, attribute, side_effect=tracked(name, 0 if attribute == 'git_setup' else None)):
                self.assertEqual(install.main(['--plain']), 0)
                self.assertEqual(events, ['acquire', name, 'release'])

    def test_lock_is_released_after_a_cancelled_run_and_a_failure(self):
        events = []
        with patch.object(install, 'installer_lock', side_effect=lambda: RecordingLock(events)), \
                patch.object(install, 'menu', side_effect=['1', '6']), \
                patch.object(install, 'install', side_effect=install.Cancelled()):
            self.assertEqual(install.main(['--plain']), 0)
        self.assertEqual(events, ['acquire', 'release'])
        events.clear()
        with patch.object(install, 'installer_lock', side_effect=lambda: RecordingLock(events)), \
                patch.object(install, 'menu', side_effect=['1']), \
                patch.object(install, 'install', side_effect=OSError('disk')):
            with self.assertRaises(OSError):
                install.main(['--plain'])
        self.assertEqual(events, ['acquire', 'release'])

    def test_health_check_does_not_take_the_installer_lock(self):
        with patch.object(install, 'menu', side_effect=['5', '5', '6']), \
                patch.object(install, 'health_report', side_effect=[2, 0]) as health:
            self.assertEqual(install.main(['--plain']), 0)
        self.assertEqual(health.call_count, 2)
        self.installer_lock.assert_not_called()

    def test_exit_does_not_take_the_installer_lock(self):
        with patch.object(install, 'menu', side_effect=['6']):
            install.main(['--plain'])
        self.installer_lock.assert_not_called()


class StartupGuardTests(unittest.TestCase):
    def setUp(self):
        MainLoopTests.setUp(self)

    def test_root_is_refused_before_anything_else(self):
        with patch('os.geteuid', return_value=0):
            with self.assertRaisesRegex(ValueError, 'ordinary account, without sudo'):
                install.main([])
        install.source_version.assert_not_called()

    def test_non_linux_is_refused(self):
        with patch.object(install.sys, 'platform', 'darwin'):
            with self.assertRaisesRegex(ValueError, 'ordinary account, without sudo'):
                install.main([])

    def test_the_clab_discovery_account_is_refused(self):
        with patch('pwd.getpwuid', return_value=SimpleNamespace(pw_name='clab-discovery', pw_dir='/home/clab-discovery')):
            with self.assertRaisesRegex(ValueError, 'not clab-discovery'):
                install.main([])
        install.source_version.assert_not_called()

    def test_a_non_tty_stdin_or_stdout_is_refused_in_every_front_end_mode(self):
        for argv in ([], ['--plain'], ['--tui'], ['--git']):
            for stdin_tty, stdout_tty in ((False, True), (True, False), (False, False)):
                with self.subTest(argv=argv, stdin=stdin_tty, stdout=stdout_tty), \
                        patch('sys.stdin.isatty', return_value=stdin_tty), patch.object(self.out, 'isatty', return_value=stdout_tty):
                    with self.assertRaisesRegex(ValueError, 'Open an interactive'):
                        install.main(argv)
        install.source_version.assert_not_called()
        self.installer_lock.assert_not_called()


class NoTextualOnThePlainPathTests(unittest.TestCase):
    MODULE = str(Path(__file__).resolve().parents[2] / 'deploy/install-manager.py')

    def run_python(self, code):
        env = {key: value for key, value in os.environ.items() if key not in ('PYTHONPATH', 'PYTHONSTARTUP')}
        env['PYTHONDONTWRITEBYTECODE'] = '1'
        return subprocess.run([sys.executable, '-I', '-c', code, self.MODULE], stdin=subprocess.DEVNULL,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=30, env=env)

    LOAD = ('import importlib.util, sys\n'
            'spec = importlib.util.spec_from_file_location("install_manager", sys.argv[1])\n'
            'm = importlib.util.module_from_spec(spec)\n'
            'spec.loader.exec_module(m)\n')

    def test_importing_the_installer_loads_neither_textual_nor_the_tui_app(self):
        result = self.run_python(self.LOAD + 'print(sorted(k for k in sys.modules if k == "textual" or k.startswith("textual.") '
                                 'or k.startswith("installer_tui.app") or k.startswith("installer_tui.theme")))')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), '[]')

    @unittest.skipIf(os.geteuid() == 0, 'main() refuses root before the terminal check')
    def test_plain_main_without_a_terminal_stops_without_importing_textual(self):
        code = self.LOAD + ('try:\n    m.main(["--plain"])\nexcept ValueError as error:\n    print("ERR", error)\n'
                            'print("textual" in sys.modules)\n'
                            'print(any(k.startswith("installer_tui.app") for k in sys.modules))\n')
        result = self.run_python(code)
        self.assertEqual(result.returncode, 0, result.stderr)
        lines = result.stdout.strip().splitlines()
        self.assertIn('Open an interactive', lines[0])
        self.assertEqual(lines[1:], ['False', 'False'])

    @unittest.skipIf(os.geteuid() == 0, 'main() refuses root before the terminal check')
    def test_plain_menu_session_never_imports_textual(self):
        code = self.LOAD + (
            'import io\n'
            'class Tty(io.StringIO):\n    def isatty(self): return True\n'
            'class In(io.StringIO):\n    def isatty(self): return True\n'
            'm.source_version = lambda: "1.0.0"\n'
            'sys.stdin = In("6\\n")\nsys.stdout = Tty()\n'
            'try:\n    status = m.main(["--plain"])\nfinally:\n    printed = sys.stdout.getvalue()\n    sys.stdout = sys.__stdout__\n'
            'print(status, "guided setup" in printed, "textual" in sys.modules, '
            'any(k.startswith("installer_tui.app") for k in sys.modules))\n')
        result = self.run_python(code)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), '0 True False False')


class TuiAvailableTests(unittest.TestCase):
    def setUp(self):
        self.ready = self.enterContext(patch.object(tui_bootstrap(), 'ready', return_value=True))

    def test_unset_dumb_and_unknown_terminals_are_unavailable_before_anything_is_checked(self):
        for term in (None, '', 'dumb', 'unknown'):
            with self.subTest(term=term), patch.dict(os.environ):
                os.environ.pop('TERM', None)
                if term is not None:
                    os.environ['TERM'] = term
                ready, reason = install.tui_available(OWNER)
                self.assertFalse(ready)
                self.assertIn('TERM=', reason)
                self.assertIn('unset' if term in (None, '') else term, reason)
        self.ready.assert_not_called()

    def test_not_provisioned_is_unavailable_and_points_at_setup_tui(self):
        self.ready.return_value = False
        with patch.dict(os.environ, {'TERM': 'xterm-256color'}):
            ready, reason = install.tui_available(OWNER)
        self.assertFalse(ready)
        self.assertIn('--setup-tui', reason)
        self.assertIn('install.sh', reason)
        self.ready.assert_called_once_with(OWNER)

    def test_provisioned_with_a_capable_terminal_is_available(self):
        with patch.dict(os.environ, {'TERM': 'xterm-256color'}):
            self.assertEqual(install.tui_available(OWNER), (True, ''))

    def test_missing_installer_files_are_unavailable_not_an_error(self):
        with patch.dict(os.environ, {'TERM': 'xterm'}), patch.object(install, 'tui_package', side_effect=ImportError('no module')):
            ready, reason = install.tui_available(OWNER)
        self.assertFalse(ready)
        self.assertIn('missing', reason)


class StartupInvariantTests(unittest.TestCase):
    """Behaviour the audit found untested: choose_env_copy, advanced choices, phase labels, plan wording."""

    def source(self):
        folder = self.enterContext(tempfile.TemporaryDirectory())
        root = Path(folder)
        (root / 'clab-backup-ui').mkdir()
        self.enterContext(patch.object(install, 'SOURCE', root))
        return root

    def test_choose_env_copy_retains_an_existing_env_without_a_menu(self):
        root = self.source()
        (root / 'clab-backup-ui/.env').write_text('UI_PORT=9000\n')
        with patch.object(install, 'menu') as menu, patch('sys.stdout', new=io.StringIO()) as printed:
            self.assertIsNone(install.choose_env_copy())
        menu.assert_not_called()
        self.assertIn('retained unchanged', printed.getvalue())

    def test_choose_env_copy_refuses_a_symlinked_env(self):
        root = self.source()
        (root / 'elsewhere.env').write_text('X=1\n')
        os.symlink(root / 'elsewhere.env', root / 'clab-backup-ui/.env')
        with patch.object(install, 'menu') as menu, self.assertRaisesRegex(ValueError, 'symlink'):
            install.choose_env_copy()
        menu.assert_not_called()

    def test_choose_env_copy_menu_defaults_and_back(self):
        self.source()
        with patch.object(install, 'menu', return_value='1') as menu:
            self.assertIsNone(install.choose_env_copy())
        self.assertEqual([key for key, _ in menu.call_args.args[1]], ['1', '2', '3'])
        with patch.object(install, 'menu', return_value='3'), self.assertRaises(install.Cancelled):
            install.choose_env_copy()

    def test_choose_env_copy_blank_path_goes_back(self):
        self.source()
        with patch.object(install, 'menu', return_value='2'), patch.object(install, 'ask', return_value=''), \
                self.assertRaises(install.Cancelled):
            install.choose_env_copy()

    def test_choose_env_copy_reasks_until_a_regular_small_env_is_given(self):
        root = self.source()
        good = root / 'previous.env'
        good.write_text('UI_PORT=8099\n')
        too_big = root / 'big.env'
        too_big.write_bytes(b'x' * 65537)
        link = root / 'link.env'
        os.symlink(good, link)
        folder = root / 'a-folder'
        folder.mkdir()
        answers = ['relative/.env', str(root / 'missing.env'), str(folder), str(link), str(too_big), str(good)]
        with patch.object(install, 'menu', return_value='2'), patch.object(install, 'ask', side_effect=answers) as ask, \
                patch('sys.stdout', new=io.StringIO()) as printed:
            result = install.choose_env_copy()
        self.assertEqual(result, good)
        self.assertEqual(ask.call_count, len(answers))
        self.assertEqual(printed.getvalue().count('Choose a regular .env file no larger than 64 KiB'), len(answers) - 1)
        self.assertNotIn('UI_PORT', printed.getvalue(), 'the file contents are never displayed')

    def test_choose_env_copy_accepts_exactly_64_kib_and_copy_env_rejects_growth_after_the_choice(self):
        root = self.source()
        edge = root / 'edge.env'
        edge.write_bytes(b'x' * 65536)
        with patch.object(install, 'menu', return_value='2'), patch.object(install, 'ask', return_value=str(edge)):
            self.assertEqual(install.choose_env_copy(), edge)
        edge.write_bytes(b'x' * 65537)
        with self.assertRaisesRegex(ValueError, '64 KiB'):
            install.copy_env(edge)
        self.assertFalse((root / 'clab-backup-ui/.env').exists())

    def test_copy_env_none_is_a_no_op(self):
        root = self.source()
        self.assertIsNone(install.copy_env(None))
        self.assertFalse((root / 'clab-backup-ui/.env').exists())

    def test_advanced_discovery_only_asks_no_engineer_question_and_runs_no_engineer_phase(self):
        with patch.object(install, 'choose_env_copy', return_value=None), \
                patch.object(install, 'menu', side_effect=['2']) as menu, patch.object(install, 'confirm', return_value=True):
            options = install.ask_install_options(OWNER, advanced=True)
        self.assertEqual(menu.call_count, 1)
        self.assertEqual(menu.call_args.args[0], 'Lab operation access')
        self.assertEqual((options.operations, options.engineer, options.repair), ('2', '2', True))
        steps = install.install_steps(OWNER, '1.30.35', options)
        self.assertNotIn('engineer', [step.key for step in steps])
        launch = next(step for step in steps if step.key == 'launch')
        self.assertNotIn('--enable-operations', launch.argv)

        order = []
        with patch.object(install, 'choose_env_copy', return_value=None), \
                patch.object(install, 'menu', side_effect=['2', '2']), patch.object(install, 'confirm', return_value=True), \
                patch.object(install, 'verify_manager'), patch.object(install, 'setup_lazydocker'), \
                patch.object(install, 'git_setup'), patch.object(install, 'run', side_effect=record_run(order)):
            install.install(OWNER, '1.30.35', advanced=True)
        self.assertFalse(any('setup-engineer-access.sh' in c for c in order))
        self.assertFalse(any('--enable-operations' in c for c in order))
        self.assertTrue(any('start-manager.sh' in c for c in order))

    def test_advanced_operations_back_is_cancelled_before_any_command_runs(self):
        with patch.object(install, 'choose_env_copy', return_value=None), \
                patch.object(install, 'menu', side_effect=['3']) as menu, patch.object(install, 'confirm') as confirm, \
                patch.object(install, 'run') as run, patch.object(install, 'copy_env') as copy:
            with self.assertRaises(install.Cancelled):
                install.install(OWNER, '1.30.35', advanced=True)
        run.assert_not_called()
        copy.assert_not_called()
        confirm.assert_not_called()
        self.assertEqual(menu.call_count, 1, 'neither the engineer nor the next-step question is asked')
        with patch.object(install, 'choose_env_copy', return_value=None), patch.object(install, 'menu', return_value='3'):
            with self.assertRaises(install.Cancelled):
                install.ask_install_options(OWNER, advanced=True)

    def test_advanced_enabled_operations_asks_the_engineer_question_with_the_owner_name(self):
        with patch.object(install, 'choose_env_copy', return_value=None), \
                patch.object(install, 'menu', side_effect=['1', '2']) as menu, patch.object(install, 'confirm', return_value=False):
            options = install.ask_install_options(OWNER, advanced=True)
        self.assertEqual(menu.call_count, 2)
        self.assertIn('owner', menu.call_args_list[1].args[0])
        self.assertEqual((options.operations, options.engineer, options.repair), ('1', '2', False))

    def test_repair_declined_omits_the_installation_media_repair_everywhere(self):
        self.assertNotIn('--repair-install-media', install.prerequisites_command(False))
        self.assertIn('--repair-install-media', install.prerequisites_command(True))
        order = []
        with patch.object(install, 'choose_env_copy', return_value=None), \
                patch.object(install, 'menu', side_effect=['1', '1', '2']), patch.object(install, 'confirm', side_effect=[False, True]), \
                patch.object(install, 'verify_manager'), patch.object(install, 'setup_lazydocker'), \
                patch.object(install, 'git_setup'), patch.object(install, 'run', side_effect=record_run(order)), \
                patch('sys.stdout', new=io.StringIO()) as printed:
            install.install(OWNER, '1.30.35', advanced=True)
        self.assertFalse(any('--repair-install-media' in c for c in order))
        self.assertTrue(any('install-prerequisites.sh' in c for c in order))
        self.assertIn('  Installation-media APT repair: not selected', printed.getvalue().splitlines())

    def test_install_steps_titles_are_numbered_out_of_five_without_engineer_access(self):
        steps = install.install_steps(OWNER, '1.30.35', install.Options(operations='2'))
        numbered = [step.title for step in steps if step.title[:1].isdigit()]
        self.assertEqual(numbered, ['1/5 Administrator access and settings', '2/5 VM prerequisites',
                                    '3/5 Password, helpers, image and manager', '4/5 Browser Wireshark capture stack',
                                    '5/5 Running manager verification'])

    def test_install_steps_titles_are_numbered_out_of_six_with_engineer_access(self):
        steps = install.install_steps(OWNER, '1.30.35', install.Options())
        numbered = [step.title for step in steps if step.title[:1].isdigit()]
        self.assertEqual(numbered, ['1/6 Administrator access and settings', '2/6 VM prerequisites',
                                    '3/6 Password, helpers, image and manager', '4/6 Browser Wireshark capture stack',
                                    '5/6 Running manager verification', '6/6 Engineer access for VS Code'])

    def test_plain_install_calls_phase_with_the_same_numbered_titles(self):
        for options_kwargs, expected in (
                ({}, ['1/6 Administrator access and settings', '2/6 VM prerequisites',
                      '3/6 Password, helpers, image and manager', '4/6 Browser Wireshark capture stack',
                      '5/6 Running manager verification', '6/6 Engineer access for VS Code']),
                ({'operations': '2'}, ['1/5 Administrator access and settings', '2/5 VM prerequisites',
                                       '3/5 Password, helpers, image and manager', '4/5 Browser Wireshark capture stack',
                                       '5/5 Running manager verification'])):
            titles = []
            options = install.Options(**options_kwargs)
            with self.subTest(**options_kwargs), patch.object(install, 'ask_install_options', return_value=options), \
                    patch.object(install, 'phase', side_effect=lambda title, action, env=None: titles.append(title)), \
                    patch.object(install, 'setup_lazydocker'), patch.object(install, 'git_setup'), \
                    patch('sys.stdout', new=io.StringIO()):
                install.install(OWNER, '1.30.35')
            self.assertEqual(titles, expected)

    def test_install_steps_structure_order_flags_and_visibility(self):
        steps = install.install_steps(OWNER, '1.30.35', install.Options())
        self.assertEqual([step.key for step in steps], ['admin', 'settings', 'prereqs', 'launch', 'capture', 'verify',
                                                        'engineer', 'lazydocker', 'git'])
        by_key = {step.key: step for step in steps}
        self.assertEqual(by_key['admin'].argv, ['sudo', '-v'])
        self.assertEqual(by_key['admin'].interactive, 'auth')
        self.assertTrue(by_key['prereqs'].tee)
        self.assertEqual(by_key['launch'].interactive, 'password')
        self.assertEqual(by_key['git'].interactive, 'always')
        self.assertTrue(by_key['git'].visible)
        self.assertFalse(by_key['settings'].visible, 'nothing to copy: the settings step is hidden')
        self.assertTrue(all(by_key[key].bare for key in ('settings', 'lazydocker', 'git')))
        self.assertTrue(all(by_key[key].post for key in ('lazydocker', 'git')))
        self.assertFalse(any(by_key[key].post for key in ('admin', 'prereqs', 'launch', 'capture', 'verify', 'engineer')))
        later = {step.key: step for step in install.install_steps(
            OWNER, '1', install.Options(env_source=Path('/x/.env'), git_now=False))}
        self.assertTrue(later['settings'].visible)
        self.assertFalse(later['git'].visible)

    def test_install_step_actions_run_the_same_commands_the_argv_describes(self):
        options = install.Options(operations='1', engineer='1', repair=False)
        steps = {step.key: step for step in install.install_steps(OWNER, '1.30.35', options)}
        with patch.object(install, 'command_step') as command_step:
            steps['admin'].action()
            steps['prereqs'].action()
            steps['launch'].action()
        self.assertEqual(command_step.call_args_list[0].args, (['sudo', '-v'], OWNER))
        self.assertEqual(command_step.call_args_list[1].args, (steps['prereqs'].argv, OWNER))
        self.assertEqual(command_step.call_args_list[1].kwargs, {'tee': True})
        self.assertEqual(command_step.call_args_list[2].args, (steps['launch'].argv, OWNER))
        self.assertEqual(steps['prereqs'].argv, install.prerequisites_command(False))
        self.assertEqual(steps['launch'].argv, install.launch_command('1'))
        self.assertEqual(steps['engineer'].argv, install.engineer_command(OWNER))
        self.assertEqual(steps['capture'].argv, install.stack_command('setup-capture.sh'))

    def test_helper_commands_are_exactly_the_documented_argv(self):
        deploy = install.SOURCE / 'deploy'
        self.assertEqual(install.prerequisites_command(True), ['sudo', 'bash', str(deploy / 'install-prerequisites.sh'),
                                                               '--docker', '--containerlab', '--repair-install-media'])
        self.assertEqual(install.prerequisites_command(False), ['sudo', 'bash', str(deploy / 'install-prerequisites.sh'),
                                                                '--docker', '--containerlab'])
        self.assertEqual(install.launch_command('1'), ['sudo', 'env', 'DOCKER_HOST=unix:///var/run/docker.sock', 'bash',
                                                       str(deploy / 'start-manager.sh'), '--manager-only', '--enable-operations'])
        self.assertEqual(install.launch_command('2'), install.launch_command('1')[:-1])
        self.assertEqual(install.engineer_command(OWNER), ['sudo', 'bash', str(deploy / 'setup-engineer-access.sh'),
                                                           '--owner', 'owner'])
        self.assertEqual(install.git_command(), ['bash', str(deploy / 'setup-git.sh')])
        self.assertEqual(install.health_command(), ['bash', str(deploy / 'check-install.sh')])
        self.assertEqual(install.lock_wait_command(), ['sudo', 'python3', str(install.APT_LOCK_SCRIPT), '--wait', '--pause-timers'])
        self.assertEqual(install.stack_command('setup-capture.sh'), [
            'sudo', 'env', 'DOCKER_HOST=unix:///var/run/docker.sock', 'bash', str(deploy / 'setup-capture.sh')])

    def test_plan_lines_for_the_standard_options(self):
        lines = install.plan_lines(OWNER, '1.30.35', install.Options())
        self.assertEqual(len(lines), 14)
        self.assertEqual(lines[0], 'Source: ' + str(install.SOURCE) + ' (1.30.35)')
        self.assertIn('Rebuild/recreate only the manager; existing lab containers remain in place.', lines)
        self.assertIn('Lab operations: enabled with default trusted roots', lines)
        self.assertIn('Engineer access: set up for owner (VS Code, Containerlab extension)', lines)
        self.assertIn('Settings: retain current .env or use defaults', lines)
        self.assertIn('Installation-media APT repair: enabled with backup', lines)
        self.assertEqual(lines[-1], 'Check running version/HTTP, then set up Git under owner.')

    def test_plan_lines_reflect_non_standard_options(self):
        lines = install.plan_lines(OWNER, '1.30.35', install.Options(env_source=Path('/old/.env'), operations='2', repair=False))
        self.assertIn('Lab operations: existing permissions retained', lines)
        self.assertIn('Engineer access: not selected', lines)
        self.assertIn('Settings: copy /old/.env', lines)
        self.assertIn('Installation-media APT repair: not selected', lines)

    def test_install_prints_exactly_two_spaces_plus_each_plan_line(self):
        options = install.Options()
        plan = install.plan_lines(OWNER, '1.30.35', options)
        with patch.object(install, 'ask_install_options', return_value=options), patch.object(install, 'phase'), \
                patch.object(install, 'setup_lazydocker'), patch.object(install, 'git_setup'), \
                patch('sys.stdout', new=io.StringIO()) as printed:
            install.install(OWNER, '1.30.35')
        lines = printed.getvalue().splitlines()
        start = lines.index('Installation plan')
        self.assertEqual(lines[start + 1:start + 1 + len(plan)], ['  ' + line for line in plan])
        self.assertTrue(lines[start + 1 + len(plan)].startswith('Starting now;'))

    def test_install_runs_copy_env_outside_phase_and_git_after_the_summary(self):
        events = []
        options = install.Options(env_source=Path('/old/.env'))
        with patch.object(install, 'ask_install_options', return_value=options), \
                patch.object(install, 'copy_env', side_effect=lambda path: events.append(('copy', path))), \
                patch.object(install, 'phase', side_effect=lambda title, action, env=None: events.append(('phase', title[:3]))), \
                patch.object(install, 'setup_lazydocker', side_effect=lambda env: events.append(('lazydocker',))), \
                patch.object(install, 'git_setup', side_effect=lambda env: events.append(('git',))), \
                patch('sys.stdout', new=io.StringIO()) as printed:
            install.install(OWNER, '1.30.35')
        kinds = [event[0] for event in events]
        self.assertEqual(kinds, ['phase', 'copy', 'phase', 'phase', 'phase', 'phase', 'phase', 'lazydocker', 'git'])
        self.assertEqual(events[1], ('copy', Path('/old/.env')))
        self.assertLess(printed.getvalue().index('Manager installation is ready'), printed.getvalue().index('In VM connection use'))
        self.assertIn('check-install.sh', printed.getvalue().splitlines()[-1])

    def test_git_setup_success_and_failure_messages(self):
        with patch.object(install, 'run', return_value=subprocess.CompletedProcess([], 0)) as run, \
                patch('sys.stdout', new=io.StringIO()) as printed:
            self.assertEqual(install.git_setup(OWNER), 0)
        self.assertEqual(run.call_args.args, (install.git_command(), OWNER))
        text = printed.getvalue()
        self.assertIn('Git setup runs as owner, with home /home/owner.', text)
        self.assertIn('Git setup completed. In the manager, connect the registered checkout to your lab.', text)
        self.assertNotIn('incomplete', text)
        with patch.object(install, 'run', return_value=subprocess.CompletedProcess([], 3)), \
                patch('sys.stdout', new=io.StringIO()) as printed:
            self.assertEqual(install.git_setup(OWNER), 3)
        text = printed.getvalue()
        self.assertIn('Git setup is incomplete. The manager and existing checkout remain available.', text)
        self.assertIn('Choose Git setup from this menu to resume without rebuilding the manager.', text)
        self.assertNotIn('completed', text)

    def test_engineer_access_prints_the_reconnect_advice_after_the_command(self):
        def step(args, env, tee=False):
            print('COMMAND-RAN')
        with patch.object(install, 'command_step', side_effect=step) as command_step, \
                patch('sys.stdout', new=io.StringIO()) as printed:
            install.engineer_access(OWNER)
        command_step.assert_called_once_with(install.engineer_command(OWNER), OWNER)
        text = printed.getvalue()
        self.assertLess(text.index('COMMAND-RAN'), text.index(install.ENGINEER_RECONNECT))
        self.assertIn('Remote-SSH: Kill VS Code Server on Host', install.ENGINEER_RECONNECT)

    def test_engineer_access_failure_prints_no_reconnect_advice(self):
        with patch.object(install, 'command_step', side_effect=ValueError('failed')), \
                patch('sys.stdout', new=io.StringIO()) as printed:
            with self.assertRaises(ValueError):
                install.engineer_access(OWNER)
        self.assertNotIn(install.ENGINEER_RECONNECT, printed.getvalue())

    def test_verify_manager_renews_sudo_before_checking(self):
        order = []
        with patch.object(install, 'command_step', side_effect=lambda args, env, tee=False: order.append(args)), \
                patch.object(install, 'check_manager', side_effect=lambda env, version: order.append(('check', version))):
            install.verify_manager(OWNER, '1.30.35')
        self.assertEqual(order, [['sudo', '-v'], ('check', '1.30.35')])

    def test_options_defaults_and_operations_two_forces_engineer_two(self):
        options = install.Options()
        self.assertEqual((options.env_source, options.operations, options.engineer, options.repair, options.git_now),
                         (None, '1', '1', True, True))
        self.assertEqual(install.Options(operations='2', engineer='1').engineer, '2')
        self.assertEqual(install.Options(operations='3', engineer='1').engineer, '2')
        self.assertEqual(install.Options(operations='1', engineer='2').engineer, '2')

    def test_action_steps_rejects_an_unknown_action_and_describes_the_known_ones(self):
        with self.assertRaisesRegex(ValueError, 'Unknown setup action: unknown'):
            install.action_steps('unknown', OWNER, '1.30.35')
        git = install.action_steps('git', OWNER, '1.30.35')
        self.assertEqual([(s.key, s.argv, s.interactive, s.bare) for s in git],
                         [('git', install.git_command(), 'always', True)])
        engineer = install.action_steps('engineer', OWNER, '1.30.35')
        self.assertEqual([(s.key, s.argv) for s in engineer], [('engineer', install.engineer_command(OWNER))])
        capture = install.action_steps('capture', OWNER, '1.30.35')
        self.assertEqual([(s.key, s.argv) for s in capture], [('capture', install.stack_command('setup-capture.sh'))])
        installed = install.action_steps('install', OWNER, '1.30.35')
        self.assertEqual([s.key for s in installed], [s.key for s in install.install_steps(OWNER, '1.30.35', install.Options())])
        no_engineer = install.action_steps('install', OWNER, '1.30.35', install.Options(operations='2'))
        self.assertNotIn('engineer', [s.key for s in no_engineer])

    def test_action_step_actions_call_the_plain_menu_functions(self):
        with patch.object(install, 'git_setup') as git, patch.object(install, 'engineer_access') as engineer, \
                patch.object(install, 'capture_stack') as capture:
            for action in ('git', 'engineer', 'capture'):
                for step in install.action_steps(action, OWNER, '1.30.35'):
                    step.action()
        git.assert_called_once_with(OWNER)
        engineer.assert_called_once_with(OWNER)
        capture.assert_called_once_with(OWNER)


class PackageLockHelperTests(unittest.TestCase):
    def test_lock_free_is_false_when_the_check_times_out(self):
        with patch.object(install, 'run', side_effect=subprocess.TimeoutExpired('sudo', 30)):
            self.assertFalse(install.lock_free({}))

    def test_lock_free_is_false_for_a_held_lock_and_uses_noninteractive_sudo(self):
        with patch.object(install, 'run', return_value=subprocess.CompletedProcess([], 1)) as run:
            self.assertFalse(install.lock_free({}))
        self.assertEqual(run.call_args.args[0][:3], ['sudo', '-n', 'python3'])
        self.assertTrue(run.call_args.kwargs['capture'])

    def test_lock_holder_text_is_empty_on_timeout_or_failure_and_the_report_otherwise(self):
        with patch.object(install, 'run', side_effect=subprocess.TimeoutExpired('sudo', 30)):
            self.assertEqual(install.lock_holder_text({}), '')
        with patch.object(install, 'run', return_value=subprocess.CompletedProcess([], 1, stdout='sudo: a password is required\n')):
            self.assertEqual(install.lock_holder_text({}), '')
        with patch.object(install, 'run', return_value=subprocess.CompletedProcess([], 0, stdout='held by pid 7\n')) as run:
            self.assertEqual(install.lock_holder_text({}), 'held by pid 7\n')
        self.assertIn('--show', run.call_args.args[0])

    def test_lock_recovery_wait_that_ends_unsuccessfully_checks_again_and_loops(self):
        printed = io.StringIO()
        with patch.object(install, 'lock_free', side_effect=[False, False]) as free, \
                patch.object(install, 'lock_holder_text', return_value=''), \
                patch.object(install, 'menu', return_value='1') as menu, \
                patch.object(install, 'run', side_effect=[subprocess.CompletedProcess([], 1),
                                                          subprocess.CompletedProcess([], 0)]) as run, \
                patch('sys.stdout', new=printed):
            self.assertTrue(install.lock_recovery({}))
        self.assertEqual(free.call_count, 2)
        self.assertEqual(menu.call_count, 2)
        self.assertEqual(run.call_count, 2)
        self.assertIn('The wait ended without releasing the package lock; checking again.', printed.getvalue())
        self.assertIn('The package lock is released.', printed.getvalue())

    def test_lock_recovery_loops_back_to_the_free_check_and_succeeds_without_another_wait(self):
        printed = io.StringIO()
        with patch.object(install, 'lock_free', side_effect=[False, True]) as free, \
                patch.object(install, 'lock_holder_text', return_value=''), patch.object(install, 'menu', return_value='1'), \
                patch.object(install, 'run', return_value=subprocess.CompletedProcess([], 1)) as run, \
                patch('sys.stdout', new=printed):
            self.assertTrue(install.lock_recovery({}))
        self.assertEqual(free.call_count, 2)
        run.assert_called_once()
        self.assertIn('The package lock is now released.', printed.getvalue())


class RunHelperTests(unittest.TestCase):
    def setUp(self):
        folder = self.enterContext(tempfile.TemporaryDirectory())
        self.root = Path(folder).resolve()
        self.enterContext(patch.object(install, 'SOURCE', self.root))
        self.env = {'PATH': os.environ.get('PATH', '/usr/bin:/bin')}

    def test_run_tee_streams_and_returns_the_combined_output(self):
        with patch('sys.stdout', new=io.StringIO()) as printed:
            result = install.run(['sh', '-c', 'echo hi'], self.env, tee=True)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, 'hi\n')
        self.assertEqual(printed.getvalue(), 'hi\n')

    def test_run_tee_merges_stderr_keeps_the_exit_status_and_runs_in_the_source_folder(self):
        with patch('sys.stdout', new=io.StringIO()) as printed:
            result = install.run(['sh', '-c', 'echo out; echo err >&2; pwd -P; exit 3'], self.env, tee=True)
        self.assertEqual(result.returncode, 3)
        self.assertEqual(result.stdout.splitlines(), ['out', 'err', str(self.root)])
        self.assertEqual(printed.getvalue(), result.stdout)

    def test_run_tee_output_feeds_the_lock_signature_decision(self):
        script = "echo 'E: Could not get lock /var/lib/dpkg/lock-frontend. It is held by process 7'; exit 100"
        with patch('sys.stdout', new=io.StringIO()):
            with self.assertRaises(ValueError) as caught:
                install.command_step(['sh', '-c', script], self.env, tee=True)
        self.assertTrue(caught.exception.lock_signature)

    def test_run_capture_returns_stdout_with_no_stdin_and_no_stderr(self):
        result = install.run(['sh', '-c', 'cat; echo out; echo err >&2'], self.env, capture=True)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, 'out\n')

    def test_output_strips_the_output_and_raises_on_failure(self):
        self.assertEqual(install.output(['sh', '-c', 'echo "  value  "'], self.env), 'value')
        with self.assertRaisesRegex(ValueError, 'Check failed'):
            install.output(['sh', '-c', 'exit 1'], self.env)


class CheckManagerReturnTests(unittest.TestCase):
    def healthy(self, command, version='1.16.0'):
        from contextlib import nullcontext
        response = SimpleNamespace(status=200, read=lambda limit: json.dumps({'version': version}).encode())
        opener = SimpleNamespace(open=lambda url, timeout: nullcontext(response))
        output = patch.object(install, 'output', side_effect=['a' * 64, version, json.dumps(command)])
        return output, patch.object(install, 'build_opener', return_value=opener)

    def test_check_manager_returns_the_vm_local_address_and_says_it(self):
        said = []
        output, opener = self.healthy(['uvicorn', '--host', '0.0.0.0', '--port', '8099'])
        with output, opener, patch('sys.stdout', new=io.StringIO()) as printed:
            address = install.check_manager({}, '1.16.0', 0, say=said.append)
        self.assertEqual(address, 'http://127.0.0.1:8099/')
        self.assertIn('VM-local address: http://127.0.0.1:8099/', said)
        self.assertIn('Manager 1.16.0: running; HTTP and version checks passed.', said)
        self.assertEqual(printed.getvalue(), '', 'say= replaces print')

    def test_check_manager_returns_a_bracketed_ipv6_address(self):
        output, opener = self.healthy(['uvicorn', '--host', '::', '--port', '8081'])
        with output, opener, patch('sys.stdout', new=io.StringIO()):
            self.assertEqual(install.check_manager({}, '1.16.0', 0), 'http://[::1]:8081/')

    def test_check_manager_sudo_parameter_reaches_every_docker_command(self):
        output, opener = self.healthy(['uvicorn', '--host', '10.0.0.5', '--port', '8081'])
        with output as called, opener, patch('sys.stdout', new=io.StringIO()):
            self.assertEqual(install.check_manager({}, '1.16.0', 0, sudo=('sudo', '-n')), 'http://10.0.0.5:8081/')
        commands = [call.args[0] for call in called.call_args_list]
        self.assertEqual(len(commands), 3)
        for command in commands:
            self.assertEqual(command[:3], ['sudo', '-n', 'docker'])

    def test_check_manager_keeps_polling_until_the_deadline_then_fails(self):
        def refuse(url, timeout):
            raise OSError('connection refused')
        clock = iter([0, 0.5, 5])
        fake_time = SimpleNamespace(monotonic=lambda: next(clock), sleep=MagicMock())
        with patch.object(install, 'output', side_effect=['a' * 64, '1.16.0', '["--host","0.0.0.0","--port","8081"]']), \
                patch.object(install, 'build_opener', return_value=SimpleNamespace(open=refuse)), \
                patch.object(install, 'time', fake_time), patch('sys.stdout', new=io.StringIO()):
            with self.assertRaisesRegex(ValueError, 'did not pass'):
                install.check_manager({}, '1.16.0', 1)
        fake_time.sleep.assert_called_once_with(2)

    def test_compose_sudo_parameter_changes_only_the_prefix(self):
        quiet = install.compose('ps', sudo=('sudo', '-n'))
        self.assertEqual(quiet[:3], ['sudo', '-n', 'docker'])
        default = install.compose('ps')
        self.assertEqual(default[:2], ['sudo', 'docker'])
        self.assertNotIn('-n', default)
        self.assertEqual(quiet[2:], default[1:])
        self.assertEqual(default[-1], 'ps')
        self.assertEqual(install.compose('ps'), install.compose('ps', sudo=('sudo',)))


class LazydockerResultTests(unittest.TestCase):
    TAG = 'v0.23.3'

    def make_tarball(self, content='BIN'):
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode='w:gz') as archive:
            info = tarfile.TarInfo(name='lazydocker')
            info.size = len(content)
            archive.addfile(info, io.BytesIO(content.encode()))
        return buffer.getvalue()

    def test_failure_returns_skipped_and_the_text(self):
        said = []
        with patch.object(install, 'lazydocker_arch', return_value='x86_64'), \
                patch.object(install, 'lazydocker_latest_tag', side_effect=OSError('network unreachable')):
            outcome = install.setup_lazydocker({'HOME': '/nonexistent-test-home'}, say=said.append)
        self.assertEqual(outcome, ('skipped', 'network unreachable'))
        self.assertIn('lazydocker setup skipped: network unreachable', said)

    def test_unsupported_architecture_returns_skipped(self):
        with patch.object(install.platform, 'machine', return_value='riscv64'):
            outcome = install.setup_lazydocker({'HOME': '/nonexistent-test-home'}, say=lambda text: None)
        self.assertEqual(outcome, ('skipped', 'unsupported architecture (riscv64)'))

    def test_up_to_date_returns_current_without_downloading(self):
        said = []
        with tempfile.TemporaryDirectory() as folder, patch.object(install, 'lazydocker_arch', return_value='x86_64'), \
                patch.object(install, 'lazydocker_latest_tag', return_value=self.TAG), \
                patch.object(install, 'lazydocker_up_to_date', return_value=True), \
                patch.object(install, 'download_lazydocker_tarball') as download, \
                patch.dict(os.environ, {'PATH': '/usr/bin'}), patch('sys.stdout', new=io.StringIO()) as printed:
            outcome = install.setup_lazydocker({'HOME': folder}, say=said.append)
        self.assertEqual(outcome, ('current', 'lazydocker 0.23.3 is already current.'))
        download.assert_not_called()
        self.assertIn('lazydocker 0.23.3 is already current.', said)
        self.assertEqual(printed.getvalue(), '')

    def test_success_returns_installed_and_reports_the_path_hint_only_when_needed(self):
        tarball = self.make_tarball()
        filename = install.lazydocker_tarball_filename(self.TAG, 'x86_64')
        checksums = hashlib.sha256(tarball).hexdigest() + '  ' + filename + '\n'
        for path_has_it in (False, True):
            said = []
            with self.subTest(path_has_it=path_has_it), tempfile.TemporaryDirectory() as folder, \
                    patch.object(install, 'lazydocker_arch', return_value='x86_64'), \
                    patch.object(install, 'lazydocker_latest_tag', return_value=self.TAG), \
                    patch.object(install, 'download_lazydocker_tarball', return_value=tarball), \
                    patch.object(install, 'download_lazydocker_checksums', return_value=checksums):
                destination = Path(folder) / '.local/bin/lazydocker'
                path = '/usr/bin' + (os.pathsep + str(destination.parent) if path_has_it else '')
                with patch.dict(os.environ, {'PATH': path}):
                    outcome = install.setup_lazydocker({'HOME': folder}, say=said.append)
                self.assertEqual(outcome, ('installed', f'lazydocker 0.23.3 installed to {destination}.'))
                self.assertEqual(destination.read_bytes(), b'BIN')
                self.assertIn('Added ~/.local/bin to PATH in ~/.bashrc (new shells only).', said)
                self.assertEqual('  export PATH="$PATH:$HOME/.local/bin"' in said, not path_has_it)


if __name__ == '__main__':
    unittest.main()
