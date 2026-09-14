"""On-demand Grafana: the start/stop control, its idle monitor and the API, against a fake VM helper and Grafana."""
import io
import os
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import URLError

from fastapi import HTTPException
from fastapi.testclient import TestClient

from app import grafana_control as module
from app.grafana_control import GRACE, GrafanaControl, activity, idle_minutes
from app.main import create_app

METRICS = '''# HELP grafana_http_request_duration_seconds Histogram of latencies.
# TYPE grafana_http_request_duration_seconds histogram
grafana_http_request_duration_seconds_bucket{handler="/api/ds/query",le="0.1",method="POST",status_code="200"} 7
grafana_http_request_duration_seconds_count{handler="/metrics",method="GET",slo_group="high-fast",status_code="200",status_source="server"} 12
grafana_http_request_duration_seconds_count{handler="/api/health",method="GET",slo_group="high-fast",status_code="200",status_source="server"} 4
grafana_http_request_duration_seconds_count{handler="/api/ds/query",method="POST",slo_group="none",status_code="200",status_source="server"} 7
grafana_http_request_duration_seconds_count{handler="/d/:uid/:slug",method="GET",slo_group="high-fast",status_code="200",status_source="server"} 2
grafana_http_request_duration_seconds_sum{handler="/api/ds/query",method="POST",slo_group="none",status_code="200",status_source="server"} 0.5
grafana_http_request_in_flight 1
'''


class FakeGrafana:
    """The loopback side: /api/health and /metrics of a Grafana that is up or down."""
    def __init__(self):
        self.up = False; self.requests = 0; self.calls = []

    def open(self, url, timeout=None):
        self.calls.append(url)
        if not self.up: raise URLError('connection refused')
        path = url.split('127.0.0.1:3000', 1)[1]
        if path == '/api/health': return io.BytesIO(b'{"database": "ok", "version": "13.0.2"}')
        if path == '/metrics':
            return io.BytesIO((f'grafana_http_request_duration_seconds_count{{handler="/metrics",method="GET"}} 99\n'
                               f'grafana_http_request_duration_seconds_count{{handler="/api/ds/query",method="POST"}} {self.requests}\n').encode())
        raise URLError('not found')


class FakeOperations:
    """The reviewed helper on the VM: docker start/stop of the named container."""
    def __init__(self, grafana):
        self.grafana = grafana; self.calls = []; self.fail = None; self.state = 'exited'; self.starts_work = True

    def invoke(self, req):
        self.calls.append(req)
        if self.fail: raise HTTPException(409, self.fail)
        if req['action'] == 'start':
            self.state = 'running'; self.grafana.up = self.starts_work
        if req['action'] == 'stop':
            self.state = 'exited'; self.grafana.up = False
        return {'container': 'clab-manager-grafana', 'state': self.state}


class FakeStore:
    def __init__(self): self.events = []
    def event(self, action, message, **fields): self.events.append((action, message))


class Telemetry:
    grafana = {'enabled': True, 'port': 3000, 'prometheus_port': 9090}


def control(idle='15'):
    grafana = FakeGrafana(); operations = FakeOperations(grafana); store = FakeStore()
    item = GrafanaControl(store, operations, Telemetry(), environ={'TELEMETRY_GRAFANA_IDLE_MINUTES': idle}, opener=grafana)
    return item, grafana, operations, store


class PureFunctionTests(unittest.TestCase):
    def test_activity_counts_viewer_requests_only(self):
        self.assertEqual(activity(METRICS), 9, 'the health and metrics handlers are the manager itself')
        self.assertEqual(activity(''), 0)
        self.assertEqual(activity('grafana_http_request_duration_seconds_count{handler="/api/ds/query"} nonsense\n'), 0)

    def test_idle_minutes_come_from_the_environment_with_bounds(self):
        self.assertEqual(idle_minutes({}), 15)
        self.assertEqual(idle_minutes({'TELEMETRY_GRAFANA_IDLE_MINUTES': '0'}), 0)
        self.assertEqual(idle_minutes({'TELEMETRY_GRAFANA_IDLE_MINUTES': ' 30 '}), 30)
        self.assertEqual(idle_minutes({'TELEMETRY_GRAFANA_IDLE_MINUTES': 'soon'}), 15)
        self.assertEqual(idle_minutes({'TELEMETRY_GRAFANA_IDLE_MINUTES': '99999'}), 15, 'five digits are not a number of minutes')
        self.assertEqual(idle_minutes({'TELEMETRY_GRAFANA_IDLE_MINUTES': '9999'}), 1440)


class ControlTests(unittest.TestCase):
    def setUp(self):
        self.sleep = patch.object(module.time, 'sleep'); self.sleep.start()
        self.clock = [1000.0]
        self.time = patch.object(module.time, 'time', side_effect=lambda: self.clock[0]); self.time.start()

    def tearDown(self):
        self.sleep.stop(); self.time.stop()

    def test_start_uses_the_helper_once_waits_for_health_and_records_it(self):
        item, grafana, operations, store = control()
        self.assertEqual(item.status()['running'], None, 'unknown until the first probe')
        status = item.start()
        self.assertEqual([c['action'] for c in operations.calls], ['start'])
        self.assertTrue(status['running']); self.assertEqual(status['port'], 3000); self.assertEqual(status['idle_minutes'], 15)
        self.assertTrue(status['started_at']); self.assertIn('stops after 15 minutes', status['message'])
        self.assertEqual([e[0] for e in store.events], ['grafana.start'])
        item.start()
        self.assertEqual(len(operations.calls), 1, 'a running Grafana is not started again')
        self.assertEqual(operations.calls[0], {'mode': 'grafana', 'action': 'start'})
        status = item.stop()
        self.assertFalse(status['running']); self.assertIn('starts when you open it', status['message'])
        self.assertEqual(operations.calls[-1], {'mode': 'grafana', 'action': 'stop'})
        self.assertEqual(store.events[-1][0], 'grafana.stop'); self.assertIn('on request', store.events[-1][1])

    def test_start_failures_are_explained(self):
        item, grafana, operations, store = control()
        operations.fail = 'Unknown request mode.'
        with self.assertRaises(HTTPException) as caught: item.start()
        self.assertIn('predates on-demand Grafana', caught.exception.detail)
        operations.fail = None; operations.state = 'missing'
        operations.invoke = lambda req: {'container': 'clab-manager-grafana', 'state': 'missing'}
        with self.assertRaises(HTTPException) as caught: item.start()
        self.assertIn('does not exist on the VM', caught.exception.detail)
        item, grafana, operations, store = control()
        operations.starts_work = False
        with patch.object(module, 'START_TIMEOUT', 0):
            with self.assertRaises(HTTPException) as caught: item.start()
        self.assertIn('did not answer', caught.exception.detail); self.assertIn('docker logs', caught.exception.detail)
        self.assertEqual(store.events, [], 'no start event for a Grafana that never answered')
        disabled = GrafanaControl(FakeStore(), FakeOperations(FakeGrafana()), type('T', (), {'grafana': {'enabled': False, 'port': 0}})(), environ={})
        with self.assertRaises(HTTPException) as caught: disabled.start()
        self.assertIn('not installed', caught.exception.detail)
        with self.assertRaises(HTTPException): disabled.stop()
        self.assertFalse(disabled.status()['enabled'])

    def test_monitor_stops_grafana_after_the_idle_time_and_a_viewer_keeps_it_alive(self):
        item, grafana, operations, store = control(idle='1')
        item.start()
        item.observe()
        self.assertEqual(item.requests, 0, 'the counter baseline is taken on the first pass')
        self.clock[0] = 1000 + GRACE + 30
        grafana.requests = 5
        item.observe()
        self.assertEqual(item.last_activity, self.clock[0], 'a dashboard request counts as activity')
        self.assertEqual([c['action'] for c in operations.calls], ['start'])
        self.clock[0] += 59
        item.observe()
        self.assertEqual([c['action'] for c in operations.calls], ['start'], 'not idle yet')
        self.clock[0] += 2
        item.observe()
        self.assertEqual([c['action'] for c in operations.calls], ['start', 'stop'])
        self.assertFalse(item.status()['running']); self.assertFalse(grafana.up)
        self.assertEqual(store.events[-1][0], 'grafana.stop'); self.assertIn('after 1 minute without an open dashboard', store.events[-1][1])
        # Stopped: the monitor keeps probing without touching the helper.
        self.clock[0] += 3600
        item.observe()
        self.assertEqual(len(operations.calls), 2)

    def test_grace_period_idle_off_and_a_hand_started_grafana(self):
        item, grafana, operations, store = control(idle='1')
        item.start()
        self.clock[0] = 1000 + 75      # past the idle minute, inside the grace period after a start
        item.observe()
        self.assertEqual([c['action'] for c in operations.calls], ['start'], 'a fresh start is not stopped before a viewer could arrive')
        item, grafana, operations, store = control(idle='0')
        item.start(); self.clock[0] += 100000; item.observe()
        self.assertEqual([c['action'] for c in operations.calls], ['start'], 'idle 0 never stops')
        self.assertIn('automatic stop is off', item.status()['message'])
        item, grafana, operations, store = control(idle='1')
        grafana.up = True               # started by hand on the VM, or before a manager restart
        item.observe()
        self.assertTrue(item.status()['running']); self.assertEqual(item.started_at, self.clock[0])
        self.assertEqual(operations.calls, [])
        self.clock[0] += GRACE + 61
        item.observe()
        self.assertEqual([c['action'] for c in operations.calls], ['stop'], 'found running, then idle: stopped like any other')

    def test_a_failing_idle_stop_is_reported_and_retried_later(self):
        item, grafana, operations, store = control(idle='1')
        item.start()
        self.clock[0] += GRACE + 61
        operations.fail = 'Cannot reach the VM operations helper. Check setup and SSH settings.'
        item.observe()
        self.assertIn('Cannot reach the VM', item.status()['error'])
        self.assertEqual([c['action'] for c in operations.calls], ['start', 'stop'])
        self.clock[0] += 60
        item.observe()
        self.assertEqual(len(operations.calls), 2, 'no retry storm while the helper is unreachable')
        self.clock[0] += 300; operations.fail = None
        item.observe()
        self.assertEqual([c['action'] for c in operations.calls], ['start', 'stop', 'stop'])
        self.assertEqual(item.status()['error'], '')


class ApiTests(unittest.TestCase):
    def test_routes_follow_the_control_and_the_stack_setting(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.dict(os.environ, {'TELEMETRY_STACK': '', 'TELEMETRY_GRAFANA_IDLE_MINUTES': ''}):
                app = create_app(folder)
            client = TestClient(app)
            try:
                status = client.get('/api/telemetry/grafana').json()
                self.assertFalse(status['enabled']); self.assertIn('not installed', status['message'])
                self.assertEqual(client.post('/api/telemetry/grafana/start', json={}).status_code, 409)
            finally:
                app.state.grafana.close(); app.state.telemetry.close(); app.state.git_progress.close(); app.state.operations.close()
                app.state.discovery.close(); app.state.runner.close(); app.state.node_services.close(); client.close()
        with tempfile.TemporaryDirectory() as folder:
            with patch.dict(os.environ, {'TELEMETRY_STACK': 'grafana', 'TELEMETRY_GRAFANA_PORT': '3000', 'TELEMETRY_GRAFANA_IDLE_MINUTES': '7'}):
                app = create_app(folder)
            client = TestClient(app)
            try:
                grafana = FakeGrafana(); operations = FakeOperations(grafana)
                app.state.grafana.opener = grafana; app.state.grafana.operations = operations
                with patch.object(module.time, 'sleep'):
                    started = client.post('/api/telemetry/grafana/start', json={})
                self.assertEqual(started.status_code, 200, started.text)
                self.assertEqual((started.json()['running'], started.json()['idle_minutes'], started.json()['port']), (True, 7, 3000))
                self.assertEqual(client.get('/api/telemetry/grafana').json()['running'], True)
                stopped = client.post('/api/telemetry/grafana/stop', json={})
                self.assertEqual(stopped.status_code, 200, stopped.text); self.assertFalse(stopped.json()['running'])
                self.assertEqual([c['action'] for c in operations.calls], ['start', 'stop'])
                events = [e['action'] for e in app.state.store.events()]
                self.assertIn('grafana.start', events); self.assertIn('grafana.stop', events)
                self.assertEqual(client.post('/api/telemetry/grafana/start', json={}, headers={'Origin': 'https://other.example'}).status_code, 403)
            finally:
                app.state.grafana.close(); app.state.telemetry.close(); app.state.git_progress.close(); app.state.operations.close()
                app.state.discovery.close(); app.state.runner.close(); app.state.node_services.close(); client.close()


if __name__ == '__main__':
    unittest.main()
