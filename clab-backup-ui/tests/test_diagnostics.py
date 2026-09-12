import copy
import json
import unittest
from unittest.mock import patch

from app import __version__
from app.diagnostics import PROBE_TIMEOUT, failure_hint
import test_discovery


class DiagnosticsTests(unittest.TestCase):
    setUp = test_discovery.DiscoveryTests.setUp
    host = test_discovery.DiscoveryTests.host
    register = test_discovery.DiscoveryTests.register

    def tearDown(self):
        self.app.state.operations.close()
        test_discovery.DiscoveryTests.tearDown(self)

    def test_snapshot_available_without_lab_or_host_and_never_calls_ssh(self):
        with patch('app.diagnostics.remote') as remote:
            response = self.client.get('/api/debug')
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data['manager_version'], __version__)
            self.assertFalse(data['vm']['configured'])
            self.assertEqual(data['saved_counts']['labs'], 0)
            remote.assert_not_called()
        self.assertEqual(response.headers['cache-control'], 'no-store')

    def test_request_metadata_is_bounded_and_excludes_secrets_and_actual_paths(self):
        self.host()
        lab = self.register()
        self.store.lab(lab['id'])['profiles'] = [{'password': 'device-secret', 'private_key': 'key-secret'}]
        self.store.state['discovery'] = {'error': 'raw-error-secret', 'helper_version': 'version-secret'}
        for _ in range(205):
            response = self.client.get('/api/jobs/private-job-secret?token=query-secret', headers={'X-Secret': 'header-secret'})
            self.assertEqual(response.status_code, 404)
        result = self.client.get('/api/debug').json()
        self.assertEqual(len(result['requests']), 200)
        self.assertEqual(result['requests'][0]['status'], 404)
        self.assertEqual(result['requests'][0]['id'], response.headers['x-request-id'])
        for secret in ('host-secret', 'device-secret', 'key-secret', 'raw-error-secret', 'version-secret', 'private-job-secret', 'query-secret', 'header-secret'):
            self.assertNotIn(secret, json.dumps(result))

    def test_probe_browse_survives_capability_failure_and_does_not_mutate_state(self):
        self.host()
        before = copy.deepcopy(self.store.state)
        def remote(host, req, **kwargs):
            self.assertEqual(kwargs['timeout'], PROBE_TIMEOUT)
            self.assertGreaterEqual(PROBE_TIMEOUT, 60)
            if req['mode'] == 'browse':
                self.assertEqual(req['path'], '/etc/containerlab/private-path-secret')
                return {'entries': [{'name': 'file-secret.clab.yaml'}]}
            raise ValueError('sudo permission host-secret private-error-secret')
        with patch('app.diagnostics.remote', side_effect=remote) as invoke:
            response = self.client.post('/api/debug/probe', json={'path': '/etc/containerlab/private-path-secret'})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(invoke.call_count, 2)
        self.assertEqual([c['status'] for c in response.json()['checks']], ['pass', 'fail'])
        self.assertEqual(response.json()['checks'][1]['code'], 'gateway-permission')
        self.assertNotIn('secret', response.text)
        self.assertEqual(self.store.state, before)

    def test_probe_mismatch_browse_failure_and_repeat(self):
        def remote(host, req, **kwargs):
            if req['mode'] == 'browse': raise ValueError('outside the trusted roots secret')
            return {'protocol': 'clab-manager-operations-v1', 'version': '0.0.1'}
        with patch('app.diagnostics.remote', side_effect=remote):
            for _ in range(2):
                data = self.client.post('/api/debug/probe', json={}).json()
                self.assertEqual([c['status'] for c in data['checks']], ['fail', 'warning'])
                self.assertEqual(data['checks'][0]['code'], 'untrusted-folder')

    def test_cross_origin_and_parallel_probes_are_rejected(self):
        for path in ('/api/debug', '/api/debug/probe'):
            response = self.client.get(path, headers={'Origin': 'https://elsewhere.example'})
            self.assertEqual(response.status_code, 403)
        with self.app.state.diagnostics.probe_lock:
            with patch('app.diagnostics.remote') as remote:
                self.assertEqual(self.client.post('/api/debug/probe', json={}).status_code, 409)
                remote.assert_not_called()

    def test_probe_rejects_settings_changed_in_flight_and_bad_request(self):
        self.host()
        def remote(host, req, **kwargs):
            self.store.state['host']['revision'] = 'changed'
            return {'entries': [], 'protocol': 'clab-manager-operations-v1', 'version': __version__}
        with patch('app.diagnostics.remote', side_effect=remote):
            self.assertEqual(self.client.post('/api/debug/probe', json={}).status_code, 409)
        self.assertEqual(self.client.post('/api/debug/probe', json={'command': 'anything'}).status_code, 422)
        self.assertEqual(self.client.post('/api/debug/probe', json={'path': 'x' * 4097}).status_code, 422)

    def test_unhandled_error_is_recorded_without_exception_text(self):
        @self.app.get('/api/fixture-error')
        def fixture_error():
            raise RuntimeError('exception-secret')
        with self.assertRaises(RuntimeError):
            self.client.get('/api/fixture-error')
        report = self.client.get('/api/debug').json()
        self.assertEqual(report['requests'][0]['status'], 500)
        self.assertEqual(report['requests'][0]['route'], '/api/fixture-error')
        self.assertNotIn('exception-secret', json.dumps(report))

    def test_saved_settings_succeed_and_debug_reports_unavailable_audit_log(self):
        with patch('app.store.os.open', side_effect=OSError('private path detail')):
            response = self.client.put('/api/host', json=dict(address='127.0.0.1', port=22,
                username='fixture', password='fixture-secret', enabled=False))
            self.assertEqual(response.status_code, 200, response.text)
            report = self.client.get('/api/debug')
        self.assertFalse(report.json()['audit_log_available'])
        self.assertNotIn('private path detail', report.text)
        self.assertNotIn('fixture-secret', report.text)
        saved = json.loads(self.store.cipher.decrypt(self.store.path.read_bytes()))
        self.assertEqual(saved['host']['password'], 'fixture-secret')

    def test_failure_hints_classify_paramiko_and_helper_errors(self):
        import paramiko
        cases = {
            paramiko.AuthenticationException('Authentication failed.'): 'authentication',
            ValueError('VM password setup required. Run sudo bash deploy/setup-discovery.sh'): 'authentication',
            ValueError('VM SSH host key changed. Verify the VM and reset the saved fingerprint'): 'host-trust',
            ValueError('Operations gateway could not obtain its restricted sudo permission.'): 'gateway-permission',
            ValueError('Operation connection interrupted. Inspect the lab before retrying.'): 'timeout',
            OSError('connection refused by host-secret'): 'helper-unavailable',
        }
        for error, code in cases.items():
            with self.subTest(error=str(error)):
                hint = failure_hint(error)
                self.assertEqual(hint['code'], code)
                self.assertNotIn('host-secret', hint['message'])


if __name__ == '__main__': unittest.main()
