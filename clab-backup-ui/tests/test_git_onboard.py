import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('git_onboard', Path(__file__).resolve().parents[2] / 'deploy/git-onboard.py')
onboard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(onboard)


class GitOnboardTests(unittest.TestCase):
    def test_rejects_credentials_and_non_https_urls(self):
        for url in ('https://token@github.com/a/b.git', 'https://github.com/a/b?token=x',
                    'git@github.com:a/b', 'http://github.com/a/b', 'https://github.com/a/b#secret',
                    'https://github.com/a/../b\n', 'https://github.com/a/%2e%2e/b'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                onboard.https_url(url)
        self.assertEqual(onboard.https_url('https://github.com/a/b.git'), 'https://github.com/a/b.git')

    def test_nonempty_non_repo_is_preserved_without_git(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            (path / 'notes.txt').write_text('Keep my notes')
            with patch.object(onboard, 'run') as run, self.assertRaisesRegex(ValueError, 'nothing was overwritten'):
                onboard.prepare_checkout(path, 'https://github.com/a/b.git', {})
            run.assert_not_called()
            self.assertEqual((path / 'notes.txt').read_text(), 'Keep my notes')

    def test_existing_checkout_is_reused_without_clone(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            (path / '.git').mkdir()
            with patch.object(onboard, 'run') as run:
                self.assertFalse(onboard.prepare_checkout(path, '', {}))
            run.assert_not_called()

    def test_empty_directory_needs_clone_and_clone_uses_literal_arguments(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'lab with spaces'
            path.mkdir()
            with self.assertRaisesRegex(ValueError, 'no Git checkout'):
                onboard.prepare_checkout(path, '', {})
            with patch.object(onboard, 'run', return_value=subprocess.CompletedProcess([], 0)) as run:
                self.assertTrue(onboard.prepare_checkout(path, 'https://github.com/a/b.git', {'HOME': 'owner'}))
                self.assertEqual(run.call_args.args[0], ['git', 'clone', '--', 'https://github.com/a/b.git', str(path)])

    def test_failed_clone_does_not_remove_existing_directory(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(onboard, 'run', return_value=subprocess.CompletedProcess([], 1)), self.assertRaisesRegex(ValueError, 'Clone failed'):
                onboard.prepare_checkout(Path(folder), 'https://github.com/a/b.git', {})
            self.assertTrue(Path(folder).is_dir())

    def test_service_environment_excludes_terminal_only_credentials(self):
        with patch.dict(os.environ, {'GH_TOKEN': 'secret', 'GIT_CONFIG_GLOBAL': '/other/config', 'SSH_AUTH_SOCK': '/tmp/agent'}):
            env = onboard.service_env('vm-owner', '/home/vm-owner')
        self.assertEqual(env['HOME'], '/home/vm-owner')
        self.assertEqual(env['USER'], 'vm-owner')
        self.assertEqual(env['GIT_TERMINAL_PROMPT'], '0')
        for key in ('GH_TOKEN', 'GIT_CONFIG_GLOBAL', 'SSH_AUTH_SOCK'):
            self.assertNotIn(key, env)

    def test_missing_identity_is_set_locally_and_validated(self):
        def result(args, *unused, **kwargs):
            return subprocess.CompletedProcess(args, 0, '' if args[1] == 'config' else 'Author <author@example.invalid>')
        with patch.object(onboard, 'run', side_effect=result) as run, patch.object(onboard, 'ask', side_effect=['Lab Author', 'author@example.invalid']):
            onboard.identity(Path('/lab'), {})
        commands = [call.args[0] for call in run.call_args_list]
        self.assertIn(['git', 'config', '--local', 'user.name', 'Lab Author'], commands)
        self.assertIn(['git', 'config', '--local', 'user.email', 'author@example.invalid'], commands)
        self.assertIn(['git', 'var', 'GIT_COMMITTER_IDENT'], commands)

    def test_existing_identity_does_not_prompt_or_rewrite_config(self):
        with patch.object(onboard, 'run', return_value=subprocess.CompletedProcess([], 0, 'existing')) as run, patch.object(onboard, 'ask') as ask:
            onboard.identity(Path('/lab'), {})
        ask.assert_not_called()
        self.assertFalse(any('--local' in call.args[0] for call in run.call_args_list))

    def test_root_and_parent_traversal_paths_rejected(self):
        for path in (str(Path.cwd().anchor), str(Path.cwd() / '..' / 'lab'), 'relative-lab'):
            with self.subTest(path=path), self.assertRaises(ValueError):
                onboard.checkout_path(path)

    def test_authentication_configured_for_same_owner_after_login(self):
        calls = []
        def run(args, env, **kwargs):
            calls.append((args, env))
            code = 1 if args[1:3] == ['auth', 'status'] else 0
            return subprocess.CompletedProcess(args, code, 'github-engineer')
        env = onboard.service_env('linux-engineer', '/home/linux-engineer')
        with patch.object(onboard.Path, 'exists', return_value=True), patch.object(onboard, 'run', side_effect=run):
            onboard.github_login(env)
        self.assertIn(['gh', 'auth', 'login', '--hostname', 'github.com', '--git-protocol', 'https', '--web'], [args for args, _ in calls])
        self.assertIn(['gh', 'auth', 'setup-git', '--hostname', 'github.com'], [args for args, _ in calls])
        self.assertTrue(all(e['HOME'] == '/home/linux-engineer' for _, e in calls))
        self.assertFalse(any(args[0] == 'sudo' for args, _ in calls))
