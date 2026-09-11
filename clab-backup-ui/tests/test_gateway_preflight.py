import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import time
import unittest
from unittest.mock import Mock, patch


spec = importlib.util.spec_from_file_location('gateway_preflight', Path(__file__).resolve().parents[2] / 'deploy/verify-gateway.py')
gateway = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gateway)
VERSION = (Path(__file__).resolve().parents[1] / 'VERSION').read_text(encoding='utf-8').strip()


def response(kind, version=VERSION):
    if kind == 'discovery':
        return {'protocol': 'clab-manager-files-v1', 'helper_version': version, 'inspect': {},
                'sources': {'PRIVATE': 'SECRET'}}
    result = {'protocol': 'clab-manager-' + ('operations' if kind == 'operations' else 'git') + '-v1',
              'version': version}
    if kind == 'operations':
        result['actions'] = {name: {'available': True} for name in ('deploy', 'destroy', 'inspect')}
    else:
        result['repositories'] = [{'path': 'PRIVATE'}]
    return {'result': result}


class GatewayPreflightTests(unittest.TestCase):
    def test_cli_checks_optional_helpers_only_when_requested(self):
        for flags, expected in (([], ['discovery']), (['--operations'], ['discovery', 'operations']),
                                (['--operations', '--git'], ['discovery', 'operations', 'git'])):
            with self.subTest(flags=flags), patch.object(gateway.sys, 'platform', 'linux'), \
                    patch.object(gateway.os, 'geteuid', return_value=0, create=True), \
                    patch.object(gateway.Path, 'is_file', return_value=True), \
                    patch.object(gateway, 'verify_gateways') as verify:
                gateway.main([VERSION, *flags])
            verify.assert_called_once_with(VERSION, expected)

    def test_all_read_only_requests_pass_without_disclosing_response_contents(self):
        def run(kind):
            return json.dumps(response(kind)).encode()
        with patch('sys.stdout', new=io.StringIO()) as printed:
            gateway.verify_gateways(VERSION, ['discovery', 'operations', 'git'], runner=run)
        self.assertIn('Verified operations through clab-discovery', printed.getvalue())
        self.assertNotIn('PRIVATE', printed.getvalue())
        self.assertNotIn('SECRET', printed.getvalue())

    def test_effective_gateway_uses_restricted_account_and_exact_allowed_command(self):
        for kind, (command, payload, _) in gateway.REQUESTS.items():
            with self.subTest(kind=kind):
                args = gateway.gateway_command(kind)
                self.assertEqual(args[:6], ['/usr/sbin/runuser', '--user', 'clab-discovery', '--', '/usr/bin/env', '-i'])
                self.assertIn('SSH_ORIGINAL_COMMAND=' + command, args)
                self.assertEqual(args[-1], '/usr/local/sbin/clab-manager-gateway')
                if payload:
                    self.assertIn(json.loads(payload)['mode'], ('capabilities', 'list'))

    def test_unavailable_core_capabilities_stop_before_success(self):
        for name in ('deploy', 'destroy', 'inspect'):
            data = response('operations')
            data['result']['actions'][name]['available'] = False
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'containerlab ' + name):
                gateway.verify_response('operations', json.dumps(data), VERSION)

    def test_malformed_and_wrong_version_responses_rejected_without_content(self):
        for data in ('SECRET', '[]', '{"error":"SECRET"}', json.dumps(response('operations', '0.0.0'))):
            with self.subTest(data=data), self.assertRaises(ValueError) as error:
                gateway.verify_response('operations', data, VERSION)
            self.assertNotIn('SECRET', str(error.exception))

    def test_failure_stops_later_checks_and_identifies_repair(self):
        run = Mock(side_effect=ValueError('Discovery gateway cannot use its passwordless sudo permission.'))
        with self.assertRaisesRegex(ValueError, 'setup-discovery.sh') as error:
            gateway.verify_gateways(VERSION, ['discovery', 'operations'], runner=run)
        self.assertIn('Manager has not been recreated', str(error.exception))
        run.assert_called_once_with('discovery')

    def _process(self, stdout=b'', stderr=b'', code=0, timeout=False):
        process = Mock(returncode=code, pid=1234, stdin=Mock(), stdout=io.BytesIO(stdout), stderr=io.BytesIO(stderr))
        process.__enter__ = Mock(return_value=process)
        process.__exit__ = Mock(return_value=False)
        process.wait.side_effect = [subprocess.TimeoutExpired('runuser', 180), code] if timeout else None
        def factory(args, **kwargs):
            return process
        return process, factory

    def test_runner_uses_root_directory_private_capture_and_closes_request_stdin(self):
        raw = json.dumps(response('operations')).encode()
        process, factory = self._process(stdout=raw)
        with patch.object(gateway.subprocess, 'Popen', side_effect=factory) as popen, \
                patch.object(gateway, 'stop_request'):
            self.assertEqual(gateway.run_request('operations'), raw)
        self.assertEqual(popen.call_args.kwargs['cwd'], '/')
        self.assertTrue(popen.call_args.kwargs['start_new_session'])
        self.assertEqual(popen.call_args.kwargs['stdout'], subprocess.PIPE)
        self.assertEqual(popen.call_args.kwargs['stderr'], subprocess.PIPE)
        self.assertEqual(popen.call_args.kwargs['bufsize'], 0)
        process.stdin.write.assert_called_once_with(b'{"mode":"capabilities"}\n')
        process.stdin.close.assert_called_once()

    def test_sudo_denial_is_actionable_without_printing_raw_stderr(self):
        _, factory = self._process(stderr=b'sudo: a password is required\nSECRET', code=1)
        with patch.object(gateway.subprocess, 'Popen', side_effect=factory), \
                patch.object(gateway, 'stop_request'):
            with self.assertRaisesRegex(ValueError, 'passwordless sudo') as error:
                gateway.run_request('operations')
        self.assertNotIn('SECRET', str(error.exception))

    def test_timeout_kills_gateway_and_helper_process_group(self):
        process, factory = self._process(timeout=True)
        with patch.object(gateway.subprocess, 'Popen', side_effect=factory), \
                patch.object(gateway.os, 'killpg', create=True) as kill:
            with self.assertRaisesRegex(ValueError, 'timed out'):
                gateway.run_request('operations')
        kill.assert_called_once_with(process.pid, getattr(gateway.signal, 'SIGKILL', 9))
        self.assertEqual(process.wait.call_count, 2)

    def test_oversized_stdout_or_stderr_stops_whole_request_during_read(self):
        for stdout, stderr in ((b'x' * (1024 * 1024 + 20), b''), (b'', b'x' * 65550)):
            process, factory = self._process(stdout=stdout, stderr=stderr)
            with patch.object(gateway.subprocess, 'Popen', side_effect=factory), \
                    patch.object(gateway, 'stop_request') as stop:
                with self.assertRaisesRegex(ValueError, 'size limit'):
                    gateway.run_request('operations')
            self.assertGreaterEqual(stop.call_count, 2)

    def test_reader_error_after_valid_json_cannot_pass(self):
        raw = json.dumps(response('operations')).encode()
        for name in ('stdout', 'stderr'):
            process, factory = self._process(stdout=raw)
            broken = Mock()
            broken.read.side_effect = [raw if name == 'stdout' else b'', OSError('SECRET')]
            if name == 'stderr':
                broken.read.side_effect = [OSError('SECRET')]
            setattr(process, name, broken)
            with self.subTest(pipe=name), patch.object(gateway.subprocess, 'Popen', side_effect=factory), \
                    patch.object(gateway, 'stop_request') as stop:
                with self.assertRaisesRegex(ValueError, 'could not be read completely') as error:
                    gateway.run_request('operations')
            self.assertNotIn('SECRET', str(error.exception))
            self.assertGreaterEqual(stop.call_count, 2)

    def test_unfinished_reader_cannot_pass(self):
        process, factory = self._process(stdout=json.dumps(response('operations')).encode())
        reader = Mock()
        reader.is_alive.return_value = True
        with patch.object(gateway.subprocess, 'Popen', side_effect=factory), \
                patch.object(gateway.threading, 'Thread', return_value=reader), \
                patch.object(gateway, 'stop_request'):
            with self.assertRaisesRegex(ValueError, 'response did not close'):
                gateway.run_request('operations')
        reader.join.assert_called_with(timeout=5)

    @unittest.skipUnless(sys.platform == 'linux', 'Requires Linux process-group cleanup')
    def test_real_process_reads_multipart_response_and_request_eof(self):
        raw = json.dumps(response('operations')).encode()
        script = ('import os,sys,time; data=sys.stdin.buffer.read(); '
                  'assert data==b\'{"mode":"capabilities"}\\n\'; '
                  'payload=' + repr(raw) + '; '
                  'os.write(1,payload[:7]); time.sleep(.05); os.write(1,payload[7:])')
        with patch.object(gateway, 'gateway_command', return_value=[sys.executable, '-c', script]):
            self.assertEqual(gateway.run_request('operations'), raw)

    @unittest.skipUnless(sys.platform == 'linux', 'Requires Linux fork and process-group cleanup')
    def test_real_process_cleans_up_descendant_holding_response_pipes(self):
        raw = json.dumps(response('operations')).encode()
        # The leader exits while a child keeps both pipe descriptors open. The
        # preflight must terminate that group and finish, rather than wait for
        # the child's sleep or silently retain an active helper descendant.
        script = ('import os,time; child=os.fork(); '
                  'time.sleep(4) if child==0 else None; '
                  'os.write(1,' + repr(raw) + ') if child else None; os._exit(0)')
        started = time.monotonic()
        with patch.object(gateway, 'gateway_command', return_value=[sys.executable, '-c', script]):
            self.assertEqual(gateway.run_request('operations'), raw)
        self.assertLess(time.monotonic() - started, 3)


if __name__ == '__main__':
    unittest.main()
