"""Automatic NOS login readiness: probes, SSH gating, restarts and the one-time login test."""
import os
from pathlib import Path
import tempfile
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
