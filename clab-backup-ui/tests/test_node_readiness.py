"""Automatic NOS login readiness: probes, SSH gating, restarts and the one-time login test."""
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import create_app
from app.node_readiness import MAX_TEST_ATTEMPTS, REFUSALS_BEFORE_FAILED, cli_answers, login_state, summarize
from app.runner import job_environment


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
        self.assertEqual(summarize([])['status'], 'idle')
        self.assertEqual(summarize([{'status': 'unmonitored'}, {'status': 'unavailable'}])['status'], 'idle')
        self.assertEqual(summarize([{'status': 'ready'}, {'status': 'booting'}])['status'], 'booting')
        self.assertEqual(summarize([{'status': 'ready'}, {'status': 'failed'}]), {'status': 'failed', 'total': 2, 'ready': 1, 'booting': 0, 'failed': 1})
        self.assertEqual(summarize([{'status': 'ready'}, {'status': 'ready'}])['status'], 'ready')


class Stream:
    def __init__(self, data=b''):
        self.data = data

    def read(self, size):
        return self.data[:size]

    def close(self):
        pass


class FakeClient:
    def __init__(self, output=None, error=None):
        self.output = output; self.error = error; self.commands = []

    def exec_command(self, command, timeout=None):
        self.commands.append((command, timeout))
        if self.error: raise self.error
        return Stream(), Stream(self.output), Stream()


class ProbeTests(unittest.TestCase):
    def test_cli_answers_requires_real_show_version_output(self):
        client = FakeClient(b'Arista cEOSLab\nSoftware image version: 4.35.0F\n')
        self.assertTrue(cli_answers(client))
        self.assertEqual(client.commands, [('show version', 25)])
        for output in (b'', b'   \n', b'% System is not yet ready. Please try again later.\n', b'error: could not connect to agent\n',
                       b'% Invalid input\n', b"Waiting for editing of configuration\n"):
            self.assertFalse(cli_answers(FakeClient(output)), output)
        self.assertFalse(cli_answers(FakeClient(error=TimeoutError('slow'))))

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


if __name__ == '__main__':
    unittest.main()
