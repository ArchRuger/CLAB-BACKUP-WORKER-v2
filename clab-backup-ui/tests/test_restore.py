"""Tests for the restore service: source validation, node mapping, guards, the
mandatory pre-restore backup, apply/verify orchestration, redaction and reconciliation.
The Junos driver and the SSH transport are faked; the driver itself is covered by
test_restore_junos.py.
"""
import copy
import hashlib
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
    def __init__(self, store, post_config=DESIRED_SET, fail_nodes=(), pre_config=DESIRED_SET):
        self.store = store
        self.post_config = post_config
        self.pre_config = pre_config
        self.fail_nodes = set(fail_nodes)
        self.fail_message = 'capture failed'
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
                nodes.append(dict(name=node['name'], status='failed', message=self.fail_message))
                continue
            name = f'cfg-{index}.set'
            body = self.post_config if source == 'restore-post' else self.pre_config
            (folder / name).write_text(body, encoding='utf-8')
            rname = f'cfg-{index}.jcfg'
            (folder / rname).write_text(DESIRED_HIER, encoding='utf-8')
            nodes.append(dict(name=node['name'], status='succeeded', file=name, restore_file=rname,
                              restore_format='junos-hierarchical', platform=node['platform'],
                              sha256=hashlib.sha256(body.encode()).hexdigest(),
                              restore_sha256=hashlib.sha256(DESIRED_HIER.encode()).hexdigest(),
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
        # The recovery window is real time in production; the tests give every node one look.
        self.svc.retry_interval = self.svc.recovery_grace = self.svc.connect_pause = 0
        self.svc.window_seconds = lambda minutes: 0
        patch.object(self.svc.pool, 'submit').start()
        # Nothing awaits confirmation unless a test arms it (run_execute does).
        patch('app.restore.junos.pending', return_value=False).start()
        patch('app.restore.junos.blocked', return_value='').start()
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
                              sha256=hashlib.sha256(DESIRED_SET.encode()).hexdigest(),
                              restore_sha256=hashlib.sha256(DESIRED_HIER.encode()).hexdigest(),
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

    def pending_ours(self):
        """The node shows a pending change under this job's own token (the Junos commit comment)."""
        def current(*_args, **_kwargs):
            job = self.store.state['restore_jobs'][-1]
            target = next((t for t in job['targets'] if t['status'] in ('applying', 'confirming')), None)
            return target['_token'] if target else False
        return patch('app.restore.junos.pending', side_effect=current)

    def run_execute(self, node_names=('PTX1', 'SW1'), **apply_kwargs):
        job = self.svc.submit('lab1', self.source(), list(node_names), 5, uuid.uuid4().hex)
        with self.fake_apply(**apply_kwargs), self.pending_ours(), \
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
        # EOS and IOS XR put a type token before the hash; nothing after the keyword may survive.
        for line, secret in (('+username admin privilege 15 role network-admin secret sha512 $6$Lq.7Rm/Hash.Bt0', '$6$Lq.7Rm'),
                             ('enable password 7 $1$abcdefgh$XyZ', '$1$abcdefgh'),
                             ('   neighbor 10.0.0.1 password 7 121A0C041104', '121A0C041104'),
                             ('ntp authentication-key 1 md5 7 0212034A0E1F', '0212034A0E1F'),
                             ('   key-string 7 070C285F4D06', '070C285F4D06'),
                             ('tacacs-server key 7 1511021F0725', '1511021F0725'),
                             ('snmp-server community s3cr3tRO ro', 's3cr3tRO'),
                             ('-  secret 5 $1$mERr$hx5rVt7rPNoS4wqbXKX7m0', 'hx5rVt7r')):
            self.assertNotIn(secret, mask_line(line), line)
            self.assertIn('[redacted]', mask_line(line))
        self.assertEqual(mask_line('+   description A to-cjunosevolved'), '+   description A to-cjunosevolved')
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
        self.assertEqual(desc['path'], '/labs/BGP-LAB/Broken/latest')  # normalised wire form: '/' + exact path
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

    def _fake_git_versioned(self):
        """A folder source whose HEAD can move between preflight and submit, with more than one
        commit in branch history, and one commit whose manifest is malformed."""
        import base64, hashlib

        def make_snap(hostname):
            raw = ('set system host-name ' + hostname + '\n').encode()
            hraw = ('system { host-name ' + hostname + '; }\n').encode()
            return {'manifest': {'schema': 2, 'lab_id': 'lab1', 'lab_name': 'clabllm-dev', 'node_names': ['PTX1'],
                                 'files': [{'path': 'PTX1.set', 'size': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
                                            'node': 'PTX1', 'platform': 'juniper_cjunosevolved', 'format': 'junos-display-set',
                                            'restore_artifact': 'PTX1.jcfg', 'restore_size': len(hraw),
                                            'restore_sha256': hashlib.sha256(hraw).hexdigest(),
                                            'restore_format': 'junos-hierarchical', 'restore_capable': True}]},
                    'files': {'PTX1.set': base64.b64encode(raw).decode(), 'PTX1.jcfg': base64.b64encode(hraw).decode()}}

        class FakeGit:
            HEAD1 = 'a' * 40
            HEAD2 = 'c' * 40
            BAD_MANIFEST = 'd' * 40

            def __init__(self):
                self.head = self.HEAD1
                self.commits = {self.HEAD1: make_snap('OLD-STATE'), self.HEAD2: make_snap('NEW-STATE')}
                self.calls = []

            def binding(self, lab_id):
                return {'binding_id': 'b', 'revision': 'r', 'repository': {'prefix': 'labs/BGP-LAB/Base'}}

            def invoke(self, request, binding=None):
                self.calls.append(dict(request))
                mode = request['mode']
                if mode == 'status':
                    return {'ready': True, 'head': self.head}
                if mode == 'read-version':
                    commit = request['commit']
                    if commit == self.BAD_MANIFEST:
                        raise ValueError('The saved version manifest is invalid.')
                    if commit not in self.commits:
                        raise ValueError('The selected commit is outside this repository branch history.')
                    return {'snapshot': self.commits[commit]}
                raise AssertionError(mode)
        return FakeGit()

    def test_folder_source_with_exact_path_resolves(self):
        # Rule 6/5: an exact repository-relative path, no /latest suffix required. desc['path'] is
        # the normalised wire form ('/' + exact path); desc['folder'] has no leading slash.
        self.svc.git = self._fake_git_versioned()
        desc, candidates = self.svc.resolve_source('lab1', {'type': 'folder', 'path': 'Final'})
        self.assertEqual(desc['path'], '/Final')
        self.assertEqual(desc['folder'], 'Final')
        self.assertEqual(desc['commit'], self.svc.git.HEAD1)
        self.assertIn('PTX1', candidates)
        reads = [c for c in self.svc.git.calls if c['mode'] == 'read-version']
        self.assertEqual(reads[0]['path'], 'Final')

    def test_folder_source_with_an_explicit_leading_slash_resolves_the_same_way(self):
        # (a): a value starting with '/' is the same exact path, one leading slash stripped.
        self.svc.git = self._fake_git_versioned()
        desc, _ = self.svc.resolve_source('lab1', {'type': 'folder', 'path': '/Final'})
        self.assertEqual(desc['path'], '/Final')
        self.assertEqual(desc['folder'], 'Final')
        reads = [c for c in self.svc.git.calls if c['mode'] == 'read-version']
        self.assertEqual(reads[0]['path'], 'Final')

    def test_folder_source_root_path_resolves_to_the_empty_helper_path(self):
        self.svc.git = self._fake_git_versioned()
        desc, _ = self.svc.resolve_source('lab1', {'type': 'folder', 'path': '/'})
        self.assertEqual(desc['path'], '/')
        self.assertEqual(desc['folder'], '')
        reads = [c for c in self.svc.git.calls if c['mode'] == 'read-version']
        self.assertEqual(reads[0]['path'], '')

    def test_folder_source_bare_reserved_name_keeps_its_pre_upgrade_meaning(self):
        # (b) compatibility: a bare 'latest' still names the connected (lab) folder, not a
        # root-level folder called 'latest' -- for a tab or tool built before this release.
        self.svc.git = self._fake_git_folder()  # binding prefix 'labs/BGP-LAB/Base'
        desc, candidates = self.svc.resolve_source('lab1', {'type': 'folder', 'path': 'latest'})
        self.assertEqual(desc['path'], '/labs/BGP-LAB/Base/latest')
        self.assertEqual(desc['folder'], 'labs/BGP-LAB/Base')
        self.assertIn('PTX1', candidates)
        reads = [c for c in self.svc.git.calls if c['mode'] == 'read-version']
        self.assertEqual(reads[0]['path'], 'labs/BGP-LAB/Base/latest')

    def test_preflight_without_a_commit_reads_head_and_returns_it_as_source_commit(self):
        self.svc.git = self._fake_git_versioned()
        with patch('app.restore.junos.capture', return_value='set system host-name OLD-STATE\n'):
            review = self.svc.preflight('lab1', {'type': 'folder', 'path': 'Final'}, {'PTX1'})
        self.assertEqual(review['source']['commit'], self.svc.git.HEAD1)

    def test_submit_with_the_reviewed_commit_reads_that_commit_not_a_later_head(self):
        self.svc.git = self._fake_git_versioned()
        with patch('app.restore.junos.capture', return_value='set system host-name OLD-STATE\n'):
            review = self.svc.preflight('lab1', {'type': 'folder', 'path': 'Final'}, {'PTX1'})
        reviewed = review['source']  # exactly what the browser is expected to resubmit
        self.assertEqual(reviewed['commit'], self.svc.git.HEAD1)
        # The repository moves on before the student submits; the pinned commit must still be read.
        self.svc.git.head = self.svc.git.HEAD2
        job = self.svc.submit('lab1', {'type': 'folder', 'path': reviewed['path'], 'commit': reviewed['commit']},
                              ['PTX1'], 5, uuid.uuid4().hex)
        self.assertEqual(job['source']['commit'], self.svc.git.HEAD1)
        stored = next(j for j in self.store.state['restore_jobs'] if j['id'] == job['id'])
        self.assertIn('OLD-STATE', stored['_candidates']['PTX1']['candidate'])
        self.assertNotIn('NEW-STATE', stored['_candidates']['PTX1']['candidate'])
        reads = [c for c in self.svc.git.calls if c['mode'] == 'read-version']
        self.assertEqual(reads[-1]['commit'], self.svc.git.HEAD1)

    def test_submit_with_an_unknown_commit_is_refused_before_any_device_is_touched(self):
        self.svc.git = self._fake_git_versioned()
        with patch('app.restore.junos.capture') as capture, patch('app.restore.junos.apply_candidate') as apply:
            with self.assertRaises(Exception) as refused:
                self.svc.submit('lab1', {'type': 'folder', 'path': 'Final', 'commit': 'f' * 40}, ['PTX1'], 5, uuid.uuid4().hex)
            self.assertEqual(refused.exception.status_code, 409)
            self.assertIn('outside this repository branch history', refused.exception.detail)
        capture.assert_not_called(); apply.assert_not_called()
        self.assertEqual(self.store.state['restore_jobs'], [])

    def test_a_malformed_manifest_at_the_reviewed_commit_is_refused_at_preflight(self):
        git = self._fake_git_versioned()
        git.head = git.BAD_MANIFEST
        self.svc.git = git
        with self.assertRaises(Exception) as refused:
            self.svc.preflight('lab1', {'type': 'folder', 'path': 'Final'}, None)
        self.assertEqual(refused.exception.status_code, 409)
        self.assertIn('manifest is invalid', refused.exception.detail)

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
        # Nothing is offered for restore, and the student is told why: each saved node is listed,
        # ineligible, with the compatibility reason (the backup text is never relabelled as a candidate).
        self.assertEqual(data['eligible_count'], 0)
        self.assertEqual([row['name'] for row in data['targets']], ['PTX1', 'SW1'])
        self.assertTrue(all(not row['eligible'] and row['reason'] == 'This saved configuration has no restore data for this node.'
                            for row in data['targets']))
        with self.assertRaises(Exception) as refused:
            self.svc.submit('lab1', {'type': 'backup', 'backup_job_id': legacy['id']}, ['PTX1'], 5, uuid.uuid4().hex)
        self.assertEqual(refused.exception.status_code, 409)

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

    def test_a_failed_safety_backup_says_why_in_fixed_words_never_in_ansibles(self):
        from app.restore import backup_failure
        self.assertEqual(backup_failure('Failed to authenticate: Authentication failed. secret=hunter2'), ' (the device rejected the login)')
        self.assertEqual(backup_failure('timed out waiting for 172.20.20.2'), ' (the device did not answer)')
        self.assertEqual(backup_failure('something else entirely'), '')
        self.runner.fail_nodes = {'PTX1'}
        self.runner.fail_message = 'Failed to authenticate: Authentication failed. secret=hunter2'
        job = self.run_execute(node_names=('PTX1',))
        message = job['targets'][0]['message']
        self.assertEqual(message, 'Pre-restore backup failed for this node (the device rejected the login); it was not changed.')
        self.assertNotIn('hunter2', str(job))

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
        with self.fake_apply(), self.pending_ours(), \
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
        # Armed, but the confirmation never gets through and the node cannot be read afterwards:
        # never "applied", and no longer an assumed rollback either. The manager says it does not know.
        job = self.svc.submit('lab1', self.source(), ['PTX1'], 5, uuid.uuid4().hex)
        with self.fake_apply(), self.pending_ours(), \
                patch('app.restore.junos.confirm', side_effect=OSError('lost mgmt')), \
                patch('app.restore.junos.capture', return_value=DESIRED_SET):
            self.svc.execute(job['id'])
        result = self.svc.get_job(job['id'])
        self.assertEqual(result['targets'][0]['status'], 'uncertain')
        self.assertEqual(result['status'], 'needs_attention')

    def test_unconfirmed_change_is_rolled_back_only_when_the_previous_configuration_is_read_back(self):
        before = 'set system host-name BEFORE\n'
        self.runner.pre_config = before
        job = self.svc.submit('lab1', self.source(), ['PTX1'], 5, uuid.uuid4().hex)
        with self.fake_apply(), patch('app.restore.junos.pending', return_value=False), \
                patch('app.restore.junos.confirm') as confirm, patch('app.restore.junos.capture', return_value=before):
            self.svc.execute(job['id'])
        result = self.svc.get_job(job['id'])
        self.assertEqual(result['targets'][0]['status'], 'rolled_back')
        self.assertEqual(result['status'], 'failed')
        confirm.assert_not_called()

    def test_lost_session_during_apply_reads_the_node_back(self):
        from app.restore_shell import SessionLost
        self.runner.pre_config = 'set system host-name BEFORE\n'
        job = self.svc.submit('lab1', self.source(), ['PTX1'], 5, uuid.uuid4().hex)
        # The session died inside the transaction; the node turns out to run the saved configuration.
        with patch('app.restore.junos.apply_candidate', side_effect=SessionLost('closed')), \
                patch('app.restore.junos.confirm') as confirm, patch('app.restore.junos.capture', return_value=DESIRED_SET):
            self.svc.execute(job['id'])
        self.assertEqual(self.svc.get_job(job['id'])['targets'][0]['status'], 'verified')
        confirm.assert_not_called()  # nothing of ours was pending, so nothing was confirmed blindly

    def test_lost_session_with_the_previous_configuration_active_is_not_called_a_rollback(self):
        from app.restore_shell import SessionLost
        before = 'set system host-name BEFORE\n'
        self.runner.pre_config = before
        job = self.svc.submit('lab1', self.source(), ['PTX1'], 5, uuid.uuid4().hex)
        with patch('app.restore.junos.apply_candidate', side_effect=SessionLost('closed')), \
                patch('app.restore.junos.confirm') as confirm, patch('app.restore.junos.capture', return_value=before):
            self.svc.execute(job['id'])
        target = self.svc.get_job(job['id'])['targets'][0]
        # Nobody saw the change armed, so "the device undid it" would be a guess.
        self.assertEqual(target['status'], 'failed')
        self.assertIn('Checked: the configuration from before the restore is active', target['message'])
        confirm.assert_not_called()

    def test_an_armed_change_with_no_token_on_the_node_is_not_confirmed_even_by_the_job_that_armed_it(self):
        # "Something is pending" proves nothing about whose it is: the node rolled ours back and
        # somebody armed their own change meanwhile. Only the token identifies ours.
        job = self.svc.submit('lab1', self.source(), ['PTX1'], 5, uuid.uuid4().hex)
        with self.fake_apply(), patch('app.restore.junos.pending', return_value=True), \
                patch('app.restore.junos.confirm') as confirm, patch('app.restore.junos.capture', return_value=DESIRED_SET):
            self.svc.execute(job['id'])
        self.assertEqual(self.svc.get_job(job['id'])['targets'][0]['status'], 'uncertain')
        confirm.assert_not_called()

    def test_our_change_seen_pending_after_a_lost_session_is_confirmed_by_its_token(self):
        from app.restore_shell import SessionLost
        job = self.svc.submit('lab1', self.source(), ['PTX1'], 5, uuid.uuid4().hex)
        # The session died right after the device armed the change; the node shows our token.
        with patch('app.restore.junos.apply_candidate', side_effect=SessionLost('closed')), self.pending_ours(), \
                patch('app.restore.junos.confirm', return_value={'confirmed': True}) as confirm, \
                patch('app.restore.junos.capture', return_value=DESIRED_SET):
            self.svc.execute(job['id'])
        self.assertEqual(self.svc.get_job(job['id'])['targets'][0]['status'], 'verified')
        self.assertEqual(confirm.call_count, 1)
        self.assertTrue(confirm.call_args.args[1]['token'].startswith('clabmgr-'))

    def test_a_programming_error_while_settling_is_not_retried_for_the_whole_window(self):
        self.svc.retry_interval, self.svc.recovery_grace = 30, 3600   # a retry would hang this test
        self.svc.window_seconds = lambda minutes: 3600
        job = self.svc.submit('lab1', self.source(), ['PTX1'], 5, uuid.uuid4().hex)
        with self.fake_apply(), patch('app.restore.junos.pending', side_effect=KeyError('bug')), \
                patch('app.restore.junos.capture', return_value=DESIRED_SET):
            self.svc.execute(job['id'])
        target = self.svc.get_job(job['id'])['targets'][0]
        self.assertEqual(target['status'], 'uncertain')
        self.assertIn('internal error', target['message'])

    def test_a_pending_change_that_is_not_ours_is_never_confirmed(self):
        from app.restore_shell import SessionLost
        job = self.svc.submit('lab1', self.source(), ['PTX1'], 5, uuid.uuid4().hex)
        with patch('app.restore.junos.apply_candidate', side_effect=SessionLost('closed')), \
                patch('app.restore.junos.pending', return_value=True), \
                patch('app.restore.junos.confirm') as confirm, patch('app.restore.junos.capture', return_value=DESIRED_SET):
            self.svc.execute(job['id'])
        self.assertEqual(self.svc.get_job(job['id'])['targets'][0]['status'], 'uncertain')
        confirm.assert_not_called()

    def test_preflight_refuses_a_node_with_a_foreign_pending_change(self):
        with patch('app.restore.junos.pending', return_value=True), patch('app.restore.junos.capture', return_value=DESIRED_SET):
            result = self.svc.preflight('lab1', self.source(), None)
        self.assertTrue(all(not row['eligible'] for row in result['targets']))
        self.assertTrue(all(row['reason'].startswith('Another change is waiting') for row in result['targets']))

    def test_a_driver_that_holds_the_arming_session_keeps_its_connection_until_the_node_is_settled(self):
        """IOS XR shape: only the arming session can confirm. The service must not close that
        connection after a successful apply, must confirm through a FRESH one, and must always
        release the held session afterwards."""
        import types
        from app import restore_compare
        log = []

        class Client:
            def __init__(self): self.closed = False; log.append(('client', id(self)))
            def close(self): self.closed = True

        clients = []
        def connector(client, node, creds): clients.append(client)
        held = {}
        def apply_candidate(client, candidate, minutes, token=None):
            held[token] = client
            return {'diff': '', 'no_op': False, 'handle': {'token': token}}
        def confirm(client, handle):
            log.append(('confirm-on-fresh', client is not held[handle['token']], held[handle['token']].closed))
            return {'confirmed': True}
        def release(token):
            log.append(('release', token)); held.pop(token).close()
        driver = types.SimpleNamespace(
            SUPPORTED_KINDS=('juniper_cjunosevolved',), RESTORE_FORMAT='junos-hierarchical', HOLDS_SESSION=True,
            validate_candidate=lambda text: None, apply_candidate=apply_candidate, confirm=confirm, release=release,
            pending=lambda client: next(iter(held), ''), capture=lambda client: DESIRED_SET,
            compare=restore_compare.compare_junos)
        svc = RestoreService(self.store, self.runner, self.git, connector=connector)
        svc.retry_interval = svc.recovery_grace = 0
        svc.window_seconds = lambda minutes: 0
        patch.object(svc.pool, 'submit').start()
        with patch('app.restore.paramiko.SSHClient', Client), patch('app.restore.drivers.for_platform', return_value=driver), \
                patch('app.restore.drivers.options', return_value={}):
            job = svc.submit('lab1', self.source(), ['PTX1'], 5, uuid.uuid4().hex)
            svc.execute(job['id'])
        self.assertEqual(svc.get_job(job['id'])['targets'][0]['status'], 'verified')
        arming = clients[0]
        self.assertIn(('confirm-on-fresh', True, False), log)      # a different connection, the armed one still open
        self.assertTrue(arming.closed)                               # released once the node was settled
        self.assertEqual([entry[0] for entry in log if entry[0] == 'release'], ['release'])
        self.assertEqual(held, {})

    def test_a_held_session_is_released_even_when_the_change_could_not_be_confirmed(self):
        import types
        from app import restore_compare
        released, armed = [], []

        def apply_candidate(client, candidate, minutes, token=None):
            armed.append(token)
            return {'diff': '', 'no_op': False, 'handle': {'token': token}}
        driver = types.SimpleNamespace(
            SUPPORTED_KINDS=('juniper_cjunosevolved',), RESTORE_FORMAT='junos-hierarchical', HOLDS_SESSION=True,
            validate_candidate=lambda text: None, apply_candidate=apply_candidate,
            confirm=lambda client, handle: (_ for _ in ()).throw(OSError('management is gone')),
            # Quiet at submit; after the apply the node shows a pending change that is not under our token.
            release=released.append, pending=lambda client: 'not-the-token' if armed and not released else '',
            capture=lambda client: 'set system host-name SOMETHING-ELSE\n', compare=restore_compare.compare_junos)
        with patch('app.restore.drivers.for_platform', return_value=driver), patch('app.restore.drivers.options', return_value={}):
            job = self.svc.submit('lab1', self.source(), ['PTX1'], 5, uuid.uuid4().hex)
            self.svc.execute(job['id'])
        self.assertEqual(self.svc.get_job(job['id'])['targets'][0]['status'], 'uncertain')
        self.assertEqual(len(released), 1)
        self.assertTrue(released[0].startswith('clabmgr-'))

    def test_submit_looks_at_the_devices_again_and_refuses_before_anything_starts(self):
        for patched, reason in ((patch('app.restore.junos.pending', return_value=True), 'Another change is waiting'),
                                (patch('app.restore.junos.blocked', return_value='Someone has uncommitted configuration changes open on this node.'),
                                 'Someone has uncommitted')):
            with patched, self.assertRaises(Exception) as refused:
                self.svc.submit('lab1', self.source(), ['PTX1'], 5, uuid.uuid4().hex)
            self.assertEqual(refused.exception.status_code, 409)
            self.assertIn(reason, refused.exception.detail)
        self.assertEqual(self.store.state['restore_jobs'], [])       # nothing was queued
        self.assertEqual(self.runner.calls, [])                       # not even the safety backup

    def test_submit_does_not_refuse_the_request_for_an_unreachable_node(self):
        # It gets its own per-node outcome in the job instead ("not changed").
        with patch('app.restore.junos.pending', side_effect=OSError('no route')):
            job = self.svc.submit('lab1', self.source(), ['PTX1'], 5, uuid.uuid4().hex)
        self.assertEqual(job['status'], 'queued')

    def test_the_review_looks_at_a_node_over_one_connection(self):
        # IOS XR turns away connections that follow each other too quickly: pending, blocked and the
        # capture share one SSH connection per node.
        opened = []
        svc = RestoreService(self.store, self.runner, self.git, connector=lambda client, node, creds: opened.append(node['name']))
        with patch('app.restore.junos.capture', return_value=DESIRED_SET):
            result = svc.preflight('lab1', self.source(), None)
        self.assertTrue(all(row['eligible'] for row in result['targets']))
        self.assertEqual(sorted(opened), ['PTX1', 'SW1'])

    def test_a_refused_connection_is_tried_again_but_rejected_credentials_are_not(self):
        import paramiko
        attempts = []

        def flaky(client, node, creds):
            attempts.append(node['name'])
            if len(attempts) < 3:
                raise paramiko.SSHException('Error reading SSH protocol banner')
        svc = RestoreService(self.store, self.runner, self.git, connector=flaky)
        svc.connect_pause = 0
        with patch('app.restore.junos.capture', return_value=DESIRED_SET):
            result = svc.preflight('lab1', self.source(), {'PTX1'})
        self.assertTrue(next(r for r in result['targets'] if r['name'] == 'PTX1')['eligible'])
        self.assertEqual(attempts, ['PTX1'] * 3)
        attempts.clear()

        def denied(client, node, creds):
            attempts.append(node['name'])
            raise paramiko.AuthenticationException('Authentication failed.')
        svc = RestoreService(self.store, self.runner, self.git, connector=denied)
        svc.connect_pause = 0
        result = svc.preflight('lab1', self.source(), {'PTX1'})
        row = next(r for r in result['targets'] if r['name'] == 'PTX1')
        self.assertFalse(row['eligible'])
        self.assertEqual(row['reason'], 'The node rejected the login credentials.')   # not "did not answer"
        self.assertEqual(attempts, ['PTX1'])                      # no hammering with a wrong password
        # At application time (the login worked at the review and was changed since) the node is "not changed", and says why.
        job = self.svc.submit('lab1', self.source(), ['PTX1'], 5, uuid.uuid4().hex)
        self.svc.connect = denied
        self.svc.execute(job['id'])
        target = self.svc.get_job(job['id'])['targets'][0]
        self.assertEqual(target['status'], 'failed')
        self.assertIn('rejected the login credentials', target['message'])

    def test_preflight_refuses_a_node_where_somebody_is_editing(self):
        reason = 'Someone has uncommitted configuration changes open on this node.'
        with patch('app.restore.junos.blocked', return_value=reason) as blocked, \
                patch('app.restore.junos.capture', return_value=DESIRED_SET) as capture:
            result = self.svc.preflight('lab1', self.source(), None)
        self.assertTrue(all(not row['eligible'] and row['reason'] == reason for row in result['targets']))
        self.assertEqual(blocked.call_count, 2)
        capture.assert_not_called()

    def test_a_stored_capture_that_no_longer_matches_its_digest_is_refused_before_any_device_is_touched(self):
        # Integrity of the backup source: the runner recorded a digest when it stored the artifact.
        folder = self.store.root / 'backups' / 'lab1' / 'history' / self.backup['id']
        (folder / 's-0.jcfg').write_text(DESIRED_HIER.replace('FINAL', 'TAMPERED'), encoding='utf-8')
        with patch('app.restore.junos.capture') as capture, patch('app.restore.junos.apply_candidate') as apply:
            for call in (lambda: self.svc.preflight('lab1', self.source(), None),
                         lambda: self.svc.submit('lab1', self.source(), ['PTX1'], 5, uuid.uuid4().hex)):
                with self.assertRaises(Exception) as refused:
                    call()
                self.assertEqual(refused.exception.status_code, 400)
                self.assertIn('no longer matches the digest', refused.exception.detail)
        capture.assert_not_called(); apply.assert_not_called()
        self.assertEqual(self.store.state['restore_jobs'], [])

    def test_a_tampered_file_in_a_saved_git_folder_is_refused_before_any_device_is_touched(self):
        # Integrity of the Git and folder sources: size and sha256 of every file against the manifest.
        import base64
        git = self._fake_git_folder()
        svc = RestoreService(self.store, self.runner, git, connector=fake_connect)
        snapshot = git.invoke({'mode': 'read-version'})['snapshot']
        snapshot['files']['PTX1.jcfg'] = base64.b64encode(DESIRED_HIER.replace('FINAL', 'TAMPERED').encode()).decode()
        with patch('app.restore.junos.capture') as capture:
            for source in ({'type': 'folder', 'path': 'labs/BGP-LAB/Broken/latest'}, {'type': 'git', 'commit': 'a' * 40, 'path': 'latest'}):
                with self.assertRaises(Exception) as refused:
                    svc.preflight('lab1', source, None)
                self.assertEqual(refused.exception.status_code, 409)
                self.assertIn('integrity check failed', refused.exception.detail)
        capture.assert_not_called()

    def test_truncated_candidate_is_refused_before_any_device_is_touched(self):
        # A capture that was stored truncated (its digest matches what was stored): the driver's own
        # completeness check is what refuses it.
        folder = self.store.root / 'backups' / 'lab1' / 'history' / self.backup['id']
        truncated = 'system {\n    host-name FINAL;\n'
        (folder / 's-0.jcfg').write_text(truncated, encoding='utf-8')
        for job in self.store.state['jobs']:
            if job['id'] == self.backup['id']:
                job['nodes'][0]['restore_sha256'] = hashlib.sha256(truncated.encode()).hexdigest()
        self.store.save()
        with patch('app.restore.junos.capture') as capture:
            result = self.svc.preflight('lab1', self.source(), None)
        row = next(r for r in result['targets'] if r['name'] == 'PTX1')
        self.assertFalse(row['eligible'])
        self.assertTrue(row['reason'].startswith('The saved restore data for this node is not usable'))
        self.assertEqual(capture.call_count, 1)  # only the healthy SW1 was probed

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
        # ... and then reads the node back instead of assuming a rollback: here the saved
        # configuration is active and nothing is pending, so it says so. Nothing is re-applied.
        again.retry_interval = again.recovery_grace = 0
        self.assertEqual(again.unchecked, [(job['id'], 'PTX1')])
        again.start = None  # the pool is not used here; the re-check is called directly
        again.rechecks[job['id']] = 1
        with patch('app.restore.junos.apply_candidate') as apply, patch('app.restore.junos.confirm') as confirm, \
                patch('app.restore.junos.capture', return_value=DESIRED_SET):
            again._recheck_interrupted(job['id'], 'PTX1')
        rechecked = again.get_job(job['id'])
        self.assertEqual(rechecked['targets'][0]['status'], 'verified')
        apply.assert_not_called()
        confirm.assert_not_called()
        # The job stops being "interrupted" once its node was looked at, and says how it knows.
        self.assertEqual(rechecked['status'], 'succeeded')
        self.assertTrue(rechecked['message'].startswith('Checked after a manager restart.'))

    def test_restart_after_the_change_was_armed_reports_a_rollback_when_the_previous_configuration_is_back(self):
        before = 'set system host-name BEFORE\n'
        self.runner.pre_config = before
        job = self.svc.submit('lab1', self.source(), ['PTX1'], 5, uuid.uuid4().hex)
        pre = self.runner.submit('lab1', source='restore-pre', node_names=['PTX1'])
        self.svc.update(job['id'], status='applying', pre_backup_job_id=pre['id'])
        for target in self.store.state['restore_jobs'][-1]['targets']:
            target.update(status='confirming', _token='clabmgr-1a2b3c4d', _handle={'token': 'clabmgr-1a2b3c4d'})
        self.store.save()
        again = RestoreService(self.store, self.runner, self.git, connector=fake_connect)
        again.retry_interval = again.recovery_grace = 0
        again.rechecks[job['id']] = 1
        with patch('app.restore.junos.confirm') as confirm, patch('app.restore.junos.capture', return_value=before):
            again._recheck_interrupted(job['id'], 'PTX1')
        rechecked = again.get_job(job['id'])
        self.assertEqual(rechecked['targets'][0]['status'], 'rolled_back')
        self.assertEqual(rechecked['status'], 'failed')
        confirm.assert_not_called()

    def _restarted_mid_change(self, token='clabmgr-1a2b3c4d'):
        """A job whose node was armed (handle stored) when the manager went down; returns (job id, new service)."""
        job = self.svc.submit('lab1', self.source(), ['PTX1'], 5, uuid.uuid4().hex)
        self.svc.update(job['id'], status='applying')
        for target in self.store.state['restore_jobs'][-1]['targets']:
            target.update(status='confirming', _token=token, _handle={'token': token})
        self.store.save()
        again = RestoreService(self.store, self.runner, self.git, connector=fake_connect)
        again.retry_interval = again.recovery_grace = 0
        again.rechecks[job['id']] = 1
        for target in again.get_job(job['id'])['targets']:
            target['_deadline'] = 1          # the undo window is long over (0 would read as "unset"): one look, no waiting
        return job['id'], again

    def test_restart_recheck_confirms_a_pending_change_only_under_the_jobs_own_token(self):
        job_id, again = self._restarted_mid_change()
        with patch('app.restore.junos.pending', return_value='clabmgr-1a2b3c4d'), \
                patch('app.restore.junos.confirm', return_value={'confirmed': True}) as confirm, \
                patch('app.restore.junos.apply_candidate') as apply, patch('app.restore.junos.capture', return_value=DESIRED_SET):
            again._recheck_interrupted(job_id, 'PTX1')
        rechecked = again.get_job(job_id)
        self.assertEqual(rechecked['targets'][0]['status'], 'verified')
        self.assertEqual(confirm.call_args.args[1]['token'], 'clabmgr-1a2b3c4d')
        apply.assert_not_called()                                   # nothing is ever re-applied
        self.assertEqual(rechecked['status'], 'succeeded')

    def test_restart_recheck_never_confirms_somebody_elses_pending_change(self):
        for foreign in ('clabmgr-ffffffff', True):
            job_id, again = self._restarted_mid_change()
            with patch('app.restore.junos.pending', return_value=foreign), patch('app.restore.junos.confirm') as confirm, \
                    patch('app.restore.junos.apply_candidate') as apply, patch('app.restore.junos.capture', return_value=DESIRED_SET):
                again._recheck_interrupted(job_id, 'PTX1')
            rechecked = again.get_job(job_id)
            self.assertEqual(rechecked['targets'][0]['status'], 'uncertain', foreign)
            confirm.assert_not_called()
            apply.assert_not_called()
            self.assertEqual(rechecked['status'], 'needs_attention')

    def test_a_shutdown_inside_the_undo_window_leaves_the_node_in_flight_for_the_restart_recheck(self):
        self.svc.retry_interval, self.svc.recovery_grace = 0, 3600
        self.svc.window_seconds = lambda minutes: 3600
        job = self.svc.submit('lab1', self.source(), ['PTX1', 'SW1'], 5, uuid.uuid4().hex)

        def unreachable_then_shutdown(client):
            self.svc.stopping.set()                      # the manager is told to stop while it keeps trying to reconnect
            raise OSError('management is down')
        with self.fake_apply(), patch('app.restore.junos.pending', side_effect=unreachable_then_shutdown), \
                patch('app.restore.junos.confirm') as confirm, patch('app.restore.junos.capture', return_value=DESIRED_SET):
            self.svc.execute(job['id'])
        stopped = self.svc.get_job(job['id'])
        by_name = {t['name']: t['status'] for t in stopped['targets']}
        self.assertEqual(by_name['PTX1'], 'confirming')         # not "uncertain": nothing was established, so nothing is claimed
        self.assertEqual(by_name['SW1'], 'backing_up')          # never started: no new node is changed during a shutdown
        self.assertEqual(stopped['status'], 'applying')
        confirm.assert_not_called()
        again = RestoreService(self.store, self.runner, self.git, connector=fake_connect)
        self.assertEqual(again.get_job(job['id'])['status'], 'interrupted')
        self.assertEqual(again.unchecked, [(job['id'], 'PTX1')])  # only the node that was mid-change is read back

    def test_remove_lab_is_refused_while_a_restore_is_running(self):
        from app.lab_operations import RESTORE_BUSY
        from app.main import create_app
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            app = create_app(folder)
            store = app.state.store
            with store.lock:
                store.state['labs'].append(dict(self.lab, id='labX', name='busy-lab'))
                store.state.setdefault('restore_jobs', []).append(dict(id='r1', lab_id='labX', status='confirming', targets=[]))
                store.save()
            self.assertIn('confirming', RESTORE_BUSY)
            client = TestClient(app, base_url='http://testserver')
            response = client.request('DELETE', '/api/labs/labX', json={'name': 'busy-lab'},
                                      headers={'Origin': 'http://testserver'})
            # get_lab() consults operation_busy, which counts a restore in RESTORE_BUSY: a lab whose device may
            # hold an armed change for the whole undo window cannot be removed from under the worker.
            self.assertEqual(response.status_code, 409, response.text)
            self.assertIn('Wait for the lab operation to finish', response.json()['detail'])
            self.assertTrue(any(l['id'] == 'labX' for l in store.state['labs']))


if __name__ == '__main__':
    unittest.main()
