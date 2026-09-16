"""Tests for the restore service: source validation, node mapping, guards, the
mandatory pre-restore backup, apply/verify orchestration, redaction and reconciliation.
The Junos driver and the SSH transport are faked; the driver itself is covered by
test_restore_junos.py.
"""
import copy
import time
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.store import Store
from app.restore import RestoreService, compare_states, mask_line, set_lines

DESIRED_SET = ('set system host-name FINAL\n'
               'set system login user admin authentication encrypted-password "$6$loginhash"\n'
               'set snmp contact FINAL-CONTACT\n')
DESIRED_HIER = ('system {\n    host-name FINAL;\n    login {\n        user admin {\n'
                '            authentication { encrypted-password "$6$loginhash"; }\n        }\n    }\n}\n'
                'snmp { contact FINAL-CONTACT; }\n')


class FakeRunner:
    """Stands in for Runner.submit: writes a completed backup job with restore artifacts."""
    def __init__(self, store, post_config=DESIRED_SET, fail_nodes=()):
        self.store = store
        self.post_config = post_config
        self.fail_nodes = set(fail_nodes)
        self.calls = []

    def submit(self, lab_id, operation='backup', source='manual', node_names=None,
               progress_id=None, progress_context=None):
        self.calls.append(dict(source=source, node_names=list(node_names or [])))
        job_id = uuid.uuid4().hex
        folder = self.store.root / 'backups' / lab_id / 'history' / job_id
        folder.mkdir(parents=True, exist_ok=True)
        lab = self.store.lab(lab_id)
        nodes = []
        for index, node in enumerate(lab['nodes']):
            if node_names and node['name'] not in node_names:
                continue
            if node['name'] in self.fail_nodes:
                nodes.append(dict(name=node['name'], status='failed', message='capture failed'))
                continue
            name = f'cfg-{index}.set'
            body = self.post_config if source == 'restore-post' else DESIRED_SET
            (folder / name).write_text(body, encoding='utf-8')
            rname = f'cfg-{index}.jcfg'
            (folder / rname).write_text(DESIRED_HIER, encoding='utf-8')
            nodes.append(dict(name=node['name'], status='succeeded', file=name, restore_file=rname,
                              restore_format='junos-hierarchical', platform=node['platform'],
                              short_name=node['name'], captured_at='2026-09-16T00:00:00+00:00'))
        status = 'succeeded' if all(n['status'] == 'succeeded' for n in nodes) else 'partial' if any(
            n['status'] == 'succeeded' for n in nodes) else 'failed'
        job = dict(id=job_id, lab_id=lab_id, lab_name=lab['name'], operation='backup', source=source,
                   status=status, created='2026-09-16T00:00:00+00:00', finished='2026-09-16T00:01:00+00:00',
                   nodes=nodes, progress_id=progress_id)
        self.store.state['jobs'].insert(0, job)
        self.store.save()
        return copy.deepcopy(job)


def fake_connect(client, node, creds):
    return None


class RestoreServiceTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(self.tmp.name)
        now = time.time()
        self.store.state['host'] = {'enabled': True, 'address': '10.0.0.1', 'port': 22,
                                    'username': 'clab', 'password': 'vm-secret', 'fingerprint': 'SHA256:fix',
                                    'auth': 'password'}
        self.lab = {'id': 'lab1', 'name': 'clabllm-dev', 'deployment_name': 'clabllm-dev',
                    'profiles': [], 'defaults': {}, 'interval': 0, 'next_run': None,
                    'nodes': [self.node('PTX1'), self.node('SW1', 'juniper_vjunosswitch')]}
        self.store.state['labs'] = [self.lab]
        self.store.state['discovery'] = {'ok': True, 'checked_epoch': now, 'checked_at': 'x',
                                         'last_success': 'x', 'labs': {'clabllm-dev': [
                                             {'name': 'PTX1', 'state': 'running', 'address': '172.20.20.2'},
                                             {'name': 'SW1', 'state': 'running', 'address': '172.20.20.3'}]}}
        self.store.save()
        self.runner = FakeRunner(self.store)
        self.git = object()  # not used by backup-source tests
        self.svc = RestoreService(self.store, self.runner, self.git, connector=fake_connect)
        patch.object(self.svc.pool, 'submit').start()
        self.addCleanup(patch.stopall)
        self.backup = self.make_source_backup()
        self.app = FastAPI()
        self.svc.install(self.app)
        self.client = TestClient(self.app)

    def node(self, name, platform='juniper_cjunosevolved'):
        return {'name': name, 'platform': platform, 'address': '172.20.20.2', 'port': 22,
                'enabled': True, 'profile_id': '', 'username': '', 'password': '',
                'endpoint_mode': 'manual', 'discovered': True, 'runtime_state': 'running',
                'discovered_address': '172.20.20.2', 'short_name': name}

    def make_source_backup(self):
        """A completed backup that carries a restore-grade artifact per node."""
        job_id = uuid.uuid4().hex
        folder = self.store.root / 'backups' / 'lab1' / 'history' / job_id
        folder.mkdir(parents=True)
        nodes = []
        for index, node in enumerate(self.lab['nodes']):
            (folder / f's-{index}.set').write_text(DESIRED_SET, encoding='utf-8')
            (folder / f's-{index}.jcfg').write_text(DESIRED_HIER, encoding='utf-8')
            nodes.append(dict(name=node['name'], status='succeeded', file=f's-{index}.set',
                              restore_file=f's-{index}.jcfg', restore_format='junos-hierarchical',
                              platform=node['platform'], short_name=node['name']))
        job = dict(id=job_id, lab_id='lab1', lab_name='clabllm-dev', operation='backup',
                   status='succeeded', created='2026-09-15T00:00:00+00:00', finished='2026-09-15T00:01:00+00:00',
                   nodes=nodes)
        self.store.state['jobs'].insert(0, job)
        self.store.save()
        return job

    def source(self):
        return {'type': 'backup', 'backup_job_id': self.backup['id']}

    def fake_apply(self, diff='[edit system]\n-  host-name OLD;\n+  host-name FINAL;', root='present', no_op=False):
        return patch('app.restore.junos.apply_candidate',
                     return_value={'diff': diff, 'root_authentication': root, 'no_op': no_op,
                                   'confirm_minutes': 5})

    def run_execute(self, node_names=('PTX1', 'SW1'), **apply_kwargs):
        job = self.svc.submit('lab1', self.source(), list(node_names), 5, uuid.uuid4().hex)
        with self.fake_apply(**apply_kwargs), \
                patch('app.restore.junos.confirm', return_value={'confirmed': True, 'had_pending_rollback': True}), \
                patch('app.restore.junos.capture', return_value=DESIRED_SET):
            self.svc.execute(job['id'])
        return self.svc.get_job(job['id'])

    # --- helper-function tests -------------------------------------------------

    def test_compare_states_tolerates_root_auth_and_detects_stale(self):
        actual = DESIRED_SET + 'set system root-authentication encrypted-password "$6$root"\n'
        missing, extra, converged = compare_states(DESIRED_SET, actual)
        self.assertTrue(converged)  # only the mandatory root-auth differs -> tolerated
        stale = DESIRED_SET + 'set interfaces lo0 unit 0 family inet address 10.9.9.9/32\n'
        _, extra2, conv2 = compare_states(DESIRED_SET, stale)
        self.assertFalse(conv2)
        self.assertIn('set interfaces lo0 unit 0 family inet address 10.9.9.9/32', extra2)

    def test_mask_hides_secrets(self):
        masked = mask_line('set system login user admin authentication encrypted-password "$6$abc"')
        self.assertNotIn('$6$abc', masked)
        self.assertEqual(set_lines('a\n#comment\n\nb'), ['a', 'b'])

    # --- source + preflight ----------------------------------------------------

    def test_preflight_lists_eligible_targets(self):
        with patch('app.restore.junos.capture', return_value=DESIRED_SET):
            review = self.client.post('/api/labs/lab1/restore/preflight', json={'source': self.source()})
        self.assertEqual(review.status_code, 200, review.text)
        data = review.json()
        self.assertEqual(data['eligible_count'], 2)
        names = {r['name']: r for r in data['targets']}
        self.assertTrue(names['PTX1']['eligible'])
        self.assertTrue(names['SW1']['reachable'])
        self.assertTrue(names['PTX1']['matches_saved'])  # probe config equals the desired state

    def test_preflight_probe_reports_reachability_failure(self):
        def boom(client, node, creds):
            raise OSError('no route')
        self.svc.connect = boom
        data = self.client.post('/api/labs/lab1/restore/preflight', json={'source': self.source()}).json()
        self.assertFalse(any(r['eligible'] and r['requested'] for r in data['targets']))
        self.assertNotIn('vm-secret', str(data))

    def test_unsupported_platform_is_ineligible(self):
        self.lab['nodes'][0]['platform'] = 'arista_ceos'
        # rebuild a source that still references PTX1 but as EOS -> no restore artifact match anyway
        data = self.svc.preflight('lab1', self.source(), None)
        row = next((r for r in data['targets'] if r['name'] == 'PTX1'), None)
        # PTX1's saved artifact still says juniper; running platform now EOS -> platform mismatch
        self.assertTrue(row is None or not row['eligible'])

    def _fake_git_folder(self):
        import base64, hashlib
        setraw = DESIRED_SET.encode(); hraw = DESIRED_HIER.encode()
        snap = {'manifest': {'schema': 2, 'lab_id': 'lab1', 'lab_name': 'clabllm-dev', 'node_names': ['PTX1'],
                             'files': [{'path': 'PTX1.set', 'size': len(setraw), 'sha256': hashlib.sha256(setraw).hexdigest(),
                                        'node': 'PTX1', 'platform': 'juniper_cjunosevolved', 'format': 'junos-display-set',
                                        'restore_artifact': 'PTX1.jcfg', 'restore_size': len(hraw),
                                        'restore_sha256': hashlib.sha256(hraw).hexdigest(),
                                        'restore_format': 'junos-hierarchical', 'restore_capable': True}]},
                'files': {'PTX1.set': base64.b64encode(setraw).decode(), 'PTX1.jcfg': base64.b64encode(hraw).decode()}}

        class FakeGit:
            calls = []
            def binding(self, lab_id):
                return {'binding_id': 'b', 'revision': 'r', 'repository': {'prefix': 'labs/BGP-LAB/Base'}}
            def invoke(self, request, binding=None):
                FakeGit.calls.append(request)
                return {'ready': True, 'head': 'a' * 40} if request['mode'] == 'status' else {'snapshot': snap}
        return FakeGit()

    def test_folder_source_applies_a_sibling_folder_without_rebinding(self):
        self.svc.git = self._fake_git_folder()
        desc, candidates = self.svc.resolve_source('lab1', {'type': 'folder', 'path': 'labs/BGP-LAB/Broken/latest'})
        self.assertEqual(desc['type'], 'folder')
        self.assertEqual(desc['folder'], 'labs/BGP-LAB/Broken')
        self.assertEqual(desc['restore_capable_nodes'], 1)
        self.assertIn('PTX1', candidates)
        self.assertIn('host-name FINAL', candidates['PTX1']['candidate'])
        # It read the folder's own path at HEAD (no rebinding).
        reads = [c for c in self.svc.git.calls if c['mode'] == 'read-version']
        self.assertEqual(reads[0]['path'], 'labs/BGP-LAB/Broken/latest')
        # Preflight over the folder source finds the node eligible.
        with patch('app.restore.junos.capture', return_value=DESIRED_SET):
            review = self.svc.preflight('lab1', {'type': 'folder', 'path': 'labs/BGP-LAB/Broken/latest'}, {'PTX1'})
        self.assertTrue(any(r['name'] == 'PTX1' and r['eligible'] for r in review['targets']))

    def test_source_without_artifact_offers_no_targets(self):
        # A snapshot whose files have no restore_artifact (legacy) yields no candidates.
        legacy = copy.deepcopy(self.backup)
        for n in legacy['nodes']:
            n.pop('restore_file', None)
            n.pop('restore_format', None)
        legacy['id'] = uuid.uuid4().hex
        folder = self.store.root / 'backups' / 'lab1' / 'history' / legacy['id']
        folder.mkdir(parents=True)
        for index in range(len(legacy['nodes'])):
            (folder / f's-{index}.set').write_text(DESIRED_SET, encoding='utf-8')
            legacy['nodes'][index]['file'] = f's-{index}.set'
        self.store.state['jobs'].insert(0, legacy)
        self.store.save()
        data = self.svc.preflight('lab1', {'type': 'backup', 'backup_job_id': legacy['id']}, None)
        self.assertEqual(data['source']['restore_capable_nodes'], 0)
        self.assertEqual(data['targets'], [])

    # --- guards ----------------------------------------------------------------

    def test_busy_backup_blocks_restore(self):
        self.store.state['jobs'].insert(0, dict(id='b', lab_id='lab1', status='running', operation='backup', nodes=[]))
        self.store.save()
        r = self.client.post('/api/labs/lab1/restore',
                             json={'request_id': 'a' * 32, 'source': self.source(),
                                   'node_names': ['PTX1'], 'acknowledge': True})
        self.assertEqual(r.status_code, 409)

    def test_acknowledge_required(self):
        r = self.client.post('/api/labs/lab1/restore',
                             json={'request_id': 'a' * 32, 'source': self.source(),
                                   'node_names': ['PTX1'], 'acknowledge': False})
        self.assertEqual(r.status_code, 400)

    def test_idempotent_request_returns_same_job(self):
        rid = 'b' * 32
        payload = {'request_id': rid, 'source': self.source(), 'node_names': ['PTX1'], 'acknowledge': True}
        first = self.client.post('/api/labs/lab1/restore', json=payload)
        self.assertEqual(first.status_code, 200, first.text)
        second = self.client.post('/api/labs/lab1/restore', json=payload)
        self.assertEqual(first.json()['id'], second.json()['id'])

    # --- execution -------------------------------------------------------------

    def test_full_restore_succeeds_and_verifies(self):
        job = self.run_execute()
        self.assertEqual(job['status'], 'succeeded', job['message'])
        self.assertTrue(job['pre_backup_job_id'])
        self.assertTrue(job['post_backup_job_id'])
        self.assertTrue(all(t['status'] == 'verified' for t in job['targets']))
        sources = [c['source'] for c in self.runner.calls]
        self.assertIn('restore-pre', sources)
        self.assertIn('restore-post', sources)

    def test_pre_backup_failure_blocks_that_node(self):
        self.runner.fail_nodes = {'PTX1'}
        job = self.run_execute(node_names=('PTX1', 'SW1'))
        ptx = next(t for t in job['targets'] if t['name'] == 'PTX1')
        self.assertEqual(ptx['status'], 'failed')
        self.assertIn('backup', ptx['message'].lower())

    def test_verify_mismatch_when_stale_remains(self):
        self.runner.post_config = DESIRED_SET + 'set interfaces lo0 unit 0 family inet address 10.9.9.9/32\n'
        job = self.run_execute()
        self.assertEqual(job['status'], 'needs_attention')
        self.assertTrue(any(t['status'] == 'verify_mismatch' for t in job['targets']))

    def test_apply_failure_before_arm_marks_not_changed(self):
        from app.restore_junos import RestoreError
        job = self.svc.submit('lab1', self.source(), ['PTX1'], 5, uuid.uuid4().hex)
        with patch('app.restore.junos.apply_candidate', side_effect=RestoreError('check failed')), \
                patch('app.restore.junos.confirm'), patch('app.restore.junos.capture', return_value=DESIRED_SET):
            self.svc.execute(job['id'])
        result = self.svc.get_job(job['id'])
        target = result['targets'][0]
        self.assertEqual(target['status'], 'failed')
        self.assertEqual(result['status'], 'failed')

    def test_node_stopping_after_submit_does_not_abort_the_healthy_node(self):
        # Eligible at submit; SW1 stops before execute runs. The all-or-nothing pre-backup
        # must not be handed SW1 (which would abort PTX1's restore); SW1 is skipped.
        job = self.svc.submit('lab1', self.source(), ['PTX1', 'SW1'], 5, uuid.uuid4().hex)
        self.lab['nodes'][1]['runtime_state'] = 'exited'  # SW1 no longer running
        self.store.save()
        with self.fake_apply(), \
                patch('app.restore.junos.confirm', return_value={'confirmed': True, 'had_pending_rollback': True}), \
                patch('app.restore.junos.capture', return_value=DESIRED_SET):
            self.svc.execute(job['id'])
        result = self.svc.get_job(job['id'])
        by_name = {t['name']: t for t in result['targets']}
        self.assertEqual(by_name['SW1']['status'], 'ineligible')
        self.assertEqual(by_name['PTX1']['status'], 'verified')
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(self.runner.calls[0]['node_names'], ['PTX1'])  # SW1 kept out of the pre-backup

    def test_confirm_failure_after_arm_expects_rollback(self):
        job = self.svc.submit('lab1', self.source(), ['PTX1'], 5, uuid.uuid4().hex)
        with self.fake_apply(), \
                patch('app.restore.junos.confirm', side_effect=OSError('lost mgmt')), \
                patch('app.restore.junos.capture', return_value=DESIRED_SET):
            self.svc.execute(job['id'])
        target = self.svc.get_job(job['id'])['targets'][0]
        self.assertEqual(target['status'], 'rollback_expected')

    def test_no_vm_or_device_secret_in_public_job(self):
        from app.restore import public_job
        self.run_execute()
        # The API only ever exposes the public projection.
        blob = str(self.client.get('/api/restore/jobs/' + self.store.state['restore_jobs'][-1]['id']).json())
        self.assertNotIn('vm-secret', blob)
        self.assertNotIn('$6$loginhash', blob)
        self.assertNotIn('_candidates', blob)
        self.assertNotIn('host_identity', blob)

    def test_restart_reconciles_busy_restore(self):
        job = self.svc.submit('lab1', self.source(), ['PTX1'], 5, uuid.uuid4().hex)
        self.svc.update(job['id'], status='applying')
        for target in self.store.state['restore_jobs'][-1]['targets']:
            target['status'] = 'applying'
        self.store.save()
        # A fresh service (manager restart) must mark the busy job interrupted.
        again = RestoreService(self.store, self.runner, self.git, connector=fake_connect)
        reloaded = again.get_job(job['id'])
        self.assertEqual(reloaded['status'], 'interrupted')
        self.assertTrue(all(t['status'] == 'interrupted' for t in reloaded['targets']))


if __name__ == '__main__':
    unittest.main()
