"""Apply a saved configuration to a running node as a managed, safe restore job.

A restore takes a saved *desired state* (a Git version, or a local backup) and drives a
running Junos node to exactly that state without a reboot or a containerlab redeploy.
It reuses the manager's existing direct node-SSH path (no new host helper) and the
Runner for durable pre- and post-restore backups, and it serialises against backups,
Git saves and lab operations through ``operation_busy``.

Flow: preflight -> mandatory pre-restore backup -> per node (load the whole-device
candidate with a confirmed commit, reconnect to prove management, confirm) -> post
backup and desired-state comparison. Only Junos is supported; the loading mechanism and
its commit-confirmed safety are in :mod:`restore_junos`.

Nothing here writes raw configuration or secrets to logs or the API: the review shows
counts and masked sample lines, and every message is scrubbed.
"""
import base64
import copy
import re
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import paramiko
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field

from . import restore_junos as junos
from .discovery import discovery_fresh, node_available
from .git_progress import captured_snapshot, decoded_snapshot, digest, host_identity, repo_path
from .inventory import PLATFORMS
from .lab_operations import RESTORE_BUSY, operation_busy, scrub
from .node_services import connect
from .runner import effective_credentials, now

PUBLIC_JOB = ('id', 'lab_id', 'lab_name', 'created', 'finished', 'status', 'message', 'source',
              'confirm_minutes', 'pre_backup_job_id', 'post_backup_job_id', 'targets')
# Statuses that let a lab be touched again once the restore has settled.
DONE = ('succeeded', 'partial', 'failed', 'needs_attention', 'preflight_failed', 'interrupted', 'dismissed')

ROOTAUTH = re.compile(r'^\s*set system root-authentication\b')
VOLATILE = re.compile(r'^\s*set (?:version|system time|.*last-changed)\b')
QUOTED = re.compile(r'"[^"]*"')
SECRET_WORD = re.compile(r'(?i)(secret|password|authentication-key|pre-shared-key|community)')


def public_job(job):
    return {k: copy.deepcopy(job[k]) for k in PUBLIC_JOB if k in job}


def set_lines(text):
    """Comparable `display set` statements: nonempty, non-comment, trimmed."""
    return [line.rstrip() for line in (text or '').splitlines()
            if line.strip() and not line.lstrip().startswith('#')]


def mask_line(line):
    """A statement safe to show: quoted values and secret operands hidden."""
    if SECRET_WORD.search(line):
        line = QUOTED.sub('"[redacted]"', line)
        line = re.sub(r'(?i)(secret|password|authentication-key|pre-shared-key|community)(\s+)(\S+)',
                      r'\1\2[redacted]', line)
    return line[:200]


def compare_states(desired_set, actual_set):
    """Compare desired vs running display-set. Returns (missing, extra, converged).

    missing: desired statements not present after restore (must be empty).
    extra:   statements present but not desired (must be empty), except the mandatory
             root-authentication the driver may synthesise and volatile version lines.
    """
    desired = set(set_lines(desired_set))
    actual = set(set_lines(actual_set))
    missing = sorted(desired - actual)
    extra = [l for l in sorted(actual - desired) if not ROOTAUTH.match(l) and not VOLATILE.match(l)]
    converged = not missing and not extra
    return missing, extra, converged


class RestoreService:
    def __init__(self, store, runner, git_progress, connector=None):
        self.store = store
        self.runner = runner
        self.git = git_progress
        self.connect = connector or connect
        self.stopping = threading.Event()
        self.pool = ThreadPoolExecutor(max_workers=1)
        with store.lock:
            for job in store.state.setdefault('restore_jobs', []):
                if job['status'] in RESTORE_BUSY:
                    job.update(status='interrupted', finished=now(),
                               message='Manager restarted during a restore. Check the target nodes; '
                                       'a confirmed commit that was not confirmed rolls back on its own.')
                    for target in job.get('targets', []):
                        if target.get('status') in ('applying', 'confirming', 'backing_up', 'pending', 'ready', 'preflight'):
                            target.update(status='interrupted',
                                          message='Restore interrupted; if a commit was armed it rolls back automatically.')
            store.save()

    def close(self):
        self.stopping.set()
        self.pool.shutdown(wait=False, cancel_futures=True)

    # --- helpers ---------------------------------------------------------------

    def get_job(self, job_id):
        job = next((j for j in self.store.state['restore_jobs'] if j['id'] == job_id), None)
        if not job:
            raise HTTPException(404, 'Restore job not found.')
        return job

    def update(self, job_id, **fields):
        with self.store.lock:
            job = self.get_job(job_id)
            old = copy.deepcopy(job)
            job.update(fields)
            try:
                self.store.save()
            except OSError:
                job.clear()
                job.update(old)
                raise

    def update_target(self, job_id, name, **fields):
        with self.store.lock:
            job = self.get_job(job_id)
            for target in job.get('targets', []):
                if target['name'] == name:
                    target.update(fields)
            try:
                self.store.save()
            except OSError:
                pass

    def event(self, action, message, lab_id, job_id, node='', level='info'):
        try:
            with self.store.lock:
                message = scrub(str(message), self.store.state)
            self.store.event(action, message[:2000], level=level, lab_id=lab_id, job_id=job_id, node=node)
        except OSError:
            pass

    def guard_idle(self, lab_id=None, exclude=None):
        state = self.store.state
        if operation_busy(state, lab_id, progress_id=exclude) or any(
                j['status'] in ('queued', 'running') for j in state['jobs']):
            raise HTTPException(409, 'Wait for the active backup, Git save, restore or lab operation to finish.')
        if self.store.reset_pending:
            raise HTTPException(409, 'Finish the storage reset first.')

    # --- source resolution -----------------------------------------------------

    def resolve_source(self, lab_id, source):
        """Return (description, candidates) where candidates maps a saved node name to
        {candidate, desired_set, platform, restore_format}. Raises HTTPException."""
        stype = source.get('type')
        if stype == 'git':
            with self.store.lock:
                binding = self.git.binding(lab_id)
            try:
                result = self.git.invoke(
                    {'mode': 'read-version', 'commit': source['commit'], 'path': repo_path(binding, source['path'])},
                    binding)
                manifest, files = decoded_snapshot(result)
            except ValueError as exc:
                raise HTTPException(409, str(exc))
            desc = {'type': 'git', 'commit': source['commit'], 'path': source['path'],
                    'captured_at': manifest.get('captured_at', ''), 'lab_name': manifest.get('lab_name', '')}
            text = {name: raw.decode('utf-8') for name, raw in files.items()}
        elif stype == 'backup':
            with self.store.lock:
                backup = next((copy.deepcopy(b) for b in self.store.state['jobs']
                               if b['id'] == source.get('backup_job_id') and b['lab_id'] == lab_id), None)
            if not backup:
                raise HTTPException(404, 'Saved capture not found in this lab.')
            try:
                snap = captured_snapshot(self.store, backup)
            except ValueError as exc:
                raise HTTPException(400, str(exc))
            manifest = snap['manifest']
            text = {name: base64.b64decode(raw).decode('utf-8') for name, raw in snap['files'].items()}
            desc = {'type': 'backup', 'backup_job_id': backup['id'],
                    'captured_at': manifest.get('captured_at', ''), 'lab_name': manifest.get('lab_name', '')}
        else:
            raise HTTPException(400, 'Choose a saved Git version or a saved capture as the restore source.')

        candidates = {}
        for entry in manifest.get('files', []):
            artifact = entry.get('restore_artifact')
            if not artifact or artifact not in text or entry.get('path') not in text:
                continue  # this node predates restore support or lacks its candidate
            candidates[entry['node']] = {
                'candidate': text[artifact], 'desired_set': text[entry['path']],
                'platform': entry.get('platform', ''), 'restore_format': entry.get('restore_format', ''),
                'short_name': entry.get('short_name', '')}
        desc['restore_capable_nodes'] = len(candidates)
        desc['saved_nodes'] = manifest.get('node_names', [])
        return desc, candidates

    # --- eligibility (no device access) ----------------------------------------

    def map_targets(self, lab, candidates, requested):
        """Match saved node names to running lab nodes and decide per-node eligibility."""
        running_names = {n['name'] for n in lab['nodes']}
        rows = []
        for name in sorted(candidates):
            cand = candidates[name]
            node = next((n for n in lab['nodes'] if n['name'] == name), None)
            reason = ''
            eligible = False
            if node is None:
                reason = 'No running node in this lab matches this saved node.'
            elif not junos.supports_restore(node.get('platform')):
                reason = 'Live restore is not supported for this platform yet.'
            elif node.get('platform') != cand['platform']:
                reason = 'The saved platform does not match the running node.'
            elif not node_available(self.store.state, lab, node):
                reason = 'The node is not currently running or discovery is stale.'
            elif not effective_credentials(lab, node).get('username'):
                reason = 'Assign NOS credentials to this node first.'
            else:
                eligible = True
            rows.append({'name': name, 'short_name': cand.get('short_name') or (node.get('short_name', '') if node else ''),
                         'platform': cand['platform'], 'running_platform': node.get('platform', '') if node else '',
                         'eligible': eligible, 'reason': reason,
                         'requested': (requested is None) or (name in requested)})
        return rows

    # --- preflight (read-only, with a live reachability + match probe) ----------

    def preflight(self, lab_id, source, requested):
        with self.store.lock:
            lab = self.store.lab(lab_id)
            if not lab:
                raise HTTPException(404, 'Lab not found.')
            self.guard_idle(lab_id)
            lab = copy.deepcopy(lab)
            fresh = discovery_fresh(self.store.state)
        desc, candidates = self.resolve_source(lab_id, source)
        rows = self.map_targets(lab, candidates, requested)
        if not fresh:
            for row in rows:
                if row['eligible']:
                    row.update(eligible=False, reason='Refresh VM discovery before restoring.')
        # Live probe eligible, requested nodes: prove SSH + compute a current-state match.
        for row in rows:
            if not (row['eligible'] and row['requested']):
                continue
            node = next(n for n in lab['nodes'] if n['name'] == row['name'])
            creds = effective_credentials(lab, node)
            try:
                current = self._capture(node, creds)
                missing, extra, converged = compare_states(candidates[row['name']]['desired_set'], current)
                row.update(reachable=True, matches_saved=converged,
                           pending_changes=len(missing) + len(extra))
            except Exception as exc:
                row.update(reachable=False, eligible=False,
                           reason=scrub(f'SSH probe failed: {type(exc).__name__}', self.store.state))
        return {'source': desc, 'targets': rows,
                'eligible_count': sum(1 for r in rows if r['eligible'] and r['requested'])}

    def _capture(self, node, creds, display_set=True):
        client = paramiko.SSHClient()
        try:
            self.connect(client, node, creds)
            return junos.capture(client, display_set=display_set)
        finally:
            client.close()

    # --- execution -------------------------------------------------------------

    def submit(self, lab_id, source, node_names, confirm_minutes, request_id):
        with self.store.lock:
            existing = next((j for j in self.store.state['restore_jobs'] if j.get('request_id') == request_id), None)
            if existing:
                return public_job(existing)
            lab = self.store.lab(lab_id)
            if not lab:
                raise HTTPException(404, 'Lab not found.')
            self.guard_idle(lab_id)
            before = host_identity(self.store.state.get('host', {}))
        desc, candidates = self.resolve_source(lab_id, source)
        rows = self.map_targets(copy.deepcopy(lab), candidates, set(node_names))
        chosen = [r for r in rows if r['name'] in node_names]
        if not chosen:
            raise HTTPException(400, 'Select at least one saved node to restore.')
        ineligible = [r for r in chosen if not r['eligible']]
        if ineligible:
            raise HTTPException(409, 'Some selected nodes cannot be restored: ' +
                                '; '.join(f"{r['name']}: {r['reason']}" for r in ineligible[:6]))
        with self.store.lock:
            if before != host_identity(self.store.state.get('host', {})):
                raise HTTPException(409, 'VM connection changed. Reconnect and try again.')
            # Re-check idempotency under the same lock that appends the job: the first check
            # ran before the slow resolve_source/map_targets I/O released the lock.
            duplicate = next((j for j in self.store.state['restore_jobs'] if j.get('request_id') == request_id), None)
            if duplicate:
                return public_job(duplicate)
            self.guard_idle(lab_id)
            job = {
                'id': uuid.uuid4().hex, 'request_id': request_id, 'lab_id': lab_id, 'lab_name': lab['name'],
                'created': now(), 'status': 'queued', 'message': 'Restore queued.',
                'confirm_minutes': int(confirm_minutes), 'source': desc,
                'pre_backup_job_id': '', 'post_backup_job_id': '', 'host_identity': before,
                'targets': [{'name': r['name'], 'short_name': r['short_name'], 'platform': r['platform'],
                             'status': 'pending', 'message': 'Waiting to restore.'} for r in chosen],
                '_candidates': {r['name']: candidates[r['name']] for r in chosen}}
            self.store.state['restore_jobs'].append(job)
            try:
                self.store.save()
            except OSError:
                self.store.state['restore_jobs'].remove(job)
                raise HTTPException(500, 'Could not save the restore request. No work was submitted.')
        self.event('restore.queued', f'Restore queued for {len(chosen)} node(s) from a saved {desc["type"]} version.',
                   lab_id, job['id'])
        try:
            self.pool.submit(self.execute, job['id'])
        except RuntimeError:
            self.update(job['id'], status='interrupted', finished=now(), message='Manager is stopping. Retry later.')
        return public_job(self.get_job(job['id']))

    def _wait_backup(self, backup_id):
        while True:
            with self.store.lock:
                backup = next((copy.deepcopy(b) for b in self.store.state['jobs'] if b['id'] == backup_id), None)
            if not backup:
                return None
            if backup['status'] not in ('queued', 'running'):
                return backup
            if self.stopping.wait(0.2):
                return None

    def _candidates(self, job_id):
        with self.store.lock:
            job = self.get_job(job_id)
            return copy.deepcopy(job.get('_candidates', {}))

    def execute(self, job_id):
        lab_id = ''
        try:
            with self.store.lock:
                job = copy.deepcopy(self.get_job(job_id))
            lab_id = job['lab_id']
            candidates = job.get('_candidates', {})
            confirm_minutes = job['confirm_minutes']
            targets = [t['name'] for t in job['targets']]

            # 1. Preflight snapshot of the lab and identity.
            self.update(job_id, status='preflight', message='Checking the lab and target nodes.')
            with self.store.lock:
                lab = copy.deepcopy(self.store.lab(job['lab_id']))
                if not lab:
                    raise _Fail('The lab was removed.')
                if job['host_identity'] != host_identity(self.store.state.get('host', {})):
                    raise _Fail('The VM connection changed before the restore started.')
                if not discovery_fresh(self.store.state):
                    raise _Fail('VM discovery is stale; refresh discovery and retry.')
            nodes = {n['name']: n for n in lab['nodes']}
            # A node that stopped between submit and now is skipped, not restored; it must
            # also be kept out of the pre-restore backup, whose Runner submit is
            # all-or-nothing and would otherwise abort the restore of the healthy nodes.
            ineligible = set()
            for name in targets:
                node = nodes.get(name)
                if not node or not node_available(self.store.state, lab, node):
                    ineligible.add(name)
                    self.update_target(job_id, name, status='ineligible', message='Node is not currently running.')
            live = [name for name in targets if name not in ineligible]
            if not live:
                raise _Fail('None of the selected nodes are currently running; no configuration was changed.')

            # 2. Mandatory pre-restore backup of every live target (durable, referenced below).
            self.update(job_id, status='backing_up', message='Backing up the current configuration first.')
            for name in live:
                self.update_target(job_id, name, status='backing_up', message='Capturing current configuration.')
            try:
                pre = self.runner.submit(job['lab_id'], operation='backup', source='restore-pre',
                                         node_names=live, progress_id=job_id,
                                         progress_context={'node_names': live})
            except ValueError as exc:
                raise _Fail('The pre-restore backup could not start (' + str(exc) + '); no configuration was changed.')
            self.update(job_id, pre_backup_job_id=pre['id'])
            backup = self._wait_backup(pre['id'])
            if not backup:
                raise _Fail('The pre-restore backup did not complete; no configuration was changed.')
            backed_up = {n['name'] for n in backup.get('nodes', []) if n.get('status') == 'succeeded'}
            self.event('restore.prebackup', f'Pre-restore backup {pre["id"]}: {len(backed_up)}/{len(live)} nodes captured.',
                       lab_id, job_id)

            # 3. Apply the candidate per live node with a confirmed commit, then reconnect + confirm.
            self.update(job_id, status='applying', message='Applying the saved configuration.')
            applied = []
            for name in live:
                node = nodes.get(name)
                if name not in backed_up:
                    self.update_target(job_id, name, status='failed',
                                       message='Pre-restore backup failed for this node; it was not changed.')
                    continue
                creds = effective_credentials(lab, node)
                candidate = candidates[name]['candidate']
                self._apply_one(job_id, lab_id, node, creds, candidate, confirm_minutes, applied)

            # 4. Post-restore backup + desired-state comparison for the applied nodes. A
            # failure to start it leaves the nodes applied-but-unverified, never "failed".
            if applied:
                self.update(job_id, status='verifying', message='Verifying the restored configuration.')
                try:
                    post = self.runner.submit(job['lab_id'], operation='backup', source='restore-post',
                                              node_names=applied, progress_id=job_id,
                                              progress_context={'node_names': applied})
                    self.update(job_id, post_backup_job_id=post['id'])
                    post_backup = self._wait_backup(post['id'])
                except ValueError:
                    post_backup = None
                self._verify(job_id, lab_id, post_backup, candidates)

            self._finalize(job_id, lab_id)
        except _Fail as exc:
            self.update(job_id, status='preflight_failed' if 'pre-restore' not in str(exc) else 'failed',
                        finished=now(), message=str(exc))
            self.event('restore.failed', str(exc), lab_id, job_id, level='error')
        except Exception as exc:
            with self.store.lock:
                message = scrub(f'Restore interrupted: {type(exc).__name__}', self.store.state)
            try:
                self.update(job_id, status='needs_attention', finished=now(), message=message)
            except OSError:
                pass
            self.event('restore.failed', message, lab_id, job_id, level='error')

    def _apply_one(self, job_id, lab_id, node, creds, candidate, confirm_minutes, applied):
        name = node['name']
        armed = False
        self.update_target(job_id, name, status='applying', message='Loading the saved configuration (commit confirmed).')
        try:
            client = paramiko.SSHClient()
            try:
                self.connect(client, node, creds)
                result = junos.apply_candidate(client, candidate, confirm_minutes)
            finally:
                client.close()
            armed = True
            sample = [mask_line(l) for l in result['diff'].splitlines() if l.strip()][:40]
            self.update_target(job_id, name, status='confirming', diff_sample=sample,
                               root_authentication=result['root_authentication'], no_op=result['no_op'],
                               message='Configuration loaded; reconnecting to confirm.')
            # Reconnect (proves management is reachable with the new config), then confirm.
            client2 = paramiko.SSHClient()
            try:
                self.connect(client2, node, creds)
                junos.confirm(client2)
            finally:
                client2.close()
            self.update_target(job_id, name, status='applied',
                               message='Configuration replaced and the commit confirmed.')
            applied.append(name)
            self.event('restore.node', 'Configuration replaced and confirmed on this node.', lab_id, job_id, name)
        except junos.RestoreError as exc:
            with self.store.lock:
                message = scrub(str(exc), self.store.state)
            if armed:
                self.update_target(job_id, name, status='rollback_expected',
                                   message='Commit was armed but not confirmed; the node rolls back automatically. ' + message)
            else:
                self.update_target(job_id, name, status='failed',
                                   message='Configuration was not changed: ' + message)
            self.event('restore.node', message, lab_id, job_id, name, level='error')
        except Exception as exc:
            with self.store.lock:
                message = scrub(f'{type(exc).__name__}', self.store.state)
            status = 'rollback_expected' if armed else 'failed'
            note = ('Commit was armed but confirmation failed; the node rolls back automatically. '
                    if armed else 'Configuration was not changed. ')
            self.update_target(job_id, name, status=status, message=note + 'Connectivity: ' + message)
            self.event('restore.node', note + message, lab_id, job_id, name, level='error')

    def _verify(self, job_id, lab_id, post_backup, candidates):
        outcomes = {n['name']: n for n in (post_backup or {}).get('nodes', [])} if post_backup else {}
        with self.store.lock:
            job = copy.deepcopy(self.get_job(job_id))
        for target in job['targets']:
            name = target['name']
            if target['status'] != 'applied':
                continue
            outcome = outcomes.get(name)
            if not post_backup or not outcome or outcome.get('status') != 'succeeded' or not outcome.get('file'):
                self.update_target(job_id, name, status='applied_unverified',
                                   message='Configuration replaced, but the post-restore backup did not confirm it. Re-check by hand.')
                continue
            from .downloads import stored_path
            path = stored_path(self.store, post_backup, outcome)
            if not path:
                self.update_target(job_id, name, status='applied_unverified',
                                   message='Configuration replaced, but its verification capture is unavailable.')
                continue
            try:
                actual = path.read_text('utf-8', 'replace')
            except OSError:
                self.update_target(job_id, name, status='applied_unverified', message='Verification capture unreadable.')
                continue
            missing, extra, converged = compare_states(candidates[name]['desired_set'], actual)
            if converged:
                self.update_target(job_id, name, status='verified',
                                   message='Configuration replaced and verified against the saved desired state.',
                                   missing_statements=0, extra_statements=0)
            else:
                self.update_target(job_id, name, status='verify_mismatch',
                                   missing_statements=len(missing), extra_statements=len(extra),
                                   missing_sample=[mask_line(l) for l in missing[:20]],
                                   extra_sample=[mask_line(l) for l in extra[:20]],
                                   message=f'Configuration replaced, but {len(missing)} desired statement(s) are missing '
                                           f'and {len(extra)} unexpected statement(s) remain.')

    def _finalize(self, job_id, lab_id):
        with self.store.lock:
            job = self.get_job(job_id)
            statuses = [t['status'] for t in job['targets']]
            total = len(statuses)
            verified = sum(s == 'verified' for s in statuses)
            needs_review = sum(s in ('verify_mismatch', 'applied_unverified') for s in statuses)
            # A node whose configuration was replaced, whether or not verification was clean.
            restored = verified + needs_review + sum(s == 'applied' for s in statuses)
            bad = sum(s in ('failed', 'rollback_expected', 'ineligible', 'interrupted') for s in statuses)
            if verified == total:
                status = 'succeeded'
                message = f'All {total} node(s) restored and verified against the saved state.'
            elif restored == 0:
                status = 'failed'
                message = 'No node was restored. Existing configurations were preserved by the safety backup.'
            elif needs_review:
                status = 'needs_attention'
                message = (f'{verified}/{total} node(s) verified; {needs_review} were applied but their '
                           f'post-restore check needs attention. Review each node.')
            else:
                status = 'partial'
                message = f'{restored}/{total} node(s) restored and verified; {bad} did not complete.'
            job.update(status=status, finished=now(), message=message)
            self.store.save()
        self.event('restore.finish', message, lab_id, job_id,
                   level='info' if status == 'succeeded' else 'warning')

    # --- routes ----------------------------------------------------------------

    def install(self, app):
        class Source(BaseModel):
            model_config = ConfigDict(extra='forbid')
            type: str
            commit: str = Field(default='', max_length=64)
            path: str = Field(default='', max_length=250)
            backup_job_id: str = Field(default='', max_length=64)

        class Preflight(BaseModel):
            model_config = ConfigDict(extra='forbid')
            source: Source
            node_names: list[str] | None = Field(default=None, max_length=500)

        class Run(BaseModel):
            model_config = ConfigDict(extra='forbid')
            request_id: str = Field(pattern=r'^[0-9a-f]{32}$')
            source: Source
            node_names: list[str] = Field(min_length=1, max_length=500)
            confirm_minutes: int = Field(default=5, ge=2, le=60)
            acknowledge: bool = False

        @app.get('/api/labs/{lab_id}/restore/sources')
        def sources(lab_id: str):
            with self.store.lock:
                lab = self.store.lab(lab_id)
                if not lab:
                    raise HTTPException(404, 'Lab not found.')
                jobs = copy.deepcopy([j for j in self.store.state['jobs']
                                      if j['lab_id'] == lab_id and j.get('operation') == 'backup'
                                      and j['status'] in ('succeeded', 'partial')])
                supported = [n['name'] for n in lab['nodes'] if junos.supports_restore(n.get('platform'))]
                unsupported = [n['name'] for n in lab['nodes'] if not junos.supports_restore(n.get('platform'))]
            backups = []
            for job in jobs:
                capable = [n['name'] for n in job.get('nodes', []) if n.get('status') == 'succeeded' and n.get('restore_file')]
                if capable:
                    backups.append({'backup_job_id': job['id'], 'created': job.get('created'),
                                    'finished': job.get('finished'), 'nodes': capable})
            return {'backups': backups, 'supported_nodes': supported, 'unsupported_nodes': unsupported,
                    'restore_supported_platforms': list(junos.SUPPORTED_KINDS)}

        @app.post('/api/labs/{lab_id}/restore/preflight')
        def preflight(lab_id: str, data: Preflight):
            requested = set(data.node_names) if data.node_names is not None else None
            return self.preflight(lab_id, data.source.model_dump(), requested)

        @app.post('/api/labs/{lab_id}/restore')
        def restore(lab_id: str, data: Run):
            if not data.acknowledge:
                raise HTTPException(400, 'Acknowledge that the running configuration will be replaced.')
            return self.submit(lab_id, data.source.model_dump(), data.node_names, data.confirm_minutes, data.request_id)

        @app.get('/api/restore/jobs/{job_id}')
        def job_status(job_id: str):
            with self.store.lock:
                return public_job(self.get_job(job_id))


class _Fail(Exception):
    """A controlled preflight/pre-backup failure that leaves the device untouched."""
