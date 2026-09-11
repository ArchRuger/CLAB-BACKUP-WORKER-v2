import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('install_manager', Path(__file__).resolve().parents[2] / 'deploy/install-manager.py')
install = importlib.util.module_from_spec(spec)
spec.loader.exec_module(install)


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

    def test_declined_plan_runs_no_commands_and_copies_no_settings(self):
        with patch.object(install, 'choose_env_copy', return_value=None), \
                patch.object(install, 'menu', return_value='1'), \
                patch.object(install, 'confirm', side_effect=[True, False]), \
                patch.object(install, 'run') as run, patch.object(install, 'copy_env') as copy:
            with self.assertRaises(install.Cancelled):
                install.install({'USER': 'owner'}, '1.16.0')
        run.assert_not_called()
        copy.assert_not_called()


if __name__ == '__main__':
    unittest.main()
