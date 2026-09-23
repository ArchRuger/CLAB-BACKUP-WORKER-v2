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
from app.restore import (RestoreService, compare_states, mask_line, set_lines,
                         RESTORE_JOB_CAP, _append_restore_job, _restore_job_active)

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


class RestoreJobCapTests(unittest.TestCase):
    """B-001: 'restore_jobs' is bounded like 'operations', never dropping a job still in progress
    or awaiting its post-restart recheck ('interrupted', see RestoreService.__init__)."""

    def test_restore_job_active_matches_restore_busy_plus_interrupted(self):
        for status in ('queued', 'preflight', 'backing_up', 'applying', 'confirming', 'verifying', 'interrupted'):
            self.assertTrue(_restore_job_active(dict(status=status)), status)
        for status in ('succeeded', 'failed', 'needs_attention', 'partial', 'preflight_failed'):
            self.assertFalse(_restore_job_active(dict(status=status)), status)

    def test_append_caps_at_the_newest_but_keeps_an_in_progress_job_beyond_it(self):
        state = {'restore_jobs': [dict(id=str(i), status='succeeded') for i in range(RESTORE_JOB_CAP)]}
        state['restore_jobs'][0]['status'] = 'interrupted'  # oldest entry; first to fall out of the window
        _append_restore_job(state, dict(id='new', status='queued'))
        self.assertEqual(len(state['restore_jobs']), RESTORE_JOB_CAP + 1)  # the newest cap, plus the survivor
        ids = [j['id'] for j in state['restore_jobs']]
        self.assertIn('0', ids)
        self.assertIn('new', ids)
        self.assertLess(ids.index('0'), ids.index('new'))  # append order (oldest to newest) is preserved

    def test_append_drops_only_terminal_jobs_once_over_cap(self):
        state = {'restore_jobs': [dict(id=str(i), status='succeeded') for i in range(RESTORE_JOB_CAP)]}
        _append_restore_job(state, dict(id='newest', status='succeeded'))
        self.assertEqual(len(state['restore_jobs']), RESTORE_JOB_CAP)
        self.assertNotIn('0', [j['id'] for j in state['restore_jobs']])   # the oldest terminal job was dropped
        self.assertIn('newest', [j['id'] for j in state['restore_jobs']])


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

    def test_snmpv3_keys_and_other_secret_words_are_masked(self):
        for line, secrets in (
                ('snmp-server user u g v3 localized 80000 auth sha 0a1b2c priv aes 9f8e7d', ('80000', '0a1b2c', '9f8e7d')),
                ('snmp-server user u g v3 auth sha encrypted 0x1234 priv aes encrypted 0x5678', ('0x1234', '0x5678')),
                ('+snmp-server user u g v3 localized 80000 auth sha 0a1b2c priv aes 9f8e7d', ('0a1b2c', '9f8e7d')),
                ('username admin sshkey ssh-rsa AAAAB3NzaC1yc2E', ('AAAAB3NzaC1yc2E',)),
                ('set system login user eve authentication ssh-rsa "ssh-rsa AAAAB3Nza eve"', ('AAAAB3Nza',))):
            masked = mask_line(line)
            for secret in secrets:
                self.assertNotIn(secret, masked, line)
            self.assertIn('[redacted]', masked)
        self.assertEqual(mask_line('set interfaces ge-0/0/0 description uplink'), 'set interfaces ge-0/0/0 description uplink')

    def test_a_node_that_is_not_converged_is_never_called_identical(self):
        from app.restore import review_diff
        # Only a left-out comment line differs: the whole texts are shown instead.
        diff = review_diff('set a 1\n', 'set a 1\n# only a comment\n', False, 'Final')
        self.assertFalse(diff['identical'])
        self.assertTrue(diff['hunks'])
        # Nothing a line view can show: still not identical, and the reason is given.
        diff = review_diff('set a 1\n', 'set a 1\n', False, 'Final')
        self.assertFalse(diff['identical'])
        self.assertEqual(diff['hunks'], [])
        self.assertIn('spacing or layout', diff['reason'])
        self.assertTrue(review_diff('set a 1\n', 'set a 1\n', True, 'Final')['identical'])

    def test_after_a_restart_every_target_is_settled_once_the_job_is_finished(self):
        job = self.svc.submit('lab1', self.source(), ['PTX1', 'SW1'], 5, uuid.uuid4().hex)
        self.svc.update(job['id'], status='applying')
        targets = {t['name']: t for t in self.store.state['restore_jobs'][-1]['targets']}
        targets['PTX1'].update(status='confirming', stage='verifying', _token='clabmgr-1a2b3c4d',
                               _handle={'token': 'clabmgr-1a2b3c4d'}, _deadline=1)
        targets['SW1'].update(status='backing_up', stage='backed_up')
        self.store.save()
        again = RestoreService(self.store, self.runner, self.git, connector=fake_connect)
        again.retry_interval = again.recovery_grace = 0
        restarted = {t['name']: t for t in again.get_job(job['id'])['targets']}
        self.assertEqual((restarted['SW1']['status'], restarted['SW1']['stage']), ('interrupted', 'failed'))
        self.assertIn('settled', restarted['SW1']['timeline'])
        self.assertEqual(again.get_job(job['id'])['progress'], {'settled': 1, 'total': 2})
        again.rechecks[job['id']] = 1
        with patch('app.restore.junos.pending', return_value='clabmgr-1a2b3c4d'), \
                patch('app.restore.junos.confirm', return_value={'confirmed': True}), \
                patch('app.restore.junos.capture', return_value=DESIRED_SET):
            again._recheck_interrupted(job['id'], 'PTX1')
        finished = again.get_job(job['id'])
        self.assertEqual(finished['progress'], {'settled': 2, 'total': 2})
        self.assertEqual({t['name']: t['status'] for t in finished['targets']}, {'PTX1': 'verified', 'SW1': 'interrupted'})
        self.assertEqual(finished['status'], 'partial')

    # --- the review diff (saved against running now) ---------------------------------------------

    def review_with(self, running, **kwargs):
        with patch('app.restore.junos.capture', return_value=running):
            return {r['name']: r for r in self.svc.preflight('lab1', self.source(), None, **kwargs)['targets']}

    def test_the_review_shows_each_differing_device_its_diff_against_the_running_configuration(self):
        running = (DESIRED_SET.replace('FINAL-CONTACT', 'CHANGED-CONTACT')
                   + 'set system login user eve authentication encrypted-password "$6$runninghash"\n'
                   + 'set interfaces lo0 unit 0 family inet address 10.9.9.9/32\n')
        rows = self.review_with(running)
        row = rows['PTX1']
        self.assertFalse(row['matches_saved'])
        self.assertEqual(row['pending_changes'], 4)                        # statement counts stay as they were
        diff = row['diff']
        self.assertFalse(diff['identical'])
        self.assertFalse(diff['truncated'])
        self.assertEqual(diff['labels'], {'old': 'Saved (backup ' + self.backup['id'][:10] + ')', 'new': 'Running now'})
        lines = [line for hunk in diff['hunks'] for line in hunk['lines']]
        self.assertIn({'del': 'set snmp contact FINAL-CONTACT'}, [{l['type']: l['text']} for l in lines if l['type'] == 'del'])
        self.assertTrue(any(l['type'] == 'add' and 'lo0' in l['text'] for l in lines))
        self.assertEqual(diff['added'], 3)
        self.assertEqual(diff['removed'], 1)
        # Masked exactly like diff_sample: nothing after the first secret keyword leaves the manager.
        self.assertNotIn('$6$runninghash', str(diff))
        self.assertNotIn('$6$loginhash', str(diff))
        self.assertTrue(any('[redacted]' in l['text'] for l in lines))

    def test_a_device_that_already_matches_carries_an_identical_diff(self):
        row = self.review_with(DESIRED_SET + '# a comment line\n')['PTX1']
        self.assertTrue(row['matches_saved'])
        self.assertEqual(row['diff']['hunks'], [])
        self.assertTrue(row['diff']['identical'])

    def test_devices_without_a_comparison_carry_a_reason_and_never_a_diff(self):
        # An unsupported device and a device the probe could not reach: a reason, no "0 differences".
        self.lab['nodes'][0]['platform'] = 'linux'
        self.store.save()
        def boom(client, node, creds):
            raise OSError('no route')
        self.svc.connect = boom
        rows = self.review_with(DESIRED_SET)
        for name in ('PTX1', 'SW1'):
            self.assertFalse(rows[name]['eligible'], name)
            self.assertTrue(rows[name]['reason'], name)
            self.assertNotIn('diff', rows[name], name)

    def test_a_saved_version_without_restore_data_has_no_diff(self):
        self.backup['nodes'][0].pop('restore_file')
        with self.store.lock:
            next(j for j in self.store.state['jobs'] if j['id'] == self.backup['id'])['nodes'][0].pop('restore_file', None)
            self.store.save()
        rows = self.review_with(DESIRED_SET)
        self.assertFalse(rows['PTX1']['eligible'])
        self.assertTrue(rows['PTX1']['reason'].startswith('This saved configuration has no restore data'))
        self.assertNotIn('diff', rows['PTX1'])
        self.assertIn('diff', rows['SW1'])                                  # the other device still has its diff

    def test_a_long_diff_is_cut_and_says_so(self):
        from app.restore import DIFF_MAX_LINES
        running = DESIRED_SET + ''.join(f'set interfaces ge-0/0/{i} description extra-{i}\n' for i in range(DIFF_MAX_LINES * 2))
        diff = self.review_with(running)['PTX1']['diff']
        self.assertTrue(diff['truncated'])
        self.assertLessEqual(sum(len(h['lines']) for h in diff['hunks']), DIFF_MAX_LINES)
        self.assertEqual(diff['added'], DIFF_MAX_LINES * 2)                 # the counts still describe the whole diff

    def test_the_review_still_answers_when_the_diff_cannot_be_built(self):
        with patch('app.restore._unified', side_effect=RuntimeError('no diff helper')), \
                patch('app.restore.junos.capture', return_value=DESIRED_SET + 'set snmp location LAB\n'):
            row = next(r for r in self.svc.preflight('lab1', self.source(), None)['targets'] if r['name'] == 'PTX1')
        self.assertTrue(row['eligible'])
        self.assertNotIn('diff', row)
        self.assertEqual(row['diff_reason'], 'The differences could not be shown for this device.')

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

    def _fake_git_folder(self, suffix='cfg'):
        import base64, hashlib
        setraw = DESIRED_SET.encode(); hraw = DESIRED_HIER.encode()
        snap = {'manifest': {'schema': 2, 'lab_id': 'lab1', 'lab_name': 'clabllm-dev', 'node_names': ['PTX1'],
                             'files': [{'path': f'PTX1.{suffix}', 'size': len(setraw), 'sha256': hashlib.sha256(setraw).hexdigest(),
                                        'node': 'PTX1', 'platform': 'juniper_cjunosevolved', 'format': 'junos-display-set',
                                        'restore_artifact': 'PTX1.jcfg', 'restore_size': len(hraw),
                                        'restore_sha256': hashlib.sha256(hraw).hexdigest(),
                                        'restore_format': 'junos-hierarchical', 'restore_capable': True}]},
                'files': {f'PTX1.{suffix}': base64.b64encode(setraw).decode(), 'PTX1.jcfg': base64.b64encode(hraw).decode()}}

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

    def test_folder_source_with_a_legacy_set_named_snapshot_still_restores(self):
        # A repository saved before Junos Git snapshots were renamed to `.cfg` still holds
        # `PTX1.set` beside its `.jcfg` restore artifact; the candidate is picked from the
        # manifest's `restore_artifact` field, never guessed from the human file's extension.
        self.svc.git = self._fake_git_folder(suffix='set')
        desc, candidates = self.svc.resolve_source('lab1', {'type': 'folder', 'path': 'labs/BGP-LAB/Broken/latest'})
        self.assertEqual(desc['restore_capable_nodes'], 1)
        self.assertIn('host-name FINAL', candidates['PTX1']['candidate'])
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
                                 'files': [{'path': 'PTX1.cfg', 'size': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
                                            'node': 'PTX1', 'platform': 'juniper_cjunosevolved', 'format': 'junos-display-set',
                                            'restore_artifact': 'PTX1.jcfg', 'restore_size': len(hraw),
                                            'restore_sha256': hashlib.sha256(hraw).hexdigest(),
                                            'restore_format': 'junos-hierarchical', 'restore_capable': True}]},
                    'files': {'PTX1.cfg': base64.b64encode(raw).decode(), 'PTX1.jcfg': base64.b64encode(hraw).decode()}}

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

    def test_finished_job_drops_candidates_from_storage(self):
        # Risk review 2, item 5: a finished job's candidate and desired-state text (tens of KiB per
        # node) is only ever read before _finalize() (by execute() itself, or by
        # _recheck_interrupted() on the restart path); _finalize() drops it so 'restore_jobs' does
        # not grow without bound while it survives its cap.
        self.run_execute()
        stored = self.store.state['restore_jobs'][-1]
        self.assertEqual(stored['status'], 'succeeded')
        self.assertNotIn('_candidates', stored)

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

    def test_restart_recheck_reports_uncertain_when_the_candidate_is_gone_and_other_nodes_still_finish(self):
        # T-003: the lab or a node's saved candidate can be gone by the time a restart-recheck runs
        # (the lab was removed, or the candidate the job started with is no longer tracked). This
        # must not abandon the batch: the affected node is reported 'uncertain', and the job's other
        # node is still looked at and finished normally by the same restart recheck.
        job = self.svc.submit('lab1', self.source(), ['PTX1', 'SW1'], 5, uuid.uuid4().hex)
        self.svc.update(job['id'], status='applying')
        stored = next(j for j in self.store.state['restore_jobs'] if j['id'] == job['id'])
        for target in stored['targets']: target['status'] = 'applying'
        stored['_candidates'].pop('PTX1')       # the saved candidate is no longer available for this node
        self.store.save()
        again = RestoreService(self.store, self.runner, self.git, connector=fake_connect)
        again.retry_interval = again.recovery_grace = 0
        self.assertEqual(sorted(again.unchecked), sorted([(job['id'], 'PTX1'), (job['id'], 'SW1')]))
        again.rechecks[job['id']] = 2
        with patch('app.restore.junos.apply_candidate') as apply, patch('app.restore.junos.confirm') as confirm, \
                patch('app.restore.junos.capture', return_value=DESIRED_SET):
            again._recheck_all([(job['id'], 'PTX1'), (job['id'], 'SW1')])
        result = again.get_job(job['id'])
        by_name = {t['name']: t for t in result['targets']}
        self.assertEqual(by_name['PTX1']['status'], 'uncertain')
        self.assertIn('could not check the device', by_name['PTX1']['message'])
        self.assertEqual(by_name['SW1']['status'], 'verified')     # the healthy node was still rechecked and finished
        self.assertEqual(result['status'], 'needs_attention')      # the job as a whole reflects the unresolved node
        apply.assert_not_called(); confirm.assert_not_called()      # nothing is ever re-applied or blindly confirmed

    def test_restart_recheck_reports_uncertain_when_the_lab_is_gone(self):
        # T-003 (risk review 2, item 7): the lab itself can be removed before a restart-recheck
        # runs; this is the same LookupError branch as a missing candidate ('not node'), exercised
        # here directly rather than only through a missing '_candidates' entry.
        job = self.svc.submit('lab1', self.source(), ['PTX1'], 5, uuid.uuid4().hex)
        self.svc.update(job['id'], status='applying')
        stored = next(j for j in self.store.state['restore_jobs'] if j['id'] == job['id'])
        stored['targets'][0]['status'] = 'applying'
        self.store.state['labs'] = [l for l in self.store.state['labs'] if l['id'] != 'lab1']
        self.store.save()
        again = RestoreService(self.store, self.runner, self.git, connector=fake_connect)
        again.retry_interval = again.recovery_grace = 0
        self.assertEqual(again.unchecked, [(job['id'], 'PTX1')])
        again.rechecks[job['id']] = 1
        with patch('app.restore.junos.apply_candidate') as apply, patch('app.restore.junos.confirm') as confirm, \
                patch('app.restore.junos.capture', return_value=DESIRED_SET):
            again._recheck_all([(job['id'], 'PTX1')])
        result = again.get_job(job['id'])
        self.assertEqual(result['targets'][0]['status'], 'uncertain')
        self.assertIn('could not check the device', result['targets'][0]['message'])
        self.assertEqual(result['status'], 'needs_attention')
        apply.assert_not_called(); confirm.assert_not_called()

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


# --- parallel nodes, stages and the review diff --------------------------------------------------------

BEFORE_SET = 'set system host-name BEFORE\n'


class NodeDriver:
    """A fake restore driver for several nodes at once. The connector labels each connection with its node,
    so the driver can tell the nodes apart and prove that nothing of one node reaches another."""
    RESTORE_FORMAT = 'junos-hierarchical'

    def __init__(self, kinds, holds=False):
        import threading
        self.SUPPORTED_KINDS = tuple(kinds)
        self.HOLDS_SESSION = holds
        self.lock = threading.Lock()
        self.armed, self.done, self.confirmed, self.released, self.crossed = {}, set(), [], [], []
        self.inside = self.peak = 0
        self.hooks, self.pending_hooks, self.confirm_hooks, self.running = {}, {}, {}, {}

    @staticmethod
    def validate_candidate(text):
        return None

    @staticmethod
    def compare(desired, actual):
        from app.restore_compare import compare_junos
        return compare_junos(desired, actual)

    def apply_candidate(self, client, candidate, minutes, token=None):
        node = client.node
        with self.lock:
            self.inside += 1
            self.peak = max(self.peak, self.inside)
            self.armed[node] = token
        try:
            hook = self.hooks.get(node)
            result = hook(token) if hook else None
            return result if result is not None else {'diff': '+ set system host-name FINAL', 'no_op': False,
                                                      'handle': {'token': token}}
        finally:
            with self.lock:
                self.inside -= 1

    def pending(self, client):
        node = client.node
        if node in self.pending_hooks:
            return self.pending_hooks[node](self.armed.get(node))
        return '' if node in self.done else self.armed.get(node, '')

    def confirm(self, client, handle):
        node = client.node
        if handle.get('token') != self.armed.get(node):
            self.crossed.append(node)
        if node in self.confirm_hooks:
            self.confirm_hooks[node]()
        with self.lock:
            self.confirmed.append((node, handle.get('token')))
            self.done.add(node)
        return {'confirmed': True}

    def release(self, token):
        with self.lock:
            self.released.append(token)

    def capture(self, client):
        return self.running.get(client.node, DESIRED_SET)


class ParallelRestoreTests(unittest.TestCase):
    """Several nodes of one restore job at the same time: overlap, the worker bound, isolation of failures,
    out-of-order outcomes, shutdown and restart, the store under concurrent writes, and the stage record."""

    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(self.tmp.name)
        self.store.state['host'] = {'enabled': True, 'address': '10.0.0.1', 'port': 22, 'username': 'clab',
                                    'password': 'vm-secret', 'fingerprint': 'SHA256:fix', 'auth': 'password'}
        self.plain = NodeDriver(('juniper_cjunosevolved',))
        self.holding = NodeDriver(('cisco_xrv9k',), holds=True)
        self.holding.RESTORE_FORMAT = ''          # the saved artifacts here are all Junos-shaped
        self.use_lab(('A', 'B', 'C', 'D'))
        self.runner = FakeRunner(self.store)
        patch('app.restore.drivers.for_platform',
              side_effect=lambda platform: {'juniper_cjunosevolved': self.plain, 'cisco_xrv9k': self.holding}.get(platform)).start()
        patch('app.restore.drivers.options', return_value={}).start()
        self.addCleanup(patch.stopall)

    def use_lab(self, names, platforms=None, addresses=None):
        platforms = platforms or {}
        addresses = addresses or {}
        nodes = []
        for index, name in enumerate(names):
            nodes.append({'name': name, 'platform': platforms.get(name, 'juniper_cjunosevolved'),
                          'address': addresses.get(name, f'172.20.20.{10 + index}'), 'port': 22, 'enabled': True,
                          'profile_id': '', 'username': 'admin', 'password': 'node-secret', 'endpoint_mode': 'manual',
                          'discovered': True, 'runtime_state': 'running', 'discovered_address': '172.20.20.2',
                          'short_name': name})
        self.lab = {'id': 'lab1', 'name': 'par-lab', 'deployment_name': 'par-lab', 'profiles': [], 'defaults': {},
                    'interval': 0, 'next_run': None, 'nodes': nodes}
        self.store.state['labs'] = [self.lab]
        self.store.state['discovery'] = {'ok': True, 'checked_epoch': time.time(), 'checked_at': 'x', 'last_success': 'x',
                                         'labs': {'par-lab': [{'name': n, 'state': 'running', 'address': '172.20.20.2'}
                                                              for n in names]}}
        self.store.save()
        self.backup = RestoreServiceTests.make_source_backup(self)

    @staticmethod
    def connector(client, node, creds):
        client.node = node['name']

    def service(self, workers):
        svc = RestoreService(self.store, self.runner, object(), connector=self.connector, node_workers=workers)
        svc.retry_interval = svc.recovery_grace = svc.connect_pause = 0
        svc.window_seconds = lambda minutes: 0
        patch.object(svc.pool, 'submit').start()
        self.addCleanup(svc.node_pool.shutdown, wait=True)
        return svc

    def run_job(self, svc, names=None):
        names = list(names or [n['name'] for n in self.lab['nodes']])
        job = svc.submit('lab1', {'type': 'backup', 'backup_job_id': self.backup['id']}, names, 5, uuid.uuid4().hex)
        svc.execute(job['id'])
        return svc.get_job(job['id'])

    @staticmethod
    def by_name(job):
        return {t['name']: t for t in job['targets']}

    # --- configuration --------------------------------------------------------------------------

    def test_the_worker_count_defaults_to_four_and_is_clamped(self):
        from app.restore import node_worker_count
        with patch.dict('os.environ', {}, clear=True):
            self.assertEqual(node_worker_count(), 4)
        for raw, expected in (('1', 1), ('3', 3), ('8', 8), ('0', 1), ('-2', 1), ('99', 8), ('', 4), ('many', 4)):
            with patch.dict('os.environ', {'RESTORE_NODE_WORKERS': raw}):
                self.assertEqual(node_worker_count(), expected, raw)
        self.assertEqual(node_worker_count(2), 2)
        with patch.dict('os.environ', {'RESTORE_NODE_WORKERS': '6'}):
            self.assertEqual(RestoreService(self.store, self.runner, object(), connector=self.connector).node_workers, 6)

    # --- overlap and the worker bound ---------------------------------------------------------------

    def test_nodes_are_inside_their_change_at_the_same_time(self):
        import threading
        gate = threading.Barrier(4, timeout=10)     # breaks (and fails every node) unless all four are inside apply at once
        for name in 'ABCD':
            self.plain.hooks[name] = lambda token: gate.wait() and None
        job = self.run_job(self.service(4))
        self.assertEqual(job['status'], 'succeeded', job['message'])
        self.assertEqual(self.plain.peak, 4)
        targets = job['targets']
        self.assertTrue(all(t['status'] == 'verified' for t in targets))
        # Overlap is visible on the job document alone: every node started before any node settled.
        self.assertLess(max(t['timeline']['connecting'] for t in targets), min(t['timeline']['settled'] for t in targets))
        self.assertEqual(len({t['worker'] for t in targets}), 4)
        self.assertTrue(all(t['worker'].startswith('restore-node') for t in targets))
        self.assertEqual(job['progress'], {'settled': 4, 'total': 4})

    def test_never_more_nodes_at_once_than_workers(self):
        for name in 'ABCD':
            self.plain.hooks[name] = lambda token: time.sleep(0.05)
        job = self.run_job(self.service(2))
        self.assertEqual(job['status'], 'succeeded', job['message'])
        self.assertEqual(self.plain.peak, 2)
        self.assertEqual(len({t['worker'] for t in job['targets']}), 2)

    def test_one_worker_changes_the_nodes_one_after_another_in_target_order(self):
        order = []
        for name in 'ABCD':
            self.plain.hooks[name] = lambda token, name=name: order.append(name)
        job = self.run_job(self.service(1))
        self.assertEqual(job['status'], 'succeeded', job['message'])
        self.assertEqual(order, ['A', 'B', 'C', 'D'])
        self.assertEqual(self.plain.peak, 1)
        targets = job['targets']
        for first, second in zip(targets, targets[1:]):
            self.assertLessEqual(first['timeline']['settled'], second['timeline']['connecting'])

    def test_two_targets_behind_one_ssh_endpoint_are_changed_one_after_another(self):
        # The IOS XR driver finds its held arming session by peer address: two targets on one endpoint must
        # never be in flight together, whatever the worker count.
        self.use_lab(('A', 'B', 'C'), addresses={'A': '172.20.20.50', 'B': '172.20.20.50'})
        for name in 'ABC':
            self.plain.hooks[name] = lambda token: time.sleep(0.05)
        job = self.run_job(self.service(4))
        self.assertEqual(job['status'], 'succeeded', job['message'])
        a, b, c = (self.by_name(job)[n] for n in 'ABC')
        self.assertLessEqual(a['timeline']['settled'], b['timeline']['connecting'])
        self.assertEqual(a['worker'], b['worker'])
        self.assertNotEqual(a['worker'], c['worker'])
        self.assertLess(c['timeline']['connecting'], b['timeline']['settled'])   # the other endpoint still ran alongside

    # --- isolation --------------------------------------------------------------------------------

    def test_one_nodes_failure_never_decides_another_nodes_outcome(self):
        from app.restore_shell import RestoreError, SessionLost
        self.use_lab(('A', 'B', 'C', 'D'), platforms={'B': 'cisco_xrv9k', 'C': 'cisco_xrv9k'})
        self.runner.pre_config = BEFORE_SET
        svc = self.service(4)
        svc.recovery_grace = 30                          # B needs a second look inside the window
        # A: the node rejects the candidate before anything is armed.
        self.plain.hooks['A'] = lambda token: (_ for _ in ()).throw(RestoreError('The node rejected it.'))
        # B: the session dies after arming; the node shows our change, the confirmation is lost with
        # management, the node undoes it and the previous configuration is read back.
        seen = []
        self.holding.hooks['B'] = lambda token: (_ for _ in ()).throw(SessionLost('closed'))
        self.holding.pending_hooks['B'] = lambda token: (seen.append(token) or token) if token and not seen else ''
        self.holding.confirm_hooks['B'] = lambda: (_ for _ in ()).throw(OSError('management is gone'))
        self.holding.running['B'] = BEFORE_SET
        # C: the held-session driver confirms normally.  D: an unexpected error inside the node's own task.
        self.plain.hooks['D'] = lambda token: 'not a result'
        self.plain.pending_hooks['D'] = lambda token: ''
        self.plain.running['D'] = 'set system host-name SOMETHING-ELSE\n'
        job = self.run_job(svc)
        targets = self.by_name(job)
        self.assertEqual({n: t['status'] for n, t in targets.items()},
                         {'A': 'failed', 'B': 'rolled_back', 'C': 'verified', 'D': 'uncertain'})
        self.assertEqual({n: t['stage'] for n, t in targets.items()},
                         {'A': 'failed', 'B': 'rolled_back', 'C': 'replaced', 'D': 'uncertain'})
        self.assertEqual(job['status'], 'needs_attention')
        self.assertNotIn('Restore interrupted', job['message'])     # nothing reached execute()
        # Tokens never cross: each confirmation carried its own node's token, and only C's got through.
        self.assertEqual(self.plain.crossed + self.holding.crossed, [])
        self.assertEqual(self.holding.confirmed, [('C', self.holding.armed['C'])])
        self.assertEqual(self.plain.confirmed, [])
        # The held sessions (B and C) are each released exactly once; A and D never held one.
        self.assertEqual(sorted(self.holding.released), sorted([self.holding.armed['B'], self.holding.armed['C']]))
        self.assertEqual(self.plain.released, [])
        self.assertEqual(self.runner.calls[-1], {'source': 'restore-post', 'node_names': ['C']})
        self.assertEqual(job['progress'], {'settled': 4, 'total': 4})

    def test_an_error_before_a_nodes_change_starts_is_that_nodes_outcome_and_its_endpoint_neighbour_still_runs(self):
        from app import restore as restore_module
        self.use_lab(('A', 'B', 'C'), addresses={'A': '172.20.20.50', 'B': '172.20.20.50'})
        svc = self.service(4)
        job = svc.submit('lab1', {'type': 'backup', 'backup_job_id': self.backup['id']}, ['A', 'B', 'C'], 5, uuid.uuid4().hex)
        real = restore_module.effective_credentials

        def credentials(lab, node):
            if node['name'] == 'A':
                raise RuntimeError('credential lookup broke')
            return real(lab, node)
        with patch('app.restore.effective_credentials', side_effect=credentials):
            svc.execute(job['id'])
        result = svc.get_job(job['id'])
        targets = self.by_name(result)
        self.assertEqual({n: t['status'] for n, t in targets.items()}, {'A': 'failed', 'B': 'verified', 'C': 'verified'})
        self.assertEqual(targets['A']['message'], 'Configuration was not changed: internal error (RuntimeError).')
        self.assertEqual(targets['A']['stage'], 'failed')
        self.assertNotIn('A', self.plain.armed)
        self.assertEqual(result['status'], 'partial')                   # decided per node, never by execute()
        self.assertNotIn('Restore interrupted', result['message'])
        self.assertEqual(result['progress'], {'settled': 3, 'total': 3})

    def test_outcomes_arrive_out_of_order_and_the_follow_up_backup_keeps_target_order(self):
        delays = {'A': 0.3, 'B': 0.1, 'C': 0.2, 'D': 0.0}
        for name, delay in delays.items():
            self.plain.hooks[name] = lambda token, delay=delay: time.sleep(delay)
        job = self.run_job(self.service(4))
        settled = sorted(job['targets'], key=lambda t: t['timeline']['settled'])
        self.assertEqual([t['name'] for t in settled], ['D', 'B', 'C', 'A'])
        self.assertEqual(self.runner.calls[-1], {'source': 'restore-post', 'node_names': ['A', 'B', 'C', 'D']})
        self.assertEqual(job['status'], 'succeeded')
        self.assertEqual(job['message'], 'All 4 node(s) restored and verified against the saved state.')

    # --- shutdown and restart ----------------------------------------------------------------------

    def test_a_shutdown_while_nodes_are_armed_records_nothing_and_starts_no_new_node(self):
        import threading
        svc = self.service(2)
        svc.retry_interval, svc.recovery_grace = 5, 3600
        svc.window_seconds = lambda minutes: 3600
        both_armed = threading.Barrier(2, timeout=10)

        def unreachable(token):
            both_armed.wait()
            svc.stopping.set()                            # the manager is told to stop while A and B wait to confirm
            raise OSError('management is down')
        self.plain.pending_hooks.update(A=lambda token: unreachable(token) if token else '',
                                        B=lambda token: unreachable(token) if token else '')
        job = self.run_job(svc)
        targets = self.by_name(job)
        self.assertEqual(targets['A']['status'], 'confirming')
        self.assertEqual(targets['B']['status'], 'confirming')
        self.assertEqual((targets['C']['status'], targets['C']['stage']), ('backing_up', 'backed_up'))
        self.assertEqual((targets['D']['status'], targets['D']['stage']), ('backing_up', 'backed_up'))
        self.assertNotIn('C', self.plain.armed)
        self.assertNotIn('D', self.plain.armed)
        self.assertEqual(job['status'], 'applying')                     # no verification, no finalize
        self.assertEqual([c['source'] for c in self.runner.calls], ['restore-pre'])
        self.assertEqual(self.plain.confirmed, [])
        again = RestoreService(self.store, self.runner, object(), connector=self.connector, node_workers=2)
        self.addCleanup(again.close)
        reloaded = again.get_job(job['id'])
        self.assertEqual(reloaded['status'], 'interrupted')
        self.assertEqual(sorted(again.unchecked), [(job['id'], 'A'), (job['id'], 'B')])
        self.assertTrue(all(t['message'] == 'Restore interrupted before this node was changed.'
                            for t in reloaded['targets'] if t['name'] in 'CD'))

    def test_close_drops_node_tasks_that_have_not_started(self):
        import threading
        svc = self.service(1)
        svc.node_workers = 2                              # two workers for the job, but the pool cannot take them
        svc.node_pool.shutdown(wait=True)
        svc.node_pool = __import__('concurrent.futures').futures.ThreadPoolExecutor(max_workers=1)
        started = threading.Event()
        release = threading.Event()

        def first(token):
            started.set()
            release.wait(10)
        self.plain.hooks['A'] = first
        job = svc.submit('lab1', {'type': 'backup', 'backup_job_id': self.backup['id']}, ['A', 'B'], 5, uuid.uuid4().hex)
        worker = threading.Thread(target=svc.execute, args=(job['id'],))
        worker.start()
        self.assertTrue(started.wait(10))
        svc.close()                                       # B's task is still queued behind A's: it is cancelled
        release.set()
        worker.join(10)
        self.assertFalse(worker.is_alive())
        targets = self.by_name(svc.get_job(job['id']))
        self.assertNotIn('B', self.plain.armed)
        self.assertEqual(targets['B']['status'], 'backing_up')
        self.assertEqual(svc.get_job(job['id'])['status'], 'applying')

    def test_after_a_restart_the_nodes_are_read_back_side_by_side_and_the_job_is_finalized_once(self):
        import threading
        svc = self.service(4)
        job = svc.submit('lab1', {'type': 'backup', 'backup_job_id': self.backup['id']}, ['A', 'B', 'C'], 5, uuid.uuid4().hex)
        with self.store.lock:
            stored = svc.get_job(job['id'])
            stored['status'] = 'applying'
            for target in stored['targets']:
                token = 'clabmgr-' + target['name'] * 8
                target.update(status='confirming', stage='verifying', _token=token, _handle={'token': token}, _deadline=1)
                self.plain.armed[target['name']] = token
            self.store.save()
        again = RestoreService(self.store, self.runner, object(), connector=self.connector, node_workers=3)
        self.addCleanup(again.close)
        again.retry_interval = again.recovery_grace = 0
        together = threading.Barrier(3, timeout=10)       # fails unless the three read-backs are open at once
        for name in 'ABC':
            self.plain.pending_hooks[name] = lambda token, name=name: (together.wait(), token)[1] if name not in self.plain.done else ''
        finalized = []
        original = again._finalize
        again._finalize = lambda *args, **kwargs: (finalized.append(args), original(*args, **kwargs))
        again.start()
        again.pool.shutdown(wait=True)                    # the scheduler waits for every read-back
        result = again.get_job(job['id'])
        self.assertEqual([t['status'] for t in result['targets']], ['verified'] * 3)
        self.assertEqual(sorted(self.plain.confirmed), [(n, 'clabmgr-' + n * 8) for n in 'ABC'])
        self.assertEqual(len(finalized), 1)
        self.assertEqual(result['status'], 'succeeded')
        self.assertTrue(result['message'].startswith('Checked after a manager restart.'))

    # --- the stage record --------------------------------------------------------------------------

    def test_stages_and_timeline_follow_one_node_through_a_restore(self):
        seen = []
        original = RestoreService.stage_target

        def spy(svc, job_id, name, stage, *args, **fields):
            seen.append((name, stage))
            return original(svc, job_id, name, stage, *args, **fields)
        with patch.object(RestoreService, 'stage_target', spy):
            job = self.run_job(self.service(4), ['A'])
        self.assertEqual([stage for name, stage in seen],
                         ['backing_up', 'backed_up', 'connecting', 'applying', 'armed', 'verifying', 'confirming',
                          'replaced', 'checking', 'replaced'])
        target = job['targets'][0]
        self.assertEqual((target['status'], target['stage'], target['attempts']), ('verified', 'replaced', 1))
        timeline = target['timeline']
        order = ['queued', 'backing_up', 'backed_up', 'connecting', 'applying', 'armed', 'verifying', 'confirming',
                 'replaced', 'checking', 'checked']
        self.assertEqual([timeline[key] for key in order], sorted(timeline[key] for key in order))
        self.assertEqual(timeline['settled'], timeline['replaced'])
        from app.restore import STAGES
        self.assertTrue(all(stage in STAGES for _name, stage in seen))

    def test_a_device_that_reports_nothing_to_change_is_labelled_matched_and_still_counts_as_verified(self):
        self.plain.hooks['A'] = lambda token: {'diff': '', 'no_op': True, 'handle': {'token': token}}
        job = self.run_job(self.service(4), ['A'])
        target = job['targets'][0]
        self.assertEqual((target['status'], target['stage']), ('verified', 'matched'))
        self.assertEqual(job['status'], 'succeeded')

    def test_a_node_that_stopped_is_skipped_and_counted_as_settled(self):
        svc = self.service(4)
        job = svc.submit('lab1', {'type': 'backup', 'backup_job_id': self.backup['id']}, ['A', 'B'], 5, uuid.uuid4().hex)
        self.lab['nodes'][1]['runtime_state'] = 'exited'
        self.store.save()
        svc.execute(job['id'])
        targets = self.by_name(svc.get_job(job['id']))
        self.assertEqual((targets['B']['status'], targets['B']['stage']), ('ineligible', 'skipped'))
        self.assertEqual(svc.get_job(job['id'])['progress'], {'settled': 2, 'total': 2})

    def test_the_public_job_carries_the_stage_record_and_no_secret(self):
        from app.restore import public_job
        job = self.run_job(self.service(4), ['A'])
        public = public_job(job)
        self.assertEqual(public['progress'], {'settled': 1, 'total': 1})
        target = public['targets'][0]
        for key in ('stage', 'timeline', 'attempts', 'worker'):
            self.assertIn(key, target)
        self.assertFalse(any(key.startswith('_') for key in target))
        blob = str(public)
        for secret in ('node-secret', 'vm-secret', '$6$loginhash', 'clabmgr-'):
            self.assertNotIn(secret, blob)

    def test_concurrent_stage_writes_on_different_targets_lose_nothing(self):
        import json
        import threading
        names = [f'N{i}' for i in range(8)]
        svc = self.service(4)
        job = {'id': 'race', 'lab_id': 'lab1', 'status': 'applying', 'targets': [
            {'name': n, 'status': 'pending', 'stage': 'queued', 'timeline': {}, 'attempts': 0} for n in names],
            'progress': {'settled': 0, 'total': 8}}
        with self.store.lock:
            self.store.state['restore_jobs'].append(job)
            self.store.save()
        cycle = ['connecting', 'applying', 'armed', 'verifying', 'confirming']

        def writer(name):
            for step in range(50):
                stage = 'replaced' if step == 49 else cycle[step % len(cycle)]
                svc.stage_target('race', name, stage, attempts=step, note=f'{name}-{step}')
        threads = [threading.Thread(target=writer, args=(n,)) for n in names]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(30)
        stored = svc.get_job('race')
        for target in stored['targets']:
            self.assertEqual((target['stage'], target['attempts'], target['note']), ('replaced', 49, target['name'] + '-49'))
            self.assertEqual(set(target['timeline']), set(cycle) | {'replaced', 'settled'})
        self.assertEqual(stored['progress'], {'settled': 8, 'total': 8})
        # What reached the disk decrypts to the same targets.
        reread = Store(self.tmp.name)
        on_disk = next(j for j in reread.state['restore_jobs'] if j['id'] == 'race')
        self.assertEqual(json.dumps(on_disk['targets'], sort_keys=True), json.dumps(stored['targets'], sort_keys=True))


if __name__ == '__main__':
    unittest.main()
