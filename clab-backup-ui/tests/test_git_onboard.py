import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('git_onboard', Path(__file__).resolve().parents[2] / 'deploy/git-onboard.py')
onboard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(onboard)


class GitOnboardTests(unittest.TestCase):
    def test_resume_arguments_preserve_checkout_path(self):
        self.assertEqual(onboard.parse_args(['--repo', '/home/owner/labs/lab with spaces']).repo,
                         '/home/owner/labs/lab with spaces')
        self.assertIsNone(onboard.parse_args([]).repo)

    def test_guided_resume_skips_clone_prompt_and_checks_identity_before_registration(self):
        with tempfile.TemporaryDirectory() as folder:
            account = SimpleNamespace(pw_name='owner', pw_dir=folder)
            url = 'https://github.com/owner/lab.git'
            def run(args, *unused, **kwargs):
                output = url if args[1] == 'remote' else 'true'
                return subprocess.CompletedProcess(args, 0, output)
            with patch.dict('sys.modules', {'pwd': SimpleNamespace(getpwuid=lambda uid: account)}), \
                    patch.object(onboard.os, 'geteuid', return_value=1000, create=True), \
                    patch.object(onboard.sys.stdin, 'isatty', return_value=True), \
                    patch.object(onboard.Path, 'is_file', return_value=True), \
                    patch.object(onboard.shutil, 'which', return_value='/usr/bin/git'), \
                    patch.object(onboard, 'prepare_checkout') as prepare, \
                    patch.object(onboard, 'read_registrations', return_value=[]), \
                    patch.object(onboard, 'github_login'), patch.object(onboard, 'identity') as identity, \
                    patch.object(onboard, 'run', side_effect=run) as commands, \
                    patch.object(onboard, 'ask') as ask, patch.object(onboard, 'confirm', return_value=False):
                onboard.main(['--repo', folder])
            ask.assert_not_called()
            identity.assert_called_once()
            self.assertEqual(identity.call_args.args[0], Path(folder))
            self.assertEqual(prepare.call_args_list[0].args[1], '')
            self.assertFalse(any(call.args[0][0] == 'sudo' or 'clone' in call.args[0]
                                 for call in commands.call_args_list))

    def test_empty_identity_reprompts(self):
        with patch.object(onboard, 'ask', side_effect=['', 'bad\x7fvalue', 'Lab Author']):
            self.assertEqual(onboard.ask_identity('Name'), 'Lab Author')

    def test_invalid_existing_identity_is_repaired_locally(self):
        config = {'user.name': '<>', 'user.email': 'bad'}
        commands = []
        def run(args, env, cwd, **kwargs):
            commands.append(args)
            if args[1:3] == ['config', '--get']:
                return subprocess.CompletedProcess(args, 0, config[args[3]])
            if args[1:3] == ['config', '--local']:
                config[args[3]] = args[4]
                return subprocess.CompletedProcess(args, 0, '')
            return subprocess.CompletedProcess(args, 0 if config['user.name'] == 'Lab Author' else 128, '')
        with patch.object(onboard, 'run', side_effect=run), patch.object(onboard, 'ask', side_effect=['Lab Author', 'lab@example.invalid']):
            onboard.identity(Path('/lab'), {})
        self.assertEqual(config, {'user.name': 'Lab Author', 'user.email': 'lab@example.invalid'})
        self.assertIn(['git', 'var', 'GIT_COMMITTER_IDENT'], commands)
        self.assertFalse(any('--global' in args for args in commands))

    def test_github_web_pages_are_rejected_before_clone(self):
        for suffix in ('/tree/main', '/blob/main/README.md', '/issues', '', '/../lab'):
            url = 'https://github.com/owner' + (suffix if not suffix else '/repo' + suffix)
            with self.subTest(url=url), self.assertRaisesRegex(ValueError, 'Code > HTTPS'):
                onboard.https_url(url)
        for url in ('https://github.com/owner/repo', 'https://github.com/owner/repo.git',
                    'https://github.com/owner/repo/', 'https://git.example.org/group/subgroup/repo.git'):
            self.assertEqual(onboard.https_url(url), url)

    def test_bad_clone_url_reprompts_without_running_commands(self):
        good = 'https://github.com/N24L/patricks-bgp-lab_2.git'
        with patch.object(onboard, 'ask', side_effect=[good[:-4] + '/issues', good]), \
                patch.object(onboard, 'run') as run, patch('builtins.print') as output:
            self.assertEqual(onboard.ask_clone_url(), good)
        run.assert_not_called()
        self.assertIn('Code > HTTPS', output.call_args.args[0])

    def test_menu_default_invalid_choice_and_cancel(self):
        options = [('clone', 'Clone'), ('existing', 'Existing')]
        with patch('builtins.input', side_effect=['wrong', '']):
            self.assertEqual(onboard.menu('Choose', options, 'clone'), 'clone')
        with patch('builtins.input', return_value='2'):
            self.assertEqual(onboard.menu('Choose', options, 'clone'), 'existing')
        with patch('builtins.input', return_value='q'), self.assertRaises(onboard.SetupCancelled):
            onboard.menu('Choose', options, 'clone')

    def test_github_page_conversion_requires_confirmation(self):
        good = 'https://github.com/N24L/patricks-bgp-lab_2.git'
        with patch.object(onboard, 'ask', return_value=good[:-4] + '/tree/main'), \
                patch.object(onboard, 'confirm', return_value=True) as confirm:
            self.assertEqual(onboard.ask_clone_url(), good)
        confirm.assert_called_once()
        with patch.object(onboard, 'ask', side_effect=[good[:-4] + '/tree/main', good]), \
                patch.object(onboard, 'confirm', return_value=False):
            self.assertEqual(onboard.ask_clone_url(), good)

    def test_page_conversion_never_accepts_credentials_or_another_host(self):
        for value in ('https://token@github.com/a/b/tree/main', 'https://github.com/a/b/tree/main?token=x',
                      'https://github.com/a/b/tree/main#fragment', 'https://other.example/a/b/tree/main',
                      'https://github.com:443/a/b/tree/main', 'https://github.com/a/%2e%2e/tree/main',
                      'https://github.com/a/b/tree/main\x7f'):
            with self.subTest(value=value):
                self.assertIsNone(onboard.github_clone_suggestion(value))

    def test_retry_only_reexecutes_failed_step(self):
        action = unittest.mock.Mock(side_effect=[ValueError('Temporary network failure'), 'ready'])
        with patch.object(onboard, 'menu', return_value='retry'):
            self.assertEqual(onboard.step(4, 'Checkout', action), 'ready')
        self.assertEqual(action.call_count, 2)

    def test_retry_can_reauthenticate_as_owner_without_root(self):
        action = unittest.mock.Mock(side_effect=[ValueError('No write permission'), 'ready'])
        env = onboard.service_env('owner', '/home/owner')
        with patch.object(onboard, 'menu', return_value='login'), patch.object(onboard, 'github_login') as login:
            self.assertEqual(onboard.step(5, 'Permission', action, env, 'https://github.com/a/b.git'), 'ready')
        login.assert_called_once_with(env, force=True)

    def test_cancel_during_failure_does_not_retry_or_remove_checkout(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            (path / 'notes.txt').write_text('Keep this file')
            action = unittest.mock.Mock(side_effect=ValueError('Access failure'))
            with patch.object(onboard, 'menu', side_effect=onboard.SetupCancelled), self.assertRaises(onboard.SetupCancelled):
                onboard.step(4, 'Checkout', action)
            action.assert_called_once()
            self.assertEqual((path / 'notes.txt').read_text(), 'Keep this file')

    def test_checkout_ownership_checked_before_any_git(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            (path / '.git').mkdir()
            with patch.object(onboard.os, 'geteuid', return_value=999999, create=True), \
                    patch.object(onboard, 'run') as run, self.assertRaisesRegex(ValueError, 'different Linux account'):
                onboard.prepare_checkout(path, '', {})
            run.assert_not_called()

    def test_checkout_directory_named_from_repository_after_page_conversion(self):
        with tempfile.TemporaryDirectory() as folder:
            account = SimpleNamespace(pw_name='owner', pw_dir=folder)
            url = 'https://github.com/a/b.git'
            with patch.object(onboard, 'menu', return_value='clone'), \
                    patch.object(onboard, 'ask_clone_url', return_value=url), \
                    patch.object(onboard, 'ask', side_effect=lambda prompt, default='': default) as ask:
                path, chosen, binding = onboard.choose_checkout(account, None, {})
            self.assertEqual(path, Path(folder) / 'labs' / 'b')
            self.assertEqual(chosen, url)
            self.assertEqual(binding['remote'], 'origin')
            self.assertEqual(ask.call_args.args[1], str(path))

    def test_resume_command_points_to_existing_checkout_after_cancellation(self):
        with tempfile.TemporaryDirectory(prefix='lab with spaces ') as folder:
            path = Path(folder)
            (path / '.git').mkdir()
            with patch('builtins.print') as output:
                onboard.resume_message(path)
            self.assertIn('--guided --repo', output.call_args.args[0])
            self.assertIn(str(path), output.call_args.args[0])

    def test_read_registrations_uses_only_root_list_and_validates_response(self):
        payload = json.dumps({'result': {'protocol': 'clab-manager-git-v1', 'repositories': []}})
        with patch.object(onboard, 'run', return_value=subprocess.CompletedProcess([], 0, payload)) as run:
            self.assertEqual(onboard.read_registrations({}), [])
        self.assertEqual(run.call_args_list[0].args[0], ['sudo', '-v'])
        self.assertEqual(run.call_args_list[1].args[0],
                         ['sudo', '-n', 'bash', str(onboard.SOURCE / 'deploy/setup-git.sh'), '--list'])
        for payload in ('{}', '[]', 'not-json', '{"result":{"protocol":"bad","repositories":[]}}'):
            with patch.object(onboard, 'run', return_value=subprocess.CompletedProcess([], 0, payload)), \
                    self.assertRaisesRegex(ValueError, 'registration list is invalid'):
                onboard.read_registrations({})

    def test_unavailable_registration_list_never_defaults_to_empty(self):
        with patch.object(onboard, 'run', return_value=subprocess.CompletedProcess([], 1, '')):
            with self.assertRaises(ValueError):
                onboard.read_registrations({})

    def test_existing_custom_registration_preserves_all_settings_and_remote(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            (path / '.git').mkdir()
            account = SimpleNamespace(pw_name='owner', pw_dir=folder)
            url = 'https://github.com/owner/lab.git'
            binding = {'id': 'one', 'path': str(path), 'owner': 'owner', 'remote': 'lab-origin',
                       'prefix': 'labs/bgp', 'label': 'My BGP lab', 'branch': 'lab-progress',
                       'push_url': url, 'revision': 'keep-this-revision'}
            with patch.object(onboard, 'run', return_value=subprocess.CompletedProcess([], 0, url)) as run:
                chosen, chosen_url, selected = onboard.choose_checkout(account, folder, {}, [binding])
            self.assertEqual((chosen, chosen_url, selected), (path, url, binding))
            run.assert_called_once_with(['git', 'remote', 'get-url', '--push', 'lab-origin'], {}, path)
            def registration_run(args, *unused, **kwargs):
                return subprocess.CompletedProcess(args, 0, url if args[1] == 'remote' else 'lab-progress')
            with patch.object(onboard, 'read_registrations', return_value=[binding]), \
                    patch.object(onboard, 'run', side_effect=registration_run) as run:
                onboard.register_checkout(account, path, {}, selected)
            self.assertEqual(run.call_args.args[0][-6:],
                             ['--remote', 'lab-origin', '--prefix', 'labs/bgp', '--label', 'My BGP lab'])

    def test_registered_owner_and_changed_branch_cannot_be_silently_rebound(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            (path / '.git').mkdir()
            account = SimpleNamespace(pw_name='owner', pw_dir=folder)
            binding = {'path': str(path), 'owner': 'another-user'}
            with self.assertRaisesRegex(ValueError, 'another Linux owner'):
                onboard.selected_registration(account, path, [binding])
            url = 'https://github.com/owner/lab.git'
            binding = {'remote': 'origin', 'branch': 'main'}
            def run(args, *unused, **kwargs):
                return subprocess.CompletedProcess(args, 0, url if args[1] == 'remote' else 'other-branch')
            with patch.object(onboard, 'run', side_effect=run), self.assertRaisesRegex(ValueError, 'registered branch'):
                onboard.check_checkout(path, url, {}, binding)

    def test_existing_registration_or_remote_changed_after_review_blocks_write(self):
        binding = {'id': 'one', 'remote': 'origin', 'branch': 'main', 'push_url': 'https://github.com/a/b.git',
                   'revision': 'original'}
        changed = dict(binding, revision='changed')
        with patch.object(onboard, 'read_registrations', return_value=[changed]), \
                patch.object(onboard, 'run') as run, self.assertRaisesRegex(ValueError, 'registration changed'):
            onboard.register_checkout(SimpleNamespace(pw_name='owner'), Path('/lab'), {}, binding)
        run.assert_not_called()
        with patch.object(onboard, 'read_registrations', return_value=[binding]), \
                patch.object(onboard, 'run', return_value=subprocess.CompletedProcess([], 0, 'https://github.com/a/different.git')) as run, \
                self.assertRaisesRegex(ValueError, 'push URL changed'):
            onboard.register_checkout(SimpleNamespace(pw_name='owner'), Path('/lab'), {}, binding)
        self.assertFalse(any(call.args[0][0] == 'sudo' for call in run.call_args_list))

    def test_multiple_prefixes_require_explicit_selection(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            (path / '.git').mkdir()
            bindings = [{'path': str(path), 'owner': 'owner', 'label': name, 'prefix': prefix,
                         'remote': 'origin', 'branch': 'main'}
                        for name, prefix in [('Lab A', 'a'), ('Lab B', 'b')]]
            with patch.object(onboard, 'menu', return_value='2') as menu:
                selected = onboard.selected_registration(SimpleNamespace(pw_name='owner'), path, bindings)
            self.assertEqual(selected['prefix'], 'b')
            self.assertNotIn('default', menu.call_args.kwargs)

    def test_source_directory_cannot_be_selected_as_config_checkout(self):
        with self.assertRaisesRegex(ValueError, 'manager source directory'):
            onboard.choose_checkout(SimpleNamespace(pw_name='owner'), str(onboard.SOURCE), {})

    def test_registered_checkout_reuses_saved_path_without_typing(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            (path / '.git').mkdir()
            url = 'https://github.com/owner/lab.git'
            binding = {'path': str(path), 'owner': 'owner', 'label': 'My lab', 'remote': 'origin',
                       'branch': 'main', 'prefix': '', 'push_url': url}
            with patch.object(onboard, 'menu', return_value='registered') as menu, \
                    patch.object(onboard, 'ask') as ask, \
                    patch.object(onboard, 'run', return_value=subprocess.CompletedProcess([], 0, url)):
                chosen, _, selected = onboard.choose_checkout(SimpleNamespace(pw_name='owner'), None, {}, [binding])
            self.assertEqual(chosen, path)
            self.assertEqual(selected, binding)
            self.assertEqual(menu.call_args.args[2], 'registered')
            ask.assert_not_called()

    def test_root_or_restricted_owner_never_runs_git_or_sudo(self):
        account = SimpleNamespace(pw_name='clab-discovery', pw_dir='/home/clab-discovery')
        with patch.dict('sys.modules', {'pwd': SimpleNamespace(getpwuid=lambda uid: account)}), \
                patch.object(onboard.sys.stdin, 'isatty', return_value=True), \
                patch.object(onboard, 'run') as run:
            with patch.object(onboard.os, 'geteuid', return_value=0, create=True), self.assertRaisesRegex(ValueError, 'without sudo'):
                onboard.main([])
            with patch.object(onboard.os, 'geteuid', return_value=1000, create=True), self.assertRaisesRegex(ValueError, 'restricted'):
                onboard.main([])
        run.assert_not_called()

    def test_registration_retry_keeps_completed_checkout_and_identity(self):
        with tempfile.TemporaryDirectory() as folder:
            account = SimpleNamespace(pw_name='owner', pw_dir=folder)
            path = Path(folder)
            (path / '.git').mkdir()
            binding = {'remote': 'origin', 'prefix': '', 'label': 'lab', 'branch': '', 'push_url': ''}
            with patch.dict('sys.modules', {'pwd': SimpleNamespace(getpwuid=lambda uid: account)}), \
                    patch.object(onboard.os, 'geteuid', return_value=1000, create=True), \
                    patch.object(onboard.sys.stdin, 'isatty', return_value=True), \
                    patch.object(onboard.Path, 'is_file', return_value=True), \
                    patch.object(onboard.shutil, 'which', return_value='/usr/bin/git'), \
                    patch.object(onboard, 'read_registrations', return_value=[]), \
                    patch.object(onboard, 'choose_checkout', return_value=(path, 'https://github.com/a/b.git', binding)), \
                    patch.object(onboard, 'github_login') as login, \
                    patch.object(onboard, 'check_checkout') as checkout, \
                    patch.object(onboard, 'identity') as identity, \
                    patch.object(onboard, 'check_permission'), \
                    patch.object(onboard, 'confirm', return_value=True), \
                    patch.object(onboard, 'menu', return_value='retry'), \
                    patch.object(onboard, 'register_checkout', side_effect=[ValueError('Network down'), None]) as register:
                self.assertEqual(onboard.main([]), 0)
            login.assert_called_once()
            checkout.assert_called_once()
            identity.assert_called_once()
            self.assertEqual(register.call_count, 2)
            self.assertTrue((path / '.git').is_dir())

    def test_cancel_after_completed_clone_returns_deferred_and_resume_path(self):
        with tempfile.TemporaryDirectory() as folder:
            account = SimpleNamespace(pw_name='owner', pw_dir=folder)
            path = Path(folder)
            (path / '.git').mkdir()
            with patch.dict('sys.modules', {'pwd': SimpleNamespace(getpwuid=lambda uid: account)}), \
                    patch.object(onboard.os, 'geteuid', return_value=1000, create=True), \
                    patch.object(onboard.sys.stdin, 'isatty', return_value=True), \
                    patch.object(onboard.Path, 'is_file', return_value=True), \
                    patch.object(onboard.shutil, 'which', return_value='/usr/bin/git'), \
                    patch.object(onboard, 'read_registrations', return_value=[]), \
                    patch.object(onboard, 'choose_checkout', return_value=(path, 'https://github.com/a/b.git', {})), \
                    patch.object(onboard, 'github_login'), patch.object(onboard, 'check_checkout'), \
                    patch.object(onboard, 'identity', side_effect=KeyboardInterrupt), \
                    patch.object(onboard, 'register_checkout') as register, patch('builtins.print') as output:
                self.assertEqual(onboard.main([]), 2)
            register.assert_not_called()
            self.assertIn('--guided --repo', output.call_args.args[0])
            self.assertIn(str(path), output.call_args.args[0])
            self.assertTrue((path / '.git').is_dir())

    def test_package_repair_requires_explicit_confirmation(self):
        for confirmed in (False, True):
            action = unittest.mock.Mock(side_effect=[onboard.PackageSourceError('APT update failed'), None])
            with patch.object(onboard, 'menu', return_value='repair'), \
                    patch.object(onboard, 'confirm', return_value=confirmed), patch.object(onboard, 'run') as run:
                onboard.step(1, 'Git', action, {})
            self.assertEqual(run.call_count, int(confirmed))
            if confirmed:
                self.assertEqual(run.call_args.args[0],
                                 ['sudo', 'python3', str(onboard.SOURCE / 'deploy/apt_sources.py'), '--repair'])

    def test_failed_apt_update_stops_before_install_or_login(self):
        with patch.object(onboard, 'run', return_value=subprocess.CompletedProcess([], 100)) as run:
            with self.assertRaisesRegex(ValueError, 'file:/cdrom') as error:
                onboard.install_package('gh', {})
        self.assertIn('GIT-SETUP.md', str(error.exception))
        self.assertIn('clock', str(error.exception))
        self.assertEqual([call.args[0] for call in run.call_args_list],
                         [['sudo', '/usr/bin/python3', str(onboard.SOURCE / 'deploy/apt_update.py')]])

    def test_package_install_failure_has_distinct_recovery(self):
        results = [subprocess.CompletedProcess([], 0), subprocess.CompletedProcess([], 100)]
        with patch.object(onboard, 'run', side_effect=results), self.assertRaisesRegex(ValueError, 'could not install gh'):
            onboard.install_package('gh', {})

    def test_successful_package_install_keeps_interactive_sudo(self):
        for package in ('git', 'gh'):
            env = onboard.service_env('owner', '/home/owner')
            with patch.object(onboard, 'run', return_value=subprocess.CompletedProcess([], 0)) as run:
                onboard.install_package(package, env)
            self.assertEqual([call.args[0] for call in run.call_args_list],
                             [['sudo', '/usr/bin/python3', str(onboard.SOURCE / 'deploy/apt_update.py')],
                              ['sudo', 'apt-get', 'install', '-y', package]])
            self.assertTrue(all(call.kwargs['interactive'] for call in run.call_args_list))
            self.assertTrue(all(call.args[1] == env for call in run.call_args_list))

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
