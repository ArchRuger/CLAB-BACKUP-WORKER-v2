import contextlib
import hashlib
import http.server
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import ssl
import subprocess
import sys
import tempfile
import threading
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
    ctx.base_url = 'https://127.0.0.1:8443'
    ctx.tls_context = object()  # a stand-in for the pinned context: the opener is mocked
    ctx.trusted_helpers = {'inspect': True, 'operate': True, 'git': True}
    ctx.run = Mock(return_value=check.Result(reason='unexpected command'))
    return ctx


def guarded_http():
    """The one HTTP question of the health check (EXPOSURE 6.1 rule 1): GET /api/health, nothing else."""
    def request(path, payload=None, **kwargs):
        assert path == '/api/health' and payload is None, 'the health check asked the manager ' + path
        return check.Result(0), {'ready': True}
    return Mock(side_effect=request)


def encoded(value):
    return check.Result(0, json.dumps(value))


def capabilities():
    return {'result': {'protocol': 'clab-manager-operations-v1', 'version': VERSION,
                       'network': False, 'actions': {name: {'available': True}
                       for name in ('deploy', 'destroy', 'inspect')}}}


def discovery():
    return {'configured': True, 'connected': True,
            'host': {'enabled': True, 'fingerprint_saved': True, 'address': '127.0.0.1', 'port': 22,
                     'auth': 'password', 'command_mode': 'helper', 'username': 'clab-discovery'},
            'checked_at': '2026-11-01T10:00:00+00:00'}


def git_registry(**changes):
    return dict({'protocol': 'clab-manager-git-v1', 'version': VERSION, 'repositories': 0, 'bound_labs': 0}, **changes)


def engine(**changes):
    return dict({'available': True, 'version': '26.9', 'path': '/usr/local/bin/netlab', 'diagnostic': ''}, **changes)


def probe_router(folders=None, discovery_value=None, engine_value=None, git_value=None, capture_value=None):
    """ctx.probe routed on the probe name, the way the tests used to route ctx.http on the path (EXPOSURE 6.3, case 10)."""
    folders = folders or {ROOT: []}

    def probe(name, *args):
        if name == 'vm-connection':
            assert not args
            return (discovery() if discovery_value is None else discovery_value), False
        if name == 'browse':
            assert len(args) == 1, 'a browse probe carries exactly one path'
            target = args[0]
            if target == '':
                return {'path': '', 'entries': [{'name': 'containerlab', 'path': ROOT, 'directory': True}]}, False
            if target not in folders:
                return {'error': 'The folder could not be listed.'}, False
            return {'path': target, 'entries': folders[target]}, False
        if name == 'git-registry':
            assert not args
            return (git_registry() if git_value is None else git_value), False
        if name == 'design-engine':
            return (engine() if engine_value is None else engine_value), False
        if name == 'capture':
            return capture_value, False
        raise AssertionError('unexpected probe ' + name)
    return probe


def browsed(ctx):
    return [call.args[1] for call in ctx.probe.call_args_list if call.args[0] == 'browse']


def by_id(ctx, ident):
    return next(record for record in ctx.checks if record['id'] == ident)


class DesignEngineCheckTests(unittest.TestCase):
    def test_an_available_engine_passes_with_its_version(self):
        ctx = context()
        ctx.probe = Mock(side_effect=probe_router())
        check.check_design_engine(ctx)
        row = by_id(ctx, 'design-engine')
        self.assertEqual(row['status'], 'PASS'); self.assertIn('netlab 26.9', row['detail'])
        ctx.probe.assert_called_once_with('design-engine')

    def test_a_missing_engine_warns_with_the_managers_diagnostic_and_keeps_the_rest(self):
        ctx = context()
        ctx.probe = Mock(side_effect=probe_router(engine_value=engine(available=False, version='', path='', diagnostic='netlab is not installed in the image')))
        check.check_design_engine(ctx)
        row = by_id(ctx, 'design-engine')
        self.assertEqual(row['status'], 'WARN'); self.assertIn('not installed', row['detail']); self.assertIn('Every other feature keeps working', str(row))
        ctx.checks.clear()
        ctx.probe = Mock(return_value=({'error': 'the engine could not be queried'}, False))
        check.check_design_engine(ctx)
        self.assertEqual(by_id(ctx, 'design-engine')['status'], 'WARN')
        self.assertIn('Every other feature keeps working', str(by_id(ctx, 'design-engine')))


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
        ctx.probe = Mock(side_effect=probe_router({ROOT: [{'path': child, 'directory': True}]}))
        check.check_manager_routes(ctx)
        self.assertEqual(by_id(ctx, 'http-browse')['status'], 'PASS')
        failure = next(row for row in ctx.checks if row['title'] == 'Browse folder: ' + child)
        self.assertEqual(failure['status'], 'FAIL')
        self.assertIn('setup-operations.sh', failure['fix'])
        self.assertEqual(check.summarize(ctx)['exit_code'], 1)

    def test_empty_trusted_folder_is_healthy_and_only_read_probes_are_run(self):
        ctx = context()
        ctx.probe = Mock(side_effect=probe_router())
        ctx.http = guarded_http()
        check.check_manager_routes(ctx)
        check.check_git_route(ctx)
        self.assertEqual(by_id(ctx, 'folder-1')['status'], 'PASS')
        self.assertIn('empty folders are valid', by_id(ctx, 'folder-1')['detail'])
        allowed = {'vm-connection', 'browse', 'git-registry'}
        for call in ctx.probe.call_args_list:
            self.assertIn(call.args[0], allowed)
            self.assertEqual(len(call.args), 2 if call.args[0] == 'browse' else 1, 'a browse carries exactly one path, the others none')
        # The one HTTP question (EXPOSURE 6.1 rule 1): no check asks the manager anything but /api/health.
        for call in ctx.http.call_args_list:
            self.assertEqual(call.args[0], '/api/health')
        ctx.http.assert_not_called()
        self.assertFalse(any(row['status'] == 'FAIL' for row in ctx.checks))

    def test_missing_vm_setup_warns_and_skips_live_operations(self):
        for host in (None, {}):
            ctx = context()
            ctx.probe = Mock(side_effect=probe_router(discovery_value={'configured': False, 'connected': False, 'host': host, 'checked_at': None}))
            check.check_manager_routes(ctx)
            self.assertEqual(by_id(ctx, 'vm-connection')['status'], 'WARN')
            self.assertEqual(by_id(ctx, 'http-browse')['status'], 'SKIP')
            self.assertEqual([call.args for call in ctx.probe.call_args_list], [('vm-connection',)])

    def test_git_route_is_checked_even_when_operations_are_unavailable(self):
        ctx = context()
        ctx.trusted_helpers['operate'] = False
        ctx.probe = Mock(side_effect=probe_router())
        check.check_manager_routes(ctx)
        check.check_git_route(ctx)
        self.assertEqual(by_id(ctx, 'http-browse')['status'], 'SKIP')
        self.assertEqual(by_id(ctx, 'git-http')['status'], 'PASS')
        self.assertEqual([call.args[0] for call in ctx.probe.call_args_list], ['vm-connection', 'git-registry'])

    def test_git_route_protocol_and_version_are_required(self):
        for payload in ({'repositories': 0, 'bound_labs': 0},
                        git_registry(version='0.0.0'),
                        git_registry(repositories=PRIVATE)):
            ctx = context(require_git=True)
            ctx.host = discovery()['host']
            ctx.probe = Mock(return_value=(payload, False))
            check.check_git_route(ctx)
            self.assertEqual(by_id(ctx, 'git-http')['status'], 'FAIL')
            ctx.probe.assert_called_once_with('git-registry')
            self.assertNotIn(PRIVATE, check.render(check.summarize(ctx)))

    def test_capture_check_reports_disabled_enabled_and_failed_provider(self):
        def answer(enabled=True, targets=0, ready=True, diagnostic='', message='Packet capture is optional.'):
            return {'enabled': enabled, 'provider': 'edgeshark' if enabled else 'disabled', 'message': message,
                    'targets': targets if enabled else None, 'ready': ready if enabled else None, 'diagnostic': diagnostic}

        def run(value):
            ctx = context()
            ctx.probe = Mock(side_effect=probe_router(capture_value=value))
            ctx.http = guarded_http()
            check.check_capture(ctx)
            ctx.http.assert_not_called()
            self.assertEqual([call.args for call in ctx.probe.call_args_list], [('capture',)], 'one probe answers all three routes')
            return ctx
        ctx = run(answer(enabled=False))
        self.assertEqual(by_id(ctx, 'capture')['status'], 'WARN', 'browser Wireshark is part of every installation')
        self.assertIn('CAPTURE_PROVIDER', by_id(ctx, 'capture')['fix'])
        self.assertIn(str(ctx.source / 'deploy/setup-capture.sh'), by_id(ctx, 'capture')['fix'], 'advice works from any directory')
        ctx = run(answer(targets=2, message=PRIVATE))
        self.assertEqual(by_id(ctx, 'capture')['status'], 'PASS')
        self.assertIn('2 capture target(s)', by_id(ctx, 'capture')['detail'])
        self.assertTrue(any('browser capture' in item for item in ctx.manual))
        self.assertNotIn(PRIVATE, check.render(check.summarize(ctx)))
        ctx = run(answer(targets=None, ready=None, diagnostic='Edgeshark discovery is unavailable.'))
        self.assertEqual(by_id(ctx, 'capture')['status'], 'FAIL')
        self.assertIn('compose.capture.yml', by_id(ctx, 'capture')['fix'])
        self.assertIn('Edgeshark discovery is unavailable.', by_id(ctx, 'capture')['detail'])
        for ready in (False, None):
            ctx = run(answer(targets=3, ready=ready))
            self.assertEqual(by_id(ctx, 'capture')['status'], 'FAIL', 'discovery works but the session service is not ready')
            self.assertIn('setup-capture.sh', by_id(ctx, 'capture')['fix'])
        ctx = context()
        ctx.container = ''
        ctx.probe = Mock()
        check.check_capture(ctx)
        self.assertEqual(by_id(ctx, 'capture')['status'], 'SKIP')
        self.assertIn('Manager container unavailable', by_id(ctx, 'capture')['detail'])
        ctx.probe.assert_not_called()

    def test_retired_telemetry_check_passes_when_nothing_remains(self):
        def command(args, **kwargs):
            if 'info' in args:
                return check.Result(0)
            if 'ps' in args:
                return check.Result(0, '')
            if 'volume' in args and 'ls' in args:
                return check.Result(0, '')
            if 'cat' in args:
                return check.Result(0, 'UI_PORT=8081\nCAPTURE_PROVIDER=edgeshark\n')
            if 'test' in args:
                return check.Result(1)
            return check.Result(reason='unexpected command')
        ctx = context()
        ctx.run = Mock(side_effect=command)
        check.check_retired_telemetry(ctx)
        record = by_id(ctx, 'telemetry-retired')
        self.assertEqual(record['status'], 'PASS')
        self.assertEqual(record['fix'], '')

    def test_retired_telemetry_check_warns_and_lists_every_kind_of_leftover_without_leaking_values(self):
        def command(args, **kwargs):
            if 'info' in args:
                return check.Result(0)
            if 'ps' in args:
                return check.Result(0, 'clab-manager-telemetry-prometheus-1\n')
            if 'volume' in args and 'ls' in args:
                return check.Result(0, 'clab-manager-telemetry_grafana-data\n')
            if 'cat' in args:
                return check.Result(0, 'UI_PORT=8081\nTELEMETRY_STACK=' + PRIVATE + '\n')
            if 'test' in args:
                return check.Result(0) if args[-1] == '/srv/containerlab-node-manager/telemetry' else check.Result(1)
            return check.Result(reason='unexpected command')
        ctx = context()
        ctx.run = Mock(side_effect=command)
        check.check_retired_telemetry(ctx)
        record = by_id(ctx, 'telemetry-retired')
        self.assertEqual(record['status'], 'WARN')
        self.assertIn('clab-manager-telemetry-prometheus-1', record['detail'])
        self.assertIn('clab-manager-telemetry_grafana-data', record['detail'])
        self.assertIn('TELEMETRY_STACK', record['detail'])
        self.assertIn('/srv/containerlab-node-manager/telemetry', record['detail'])
        self.assertIn('retire-telemetry.sh', record['fix'])
        self.assertNotIn(PRIVATE, check.render(check.summarize(ctx)))

    def test_retired_telemetry_check_skips_when_docker_is_unavailable(self):
        ctx = context()
        ctx.run = Mock(return_value=check.Result(1, PRIVATE))
        check.check_retired_telemetry(ctx)
        self.assertEqual(by_id(ctx, 'telemetry-retired')['status'], 'SKIP')
        self.assertEqual(ctx.run.call_count, 1, 'nothing further is probed once Docker itself is unavailable')
        self.assertNotIn(PRIVATE, check.render(check.summarize(ctx)))

    def test_untrusted_helper_cannot_be_executed_or_reached_over_http(self):
        ctx = context(require_git=True)
        ctx.trusted_helpers = {'inspect': False, 'operate': False, 'git': False}
        result = check.helper_request(ctx, 'operate', {'mode': 'capabilities'})
        self.assertFalse(result.ok)
        ctx.run.assert_not_called()
        ctx.host = discovery()['host']
        ctx.http = Mock()
        ctx.probe = Mock()
        check.check_git_route(ctx)
        ctx.http.assert_not_called()
        ctx.probe.assert_not_called()
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
        ctx.container = ''  # the guard moved from the HTTP address to the container: the probes run inside it
        ctx.http = Mock()
        ctx.probe = Mock()
        check.check_manager_routes(ctx)
        self.assertEqual(by_id(ctx, 'vm-connection')['status'], 'SKIP')
        self.assertIn('Manager container unavailable', by_id(ctx, 'vm-connection')['detail'])
        ctx.http.assert_not_called()
        ctx.probe.assert_not_called()

    def test_folder_budget_prioritizes_explicit_problem_path_and_reports_remaining(self):
        problem = ROOT + '/vJunOS-SW'
        ctx = context(lab_path=[problem], max_folders=1)
        ctx.probe = Mock(side_effect=probe_router({problem: [], ROOT: []}))
        check.check_manager_routes(ctx)
        self.assertEqual(browsed(ctx), ['', problem])
        self.assertEqual(by_id(ctx, 'folder-budget')['status'], 'WARN')

    def test_folder_traversal_does_not_follow_malformed_or_nonchild_paths(self):
        entries = [{'path': '/etc/passwd', 'directory': True},
                   {'path': ROOT + '/../escape', 'directory': True},
                   {'path': ROOT + '/\x00bad', 'directory': True},
                   {'path': ROOT + '/lab.clab.yml', 'directory': False}]
        ctx = context()
        ctx.probe = Mock(side_effect=probe_router({ROOT: entries}))
        check.check_manager_routes(ctx)
        self.assertEqual(browsed(ctx), ['', ROOT])

    def test_wrong_folder_response_path_fails_instead_of_claiming_listed(self):
        ctx = context()
        responses = [(discovery(), False),
                     ({'entries': [{'directory': True, 'path': ROOT}]}, False),
                     ({'path': '/different', 'entries': []}, False),
                     (git_registry(), False)]
        ctx.probe = Mock(side_effect=responses)
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
                ctx.pin_certificate = lambda: setattr(ctx, 'tls_context', object())
                ctx.http = Mock(return_value=(check.Result(0), {'ready': True, 'private': PRIVATE}))
                ctx.probe = Mock(side_effect=probe_router())
                installer = SimpleNamespace(health_url=lambda command: 'https://127.0.0.1:8443/api/health')
                with patch.object(check, 'check_storage'), patch.object(check, 'module', return_value=installer):
                    check.check_docker(ctx)
                ident = 'manager-version' if condition == 'old-version' else 'manager'
                self.assertEqual(by_id(ctx, ident)['status'], 'PASS' if condition == 'healthy' else 'FAIL')
                if condition in ('missing', 'stopped', 'invalid-metadata'):
                    ctx.http.assert_not_called()
                else:
                    ctx.http.assert_called_once_with('/api/health')
                    self.assertEqual(ctx.base_url, 'https://127.0.0.1:8443')
                    self.assertEqual(by_id(ctx, 'http')['status'], 'PASS')
                if condition == 'stopped':
                    self.assertEqual(ctx.manager_command, metadata['command'], 'tls.bind reads the command of a stopped manager too')
                self.assertNotIn(PRIVATE, check.render(check.summarize(ctx)))

    def test_daemon_failure_prevents_http_or_container_claims(self):
        ctx = context()
        ctx.container = ''  # nothing was found: the daemon could not be asked
        ctx.run = Mock(return_value=check.Result(1, PRIVATE))
        ctx.http = Mock()
        ctx.probe = Mock()
        check.check_docker(ctx)
        self.assertEqual(by_id(ctx, 'docker')['status'], 'FAIL')
        self.assertEqual(by_id(ctx, 'manager')['status'], 'SKIP')
        ctx.http.assert_not_called()
        ctx.probe.assert_not_called()

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
            # The manager refuses a DNS name it was not told about (DNS rebinding), so the workstation step says how to allow one,
            # on both installation routes (the prepared-image route reads deploy/image.env, never clab-backup-ui/.env).
            self.assertIn('UI_ALLOWED_HOSTS in clab-backup-ui/.env', rendered)
            self.assertIn('deploy/image.env for a prepared release image', rendered)
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
                                  check_exposure=Mock(),
                                  check_git=Mock(side_effect=lambda ctx: ctx.add('last', 'PASS', 'Last group', 'Completed')))
        account = SimpleNamespace(pw_uid=1000, pw_name='archtop')
        fake_pwd = SimpleNamespace(getpwnam=lambda _: account)
        functions = ('check_source', 'check_docker', 'check_containerlab', 'check_helper_files',
                     'check_helpers', 'check_manager_routes', 'check_git_route', 'check_capture', 'check_retired_telemetry')
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
        modules = SimpleNamespace(check_host=Mock(), check_exposure=Mock(), check_git=Mock())
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
        modules.check_exposure.assert_not_called()
        self.assertTrue(any(row['status'] == 'SKIP' and row['title'] == 'TLS, firewall and exposure' for row in report['checks']))
        self.assertTrue(any(row['status'] == 'SKIP' and row['title'] == 'Registered Git checkouts'
                            for row in report['checks']))

    def test_initial_sudo_success_cannot_mask_failed_query_runner(self):
        output = io.StringIO()
        account = SimpleNamespace(pw_uid=1000, pw_name='archtop')
        modules = SimpleNamespace(check_host=Mock(), check_exposure=Mock(), check_git=Mock())
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
        modules.check_exposure.assert_not_called()
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


class ProbeFailureTests(unittest.TestCase):
    """EXPOSURE 6.3 case 11 and the SKIP table of 6.1: a probe that cannot answer is a SKIP with its reason, a probe
    whose helper refused is a FAIL with the helper's sentence, and neither is ever a PASS."""

    CHECKS = (('design-engine', check.check_design_engine), ('vm-connection', check.check_manager_routes),
              ('git-http', check.check_git_route), ('capture', check.check_capture))

    def trusted(self):
        ctx = context(require_git=True)
        ctx.host = discovery()['host']
        return ctx

    def test_a_manager_that_predates_the_probes_skips_every_probe_check_with_the_rebuild_fix(self):
        ctx = self.trusted()
        ctx.probe = Mock(return_value=(None, True))
        for _, function in self.CHECKS:
            function(ctx)
        for ident in ('design-engine', 'vm-connection', 'http-browse', 'git-http', 'capture'):
            with self.subTest(ident=ident):
                row = by_id(ctx, ident)
                self.assertEqual(row['status'], 'SKIP')
                self.assertIn('predates this check', row['detail'])
                self.assertIn('start-manager.sh', row['fix'])
        self.assertFalse(any(row['status'] in ('PASS', 'FAIL') for row in ctx.checks if row['id'] in ('design-engine', 'vm-connection', 'http-browse', 'git-http', 'capture')))

    def test_unreadable_saved_state_skips_and_names_the_page_that_runs_the_same_check(self):
        for sentence in ('state unreadable', 'reset pending'):
            with self.subTest(sentence=sentence):
                ctx = self.trusted()
                ctx.probe = Mock(return_value=({'error': sentence}, False))
                check.check_manager_routes(ctx)
                check.check_git_route(ctx)
                for ident in ('vm-connection', 'http-browse'):
                    self.assertEqual(by_id(ctx, ident)['status'], 'SKIP')
                    self.assertIn(sentence, by_id(ctx, ident)['detail'])
                    self.assertIn('Diagnostics', by_id(ctx, ident)['fix'])
                self.assertEqual(by_id(ctx, 'git-http')['status'], 'SKIP')
                self.assertIn('Save', by_id(ctx, 'git-http')['fix'])
                self.assertNotIn('Diagnostics', by_id(ctx, 'git-http')['fix'], 'Diagnostics never lists the Git registry')

    def test_a_helper_sentence_is_a_failure_with_that_sentence(self):
        sentence = 'The operations helper refused the request.'
        ctx = self.trusted()
        ctx.probe = Mock(side_effect=lambda name, *args: (discovery(), False) if name == 'vm-connection' else ({'error': sentence}, False))
        check.check_manager_routes(ctx)
        check.check_git_route(ctx)
        self.assertEqual(by_id(ctx, 'http-browse')['status'], 'FAIL')
        self.assertIn(sentence, by_id(ctx, 'http-browse')['detail'])
        self.assertEqual(by_id(ctx, 'git-http')['status'], 'FAIL')
        self.assertIn(sentence, by_id(ctx, 'git-http')['detail'])
        optional = context()
        optional.host = discovery()['host']
        optional.probe = Mock(return_value=({'error': sentence}, False))
        check.check_git_route(optional)
        self.assertEqual(by_id(optional, 'git-http')['status'], 'WARN', 'Git is optional unless --require-git')

    def test_a_probe_that_prints_nothing_is_not_a_pass(self):
        ctx = self.trusted()
        ctx.probe = Mock(return_value=(None, False))
        for _, function in self.CHECKS:
            function(ctx)
        self.assertEqual(by_id(ctx, 'vm-connection')['status'], 'FAIL')
        self.assertEqual(by_id(ctx, 'design-engine')['status'], 'WARN')
        self.assertEqual(by_id(ctx, 'capture')['status'], 'WARN')

    def test_a_connection_without_a_saved_fingerprint_warns_and_skips_the_live_checks(self):
        value = discovery()
        del value['host']['fingerprint_saved']
        ctx = context()
        ctx.probe = Mock(side_effect=probe_router(discovery_value=value))
        check.check_manager_routes(ctx)
        check.check_git_route(ctx)
        self.assertEqual(by_id(ctx, 'vm-connection')['status'], 'WARN')
        self.assertEqual(by_id(ctx, 'http-browse')['status'], 'SKIP')
        self.assertEqual(by_id(ctx, 'git-http')['status'], 'SKIP')
        self.assertEqual([call.args[0] for call in ctx.probe.call_args_list], ['vm-connection'])

    def test_the_fingerprint_value_is_never_asked_for_or_printed(self):
        ctx = context()
        ctx.probe = Mock(side_effect=probe_router())
        check.check_manager_routes(ctx)
        self.assertIn('fingerprint', by_id(ctx, 'vm-connection')['detail'])
        self.assertEqual(by_id(ctx, 'vm-connection')['status'], 'PASS')

    def test_health_must_say_ready_and_a_version_alone_fails(self):
        for body in ({'version': VERSION}, {'ready': False}, {'ready': 'true'}, ['ready']):
            with self.subTest(body=body):
                ctx = context()
                self.run_docker(ctx, Mock(return_value=(check.Result(0), body)))
                self.assertEqual(by_id(ctx, 'http')['status'], 'FAIL')
                self.assertEqual(ctx.base_url, 'https://127.0.0.1:8443', 'tls.listener still reports the TLS fact')

    def test_an_unreadable_certificate_skips_http_without_sending_a_request(self):
        ctx = context()
        http = Mock()
        self.run_docker(ctx, http, pinned=False)
        http.assert_not_called()
        row = by_id(ctx, 'http')
        self.assertEqual(row['status'], 'SKIP')
        self.assertIn('The installed certificate could not be read, so the manager was not asked over HTTPS.', row['detail'])
        self.assertIn('setup-tls.sh', row['fix'])
        self.assertEqual(ctx.base_url, '')
        self.assertEqual(by_id(ctx, 'manager-version')['status'], 'PASS', 'proved by docker exec, unaffected')
        self.assertIn(by_id(ctx, 'design-engine')['status'], ('PASS', 'WARN'), 'the probe checks run regardless')

    def run_docker(self, ctx, http, pinned=True):
        metadata = {'state': {'Running': True}, 'mounts': [], 'network': 'host', 'restart': 'unless-stopped',
                    'command': ['uvicorn', 'app.main:create_app', '--host', '0.0.0.0', '--port', '8443', '--ssl-certfile', '/tls/cert.pem']}

        def command(args, **kwargs):
            if 'info' in args or args[-1] == 'version':
                return check.Result(0)
            if 'ps' in args:
                return check.Result(0, 'a' * 64)
            if 'inspect' in args:
                return encoded(metadata)
            if 'exec' in args:
                return check.Result(0, VERSION)
            return check.Result(reason='unexpected read command')
        ctx.run = Mock(side_effect=command)
        ctx.http = http
        ctx.probe = Mock(side_effect=probe_router())
        ctx.tls_context = None
        ctx.pin_certificate = (lambda: setattr(ctx, 'tls_context', object())) if pinned else (lambda: None)
        installer = SimpleNamespace(health_url=lambda command: 'https://127.0.0.1:8443/api/health')
        with patch.object(check, 'check_storage'), patch.object(check, 'module', return_value=installer):
            check.check_docker(ctx)


class ContextHelperTests(unittest.TestCase):
    def test_probe_runs_the_module_privileged_through_docker_exec_and_parses_the_one_line(self):
        ctx = context()
        ctx.run = Mock(return_value=check.Result(0, json.dumps({'available': True}) + '\n'))
        self.assertEqual(ctx.probe('browse', '/etc/containerlab'), ({'available': True}, False))
        argv = ctx.run.call_args.args[0]
        self.assertEqual(argv[-5:], ['python', '-m', 'app.probe', 'browse', '/etc/containerlab'])
        self.assertEqual(argv[argv.index('exec') + 1], ctx.container)
        self.assertTrue(ctx.run.call_args.kwargs['privileged'])
        self.assertEqual(ctx.run.call_args.kwargs['timeout'], 30)

    def test_probe_reads_an_error_line_from_a_nonzero_exit_and_reports_a_missing_module(self):
        ctx = context()
        ctx.run = Mock(return_value=check.Result(1, '{"error": "state unreadable"}\n'))
        self.assertEqual(ctx.probe('vm-connection'), ({'error': 'state unreadable'}, False))
        ctx.run = Mock(return_value=check.Result(1, '', stderr='/usr/local/bin/python: No module named app.probe\n'))
        self.assertEqual(ctx.probe('capture'), (None, True))
        for result in (check.Result(2, ''), check.Result(0, PRIVATE), check.Result(0, '[1]'), check.Result(reason='command timed out')):
            ctx.run = Mock(return_value=result)
            self.assertEqual(ctx.probe('capture'), (None, False))

    def test_run_captures_stderr_only_when_asked(self):
        ctx = check.Context(check.arguments([]), owner='archtop', privileged=False)
        script = 'import sys; print("out"); print("No module named app.probe", file=sys.stderr)'
        quiet = ctx.run([sys.executable, '-c', script])
        self.assertEqual((quiet.stdout.strip(), quiet.stderr), ('out', ''))
        loud = ctx.run([sys.executable, '-c', script], capture_stderr=True)
        self.assertIn('No module named app.probe', loud.stderr)

    def test_head_returns_status_and_lowercase_headers_without_following_a_redirect(self):
        ctx = context()
        redirect = HTTPError('http://127.0.0.1:8081/', 301, 'Moved', {'Location': 'https://127.0.0.1:8443/'}, io.BytesIO(b''))
        with patch.object(check, 'build_opener', return_value=SimpleNamespace(open=Mock(side_effect=redirect))):
            self.assertEqual(ctx.head('/', base='http://127.0.0.1:8081'), (301, {'location': 'https://127.0.0.1:8443/'}))
        response = Mock(status=200, headers={'Strict-Transport-Security': 'max-age=15552000'})
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        with patch.object(check, 'build_opener', return_value=SimpleNamespace(open=Mock(return_value=response))):
            self.assertEqual(ctx.head('/api/health'), (200, {'strict-transport-security': 'max-age=15552000'}))
        for failure in (OSError('refused'), check.http.client.BadStatusLine('x'), ValueError('bad')):
            with patch.object(check, 'build_opener', return_value=SimpleNamespace(open=Mock(side_effect=failure))):
                self.assertEqual(ctx.head('/', base='http://127.0.0.1:8443'), (None, {}))

    def test_https_without_a_pinned_certificate_sends_nothing(self):
        ctx = context()
        ctx.tls_context = None
        with patch.object(check, 'build_opener') as network:
            result, value = ctx.http('/api/health')
            status, headers = ctx.head('/api/health')
        network.assert_not_called()
        self.assertFalse(result.ok)
        self.assertIsNone(value)
        self.assertEqual((status, headers), (None, {}))

    def test_the_report_deadline_bounds_head(self):
        ctx = context()
        ctx.deadline = 0
        with patch.object(check, 'build_opener') as network:
            self.assertEqual(ctx.head('/', base='http://127.0.0.1:8081'), (None, {}))
        network.assert_not_called()

    def test_module_and_manual_text(self):
        ctx = context()
        self.assertIn('https://<VM address>:8443', ctx.manual[0])
        self.assertIn('fingerprint', ctx.manual[0])
        self.assertEqual(ctx.module('check_exposure').__name__, 'check_exposure')


@unittest.skipUnless(sys.platform == 'linux' and shutil.which('openssl'), 'needs openssl to make a real certificate')
class PinnedTlsTests(unittest.TestCase):
    """The pinned opener against a real TLS server and a certificate made the way setup-tls.sh makes one
    (EC P-256, CA:FALSE, digitalSignature, serverAuth, IP and DNS names): a PASS proves the listener serves
    exactly that file, and another certificate is refused."""

    def make_certificate(self, directory, name):
        cert, key = Path(directory) / (name + '.pem'), Path(directory) / (name + '.key')
        subprocess.run(['openssl', 'req', '-x509', '-newkey', 'ec', '-pkeyopt', 'ec_paramgen_curve:P-256', '-nodes', '-sha256',
                        '-days', '2', '-subj', '/CN=localhost', '-addext', 'subjectAltName=DNS:localhost,IP:127.0.0.1',
                        '-addext', 'basicConstraints=critical,CA:FALSE', '-addext', 'keyUsage=digitalSignature',
                        '-addext', 'extendedKeyUsage=serverAuth', '-keyout', str(key), '-out', str(cert)],
                       check=True, capture_output=True)
        return cert, key

    def serve(self, cert, key):
        context_ = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context_.load_cert_chain(str(cert), str(key))

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                body = b'{"ready": true}'
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Strict-Transport-Security', 'max-age=15552000')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        server = http.server.HTTPServer(('127.0.0.1', 0), Handler)
        server.socket = context_.wrap_socket(server.socket, server_side=True)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return 'https://127.0.0.1:%d' % server.server_address[1]

    def test_only_the_installed_certificate_is_trusted(self):
        with tempfile.TemporaryDirectory() as directory:
            cert, key = self.make_certificate(directory, 'installed')
            other_cert, other_key = self.make_certificate(directory, 'other')
            ctx = check.Context(check.arguments([]), owner='archtop', privileged=True)
            ctx.pin_certificate(cert)
            self.assertIsNotNone(ctx.tls_context)
            ctx.base_url = self.serve(cert, key)
            result, body = ctx.http('/api/health')
            self.assertTrue(result.ok, result.reason)
            self.assertEqual(body, {'ready': True})
            status, headers = ctx.head('/api/health')
            self.assertEqual(status, 200)
            self.assertEqual(headers['strict-transport-security'], 'max-age=15552000')
            ctx.base_url = self.serve(other_cert, other_key)
            result, body = ctx.http('/api/health')
            self.assertFalse(result.ok)
            self.assertEqual(ctx.head('/api/health'), (None, {}))

    def test_an_unreadable_or_garbage_certificate_leaves_no_context(self):
        with tempfile.TemporaryDirectory() as directory:
            ctx = check.Context(check.arguments([]), owner='archtop', privileged=True)
            ctx.pin_certificate(Path(directory) / 'missing.pem')
            self.assertIsNone(ctx.tls_context)
            garbage = Path(directory) / 'garbage.pem'
            garbage.write_text('not a certificate')
            ctx.pin_certificate(garbage)
            self.assertIsNone(ctx.tls_context)


if __name__ == '__main__':
    unittest.main()
