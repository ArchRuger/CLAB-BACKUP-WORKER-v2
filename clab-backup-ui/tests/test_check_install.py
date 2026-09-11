import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError


spec = importlib.util.spec_from_file_location('check_install', Path(__file__).resolve().parents[2] / 'deploy/check_install.py')
check = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = check
spec.loader.exec_module(check)

VERSION = '1.16.2'
PRIVATE = 'PRIVATE-PASSWORD-TOKEN-DO-NOT-PRINT'
ROOT = '/etc/containerlab'


def context(**overrides):
    args = check.arguments([])
    for key, value in overrides.items():
        setattr(args, key, value)
    ctx = check.Context(args, owner='archtop', privileged=True)
    ctx.version = VERSION
    ctx.container = 'a' * 64
    ctx.base_url = 'http://127.0.0.1:8081'
    ctx.trusted_helpers = {'inspect': True, 'operate': True, 'git': True}
    ctx.run = Mock(return_value=check.Result(reason='unexpected command'))
    return ctx


def encoded(value):
    return check.Result(0, json.dumps(value))


def capabilities():
    return {'result': {'protocol': 'clab-manager-operations-v1', 'version': VERSION,
                       'network': False, 'actions': {name: {'available': True}
                       for name in ('deploy', 'destroy', 'inspect')}}}


def discovery():
    return {'configured': True, 'connected': True,
            'host': {'enabled': True, 'fingerprint': 'public-host-fingerprint', 'address': '127.0.0.1',
                     'auth': 'password', 'command_mode': 'helper', 'username': 'clab-discovery'}}


def browse_router(folders=None, discovery_value=None):
    folders = folders or {ROOT: []}

    def request(path, payload=None, **kwargs):
        if path == '/api/discovery':
            return check.Result(0), discovery() if discovery_value is None else discovery_value
        if path == '/api/operations/browse':
            target = payload['path']
            if target == '':
                return check.Result(0), {'path': '', 'entries': [{'path': ROOT, 'directory': True}]}
            if target not in folders:
                return check.Result(503, reason='HTTP 503'), None
            return check.Result(0), {'path': target, 'entries': folders[target]}
        if path == '/api/git/repositories':
            return check.Result(0), {'repositories': [], 'protocol': 'clab-manager-git-v1', 'version': VERSION}
        return check.Result(reason='unexpected route'), None
    return request


def by_id(ctx, ident):
    return next(record for record in ctx.checks if record['id'] == ident)


class InstallationCheckTests(unittest.TestCase):
    def test_root_capabilities_do_not_mask_failed_restricted_gateway(self):
        ctx = context()

        def helper(_ctx, kind, request=None, delegated=True, **kwargs):
            if kind == 'inspect':
                return encoded({'protocol': 'clab-manager-files-v1', 'helper_version': VERSION,
                                'inspect': {}, 'sources': {}})
            if delegated:
                return check.Result(1, PRIVATE, stderr=PRIVATE)
            return encoded(capabilities())

        with patch.object(check, 'helper_request', side_effect=helper):
            check.check_helpers(ctx)
        record = by_id(ctx, 'operations-helper')
        self.assertEqual(record['status'], 'FAIL')
        self.assertIn('root', record['detail'])
        self.assertIn('clab-discovery', record['detail'])
        self.assertNotIn(PRIVATE, check.render(check.summarize(ctx)))

    def test_missing_operations_is_explicitly_optional_only_in_discovery_mode(self):
        ctx = context(discovery_only=True)
        with patch.object(check, 'helper_request', return_value=check.Result(1)):
            check.check_helpers(ctx)
        self.assertEqual(by_id(ctx, 'operations-helper')['status'], 'INFO')

    def test_negative_operation_capability_and_old_helper_version_fail(self):
        for change in ('negative', 'version'):
            with self.subTest(change=change):
                ctx = context()
                caps = capabilities()
                if change == 'negative':
                    caps['result']['actions']['deploy']['available'] = False
                else:
                    caps['result']['version'] = '0.0.0'
                with patch.object(check, 'helper_request', return_value=encoded(caps)):
                    check.check_helpers(ctx)
                record = by_id(ctx, 'operations-actions' if change == 'negative' else 'operations-helper')
                self.assertEqual(record['status'], 'FAIL')

    def test_invalid_helper_json_never_passes(self):
        ctx = context()
        with patch.object(check, 'helper_request', return_value=check.Result(0, PRIVATE)):
            check.check_helpers(ctx)
        self.assertEqual(by_id(ctx, 'discovery-helper')['status'], 'FAIL')
        self.assertEqual(by_id(ctx, 'operations-helper')['status'], 'FAIL')
        self.assertNotIn(PRIVATE, json.dumps(check.summarize(ctx)))

    def test_successful_root_browse_does_not_mask_failed_child_folder(self):
        ctx = context()
        child = ROOT + '/vJunOS-SW'
        ctx.http = Mock(side_effect=browse_router({ROOT: [{'path': child, 'directory': True}]}))
        check.check_manager_routes(ctx)
        self.assertEqual(by_id(ctx, 'http-browse')['status'], 'PASS')
        failure = next(row for row in ctx.checks if row['title'] == 'Browse folder: ' + child)
        self.assertEqual(failure['status'], 'FAIL')
        self.assertIn('setup-operations.sh', failure['fix'])
        self.assertEqual(check.summarize(ctx)['exit_code'], 1)

    def test_empty_trusted_folder_is_healthy_and_only_read_routes_are_called(self):
        ctx = context()
        ctx.http = Mock(side_effect=browse_router())
        check.check_manager_routes(ctx)
        self.assertEqual(by_id(ctx, 'folder-1')['status'], 'PASS')
        self.assertIn('empty folders are valid', by_id(ctx, 'folder-1')['detail'])
        allowed = {'/api/discovery', '/api/operations/browse', '/api/git/repositories'}
        for call in ctx.http.call_args_list:
            self.assertIn(call.args[0], allowed)
            if call.args[0] == '/api/operations/browse':
                self.assertEqual(set(call.args[1]), {'path'})
            else:
                self.assertEqual(len(call.args), 1)
        self.assertFalse(any(row['status'] == 'FAIL' for row in ctx.checks))

    def test_missing_vm_setup_warns_and_skips_live_operations(self):
        for host in (None, {}):
            ctx = context()
            ctx.http = Mock(side_effect=browse_router(discovery_value={'configured': False, 'host': host}))
            check.check_manager_routes(ctx)
            self.assertEqual(by_id(ctx, 'vm-connection')['status'], 'WARN')
            self.assertEqual(by_id(ctx, 'http-browse')['status'], 'SKIP')
            self.assertEqual(len(ctx.http.call_args_list), 1)

    def test_git_route_is_checked_even_when_operations_are_unavailable(self):
        ctx = context()
        ctx.trusted_helpers['operate'] = False
        ctx.http = Mock(side_effect=browse_router())
        check.check_manager_routes(ctx)
        check.check_git_route(ctx)
        self.assertEqual(by_id(ctx, 'http-browse')['status'], 'SKIP')
        self.assertEqual(by_id(ctx, 'git-http')['status'], 'PASS')
        self.assertEqual([call.args[0] for call in ctx.http.call_args_list], ['/api/discovery', '/api/git/repositories'])

    def test_git_route_protocol_and_version_are_required(self):
        for payload in ({'repositories': []},
                        {'repositories': [], 'protocol': 'clab-manager-git-v1', 'version': '0.0.0'},
                        {'repositories': PRIVATE, 'protocol': 'clab-manager-git-v1', 'version': VERSION}):
            ctx = context(require_git=True)
            ctx.host = discovery()['host']
            ctx.http = Mock(return_value=(check.Result(0), payload))
            check.check_git_route(ctx)
            self.assertEqual(by_id(ctx, 'git-http')['status'], 'FAIL')
            ctx.http.assert_called_once_with('/api/git/repositories')
            self.assertNotIn(PRIVATE, check.render(check.summarize(ctx)))

    def test_untrusted_helper_cannot_be_executed_or_reached_over_http(self):
        ctx = context(require_git=True)
        ctx.trusted_helpers = {'inspect': False, 'operate': False, 'git': False}
        result = check.helper_request(ctx, 'operate', {'mode': 'capabilities'})
        self.assertFalse(result.ok)
        ctx.run.assert_not_called()
        ctx.host = discovery()['host']
        ctx.http = Mock()
        check.check_git_route(ctx)
        ctx.http.assert_not_called()
        self.assertEqual(by_id(ctx, 'git-http')['status'], 'SKIP')

    def test_installed_helper_paths_match_setup_scripts_and_stale_code_blocks_execution(self):
        # The inspect payload deliberately retains its historical installed filename.
        # Using host_files.py at that destination would fail every real installation.
        layout = {
            '/usr/local/sbin/clab-manager-gateway': ('deploy/clab-manager-gateway', 0o755),
            '/usr/local/sbin/clab-manager-inspect': (None, 0o755),
            '/usr/local/lib/clab-manager/clab_manager_files.py': ('clab-backup-ui/app/host_files.py', 0o644),
            '/etc/sudoers.d/clab-manager-discovery': (None, 0o440),
            '/usr/local/sbin/clab-manager-operate': (None, 0o755),
            '/usr/local/lib/clab-manager/host_operations.py': ('clab-backup-ui/app/host_operations.py', 0o644),
            '/etc/clab-manager/operations.json': (None, 0o600),
            '/usr/local/sbin/clab-manager-git': (None, 0o755),
            '/usr/local/lib/clab-manager/host_git.py': ('clab-backup-ui/app/host_git.py', 0o644),
            '/etc/sudoers.d/clab-manager-git': (None, 0o440),
        }
        for stale in (False, True):
            ctx = context()
            payload = [{'path': path, 'safe': True, 'mode': mode,
                        'sha256': hashlib.sha256((ctx.source / source).read_bytes()).hexdigest() if source else ''}
                       for path, (source, mode) in layout.items()]
            if stale:
                next(row for row in payload if row['path'].endswith('/host_operations.py'))['sha256'] = 'old-code'
            ctx.run = Mock(side_effect=[encoded(payload), check.Result(0)])
            check.check_helper_files(ctx)
            self.assertEqual(by_id(ctx, 'helper-files-inspect')['status'], 'PASS')
            self.assertEqual(by_id(ctx, 'helper-files-operate')['status'], 'FAIL' if stale else 'PASS')
            self.assertEqual(ctx.trusted_helpers['operate'], not stale)
            self.assertEqual(by_id(ctx, 'sudoers')['status'], 'PASS')

    def test_manager_unavailable_does_not_report_connection_success(self):
        ctx = context()
        ctx.base_url = ''
        ctx.http = Mock()
        check.check_manager_routes(ctx)
        self.assertEqual(by_id(ctx, 'vm-connection')['status'], 'SKIP')
        ctx.http.assert_not_called()

    def test_folder_budget_prioritizes_explicit_problem_path_and_reports_remaining(self):
        problem = ROOT + '/vJunOS-SW'
        ctx = context(lab_path=[problem], max_folders=1)
        ctx.http = Mock(side_effect=browse_router({problem: [], ROOT: []}))
        check.check_manager_routes(ctx)
        paths = [call.args[1]['path'] for call in ctx.http.call_args_list if call.args[0] == '/api/operations/browse']
        self.assertEqual(paths, ['', problem])
        self.assertEqual(by_id(ctx, 'folder-budget')['status'], 'WARN')

    def test_folder_traversal_does_not_follow_malformed_or_nonchild_paths(self):
        entries = [{'path': '/etc/passwd', 'directory': True},
                   {'path': ROOT + '/../escape', 'directory': True},
                   {'path': ROOT + '/\x00bad', 'directory': True},
                   {'path': ROOT + '/lab.clab.yml', 'directory': False}]
        ctx = context()
        ctx.http = Mock(side_effect=browse_router({ROOT: entries}))
        check.check_manager_routes(ctx)
        paths = [call.args[1]['path'] for call in ctx.http.call_args_list if call.args[0] == '/api/operations/browse']
        self.assertEqual(paths, ['', ROOT])

    def test_wrong_folder_response_path_fails_instead_of_claiming_listed(self):
        ctx = context()
        responses = [(check.Result(0), discovery()),
                     (check.Result(0), {'entries': [{'directory': True, 'path': ROOT}]}),
                     (check.Result(0), {'path': '/different', 'entries': []}),
                     (check.Result(0), {'repositories': []})]
        ctx.http = Mock(side_effect=responses)
        check.check_manager_routes(ctx)
        self.assertEqual(by_id(ctx, 'folder-1')['status'], 'FAIL')

    def test_inspection_with_no_deployed_labs_is_valid(self):
        ctx = context()
        ctx.run = Mock(side_effect=[check.Result(0, 'containerlab version'), encoded({})])
        check.check_containerlab(ctx)
        self.assertEqual(by_id(ctx, 'labs')['status'], 'PASS')
        self.assertIn('No deployed labs is normal', by_id(ctx, 'labs')['detail'])
        for call in ctx.run.call_args_list:
            self.assertNotIn('deploy', call.args[0])
            self.assertNotIn('destroy', call.args[0])

    def test_invalid_containerlab_inventory_is_not_empty_success(self):
        for data in (None, {'lab': 'private'}, [None]):
            ctx = context()
            ctx.run = Mock(side_effect=[check.Result(0), encoded(data)])
            check.check_containerlab(ctx)
            self.assertEqual(by_id(ctx, 'labs')['status'], 'FAIL')

    def test_persistent_storage_requires_mount_key_and_successful_decryption(self):
        healthy = {'path': '/data', 'uid': 10001, 'writable': True, 'key': True,
                   'state': True, 'decryptable': True, 'untrusted': PRIVATE}
        mount = {'Destination': '/data', 'Type': 'bind', 'RW': True}
        cases = [(healthy, [mount], 'PASS'), (healthy, [], 'FAIL'),
                 (dict(healthy, key=False), [mount], 'FAIL'),
                 (dict(healthy, decryptable=False), [mount], 'FAIL'),
                 (dict(healthy, writable=False), [mount], 'FAIL'),
                 (dict(healthy, uid=0), [mount], 'FAIL'),
                 (healthy, [dict(mount, RW=False)], 'FAIL')]
        for value, mounts, expected in cases:
            with self.subTest(value=value, mounts=mounts):
                ctx = context()
                ctx.run = Mock(return_value=encoded(value))
                check.check_storage(ctx, ['docker', '--host', 'unix:///var/run/docker.sock'], mounts)
                self.assertEqual(by_id(ctx, 'storage')['status'], expected)
                self.assertNotIn(PRIVATE, json.dumps(check.summarize(ctx)))

    def test_storage_malformed_or_failed_probe_fails(self):
        for result in (check.Result(1, PRIVATE), check.Result(0, PRIVATE), encoded([])):
            ctx = context()
            ctx.run = Mock(return_value=result)
            check.check_storage(ctx, ['docker'], [])
            self.assertEqual(by_id(ctx, 'storage')['status'], 'FAIL')

    def test_running_source_mismatch_and_stopped_or_missing_manager(self):
        for condition in ('healthy', 'missing', 'stopped', 'old-version', 'invalid-metadata'):
            with self.subTest(condition=condition):
                ctx = context()
                metadata = {'state': {'Running': condition != 'stopped'}, 'mounts': [],
                            'command': ['uvicorn', 'app.main:create_app', '--host', '0.0.0.0', '--port', '8081'],
                            'network': 'host', 'restart': 'unless-stopped'}

                def command(args, **kwargs):
                    if 'info' in args or args[-1] == 'version':
                        return check.Result(0)
                    if 'ps' in args:
                        return check.Result(0, '' if condition == 'missing' else 'a' * 64)
                    if 'inspect' in args:
                        return check.Result(0, PRIVATE) if condition == 'invalid-metadata' else encoded(metadata)
                    if 'exec' in args and args[-1] == 'from app import __version__; print(__version__)':
                        return check.Result(0, '0.0.0' if condition == 'old-version' else VERSION)
                    return check.Result(reason='unexpected read command')

                ctx.run = Mock(side_effect=command)
                ctx.http = Mock(return_value=(check.Result(0), {'version': VERSION, 'private': PRIVATE}))
                with patch.object(check, 'check_storage'):
                    check.check_docker(ctx)
                ident = 'manager-version' if condition == 'old-version' else 'manager'
                self.assertEqual(by_id(ctx, ident)['status'], 'PASS' if condition == 'healthy' else 'FAIL')
                if condition in ('missing', 'stopped', 'invalid-metadata'):
                    ctx.http.assert_not_called()
                self.assertNotIn(PRIVATE, check.render(check.summarize(ctx)))

    def test_daemon_failure_prevents_http_or_container_claims(self):
        ctx = context()
        ctx.run = Mock(return_value=check.Result(1, PRIVATE))
        ctx.http = Mock()
        check.check_docker(ctx)
        self.assertEqual(by_id(ctx, 'docker')['status'], 'FAIL')
        self.assertEqual(by_id(ctx, 'manager')['status'], 'SKIP')
        ctx.http.assert_not_called()

    def test_mixed_source_release_is_failure_without_raw_exception_output(self):
        ctx = context()
        verifier = SimpleNamespace(verify=Mock(side_effect=ValueError(PRIVATE)))
        with patch.object(check, 'module', return_value=verifier):
            check.check_source(ctx)
        self.assertEqual(by_id(ctx, 'source')['status'], 'FAIL')
        self.assertNotIn(PRIVATE, check.render(check.summarize(ctx)))

    def test_exit_codes_and_manual_verification_remain_explicit(self):
        for statuses, code in ((['PASS'], 0), (['PASS', 'INFO'], 0), (['WARN'], 2),
                               (['SKIP'], 2), (['PASS', 'FAIL', 'WARN'], 1)):
            ctx = context()
            for index, status in enumerate(statuses):
                ctx.add(str(index), status, 'Example', 'Safe detail')
            report = check.summarize(ctx)
            self.assertEqual(report['exit_code'], code)
            rendered = check.render(report)
            self.assertIn('MANUAL VERIFICATION STILL REQUIRED', rendered)
            self.assertIn('WinSCP', rendered)
            self.assertIn('NOS', rendered)
            self.assertIn('push permission', rendered)
            self.assertEqual(report['counts']['PASS'], statuses.count('PASS'))

    def test_args_require_absolute_safe_lab_folder_and_bounded_work(self):
        args = check.arguments(['--lab-path', ROOT + '/vJunOS-SW', '--max-folders', '1'])
        self.assertEqual(args.lab_path, [ROOT + '/vJunOS-SW'])
        for argv in (['--lab-path', 'relative'], ['--lab-path', '/etc/../root'],
                     ['--lab-path', '/bad\npath'], ['--max-folders', '0'], ['--max-folders', '501'],
                     ['--deadline', '29'], ['--deadline', '1801']):
            with self.subTest(argv=argv), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
                check.arguments(argv)
            self.assertEqual(raised.exception.code, 2)

    def test_http_errors_and_malformed_json_discard_private_bodies(self):
        ctx = context()
        for body in (b'{invalid', PRIVATE.encode()):
            response = io.BytesIO(body)
            opener = Mock()
            opener.open.return_value = response
            with patch.object(check, 'build_opener', return_value=opener):
                result, data = ctx.http('/api/state')
            self.assertFalse(result.ok)
            self.assertIsNone(data)
            self.assertNotIn(PRIVATE, result.reason)
        failure = HTTPError('http://127.0.0.1:8081/' + PRIVATE, 500, PRIVATE, {}, io.BytesIO(PRIVATE.encode()))
        with patch.object(check, 'build_opener', return_value=SimpleNamespace(open=Mock(side_effect=failure))):
            result, data = ctx.http('/api/operations/browse', {'path': ROOT})
        self.assertEqual(result.reason, 'HTTP 500')
        self.assertIsNone(data)

    def test_http_response_size_and_report_deadline_are_bounded(self):
        ctx = context()
        response = io.BytesIO(b' ' * 17)
        response.read1 = Mock(wraps=response.read1)
        opener = Mock(open=Mock(return_value=response))
        with patch.object(check, 'build_opener', return_value=opener):
            result, data = ctx.http('/api/state', limit=16)
        self.assertFalse(result.ok)
        response.read1.assert_called_once_with(17)
        ctx.deadline = 0
        with patch.object(check, 'build_opener') as network:
            result, data = ctx.http('/api/state')
        network.assert_not_called()
        self.assertIn('time limit', result.reason)

    def test_main_keeps_reporting_after_failed_group_without_printing_exception(self):
        output = io.StringIO()
        modules = SimpleNamespace(check_host=Mock(side_effect=RuntimeError(PRIVATE)),
                                  check_git=Mock(side_effect=lambda ctx: ctx.add('last', 'PASS', 'Last group', 'Completed')))
        account = SimpleNamespace(pw_uid=1000, pw_name='archtop')
        fake_pwd = SimpleNamespace(getpwnam=lambda _: account)
        functions = ('check_source', 'check_docker', 'check_containerlab', 'check_helper_files',
                     'check_helpers', 'check_manager_routes', 'check_git_route')
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(check.sys, 'platform', 'linux'))
            stack.enter_context(patch.object(check.os, 'geteuid', create=True, return_value=0))
            stack.enter_context(patch.object(check.Context, 'run', return_value=check.Result(0)))
            stack.enter_context(patch.dict(sys.modules, {'pwd': fake_pwd}))
            stack.enter_context(patch.object(check, 'module', return_value=modules))
            for name in functions:
                stack.enter_context(patch.object(check, name))
            stack.enter_context(contextlib.redirect_stdout(output))
            stack.enter_context(contextlib.redirect_stderr(io.StringIO()))
            code = check.main(['--json', '--owner', 'archtop'])
        report = json.loads(output.getvalue())
        self.assertEqual(code, 1)
        self.assertTrue(any(row['id'] == 'last' for row in report['checks']))
        self.assertTrue(any(row['status'] == 'FAIL' for row in report['checks']))
        self.assertNotIn(PRIVATE, output.getvalue())

    def test_watchdog_kills_descendant_group_after_leader_already_exited(self):
        ctx = check.Context(check.arguments([]), owner='archtop', privileged=True)
        process = Mock(pid=12345, stdin=None)
        process.poll.return_value = 0  # The original command has exited already.
        process.wait.return_value = 0
        callbacks = []
        timer = Mock()

        def make_timer(duration, callback):
            callbacks.append(callback)
            return timer

        def held_stdout(_size):
            # A descendant still owns stdout. The deadline must signal its process
            # group even though polling the original leader reports exit success.
            self.assertEqual(process.poll(), 0)
            callbacks[0]()
            kill.assert_called_with(process.pid, 9)
            return b'partial output\n'

        process.stdout.read.side_effect = held_stdout
        with patch.object(check.os, 'geteuid', create=True, return_value=0), \
                patch.object(check.os, 'killpg', create=True) as kill, \
                patch.object(check.signal, 'SIGKILL', create=True, new=9), \
                patch.object(check.subprocess, 'Popen', return_value=process), \
                patch.object(check.threading, 'Timer', side_effect=make_timer):
            result = ctx.run(['/usr/sbin/sshd', '-t'], privileged=True)
        self.assertFalse(result.ok)
        self.assertEqual(result.reason, 'command timed out')
        self.assertEqual(result.stdout, 'partial output\n')
        self.assertGreaterEqual(kill.call_count, 2)
        timer.cancel.assert_called_once()

    def test_privileged_command_has_root_timeout_and_caller_watchdog(self):
        ctx = check.Context(check.arguments([]), owner='archtop', privileged=True)
        ctx.deadline = 110
        process = Mock(pid=12345, stdin=None)
        process.wait.return_value = 0
        process.stdout.read.return_value = b''
        with patch.object(check.os, 'geteuid', create=True, return_value=1000), \
                patch.object(check.os, 'killpg', create=True, side_effect=PermissionError), \
                patch.object(check.signal, 'SIGKILL', create=True, new=9), \
                patch.object(check.time, 'monotonic', return_value=100), \
                patch.object(check.subprocess, 'Popen', return_value=process) as popen, \
                patch.object(check.threading, 'Timer') as timer:
            result = ctx.run(['/usr/sbin/sshd', '-t'], privileged=True, timeout=5)
        self.assertTrue(result.ok)
        self.assertEqual(popen.call_args.args[0], ['sudo', '-n', '--', '/usr/bin/timeout',
                                                 '--kill-after=2s', '5s', '/usr/sbin/sshd', '-t'])
        self.assertFalse(popen.call_args.kwargs.get('start_new_session', False))
        self.assertEqual(popen.call_args.kwargs['process_group'], 0)
        self.assertEqual(timer.call_args.args[0], 7)
        self.assertIs(popen.call_args.kwargs['stderr'], check.subprocess.DEVNULL)

    def test_helpers_begin_untrusted_until_installation_files_are_verified(self):
        ctx = check.Context(check.arguments([]), owner='archtop', privileged=True)
        ctx.run = Mock()
        self.assertEqual(ctx.trusted_helpers, {'inspect': False, 'operate': False, 'git': False})
        for helper in ('inspect', 'operate', 'git'):
            self.assertFalse(check.helper_request(ctx, helper).ok)
        ctx.run.assert_not_called()

    def test_initial_sudo_timeout_is_reported_without_aborting_remaining_checks(self):
        output = io.StringIO()
        modules = SimpleNamespace(check_host=Mock(), check_git=Mock())
        account = SimpleNamespace(pw_uid=1000, pw_name='archtop')
        functions = ('check_source', 'check_docker', 'check_containerlab', 'check_helper_files',
                     'check_helpers', 'check_manager_routes', 'check_git_route')
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(check.sys, 'platform', 'linux'))
            stack.enter_context(patch.object(check.os, 'geteuid', create=True, return_value=1000))
            stack.enter_context(patch.dict(sys.modules, {'pwd': SimpleNamespace(getpwnam=lambda _: account)}))
            sudo = stack.enter_context(patch.object(check.subprocess, 'run',
                                       side_effect=check.subprocess.TimeoutExpired('sudo', 15)))
            stack.enter_context(patch.object(check, 'module', return_value=modules))
            for name in functions:
                stack.enter_context(patch.object(check, name))
            stack.enter_context(contextlib.redirect_stdout(output))
            stack.enter_context(contextlib.redirect_stderr(io.StringIO()))
            code = check.main(['--json', '--owner', 'archtop'])
        report = json.loads(output.getvalue())
        self.assertEqual(code, 1)
        self.assertEqual(next(row for row in report['checks'] if row['id'] == 'privileges')['status'], 'FAIL')
        self.assertEqual(sudo.call_args.kwargs['timeout'], 15)
        modules.check_git.assert_not_called()
        self.assertTrue(any(row['status'] == 'SKIP' and row['title'] == 'Registered Git checkouts'
                            for row in report['checks']))

    def test_initial_sudo_success_cannot_mask_failed_query_runner(self):
        output = io.StringIO()
        account = SimpleNamespace(pw_uid=1000, pw_name='archtop')
        modules = SimpleNamespace(check_host=Mock(), check_git=Mock())
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(check.sys, 'platform', 'linux'))
            stack.enter_context(patch.object(check.os, 'geteuid', create=True, return_value=1000))
            stack.enter_context(patch.dict(sys.modules, {'pwd': SimpleNamespace(getpwnam=lambda _: account)}))
            stack.enter_context(patch.object(check.subprocess, 'run', return_value=SimpleNamespace(returncode=0)))
            runner = stack.enter_context(patch.object(check.Context, 'run', return_value=check.Result(1, PRIVATE)))
            stack.enter_context(patch.object(check, 'module', return_value=modules))
            docker = stack.enter_context(patch.object(check, 'check_docker'))
            stack.enter_context(patch.object(check, 'check_source'))
            stack.enter_context(contextlib.redirect_stdout(output))
            stack.enter_context(contextlib.redirect_stderr(io.StringIO()))
            code = check.main(['--json', '--owner', 'archtop'])
        report = json.loads(output.getvalue())
        self.assertEqual(code, 1)
        self.assertEqual(report['counts']['FAIL'], 1)
        self.assertEqual(next(row for row in report['checks'] if row['id'] == 'privileges')['status'], 'FAIL')
        self.assertTrue(any(row['status'] == 'SKIP' and row['title'] == 'Docker, manager and persistent storage'
                            for row in report['checks']))
        runner.assert_called_once_with(['/usr/bin/true'], privileged=True, timeout=5)
        docker.assert_not_called()
        modules.check_git.assert_not_called()
        self.assertNotIn(PRIVATE, output.getvalue())

    @unittest.skipUnless(sys.platform == 'linux', 'Requires a real Linux controlling terminal and process groups')
    def test_query_keeps_terminal_session_with_separate_watchdog_process_group(self):
        # sudo caches authentication by terminal AND session ID. Exercise an
        # actual PTY so a change back to setsid fails even without sudo installed.
        # No credentials, sudo policy, accounts or host services are changed.
        import pty
        import signal

        child, terminal = pty.fork()
        if child == 0:
            try:
                signal.alarm(10)
                session = os.getsid(0)
                group = os.getpgrp()
                ctx = check.Context(check.arguments([]), owner='test', privileged=False)
                script = ('import json,os; fd=os.open("/dev/tty",os.O_RDONLY); '
                          'print(json.dumps(dict(session=os.getsid(0),group=os.getpgrp(),pid=os.getpid()))); '
                          'os.close(fd)')
                result = ctx.run([sys.executable, '-c', script], timeout=3)
                value = json.loads(result.stdout) if result.ok else {}
                good = (result.ok and value.get('session') == session and value.get('group') != group
                        and value.get('group') == value.get('pid'))
                print(json.dumps({'ok': good, 'code': result.code, 'reason': result.reason}), flush=True)
                os._exit(0 if good else 1)
            except BaseException:
                os._exit(2)
        output = bytearray()
        try:
            while True:
                try:
                    part = os.read(terminal, 1024)
                except OSError:
                    break
                if not part:
                    break
                output.extend(part)
        finally:
            os.close(terminal)
            _, status = os.waitpid(child, 0)
        self.assertEqual(os.waitstatus_to_exitcode(status), 0, output.decode(errors='replace'))

    def test_http_open_and_body_share_one_absolute_deadline(self):
        ctx = context()
        ctx.deadline = 100
        clock = [0]
        sock = Mock()
        response = Mock(fp=SimpleNamespace(raw=SimpleNamespace(_sock=sock)))
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)

        def slow_body(_size):
            clock[0] += 5
            return b'{"version":"1.16.2"}'

        response.read1.side_effect = slow_body

        def slow_open(_request, timeout):
            self.assertEqual(timeout, 20)
            clock[0] += 19
            return response

        opener = SimpleNamespace(open=Mock(side_effect=slow_open))
        with patch.object(check.time, 'monotonic', side_effect=lambda: clock[0]), \
                patch.object(check, 'build_opener', return_value=opener):
            result, value = ctx.http('/api/state')
        self.assertFalse(result.ok)
        self.assertIsNone(value)
        self.assertEqual(result.reason, 'HTTP request time limit reached')
        sock.settimeout.assert_called_once_with(1)
        self.assertEqual(response.read1.call_count, 1)


if __name__ == '__main__':
    unittest.main()
