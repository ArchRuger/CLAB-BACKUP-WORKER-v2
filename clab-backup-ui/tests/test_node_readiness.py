"""Automatic NOS login readiness: probes, SSH gating, restarts and the one-time login test."""
import os
from datetime import datetime, timezone
from pathlib import Path
import socket
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import paramiko
from fastapi.testclient import TestClient

from app.main import create_app
from app.node_readiness import MAX_TEST_ATTEMPTS, REFUSALS_BEFORE_FAILED, cli_answers, login_state, summarize
from app.runner import job_environment, effective_credentials, credential_source
from app.inventory import IMAGE_DEFAULT_CREDENTIALS, DEFAULT_CREDENTIALS, image_default_credentials, image_repository


class Inline:
    """Runs probes on the calling thread so one scan is deterministic."""
    def submit(self, fn, *args):
        fn(*args)

    def shutdown(self, **kwargs):
        pass


def node(short, address, platform='arista_ceos'):
    return dict(name='clab-demo-' + short, short_name=short, definition_node=short, address=address, port=22,
                platform=platform, enabled=bool(platform), profile_id='', username='', password='', enable_password='',
                groups=[], endpoint_mode='auto', discovered=True, runtime_state='running', discovered_address=address)


class ReadinessTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = create_app(self.tmp.name)
        self.client = TestClient(self.app)
        self.store = self.app.state.store
        self.monitor = self.app.state.readiness
        self.monitor.pool = Inline()
        self.answers = {}
        self.probes = []

        def probe(item, creds):
            self.probes.append((item['name'], creds['username'], creds['password']))
            return self.answers.get(item['name'], 'booting')
        self.monitor.probe = probe
        self.lab = dict(id='lab', name='demo', deployment_name='demo', container_prefix='clab', profiles=[], defaults={},
                        interval=0, next_run=None, nodes=[node('r1', '172.20.20.2'), node('r2', '172.20.20.3')])
        self.store.state['labs'].append(self.lab)
        self.store.state['host'] = dict(address='127.0.0.1', port=22, username='clab-discovery', auth='password',
                                        password='vm-secret', enabled=True, command_mode='helper',
                                        fingerprint='SHA256:fixture', revision='r1')
        self.store.state['discovery'] = dict(
            ok=True, error='', checked_epoch=time.time(), checked_at='now', last_success='now',
            labs={'demo': [dict(name=n['name'], address=n['address'], state='running', kind='ceos') for n in self.lab['nodes']]})
        self.store.save()

    def tearDown(self):
        for service in ('git_progress', 'operations', 'discovery', 'readiness', 'node_services', 'runner'):
            getattr(self.app.state, service).close()
        self.client.close()
        self.tmp.cleanup()

    def public(self):
        return next(l for l in self.client.get('/api/state').json()['labs'] if l['id'] == 'lab')

    def test_jobs(self):
        return [j for j in self.store.state['jobs'] if j['operation'] == 'test']

    def rescan(self):
        self.monitor.retry_at.clear()
        self.monitor.scan()

    def test_running_nodes_are_probed_with_the_default_login_and_ssh_waits_for_an_answer(self):
        before = self.public()
        self.assertEqual([n['credential_source'] for n in before['nodes']], ['default', 'default'])
        self.assertTrue(all(n['login_configured'] for n in before['nodes']))
        self.assertFalse(any(n['ssh_ready'] for n in before['nodes']))
        self.assertEqual(before['nos_readiness'], {'status': 'booting', 'total': 2, 'ready': 0, 'booting': 2, 'failed': 0})
        with patch.object(self.app.state.runner.pool, 'submit') as submit:
            self.monitor.scan()
            self.assertEqual(sorted(self.probes), [('clab-demo-r1', 'admin', 'admin'), ('clab-demo-r2', 'admin', 'admin')])
            self.monitor.scan()   # inside the retry window: no second probe yet
            self.assertEqual(len(self.probes), 2)
            self.answers = {'clab-demo-r1': 'reachable'}
            self.rescan()
            middle = self.public()
            self.assertEqual([n['ssh_ready'] for n in middle['nodes']], [True, False])
            self.assertEqual(middle['nodes'][1]['nos_login']['status'], 'booting')
            self.assertEqual(middle['nos_readiness']['status'], 'booting')
            submit.assert_not_called()
            self.answers['clab-demo-r2'] = 'reachable'
            self.rescan()
            after = self.public()
            self.assertTrue(all(n['ssh_ready'] for n in after['nodes']))
            self.assertEqual(after['nos_readiness']['status'], 'ready')
            self.assertEqual(len(self.test_jobs()), 1)
            self.assertEqual(len(self.test_jobs()[0]['nodes']), 2)
            submit.assert_called_once()
            self.rescan(); self.rescan()
            self.assertEqual(len(self.test_jobs()), 1, 'the automatic login test runs once per boot')
        health = self.client.get('/api/labs/lab/health').json()['nodes'][0]['ssh']
        self.assertEqual((health['status'], health['source']), ('reachable', 'automatic'))
        text = self.client.get('/api/logs?lab_id=lab').text
        self.assertIn('automatic NOS login test started', text)
        self.assertIn('NOS accepted SSH login', text)

    def test_a_manual_login_that_found_the_cli_silent_is_probed_and_corrected_by_the_monitor(self):
        # M-11: Test login stores 'booting' (not 'reachable') while the CLI is silent, so the monitor,
        # which skips only 'reachable' nodes, keeps asking and replaces it with the real answer.
        from app.node_services import BOOTING_MESSAGE
        services = self.app.state.node_services
        services.checks[('lab', 'clab-demo-r1')] = {'status': 'booting', 'at': 'then', 'message': BOOTING_MESSAGE}
        with patch.object(self.app.state.runner.pool, 'submit'):
            self.assertEqual(self.public()['nodes'][0]['nos_login']['status'], 'booting')
            self.assertFalse(self.public()['nodes'][0]['ssh_ready'])
            self.answers = {'clab-demo-r1': 'reachable'}
            self.monitor.scan()
        self.assertIn('clab-demo-r1', [p[0] for p in self.probes])
        self.assertEqual(services.checks[('lab', 'clab-demo-r1')]['status'], 'reachable')
        self.assertTrue(self.public()['nodes'][0]['ssh_ready'])

    def test_a_restarted_node_must_answer_again_and_the_login_test_repeats_once(self):
        self.answers = {n['name']: 'reachable' for n in self.lab['nodes']}
        with patch.object(self.app.state.runner.pool, 'submit'):
            self.monitor.scan()
            self.assertEqual(self.public()['nos_readiness']['status'], 'ready')
            self.assertEqual(len(self.test_jobs()), 1)
            self.store.state['jobs'].clear()
            # Discovery sees r2 stop and come back: a redeploy or a docker restart.
            self.lab['nodes'][1].update(runtime_state='exited')
            self.rescan()
            self.assertEqual([n['nos_login']['status'] for n in self.public()['nodes']], ['ready', 'unavailable'])
            self.lab['nodes'][1].update(runtime_state='running')
            self.answers['clab-demo-r2'] = 'booting'
            self.rescan()
            self.assertEqual(self.public()['nodes'][1]['nos_login']['status'], 'booting')
            self.assertFalse(self.public()['nodes'][1]['ssh_ready'])
            self.assertTrue(self.public()['nodes'][0]['ssh_ready'], 'the node that kept running stays ready')
            self.answers['clab-demo-r2'] = 'reachable'
            self.rescan()
            self.assertEqual(self.public()['nos_readiness']['status'], 'ready')
            self.assertEqual(len(self.test_jobs()), 1, 'a new boot cycle earns one new login test')

    def test_a_login_proof_from_before_a_restart_epoch_is_dropped_and_the_uptime_reveals_an_external_restart(self):
        key = ('lab', 'clab-demo-r1'); self.answers = {n['name']: 'reachable' for n in self.lab['nodes']}
        # A probe in flight when a Restart device job is accepted: forget() during the probe starts a new epoch.
        real = self.monitor.probe
        def late(item, creds):
            if item['name'] == 'clab-demo-r1': self.monitor.forget(key)
            return real(item, creds)
        self.monitor.probe = late
        with patch.object(self.app.state.runner.pool, 'submit'):
            self.monitor.scan()
            with self.app.state.node_services.lock: checks = dict(self.app.state.node_services.checks)
            self.assertNotIn(key, checks, 'the answer from before the epoch never marks the restarted device ready')
            self.assertEqual(checks[('lab', 'clab-demo-r2')]['status'], 'reachable')
            self.monitor.probe = real; self.rescan()
            with self.app.state.node_services.lock: self.assertEqual(self.app.state.node_services.checks[key]['status'], 'reachable', 'the next probe counts')
            self.assertEqual(self.public()['nodes'][0]['nos_login']['status'], 'ready')
            # An external restart (VS Code, the CLI): the same container id, running throughout, but the runtime says it is 5 s old.
            self.store.state['discovery']['checked_epoch'] = time.time() + 600
            self.lab['nodes'][0]['runtime_status'] = 'Up 5 seconds'
            self.answers['clab-demo-r1'] = 'booting'
            self.rescan()
            self.assertEqual(self.public()['nodes'][0]['nos_login']['status'], 'booting', 'the old proof is gone; the device must answer again')
            self.assertEqual(self.public()['nodes'][1]['nos_login']['status'], 'ready', 'the neighbour keeps its proof')
            # Once it answers again it is ready; a coarse or old uptime, or none, says nothing more.
            self.answers['clab-demo-r1'] = 'reachable'; self.rescan(); self.assertEqual(self.public()['nodes'][0]['nos_login']['status'], 'ready')
            for status in ('Up 2 hours', 'Up 3 days', '', 'Exited (0) 2 minutes ago', 'Up About an hour'):
                self.lab['nodes'][0]['runtime_status'] = status; self.store.state['discovery']['checked_epoch'] = time.time() + 7200; self.rescan()
                self.assertEqual(self.public()['nodes'][0]['nos_login']['status'], 'ready', status)
            # A minutes value is floored by the runtime: a proof from just before that start is still trusted (a minute of margin).
            self.store.state['discovery']['checked_epoch'] = time.time() + 130; self.lab['nodes'][0]['runtime_status'] = 'Up 2 minutes'; self.rescan()
            self.assertEqual(self.public()['nodes'][0]['nos_login']['status'], 'ready', 'checked 130 s later, up 120 s: the start is not 60 s after the proof')
            # The start is measured from the moment the discovery pass began, not from its end: a slow pass never
            # turns a proof taken after the start into a "restart" (the review's reproducer: proven 1.5 s after the
            # start, "Up About a minute" at 119.5 s, the pass ending 2.5 s later).
            base = time.time(); proof = {'status': 'reachable', 'at': datetime.fromtimestamp(base + 1.5, timezone.utc).isoformat()}
            slow = {'discovery': {'inspected_epoch': base + 119.5, 'checked_epoch': base + 122}}
            self.assertFalse(self.monitor.restarted_since(slow, {'runtime_status': 'Up About a minute'}, proof))
            self.assertTrue(self.monitor.restarted_since({'discovery': {'inspected_epoch': base + 300, 'checked_epoch': base + 302}}, {'runtime_status': 'Up 5 seconds'}, proof), 'a real restart 5 s before a pass is seen')
            self.assertFalse(self.monitor.restarted_since({'discovery': {'checked_epoch': base + 122}}, {'runtime_status': 'Up About a minute'}, {'status': 'reachable', 'at': datetime.fromtimestamp(base + 61.5, timezone.utc).isoformat()}), 'without inspected_epoch the pass end is used, with the same margin')

    def test_a_device_with_a_restart_job_reads_restarting_and_counts_as_booting(self):
        self.assertEqual(summarize([{'status': 'ready'}, {'status': 'restarting'}]), {'status': 'booting', 'total': 2, 'ready': 1, 'booting': 1, 'failed': 0})
        self.store.state['operations'] = [dict(id='op', lab_id='lab', action='restart-node', node='clab-demo-r1', node_label='r1', status='running')]
        self.answers = {n['name']: 'reachable' for n in self.lab['nodes']}
        with patch.object(self.app.state.runner.pool, 'submit'):
            self.rescan()
            nodes = self.public()['nodes']
            self.assertEqual(nodes[0]['nos_login']['status'], 'restarting'); self.assertFalse(nodes[0]['ssh_ready'])
            self.assertIn('containerlab restart --node', nodes[0]['nos_login']['message'])
            self.assertEqual(nodes[1]['nos_login']['status'], 'booting', 'the lab is busy while the job runs, so no probe has run yet for the neighbour either')
            self.assertEqual(self.public()['nos_readiness']['status'], 'booting')
            self.store.state['operations'][0]['status'] = 'succeeded'
            self.assertEqual(self.public()['nodes'][0]['nos_login']['status'], 'booting', 'after the job the device reads Starting until it answers again (no proof exists yet)')
            self.rescan()
            self.assertEqual([n['nos_login']['status'] for n in self.public()['nodes']], ['ready', 'ready'], 'the lab is free again: both devices are probed and answer')

    def test_a_refused_login_right_after_a_manager_restart_reads_booting_until_the_grace_window_closes(self):
        # QA-019: IOS XR answers SSH for minutes before it accepts any login. After a restart, start or deploy the
        # manager itself performed (forget() marks the epoch), a refused login is the boot, not wrong credentials.
        from app.node_readiness import LOGIN_GRACE
        key = ('lab', 'clab-demo-r1'); self.answers = {'clab-demo-r1': 'failed', 'clab-demo-r2': 'reachable'}
        with patch.object(self.app.state.runner.pool, 'submit'):
            self.monitor.forget(key)
            for _ in range(REFUSALS_BEFORE_FAILED + 2):
                self.rescan()
                login = self.public()['nodes'][0]['nos_login']
                self.assertEqual(login['status'], 'booting', login)
                self.assertIn('not accepted yet', login['message'])
            self.assertEqual(self.monitor.refusals.get(key, 0), 0, 'the count does not start inside the window')
            # Once the window is over the ordinary rule applies: three refusals in a row are a failure.
            later = time.monotonic() + LOGIN_GRACE + 1
            with patch('app.node_readiness.time.monotonic', return_value=later):
                for attempt in range(REFUSALS_BEFORE_FAILED):
                    self.rescan()
                    status = self.public()['nodes'][0]['nos_login']['status']
                    self.assertEqual(status, 'booting' if attempt < REFUSALS_BEFORE_FAILED - 1 else 'failed', attempt)
            # A device the manager never touched gets no window: test_a_refused_login_is_reported_only_when_it_persists… above.

    def test_a_refused_login_is_reported_only_when_it_persists_and_never_opens_ssh(self):
        self.answers = {'clab-demo-r1': 'failed', 'clab-demo-r2': 'reachable'}
        with patch.object(self.app.state.runner.pool, 'submit') as submit:
            for attempt in range(REFUSALS_BEFORE_FAILED):
                self.rescan()
                status = self.public()['nodes'][0]['nos_login']['status']
                self.assertEqual(status, 'booting' if attempt < REFUSALS_BEFORE_FAILED - 1 else 'failed', attempt)
            public = self.public()
            self.assertEqual([n['ssh_ready'] for n in public['nodes']], [False, True])
            self.assertTrue(public['nodes'][0]['login_configured'], 'Test login stays available to retry by hand')
            self.assertEqual(public['nos_readiness']['status'], 'failed')
            submit.assert_not_called()
            # Fixing the login (a profile) is picked up by the next probe; the lab test then runs.
            self.answers['clab-demo-r1'] = 'reachable'
            self.rescan()
            self.assertEqual(self.public()['nos_readiness']['status'], 'ready')
            submit.assert_called_once()

    def test_profiles_win_over_defaults_and_nodes_without_any_login_are_not_probed(self):
        self.lab['profiles'] = [dict(id='p', label='Custom', platform='arista_ceos', username='ops', auth='password',
                                     password='ops-secret', private_key='', passphrase='', enable_password='')]
        self.lab['defaults'] = {'arista_ceos': 'p'}
        self.lab['nodes'][1]['platform'] = ''
        self.store.save()
        self.monitor.scan()
        self.assertEqual(self.probes, [('clab-demo-r1', 'ops', 'ops-secret')])
        public = self.public()
        self.assertEqual(public['nodes'][1]['nos_login']['status'], 'needs_credentials')
        self.assertFalse(public['nodes'][1]['login_configured'])
        self.assertNotIn('ops-secret', self.client.get('/api/state').text)
        self.assertNotIn('ops-secret', self.client.get('/api/logs').text)

    def test_unlinked_labs_and_busy_operations_are_left_alone(self):
        self.lab.pop('deployment_name')
        self.monitor.scan()
        self.assertEqual(self.probes, [])
        public = self.public()
        self.assertTrue(all(n['ssh_ready'] for n in public['nodes']), 'without a deployment a configured login still offers SSH')
        self.assertEqual(public['nos_readiness']['status'], 'idle')
        self.lab['deployment_name'] = 'demo'
        self.store.state['operations'] = [dict(id='op', lab_id='lab', status='running', action='deploy')]
        self.monitor.scan()
        self.assertEqual(self.probes, [], 'no probes while a deploy or destroy runs on the VM')
        self.store.state['operations'] = []
        self.store.state['discovery']['checked_epoch'] = time.time() - 1000
        self.monitor.scan()
        self.assertEqual(self.probes, [], 'stale discovery is not evidence that a node runs')

    def test_a_failed_automatic_login_test_sends_nodes_back_to_booting_and_retries_a_bounded_number_of_times(self):
        self.answers = {n['name']: 'reachable' for n in self.lab['nodes']}
        with patch.object(self.app.state.runner.pool, 'submit'):
            self.monitor.scan()
            self.assertEqual(len(self.test_jobs()), 1)
            self.assertEqual(self.test_jobs()[0]['source'], 'automatic')
            # The driver refused the nodes (the host-key mismatch of 1.21.1): only r2 failed.
            job = self.test_jobs()[0]
            job.update(status='partial', finished='t')
            job['nodes'][1]['status'] = 'failed'
            self.store.save()
            self.answers['clab-demo-r2'] = 'booting'
            self.monitor.scan()
            public = self.public()
            self.assertEqual([n['nos_login']['status'] for n in public['nodes']], ['ready', 'booting'])
            self.assertEqual([n['ssh_ready'] for n in public['nodes']], [True, False])
            self.assertEqual(len(self.test_jobs()), 1, 'no new test while a node is back in booting')
            self.assertIn('checking them again', self.client.get('/api/logs?lab_id=lab').text)
            self.answers['clab-demo-r2'] = 'reachable'
            self.rescan()
            self.assertEqual(len(self.test_jobs()), 2, 'the test runs again once the node answers')
            # Persistent failures stop after a bounded number of attempts.
            for expected in range(3, MAX_TEST_ATTEMPTS + 2):
                job = self.test_jobs()[0]
                job.update(status='failed', finished='t')
                for item in job['nodes']: item['status'] = 'failed'
                self.store.save()
                self.rescan()
                self.assertEqual(len(self.test_jobs()), min(expected, MAX_TEST_ATTEMPTS))
            self.assertIn('failed repeatedly', self.client.get('/api/logs?lab_id=lab').text)
            self.assertTrue(all(n['ssh_ready'] for n in self.public()['nodes']), 'nodes that answer keep SSH open')
            # A new boot cycle (the lab was redeployed) starts the budget again.
            self.lab['nodes'][0].update(runtime_state='exited'); self.rescan()
            self.lab['nodes'][0].update(runtime_state='running'); self.rescan()
            self.assertEqual(len(self.test_jobs()), MAX_TEST_ATTEMPTS + 1)

    def test_login_state_and_summary_vocabulary(self):
        lab = dict(deployment_name='demo', profiles=[], defaults={})
        item = node('r1', '172.20.20.2')
        self.assertEqual(login_state({'profiles': [], 'defaults': {}}, item, True, None)['status'], 'unmonitored')
        self.assertEqual(login_state(lab, item, False, None)['status'], 'unavailable')
        self.assertEqual(login_state(lab, dict(item, platform=''), True, None)['status'], 'needs_credentials')
        self.assertEqual(login_state(lab, item, True, None)['status'], 'booting')
        self.assertEqual(login_state(lab, item, True, {'status': 'reachable', 'at': 't', 'message': 'ok'}),
                         {'status': 'ready', 'message': 'ok', 'at': 't'})
        self.assertEqual(login_state(lab, item, True, {'status': 'failed', 'at': 't', 'message': 'no'})['status'], 'failed')
        # 'checking': ssh-check-all (or a manual Test login) is answering right now; never a real
        # answer by itself, so it must never read as 'ready' or 'unmonitored'.
        checking = login_state(lab, item, True, {'status': 'checking', 'at': 't', 'message': 'Testing the SSH login…'})
        self.assertEqual(checking, {'status': 'checking', 'message': 'Testing the SSH login…', 'at': 't'})
        self.assertEqual(summarize([])['status'], 'idle')
        self.assertEqual(summarize([{'status': 'unmonitored'}, {'status': 'unavailable'}])['status'], 'idle')
        self.assertEqual(summarize([{'status': 'ready'}, {'status': 'booting'}])['status'], 'booting')
        self.assertEqual(summarize([{'status': 'ready'}, {'status': 'failed'}]), {'status': 'failed', 'total': 2, 'ready': 1, 'booting': 0, 'failed': 1})
        self.assertEqual(summarize([{'status': 'ready'}, {'status': 'ready'}])['status'], 'ready')
        # A node being tested counts with 'booting' at the lab level: the total does not shrink
        # while a refresh is in flight, and one node "checking" alongside a failed node still reads
        # as 'booting' overall (not 'failed') because it might still turn out ready.
        self.assertEqual(summarize([{'status': 'ready'}, {'status': 'checking'}]), {'status': 'booting', 'total': 2, 'ready': 1, 'booting': 1, 'failed': 0})
        self.assertEqual(summarize([{'status': 'checking'}])['status'], 'booting')

    def test_image_default_login_reaches_ready_while_a_different_linux_image_still_needs_credentials(self):
        multitool = next(iter(IMAGE_DEFAULT_CREDENTIALS))
        self.lab['nodes'].append(dict(node('host1', '172.20.20.9', platform=''), image=multitool + ':latest'))
        self.lab['nodes'].append(dict(node('host2', '172.20.20.10', platform=''), image='ghcr.io/library/alpine'))
        self.store.state['discovery']['labs']['demo'] += [
            dict(name='clab-demo-host1', address='172.20.20.9', state='running', kind='linux'),
            dict(name='clab-demo-host2', address='172.20.20.10', state='running', kind='linux')]
        self.store.save()
        before = self.public()
        host1 = next(n for n in before['nodes'] if n['name'] == 'clab-demo-host1')
        host2 = next(n for n in before['nodes'] if n['name'] == 'clab-demo-host2')
        self.assertEqual(host1['credential_source'], 'default')
        self.assertTrue(host1['login_configured'])
        self.assertNotEqual(host1['nos_login']['status'], 'needs_credentials')
        self.assertEqual(host2['credential_source'], '')
        self.assertEqual(host2['nos_login']['status'], 'needs_credentials')
        with patch.object(self.app.state.runner.pool, 'submit'):
            self.answers = {n['name']: 'reachable' for n in self.lab['nodes']}
            self.monitor.scan()
        self.assertIn(('clab-demo-host1', 'admin', IMAGE_DEFAULT_CREDENTIALS[multitool][1]), self.probes)
        after = next(n for n in self.public()['nodes'] if n['name'] == 'clab-demo-host1')
        self.assertEqual(after['nos_login']['status'], 'ready')
        self.assertTrue(after['ssh_ready'])

    def test_ssh_check_all_reflects_through_nos_login_as_checking_then_a_real_answer(self):
        # A refresh in flight (node_services.py ssh-check-all) shows through the same nos_login and
        # ssh_ready a deployed lab already uses: 'checking' while it runs, never optimistic, and a
        # real answer (or a real refusal) once it is done — one node's failure does not stop the other.
        services = self.app.state.node_services
        release = threading.Event()

        def fake_connect(client, item, creds):
            release.wait(2)
            if item['name'] == 'clab-demo-r2':
                raise ValueError('nope')

        with patch('app.node_services.connect', side_effect=fake_connect), patch('app.node_services.cli_answers', return_value=True):
            result = self.client.post('/api/labs/lab/ssh-check-all', json={})
            self.assertEqual(result.status_code, 200, result.text)
            self.assertEqual(result.json()['started'], 2)
            keys = [('lab', 'clab-demo-r1'), ('lab', 'clab-demo-r2')]
            deadline = time.monotonic() + 2
            while not all(k in services.checking for k in keys) and time.monotonic() < deadline:
                time.sleep(0.01)
            during = self.public()
            self.assertEqual([n['nos_login']['status'] for n in during['nodes']], ['checking', 'checking'])
            self.assertFalse(any(n['ssh_ready'] for n in during['nodes']), 'a refresh in flight never marks a device ready')
            release.set()
            deadline = time.monotonic() + 2
            while services.checking_all and time.monotonic() < deadline:
                time.sleep(0.01)
        after = self.public()
        self.assertEqual([n['nos_login']['status'] for n in after['nodes']], ['ready', 'failed'])
        self.assertEqual([n['ssh_ready'] for n in after['nodes']], [True, False])


class Stream:
    def __init__(self, data=b''):
        self.data = data

    def read(self, size):
        return self.data[:size]

    def close(self):
        pass


class FakeTransport:
    """What the check's deadline closes: closing it ends a wait inside a stalled exec or read (as paramiko's does)."""
    def __init__(self):
        self.closed = threading.Event()

    def close(self):
        self.closed.set()


class FakeClient:
    def __init__(self, output=None, error=None):
        self.output = output; self.error = error; self.commands = []; self.transport = FakeTransport()

    def get_transport(self):
        return self.transport

    def exec_command(self, command, timeout=None):
        self.commands.append((command, timeout))
        if self.error: raise self.error
        return Stream(), Stream(self.output), Stream()


class HungExecClient(FakeClient):
    """The SSH server accepted the session but never answers the exec request (paramiko waits for that reply without a
    timeout): only closing the transport ends the wait. Gives up by itself after `limit` so a missing deadline fails the
    test instead of hanging it."""
    def __init__(self, limit=3):
        super().__init__(); self.limit = limit

    def exec_command(self, command, timeout=None):
        self.commands.append((command, timeout))
        self.transport.closed.wait(self.limit)
        raise paramiko.SSHException('Channel closed.')


class TrickleStream(Stream):
    """stdout of a command whose output never ends: one byte at a time, each well inside the per-read timeout, until the
    transport closes (then what arrived so far is returned, as paramiko's buffered read does) or `limit` passes."""
    def __init__(self, transport, data, limit=3):
        super().__init__(data); self.transport = transport; self.limit = limit

    def read(self, size):
        received = b''; ends = time.monotonic() + self.limit
        while len(received) < size and time.monotonic() < ends and not self.transport.closed.wait(0.02):
            received += self.data[len(received) % len(self.data):][:1]
        return received


class TrickleClient(FakeClient):
    def __init__(self, data=b'Arista cEOSLab\n', limit=3):
        super().__init__(); self.data = data; self.limit = limit

    def exec_command(self, command, timeout=None):
        self.commands.append((command, timeout))
        return Stream(), TrickleStream(self.transport, self.data, self.limit), Stream()


class LoopbackServer(paramiko.ServerInterface):
    """A real paramiko SSH server on a socket pair: 'answer' runs the command, 'hang' never answers the exec request,
    'trickle' accepts it and then sends one byte at a time without ever finishing (each for at most `limit` seconds)."""
    key = None

    def __init__(self, mode, output=b'Arista cEOSLab\nSoftware image version: 4.35.0F\n', limit=3):
        self.mode = mode; self.output = output; self.limit = limit; self.done = threading.Event()

    def get_allowed_auths(self, username):
        return 'password'

    def check_auth_password(self, username, password):
        return paramiko.AUTH_SUCCESSFUL

    def check_channel_request(self, kind, chanid):
        return paramiko.OPEN_SUCCEEDED

    def check_channel_exec_request(self, channel, command):
        if self.mode == 'hang':
            self.done.wait(self.limit)      # blocks the server's transport thread: no reply to the exec request
            return False
        threading.Thread(target=self.respond, args=(channel,), daemon=True).start()
        return True

    def respond(self, channel):
        # paramiko sends the exec reply only after check_channel_exec_request returns; output and a close sent before it
        # would race the reply (the client then sees "Channel closed."), so this waits for it to leave first.
        time.sleep(0.2)
        try:
            if self.mode == 'answer':
                channel.sendall(self.output); channel.send_exit_status(0); channel.close(); return
            ends = time.monotonic() + self.limit
            while time.monotonic() < ends and not self.done.wait(0.05) and not channel.closed:
                channel.send(b'.')
            channel.close()
        except Exception:
            pass

    def client(self):
        """An authenticated paramiko.SSHClient talking to this server; the caller closes it and calls stop()."""
        if LoopbackServer.key is None: LoopbackServer.key = paramiko.RSAKey.generate(2048)
        near, far = socket.socketpair()
        self.transport = paramiko.Transport(far)
        self.transport.add_server_key(LoopbackServer.key)
        self.transport.start_server(event=threading.Event(), server=self)
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect('loopback', sock=near, username='admin', password='admin', allow_agent=False, look_for_keys=False, timeout=5)
        return client

    def stop(self):
        self.done.set(); self.transport.close()


class ProbeTests(unittest.TestCase):
    def test_cli_answers_requires_real_show_version_output(self):
        client = FakeClient(b'Arista cEOSLab\nSoftware image version: 4.35.0F\n')
        self.assertTrue(cli_answers(client))
        self.assertEqual(client.commands, [('show version', 25)])
        for output in (b'', b'   \n', b'% System is not yet ready. Please try again later.\n', b'error: could not connect to agent\n',
                       b'% Invalid input\n', b"Waiting for editing of configuration\n"):
            self.assertFalse(cli_answers(FakeClient(output)), output)
        self.assertFalse(cli_answers(FakeClient(error=TimeoutError('slow'))))

    def make_monitor(self, client):
        from app.node_readiness import ReadinessMonitor

        class FakeServices:
            def reserve(self):
                return client

            def release(self, given):
                pass

        return ReadinessMonitor(store=None, services=FakeServices(), runner=None)

    def test_ssh_probe_asks_show_version_only_for_a_node_with_a_nos_platform(self):
        client = FakeClient(b'Arista cEOSLab\nSoftware image version: 4.35.0F\n')
        monitor = self.make_monitor(client)
        with patch('app.node_readiness.connect'):
            status = monitor.ssh_probe({'platform': 'arista_ceos'}, {'username': 'admin', 'password': 'admin'})
        self.assertEqual(status, 'reachable')
        self.assertEqual(client.commands, [('show version', 25)])

    def test_ssh_probe_uses_a_generic_command_for_a_node_without_a_nos_platform(self):
        from app.node_readiness import GENERIC_CLI_COMMAND
        # A Linux host (kind `linux`, an unmapped kind, or a generic SSH profile) has
        # no NOS CLI; `show version` would never answer and readiness would never
        # leave 'booting'. A harmless real shell command still proves a real login.
        client = FakeClient(b'readiness-check\n')
        monitor = self.make_monitor(client)
        with patch('app.node_readiness.connect'):
            status = monitor.ssh_probe({'platform': ''}, {'username': 'admin', 'password': ''})
        self.assertEqual(status, 'reachable')
        self.assertEqual(client.commands, [(GENERIC_CLI_COMMAND, 25)])

    def test_ssh_probe_reports_failed_only_on_an_authentication_error(self):
        client = FakeClient(b'ok')
        monitor = self.make_monitor(client)
        with patch('app.node_readiness.connect', side_effect=paramiko.AuthenticationException('no')):
            self.assertEqual(monitor.ssh_probe({'platform': ''}, {'username': 'admin', 'password': 'wrong'}), 'failed')
        with patch('app.node_readiness.connect', side_effect=OSError('unreachable')):
            self.assertEqual(monitor.ssh_probe({'platform': ''}, {'username': 'admin', 'password': ''}), 'booting')

    def test_a_node_without_a_platform_is_ready_when_its_cli_answers_even_by_rejecting_the_shell_command(self):
        # N2 (M-11 follow-up): a NOS kind outside the supported four (cisco_iol or cisco_xrd from discovery, another
        # ansible_network_os from an inventory) is stored with platform ''. Its CLI rejects `echo`, and that rejection is
        # still an answering CLI: before the fix it read as a CLI error, so the node stayed 'booting' for good.
        probe = lambda client, platform='': self.make_monitor(client).ssh_probe({'platform': platform}, {'username': 'admin', 'password': 'x'})
        with patch('app.node_readiness.connect'):
            for output in (b'readiness-check\n', b"           ^\n% Invalid input detected at '^' marker.\n\nrouter#",
                           b'                    ^\nunknown command.\n', b'error: unknown command: echo\n', b'% Unrecognized command found at \'^\' position.\n'):
                self.assertEqual(probe(FakeClient(output)), 'reachable', output)
            # Still never ready without a real answer: nothing, a timeout, a refused exec or a NOS that says it is still starting.
            for output, error in ((b'', None), (b'  \n', None), (b'% System is not yet ready. Please try again later.\n', None),
                                  (b'Waiting for editing of configuration\n', None), (b'error: could not connect to agent\n', None),
                                  (None, TimeoutError('slow')), (None, paramiko.SSHException('Channel closed.'))):
                self.assertEqual(probe(FakeClient(output, error)), 'booting', output or error)
            # A supported platform keeps its rule: show version must really succeed, a CLI error is not an answer.
            for output in (b"% Invalid input detected at '^' marker.\n", b'error: unknown command\n', b'% System is not yet ready\n'):
                self.assertEqual(probe(FakeClient(output), 'arista_ceos'), 'booting', output)

    def test_a_hung_exec_request_ends_at_the_deadline_and_closes_the_transport(self):
        # N3 (M-11 follow-up): paramiko waits for the exec request's reply with no timeout of its own; without one deadline
        # on the whole check a device that accepts the session but never answers held Test login (its node key and an
        # SSH client slot) for as long as it stayed silent.
        client = HungExecClient()
        started = time.monotonic()
        self.assertFalse(cli_answers(client, timeout=0.3))
        self.assertLess(time.monotonic() - started, 1.5, 'the check ends at its deadline, not when the device gives up')
        self.assertTrue(client.transport.closed.is_set())
        with patch('app.node_readiness.connect'), patch('app.node_services.CLI_TIMEOUT', 0.3):
            started = time.monotonic()
            self.assertEqual(self.make_monitor(HungExecClient()).ssh_probe({'platform': 'arista_ceos'}, {'username': 'admin', 'password': 'x'}), 'booting')
            self.assertLess(time.monotonic() - started, 1.5, 'the stated CLI_TIMEOUT bounds the monitor probe too')

    def test_output_that_keeps_trickling_is_not_an_answer_once_the_deadline_passes(self):
        # Each byte arrives well inside the per-read timeout, so only an overall deadline stops the read.
        for platform, data in (('arista_ceos', b'Arista cEOSLab\n'), ('', b'readiness-check\n')):
            client = TrickleClient(data)
            started = time.monotonic()
            with patch('app.node_readiness.connect'), patch('app.node_services.CLI_TIMEOUT', 0.3):
                status = self.make_monitor(client).ssh_probe({'platform': platform}, {'username': 'admin', 'password': 'x'})
            self.assertEqual(status, 'booting', platform or 'no platform')
            self.assertLess(time.monotonic() - started, 1.5, platform or 'no platform')
            self.assertTrue(client.transport.closed.is_set())

    def test_an_answer_inside_the_deadline_counts_and_leaves_the_transport_open(self):
        client = FakeClient(b'Arista cEOSLab\nSoftware image version: 4.35.0F\n')
        self.assertTrue(cli_answers(client, timeout=0.3))
        time.sleep(0.5)
        self.assertFalse(client.transport.closed.is_set(), 'the deadline is cancelled once the check has its answer')

    def test_real_paramiko_answer_hung_exec_and_endless_output_against_the_deadline(self):
        # The same three cases against a real paramiko server on a socket pair: proves that closing the transport really
        # ends paramiko's own waits (the exec reply and a buffered read), not only the fakes above.
        for mode, expected in (('answer', True), ('hang', False), ('trickle', False)):
            server = LoopbackServer(mode, limit=4)
            client = server.client()
            try:
                started = time.monotonic()
                self.assertEqual(cli_answers(client, timeout=1), expected, mode)
                self.assertLess(time.monotonic() - started, 2.5, mode)
            finally:
                client.close(); server.stop()

    def test_job_environment_starts_every_ansible_run_without_recorded_host_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            env = job_environment(work, work / 'events.jsonl')
            self.assertEqual(env['HOME'], str(work))
            self.assertTrue((work / '.ssh').is_dir())
            self.assertFalse((work / '.ssh' / 'known_hosts').exists())
            self.assertEqual(env['ANSIBLE_HOST_KEY_CHECKING'], 'False')
            self.assertEqual(env['BACKUP_EVENT_FILE'], str(work / 'events.jsonl'))
            self.assertNotIn('ANSIBLE_COLLECTIONS_PATH', {k: v for k, v in env.items() if k not in os.environ},
                             'the image, not the job, decides where collections live')


class ImageDefaultCredentialTests(unittest.TestCase):
    """profile > inventory > kind default > image default > none (CLAUDE.md login order)."""

    def setUp(self):
        self.multitool = next(iter(IMAGE_DEFAULT_CREDENTIALS))
        self.lab = dict(profiles=[], defaults={})

    def test_image_repository_strips_a_tag_or_digest_but_keeps_a_registry_port(self):
        self.assertEqual(image_repository(self.multitool + ':latest'), self.multitool)
        self.assertEqual(image_repository(self.multitool), self.multitool)
        self.assertEqual(image_repository(self.multitool + '@sha256:' + 'a' * 64), self.multitool)
        self.assertEqual(image_repository('localhost:5000/team/tool:v1'), 'localhost:5000/team/tool')
        self.assertEqual(image_repository(''), '')

    def test_image_default_applies_only_to_the_exact_repository_and_only_without_a_platform(self):
        matching = {'platform': '', 'image': self.multitool + ':v2'}
        self.assertEqual(image_default_credentials(matching), IMAGE_DEFAULT_CREDENTIALS[self.multitool])
        other_image = {'platform': '', 'image': 'ghcr.io/library/alpine:latest'}
        self.assertIsNone(image_default_credentials(other_image))
        prefix_only = {'platform': '', 'image': self.multitool + '-extra'}
        self.assertIsNone(image_default_credentials(prefix_only), 'a same-prefix image is a different repository')
        has_platform = {'platform': 'arista_ceos', 'image': self.multitool}
        self.assertIsNone(image_default_credentials(has_platform), 'a device kind never reaches the image table')
        self.assertIsNone(image_default_credentials({'platform': '', 'image': ''}))

    def test_precedence_profile_then_inventory_then_kind_default_then_image_default(self):
        node = {'profile_id': '', 'platform': '', 'image': self.multitool, 'username': '', 'password': ''}
        # No profile, no inventory login, no kind default (platform is empty): image default applies.
        creds = effective_credentials(self.lab, node)
        self.assertEqual((creds['username'], creds['password']), IMAGE_DEFAULT_CREDENTIALS[self.multitool])
        self.assertEqual(credential_source(self.lab, node), 'default')
        # Inventory credentials win over the image default.
        with_inventory = dict(node, username='inv-user', password='inv-pass')
        self.assertEqual(effective_credentials(self.lab, with_inventory), {'username': 'inv-user', 'password': 'inv-pass',
                                                                            'auth': 'password', 'enable_password': ''})
        self.assertEqual(credential_source(self.lab, with_inventory), 'inventory')
        # A profile wins over both.
        profiled_lab = dict(self.lab, profiles=[{'id': 'p', 'label': 'Ops', 'platform': '', 'username': 'ops',
                                                  'auth': 'password', 'password': 'ops-secret'}])
        with_profile = dict(node, profile_id='p')
        self.assertEqual(effective_credentials(profiled_lab, with_profile)['username'], 'ops')
        self.assertEqual(credential_source(profiled_lab, with_profile), 'profile')
        # A node with a real NOS kind default never falls through to the image table,
        # even if (implausibly) it also named this image.
        kind_default_node = {'profile_id': '', 'platform': 'arista_ceos', 'image': self.multitool, 'username': '', 'password': ''}
        eos_user, eos_password = DEFAULT_CREDENTIALS['arista_ceos']
        creds = effective_credentials(self.lab, kind_default_node)
        self.assertEqual((creds['username'], creds['password']), (eos_user, eos_password))
        # No profile, no inventory, no kind default and no matching image: nothing applies.
        self.assertEqual(effective_credentials(self.lab, {'profile_id': '', 'platform': '', 'image': '',
                                                            'username': '', 'password': ''}), {})
        self.assertEqual(credential_source(self.lab, {'profile_id': '', 'platform': '', 'image': '',
                                                       'username': '', 'password': ''}), '')

    def test_a_tag_variant_still_matches_but_a_different_image_does_not(self):
        for tag in (':latest', ':v1.2.3', ''):
            node = {'profile_id': '', 'platform': '', 'image': self.multitool + tag, 'username': '', 'password': ''}
            self.assertEqual(credential_source(self.lab, node), 'default', tag)
        different = {'profile_id': '', 'platform': '', 'image': 'ghcr.io/library/alpine:latest', 'username': '', 'password': ''}
        self.assertEqual(credential_source(self.lab, different), '')
        self.assertEqual(effective_credentials(self.lab, different), {})


if __name__ == '__main__':
    unittest.main()
