import copy
import json
import unittest
from unittest.mock import patch

from app import __version__
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
            self.assertEqual(kwargs['timeout'], 30)
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


if __name__ == '__main__': unittest.main()
