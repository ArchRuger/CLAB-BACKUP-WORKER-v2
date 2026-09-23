import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('install_manager', Path(__file__).resolve().parents[2] / 'deploy/install-manager.py')
install = importlib.util.module_from_spec(spec)
spec.loader.exec_module(install)


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
        order = []
        with patch.object(install, 'default_env_choice', return_value=None), \
                patch.object(install, 'setup_lazydocker'), patch.object(install, 'git_setup'), \
                patch.object(install, 'verify_manager', side_effect=lambda env, version: order.append('verify')), \
                patch.object(install, 'run', side_effect=record_run(order)):
            install.install({'USER': 'owner', 'HOME': '/home/owner'}, '1.25.0')
        launch = next(i for i, c in enumerate(order) if 'start-manager.sh' in c)
        capture = next(i for i, c in enumerate(order) if 'setup-capture.sh' in c)
        grafana = next(i for i, c in enumerate(order) if 'setup-telemetry.sh' in c)
        self.assertIn('--manager-only', order[launch], 'the launcher leaves the stacks to their own retryable phases')
        self.assertEqual([launch, capture, grafana, order.index('verify')], sorted([launch, capture, grafana, order.index('verify')]))
        for index in (capture, grafana):
            self.assertTrue(order[index].startswith('sudo env DOCKER_HOST=unix:///var/run/docker.sock bash ' + str(install.SOURCE / 'deploy')))
            self.assertNotIn('--no-recreate', order[index], 'standalone stack setup recreates the manager itself')

    def test_stack_menu_reinstalls_both_stacks_without_a_rebuild(self):
        commands = []
        with patch.object(install, 'run', side_effect=lambda args, env, capture=False, tee=False: (commands.append(' '.join(args)), subprocess.CompletedProcess(args, 0, stdout=''))[1]):
            install.stacks({'USER': 'owner'})
        self.assertEqual([c for c in commands if 'start-manager.sh' in c], [])
        self.assertTrue(any('setup-capture.sh' in c for c in commands) and any('setup-telemetry.sh' in c for c in commands))

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

    def test_successful_install_reports_version_and_path(self):
        tarball = self._make_tarball([('lazydocker', 'BIN')])
        with tempfile.TemporaryDirectory() as folder:
            printed = io.StringIO()
            with patch.object(install, 'lazydocker_arch', return_value='x86_64'), \
                    patch.object(install, 'lazydocker_latest_tag', return_value='v0.23.3'), \
                    patch.object(install, 'download_lazydocker_tarball', return_value=tarball), \
                    patch('sys.stdout', new=printed):
                install.setup_lazydocker({'HOME': folder})
            destination = Path(folder) / '.local/bin/lazydocker'
            self.assertEqual(destination.read_bytes(), b'BIN')
            self.assertIn('0.23.3', printed.getvalue())
            home_bashrc = Path(folder) / '.bashrc'
            self.assertIn('.local/bin', home_bashrc.read_text())


class MainLoopTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.object(install, 'source_version', return_value='1.30.35'))
        self.enterContext(patch('os.geteuid', return_value=1000))
        self.enterContext(patch('pwd.getpwuid', return_value=SimpleNamespace(pw_name='owner', pw_dir='/home/owner')))
        self.enterContext(patch('sys.stdin.isatty', return_value=True))
        fake_stdout = io.StringIO()
        self.enterContext(patch.object(fake_stdout, 'isatty', return_value=True))
        self.enterContext(patch('sys.stdout', new=fake_stdout))

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


if __name__ == '__main__':
    unittest.main()
