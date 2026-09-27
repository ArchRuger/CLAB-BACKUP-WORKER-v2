"""Apply a generated plan to the lab's devices: the review, the token, the apply job and the ownership ledger.

docs/netlab-integration/PROVISIONING.md is the contract. This module orchestrates and knows no NOS command:
the platform drivers (``DRIVERS``, today :mod:`design_eos`) stage, arm and confirm; :mod:`design_provision`
decides what a fragment may carry; :mod:`design_ownership` decides what is added, stale, in conflict and
how it is removed. The manager owns exactly what its own confirmed commits added, per device, under the
lab's private key ``network_ownership``.

Flow: review (the whole transaction, aborted: reviewed bytes are applied bytes) -> token -> apply job:
preflight -> mandatory pre-change backup -> per device (drift check, stage removals and candidate, arm the
NOS's timed recovery, fresh connection, confirm only under our own session name, read back, ledger written
with the outcome) -> post-change backup -> finalisation from the per-device outcomes. Nothing here is
lab-wide atomic; the job says what happened to each device.

Nothing here writes configuration text or secrets to logs or the API: statements are masked with
:func:`restore.mask_line` and bounded, messages are scrubbed.
"""
import copy
import hashlib
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import paramiko
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field

from . import design_eos, design_iosxr, design_junos
from . import design_ownership as own
from . import design_provision as provision
from .discovery import discovery_fresh, node_available
from .git_progress import host_identity
from .lab_operations import RESTORE_BUSY, operation_busy, scrub
from .network_design import digest as plan_digest
from .node_services import connect
from .restore import mask_line
from .restore_shell import RestoreError, SessionLost
from .runner import effective_credentials, now, trim_jobs

DRIVERS = {**{kind: design_eos for kind in design_eos.SUPPORTED_KINDS}, **{kind: design_junos for kind in design_junos.SUPPORTED_KINDS},
           **{kind: design_iosxr for kind in design_iosxr.SUPPORTED_KINDS}}
DESIGN_APPLY_BUSY = ('queued', 'preflight', 'backing_up', 'applying', 'confirming', 'verifying')
IN_FLIGHT = ('applying', 'confirming')
JOB_CAP = 200
REVIEW_TTL = 600
SAMPLE = 40
PUBLIC_JOB = ('id', 'lab_id', 'lab_name', 'generation_id', 'created', 'started', 'finished', 'status', 'message',
              'confirm_minutes', 'pre_backup_job_id', 'post_backup_job_id', 'targets', 'progress', 'takeover')
NOT_AVAILABLE = 'Applying to this kind of device is not available yet; its generated files are preview and download only.'


def public_job(job):
    value = {k: copy.deepcopy(job[k]) for k in PUBLIC_JOB if k in job}
    value['targets'] = [{k: v for k, v in t.items() if not k.startswith('_')} for t in value.get('targets', [])]
    value['server_time'] = time.time()
    return value


def public_ownership(lab):
    """Per device: how many statements the manager owns, from which plan, and whether a read-back is pending."""
    ledger = lab.get('network_ownership') or {}
    return {node: {'statements': len(entry.get('statements') or []), 'generation_id': entry.get('generation_id', ''),
                   'applied_at': entry.get('applied_at', ''), 'pending': bool(entry.get('pending'))}
            for node, entry in ledger.items() if isinstance(entry, dict)}


def _append_job(state, job):
    jobs = state.setdefault('design_jobs', [])
    jobs.append(job)
    state['design_jobs'] = trim_jobs(jobs, JOB_CAP, lambda j: j['status'] in DESIGN_APPLY_BUSY or j['status'] == 'interrupted', newest_first=False)


def digest_of(statements):
    return hashlib.sha256('\n'.join(sorted(statements)).encode()).hexdigest()


def masked(items, limit=SAMPLE):
    return [mask_line(s) for s in sorted(items)[:limit]]


class DesignApply:
    def __init__(self, store, runner, network_design, connector=None, node_workers=4):
        self.store = store
        self.runner = runner
        self.designs = network_design
        self.connect = connector or connect
        self.stopping = threading.Event()
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='design-apply')
        self.node_pool = ThreadPoolExecutor(max_workers=max(1, min(8, node_workers)), thread_name_prefix='design-node')
        self.reviews = {}
        self.retry_interval = 10
        self.recovery_grace = 90
        self.connect_pause = 3
        self.unchecked = []
        with store.lock:
            for job in store.state.setdefault('design_jobs', []):
                if job['status'] in DESIGN_APPLY_BUSY:
                    job.update(status='interrupted', finished=now(),
                               message='Manager restarted while the design was being applied. Devices that were being changed are read back; a change the manager had not confirmed is undone by the device itself.')
                    for target in job.get('targets', []):
                        if target.get('status') in IN_FLIGHT:
                            self.unchecked.append((job['id'], target['name']))
                            target.update(status='interrupted', message='Interrupted while this device was being changed; reading it back.')
                        elif target.get('status') in ('pending', 'backing_up'):
                            target.update(status='interrupted', message='Interrupted before this device was changed.', stage='failed')
            store.save()

    def start(self):
        pending, self.unchecked = self.unchecked, []
        if pending:
            def recheck_all():
                for job_id, name in pending: self._recheck(job_id, name)
                for job_id in dict.fromkeys(job_id for job_id, _ in pending): self._summarize_interrupted(job_id)
            try: self.pool.submit(recheck_all)
            except RuntimeError: pass

    def _summarize_interrupted(self, job_id):
        """After the restart's read-back: say per device what the interrupted apply came to (the status stays `interrupted`)."""
        words = {'verified': 'applied and verified', 'verify_mismatch': 'applied, read-back differs', 'rolled_back': 'undone by the device',
                 'uncertain': 'outcome unknown', 'no_op': 'already matched', 'interrupted': 'not changed'}
        with self.store.lock:
            try: job = self.get_job(job_id)
            except HTTPException: return
            outcomes = ', '.join(f"{t['name']} {words.get(t['status'], t['status'])}" for t in job.get('targets', []))
            job['message'] = 'Manager restarted while the design was being applied. Read back afterwards: ' + (outcomes or 'nothing to check') + '.'
            try: self.store.save()
            except OSError: pass

    def close(self):
        self.stopping.set()
        self.pool.shutdown(wait=False, cancel_futures=True)
        self.node_pool.shutdown(wait=False, cancel_futures=True)

    # --- helpers -----------------------------------------------------------------------------------------

    def get_job(self, job_id):
        job = next((j for j in self.store.state.get('design_jobs', []) if j['id'] == job_id), None)
        if not job: raise HTTPException(404, 'Design apply job not found.')
        return job

    def update(self, job_id, **fields):
        with self.store.lock:
            job = self.get_job(job_id); job.update(fields)
            try: self.store.save()
            except OSError: pass

    def stage_target(self, job_id, name, stage=None, **fields):
        with self.store.lock:
            job = self.get_job(job_id)
            target = next((t for t in job['targets'] if t['name'] == name), None)
            if target is None: return
            target.update(fields)
            if stage:
                target['stage'] = stage; target.setdefault('timeline', {}).setdefault(stage, time.time())
                if stage in ('applied', 'no_op', 'failed', 'rolled_back', 'uncertain', 'drifted', 'conflict', 'skipped'):
                    target['timeline'].setdefault('settled', time.time())
                    job['progress'] = {'settled': sum(1 for t in job['targets'] if 'settled' in t.get('timeline', {})), 'total': len(job['targets'])}
            try: self.store.save()
            except OSError: pass

    def event(self, action, message, lab_id, job_id='', node='', level='info'):
        try:
            with self.store.lock: message = scrub(str(message), self.store.state)
            self.store.event(action, message[:2000], level=level, lab_id=lab_id, job_id=job_id, node=node)
        except OSError: pass

    def guard_idle(self, lab_id):
        state = self.store.state
        if operation_busy(state, lab_id) or any(j['status'] in ('queued', 'running') for j in state['jobs']):
            raise HTTPException(409, 'Wait for the active backup, Git save, restore, lab operation or design apply to finish.')
        # The Runner refuses every other backup while a design apply or a restore runs on any lab: an apply queued now
        # would lose its mandatory pre-change backup, so it waits here instead (review O6).
        if any(j.get('status') in DESIGN_APPLY_BUSY for j in state.get('design_jobs', [])):
            raise HTTPException(409, 'Another design apply is running; wait for it to finish.')
        if any(j.get('status') in RESTORE_BUSY for j in state.get('restore_jobs', [])):
            raise HTTPException(409, 'A restore is running; wait for it to finish.')
        if self.store.reset_pending: raise HTTPException(409, 'Finish the storage reset first.')

    def _current_plan(self, lab, generation):
        """A plan is applied only while it is the plan of the lab's current design and topology (review O4)."""
        current = lab.get('network_design') or {}
        if not current: raise HTTPException(409, 'This lab has no design any more; the plan cannot be applied.')
        if generation.get('intent_revision') != current.get('revision') or generation.get('topology_digest') != plan_digest(lab.get('definition_yaml') or ''):
            raise HTTPException(409, 'The plan is older than the design or the topology; generate it again.')

    def _release(self, driver, session):
        """Let a driver that keeps the arming connection (IOS XR) close it: the device undoes an unconfirmed trial at once."""
        release = getattr(driver, 'release', None)
        if release and session:
            try: release(session)
            except Exception: pass

    def _scrubbed(self, text):
        with self.store.lock: return scrub(str(text), self.store.state)

    def _open(self, node, creds):
        last = RestoreError('The device could not be reached.')
        for attempt in range(3):
            client = paramiko.SSHClient()
            try:
                self.connect(client, node, creds); return client
            except (OSError, EOFError, paramiko.SSHException) as exc:
                last = exc; client.close()
                if isinstance(exc, paramiko.AuthenticationException): raise
                if self.stopping.wait(self.connect_pause): raise
        raise last

    def _fragments(self, lab_id, generation, node):
        """The generation's stored files for `node`, verified against their recorded digests."""
        folder = self.designs.folder(lab_id, generation['id'])
        entries = (generation.get('artifacts') or {}).get(node) or []
        fragments = []
        for index, entry in enumerate(entries):
            path = folder / 'nodes' / node / ('%02d-%s' % (index, entry['module']))
            try: raw = path.read_bytes()
            except OSError: raise HTTPException(409, 'A generated file of this plan is missing; generate the plan again.')
            if hashlib.sha256(raw).hexdigest() != entry['sha256']: raise HTTPException(409, 'A generated file of this plan changed on disk; generate the plan again.')
            fragments.append((entry['module'], raw.decode('utf-8', 'replace')))
        return fragments

    # --- review -------------------------------------------------------------------------------------------

    def review(self, lab_id, generation_id, targets, takeover):
        with self.store.lock:
            lab = self.store.lab(lab_id)
            if not lab: raise HTTPException(404, 'Lab not found.')
            self.guard_idle(lab_id)
            generation = copy.deepcopy(self.designs.generation(lab, generation_id))
            if generation.get('status') != 'succeeded': raise HTTPException(409, 'Only a generated plan can be applied.')
            self._current_plan(lab, generation)
            if not discovery_fresh(self.store.state): raise HTTPException(409, 'Refresh the lab list before applying a design.')
            lab = copy.deepcopy(lab); before_identity = host_identity(self.store.state.get('host', {}))
        nodes_by_short = {n.get('definition_node') or n.get('short_name') or n['name']: n for n in lab['nodes']}
        rows = []
        for short in targets:
            info = (generation.get('nodes') or {}).get(short)
            node = nodes_by_short.get(short)
            row = {'name': short, 'kind': (info or {}).get('kind', ''), 'eligible': False, 'reason': ''}
            if not info or not info.get('included'): row['reason'] = 'This device is not part of the plan.'
            elif info.get('blocked'): row['reason'] = info['blocked']
            elif info.get('role') == 'host': row['reason'] = 'A support host is generated only, never applied.'
            elif info['kind'] not in DRIVERS: row['reason'] = NOT_AVAILABLE
            elif not node: row['reason'] = 'This device is not in the lab any more.'
            elif not node_available(self.store.state, lab, node): row['reason'] = 'This device is not running, or the lab status is out of date.'
            elif not effective_credentials(lab, node).get('username'): row['reason'] = 'Add login credentials for this device first.'
            elif any(c['level'] in ('unsupported', 'blocked_missing_prerequisite') for c in (generation.get('compatibility') or {}).get(short, [])):
                row['reason'] = 'The plan asks for something this device cannot do.'
            else: row['eligible'] = True; row['node'] = node
            rows.append(row)
        if not any(r['eligible'] for r in rows): raise HTTPException(409, 'None of the selected devices can be applied to: ' + '; '.join(f"{r['name']}: {r['reason']}" for r in rows[:6]))
        ledger = lab.get('network_ownership') or {}
        results = {}
        def work(row):
            try: results[row['name']] = self._review_one(lab, generation, row, ledger.get(row['name']) or {}, row['name'] in takeover)
            except Exception as exc:
                results[row['name']] = {'reachable': False, 'reason': self._scrubbed(exc if isinstance(exc, RestoreError) else 'Connectivity: ' + type(exc).__name__)}
        eligible = [r for r in rows if r['eligible']]
        list(self.node_pool.map(work, eligible))
        with self.store.lock:
            if before_identity != host_identity(self.store.state.get('host', {})): raise HTTPException(409, 'VM connection changed. Review again.')
            self.reviews = {k: v for k, v in self.reviews.items() if v['expires'] > time.monotonic()}
            if len(self.reviews) >= 20: self.reviews.pop(next(iter(self.reviews)))
            token = uuid.uuid4().hex
            bound = {name: r for name, r in results.items() if r.get('ready')}
            self.reviews[token] = {'lab_id': lab_id, 'generation_id': generation_id, 'intent_revision': generation.get('intent_revision', ''),
                                   'topology_digest': generation.get('topology_digest', ''), 'mapping_digest': generation.get('mapping_digest', ''),
                                   'targets': bound, 'takeover': sorted(set(takeover) & set(bound)), 'expires': time.monotonic() + REVIEW_TTL}
        public = []
        for row in rows:
            entry = {'name': row['name'], 'kind': row['kind'], 'eligible': row['eligible'], 'reason': row['reason'],
                     'compatibility': (generation.get('compatibility') or {}).get(row['name'], [])}
            if row['eligible']:
                r = results.get(row['name'], {})
                entry.update({k: r.get(k) for k in ('reachable', 'reason', 'ready', 'no_op', 'protected', 'diff', 'added', 'removed', 'stale', 'conflicts',
                                                     'expected', 'removals', 'kept_manual', 'skipped', 'counts', 'takeover')})
            public.append(entry)
        return {'token': token, 'expires_in': REVIEW_TTL, 'generation_id': generation_id, 'targets': public,
                'applicable': [r['name'] for r in public if r.get('ready') and (not r.get('counts', {}).get('conflicts') or r.get('takeover'))]}

    def _review_one(self, lab, generation, row, entry, takeover):
        node, kind = row['node'], row['kind']
        driver = DRIVERS[kind]; creds = effective_credentials(lab, node); opts = driver.options(creds)
        fragments = self._fragments(lab['id'], generation, row['name'])
        candidate, protected = provision.prepare(kind, fragments)
        owned = set(entry.get('statements') or []); anc = set(entry.get('ancestors') or [])
        client = self._open(node, creds)
        try:
            if entry.get('pending'):
                owned, anc = self._resolve_pending(lab['id'], kind, row['name'], entry, driver, client, opts)
            pending = driver.pending(client, **opts)
            if pending: return {'reachable': True, 'ready': False, 'reason': 'Another change is waiting for confirmation on this device.'}
            clean, rendered = driver.render_desired(client, candidate, **opts)
            desired = own.statements(kind, rendered) - own.statements(kind, clean)
            before_text = driver.snapshot(client, **opts)
            before = own.statements(kind, before_text)
            plan = own.plan_removals(kind, before, owned, anc, desired)
            removals = own.render_removals(kind, plan)
            name = driver.session_name()
            staged = driver.stage(client, candidate, removals, name, arm=False, **opts)
        finally:
            client.close()
        before = own.statements(kind, staged['before']); would_be = own.statements(kind, staged['would_be'])
        containers = own.junos_blocks(staged.get('hierarchy')) if kind in own.SET_KINDS else None
        if containers is not None:   # a ledger written before the device's blocks were known may hold keyword-only levels
            anc = {a for a in anc if a in containers or a in plan['remove']}
        sets = own.diff(kind, before, would_be, owned, desired, anc)
        leftovers = own.takeover_leftovers(sets['conflicts'], would_be) if takeover else []
        if leftovers:
            # Taking over an exclusive sibling means removing it: stage once more with those leaves among the removals,
            # so the reviewed bytes are the applied bytes.
            removals = removals + own.render_removals(kind, {'leaves': leftovers, 'remove': []})
            client = self._open(node, creds)
            try: staged = driver.stage(client, candidate, removals, name, arm=False, **opts)
            finally: client.close()
            before = own.statements(kind, staged['before']); would_be = own.statements(kind, staged['would_be'])
            sets = own.diff(kind, before, would_be, owned, desired, anc)
        taken_over = sorted(sets['conflicts']) if takeover else []
        diff_lines = [mask_line(l) for l in staged['diff'].splitlines() if l.strip()][:400]
        counts = {k: len(sets[k]) for k in ('added', 'removed', 'stale', 'conflicts', 'expected')}
        counts['removals'] = len(plan['remove']) + len(plan['leaves']) + len(leftovers); counts['kept_manual'] = len(plan['kept_manual'])
        return {'reachable': True, 'ready': True, 'no_op': staged['no_op'] and not removals, 'diff': diff_lines,
                'protected': [{**p, 'statement': mask_line(str(p.get('statement', '')))} for p in protected],
                'added': masked(sets['added']), 'removed': masked(sets['removed']), 'stale': masked(sets['stale']), 'conflicts': masked(sets['conflicts']),
                'expected': masked(sets['expected']), 'removals': [mask_line(l) for l in removals][:SAMPLE], 'kept_manual': masked(plan['kept_manual']),
                'skipped': masked(plan['skipped']), 'counts': counts, 'takeover': takeover,
                # bound to the token, never public:
                '_before_digest': digest_of(before), '_candidate': candidate, '_removals': removals, '_desired': sorted(desired),
                '_added': sorted(sets['added']), '_stale': sorted(set(sets['stale']) | set(taken_over)),   # a taken-over statement must be gone afterwards
                '_ancestors': sorted(own.created_ancestors(kind, sets['added'], before, containers) | anc),
                '_removed_ancestors': plan['remove'], '_kept_manual': sorted(plan['kept_manual']), '_conflicts': sorted(sets['conflicts']),
                '_would_be_digest': digest_of(would_be)}

    def _resolve_pending(self, lab_id, kind, name, entry, driver, client, opts):
        """An earlier apply on this device ended unknown: read it back once and settle the ledger (PROVISIONING §3:
        present → owned, absent → dropped), then let the review continue with the settled owned set."""
        pend = entry.get('pending') or {}
        after = own.statements(kind, driver.snapshot(client, **opts))
        owned = set(entry.get('statements') or []); anc = set(entry.get('ancestors') or [])
        desired = set(pend.get('desired') or [])
        present = bool(desired) and desired <= after
        if present:
            owned |= set(pend.get('added') or []) & after; anc |= set(pend.get('ancestors') or [])
        owned &= after
        with self.store.lock:
            lab = self.store.lab(lab_id)
            if lab is not None:
                ledger = lab.setdefault('network_ownership', {}); current = ledger.get(name) or {}
                current.update(statements=sorted(owned), ancestors=sorted(anc), pending=None)
                ledger[name] = current
                try: self.store.save()
                except OSError: pass
        self.event('design.apply.node', 'Read back after an unknown outcome: the change is ' + ('present and owned.' if present else 'not there; nothing is owned from it.'), lab_id, pend.get('job_id', ''), name)
        return owned, anc

    # --- apply ---------------------------------------------------------------------------------------------

    def submit(self, lab_id, token, confirm_minutes, request_id, takeover):
        with self.store.lock:
            existing = next((j for j in self.store.state.get('design_jobs', []) if j.get('request_id') == request_id), None)
            if existing: return public_job(existing)
            review = self.reviews.get(token)
            if not review or review['expires'] < time.monotonic() or review['lab_id'] != lab_id: raise HTTPException(409, 'The review expired; review the plan again.')
            if sorted(set(takeover)) != review['takeover']: raise HTTPException(409, 'The take-over choice differs from the review. Review again.')
            lab = self.store.lab(lab_id)
            if not lab: raise HTTPException(404, 'Lab not found.')
            self.guard_idle(lab_id)
            generation = self.designs.generation(lab, review['generation_id'])
            if generation.get('intent_revision') != review['intent_revision'] or generation.get('topology_digest') != review['topology_digest']: raise HTTPException(409, 'The plan changed; review again.')
            self._current_plan(lab, generation)
            blocked = [n for n, r in review['targets'].items() if r['_conflicts'] and n not in review['takeover']]
            if blocked: raise HTTPException(409, 'Conflicts with manual configuration on ' + ', '.join(sorted(blocked)) + '. Resolve them or take the settings over in the review.')
            targets = [n for n, r in review['targets'].items() if not r.get('no_op')]
            noops = [n for n, r in review['targets'].items() if r.get('no_op')]
            if not targets and not noops: raise HTTPException(409, 'Nothing to apply.')
            job = {'id': uuid.uuid4().hex, 'request_id': request_id, 'lab_id': lab_id, 'lab_name': lab['name'], 'generation_id': review['generation_id'],
                   'created': now(), 'status': 'queued', 'message': 'Design apply queued.', 'confirm_minutes': int(confirm_minutes),
                   'host_identity': host_identity(self.store.state.get('host', {})), 'takeover': review['takeover'],
                   'targets': [{'name': n, 'kind': review['targets'][n].get('kind', ''), 'status': 'pending', 'stage': 'queued', 'message': 'Waiting.',
                                'timeline': {'queued': time.time()}, **{k: v for k, v in review['targets'][n].items() if k.startswith('_')}} for n in targets]
                              + [{'name': n, 'status': 'no_op', 'stage': 'no_op', 'message': 'Already matches the plan; nothing to change.', 'timeline': {'queued': time.time(), 'settled': time.time()}} for n in noops],
                   'progress': {'settled': len(noops), 'total': len(targets) + len(noops)}}
            for target in job['targets']:
                target['kind'] = next((n.get('kind', '') for n in lab['nodes'] if (n.get('definition_node') or n.get('short_name') or n['name']) == target['name']), target.get('kind', ''))
            _append_job(self.store.state, job)
            try: self.store.save()
            except OSError:
                self.store.state['design_jobs'].remove(job); raise HTTPException(500, 'Could not save the apply request. No work was submitted.')
            self.reviews.pop(token, None)
        self.event('design.apply.queued', f'Design apply queued for {len(targets)} device(s) from plan {review["generation_id"][:12]}.', lab_id, job['id'])
        try: self.pool.submit(self.execute, job['id'])
        except RuntimeError: self.update(job['id'], status='interrupted', finished=now(), message='Manager is stopping. Retry later.')
        return public_job(self.get_job(job['id']))

    def execute(self, job_id):
        lab_id = ''
        try:
            with self.store.lock: job = copy.deepcopy(self.get_job(job_id))
            lab_id = job['lab_id']
            self.update(job_id, status='preflight', started=now(), message='Checking the lab and the devices.')
            with self.store.lock:
                lab = copy.deepcopy(self.store.lab(lab_id))
                if not lab: raise _Fail('The lab was removed.')
                if job['host_identity'] != host_identity(self.store.state.get('host', {})): raise _Fail('The VM connection changed before the apply started.')
                if not discovery_fresh(self.store.state): raise _Fail('VM discovery is stale; refresh discovery and retry.')
            nodes = {(n.get('definition_node') or n.get('short_name') or n['name']): n for n in lab['nodes']}
            live = []
            for target in job['targets']:
                if target['status'] == 'no_op': continue
                node = nodes.get(target['name'])
                if not node or not node_available(self.store.state, lab, node):
                    self.stage_target(job_id, target['name'], 'skipped', status='ineligible', message='Device is not currently running.'); continue
                live.append(target['name'])
            if not live:
                if any(t['status'] == 'no_op' for t in job['targets']): self._finalize(job_id, lab_id); return   # every device already matched
                raise _Fail('None of the selected devices is running; no configuration was changed.')
            self.update(job_id, status='backing_up', message='Backing up the current configurations first.')
            for name in live: self.stage_target(job_id, name, 'backing_up', status='backing_up', message='Capturing the current configuration.')
            try:
                pre = self.runner.submit(lab_id, operation='backup', source='design-pre', node_names=[nodes[n]['name'] for n in live],
                                         progress_id=job_id, progress_context={'node_names': [nodes[n]['name'] for n in live]})
            except ValueError as exc:
                raise _Fail('The pre-change backup could not start (' + str(exc) + '); no configuration was changed.')
            self.update(job_id, pre_backup_job_id=pre['id'])
            backup = self._wait_backup(pre['id'])
            if not backup: raise _Fail('The pre-change backup did not complete; no configuration was changed.')
            backed_up = {n['name'] for n in backup.get('nodes', []) if n.get('status') == 'succeeded'}
            self.update(job_id, status='applying', message='Applying the plan to the devices.')
            groups = {}
            for name in live:
                node = nodes[name]; groups.setdefault((node['address'], node['port']), []).append(name)
            def run(group):
                for name in group:
                    self._node_task(job_id, lab_id, lab, nodes[name], name, nodes[name]['name'] in backed_up, job['confirm_minutes'])
            futures = [self.node_pool.submit(run, group) for group in groups.values()]
            for future in futures:
                try: future.result()
                except Exception: pass
            if self.stopping.is_set(): return
            with self.store.lock: applied = [t['name'] for t in self.get_job(job_id)['targets'] if t['status'] in ('applied', 'verified', 'verify_mismatch')]
            if applied:
                self.update(job_id, status='verifying', message='Recording the changed configurations.')
                try:
                    post = self.runner.submit(lab_id, operation='backup', source='design-post', node_names=[nodes[n]['name'] for n in applied], progress_id=job_id,
                                              progress_context={'node_names': [nodes[n]['name'] for n in applied]})
                    self.update(job_id, post_backup_job_id=post['id']); self._wait_backup(post['id'])
                except ValueError as exc:
                    self.update(job_id, post_backup_note='The post-change backup could not start (' + str(exc) + '); the devices were applied as recorded.')
            self._finalize(job_id, lab_id)
        except _Fail as exc:
            self.update(job_id, status='failed', finished=now(), message=str(exc)); self.event('design.apply.failed', str(exc), lab_id, job_id, level='error')
        except Exception as exc:
            message = self._scrubbed('Design apply interrupted: ' + type(exc).__name__)
            self.update(job_id, status='needs_attention', finished=now(), message=message); self.event('design.apply.failed', message, lab_id, job_id, level='error')

    def _wait_backup(self, backup_id):
        while True:
            with self.store.lock: backup = next((copy.deepcopy(b) for b in self.store.state['jobs'] if b['id'] == backup_id), None)
            if not backup or backup['status'] not in ('queued', 'running'): return backup
            if self.stopping.wait(0.2): return None

    def _node_task(self, job_id, lab_id, lab, node, name, backed_up, confirm_minutes):
        if self.stopping.is_set(): return
        try:
            if not backed_up:
                self.stage_target(job_id, name, 'failed', status='failed', message='The pre-change backup failed for this device; it was not changed.'); return
            self._apply_one(job_id, lab_id, lab, node, name, confirm_minutes)
        except Exception as exc:
            why = self._scrubbed(type(exc).__name__)
            with self.store.lock:
                target = copy.deepcopy(next(t for t in self.get_job(job_id)['targets'] if t['name'] == name))
            if target.get('status') in IN_FLIGHT:
                self._settle_and_record(job_id, lab_id, lab, node, name, target, confirm_minutes)
            else:
                self.stage_target(job_id, name, 'failed', status='failed', message='Configuration was not changed: internal error (' + why + ').')
            self.event('design.apply.node', 'Internal error while applying to this device: ' + why, lab_id, job_id, name, level='error')

    def _apply_one(self, job_id, lab_id, lab, node, name, confirm_minutes):
        kind = node.get('kind') or ''
        driver = DRIVERS[kind]; creds = effective_credentials(lab, node); opts = driver.options(creds)
        with self.store.lock: target = copy.deepcopy(next(t for t in self.get_job(job_id)['targets'] if t['name'] == name))
        session = driver.session_name()
        self.stage_target(job_id, name, 'connecting', status='applying', _session=session, message='Connecting to stage the change.')
        try: client = self._open(node, creds)
        except Exception as exc:
            message = 'The device rejected the login credentials.' if isinstance(exc, paramiko.AuthenticationException) else 'Connectivity: ' + self._scrubbed(type(exc).__name__)
            self.stage_target(job_id, name, 'failed', status='failed', message='Configuration was not changed. ' + message); return
        result = None; lost = ''
        try:
            before_text = driver.snapshot(client, **opts)
            if digest_of(own.statements(kind, before_text)) != target['_before_digest']:
                self.stage_target(job_id, name, 'drifted', status='drifted', message='The configuration changed since you reviewed it; this device was not changed. Review again.'); return
            self.stage_target(job_id, name, 'applying', message='Staging the removals and the generated configuration; the device undoes them by itself unless the manager confirms.')
            try:
                result = driver.stage(client, target['_candidate'], target['_removals'], session, confirm_minutes, arm=True, **opts)
            except SessionLost as exc: result, lost = None, self._scrubbed(exc)
            except RestoreError as exc:
                self.stage_target(job_id, name, 'failed', status='failed', message='Configuration was not changed: ' + self._scrubbed(exc)); return
        finally:
            # An IOS XR trial is confirmed only from the session that armed it: the driver keeps that connection
            # (`held`) and closes it itself on confirm or release; every other connection is closed here.
            if not (result and result.get('held')): client.close()
        if result is not None and not result['armed']:
            self.stage_target(job_id, name, 'no_op', status='no_op', message='Already matches the plan; nothing to change.'); return
        if result is not None and digest_of(own.statements(kind, result['would_be'])) != target['_would_be_digest']:
            # The device rendered something else than at review time: the timer runs; do not confirm.
            self.stage_target(job_id, name, 'confirming', status='confirming', _armed=True, _deadline=time.time() + confirm_minutes * 60, _mismatch=True,
                              message='The staged configuration differs from the reviewed one; the change is left to the device\'s own timer.')
        elif result is not None:
            self.stage_target(job_id, name, 'armed', status='confirming', _armed=True, _deadline=time.time() + confirm_minutes * 60,
                              diff_sample=[mask_line(l) for l in result['diff'].splitlines() if l.strip()][:SAMPLE], message='Change armed; reconnecting to confirm.')
        else:
            self.stage_target(job_id, name, 'confirming', status='confirming', _armed=None, _deadline=time.time() + confirm_minutes * 60,
                              message='The session to the device was lost during the change; checking what is active. ' + lost)
        with self.store.lock: target = copy.deepcopy(next(t for t in self.get_job(job_id)['targets'] if t['name'] == name))
        self._settle_and_record(job_id, lab_id, lab, node, name, target, confirm_minutes)

    def _settle_and_record(self, job_id, lab_id, lab, node, name, target, confirm_minutes):
        kind = node.get('kind') or ''
        driver = DRIVERS[kind]; creds = effective_credentials(lab, node); opts = driver.options(creds)
        session = target.get('_session', ''); armed = target.get('_armed'); deadline = target.get('_deadline') or time.time()
        desired = set(target.get('_desired') or []); stale = set(target.get('_stale') or []); added = set(target.get('_added') or [])
        removed_ancestors = target.get('_removed_ancestors') or []
        mismatch = target.get('_mismatch', False)
        if mismatch: self._release(driver, session)   # never confirmed: a held IOS XR trial is undone at once
        attempts = 0; why = ''
        while True:
            attempts += 1
            self.stage_target(job_id, name, 'verifying', attempts=attempts)
            try:
                client = self._open(node, creds)
                try:
                    pending = driver.pending(client, session=session, **opts)
                    if pending:
                        if pending != session: why = 'a change that is not this apply\'s is waiting for confirmation'; self._release(driver, session)
                        elif mismatch: why = 'the staged configuration differed from the reviewed one; left to the device\'s timer'
                        elif armed is not True and digest_of(own.statements(kind, driver.snapshot(client, **opts))) != target.get('_would_be_digest'):
                            # Armed without the review's confirmation of what was staged (a lost session, a restart before the
                            # arming was recorded): while the timer runs the running configuration is the would-be one, so it can
                            # be compared now; anything else is left to the device's timer (review O5).
                            mismatch = True; why = 'the armed change could not be matched with the reviewed one; left to the device\'s timer'
                            self._release(driver, session)
                        else:
                            self.stage_target(job_id, name, 'confirming')
                            confirmed = driver.confirm(client, {'session': session}, **opts)
                            after = own.statements(kind, driver.snapshot(client, **opts))
                            self._record_applied(job_id, lab_id, lab, name, target, after, desired, stale, added, removed_ancestors, confirmed.get('saved', True)); return
                    else:
                        self._release(driver, session)
                        driver.cleanup(client, **opts)
                        after = own.statements(kind, driver.snapshot(client, **opts))
                        if digest_of(after) == target['_before_digest']:
                            state = 'rolled_back' if armed or mismatch else 'unchanged'
                            self.stage_target(job_id, name, state if state == 'rolled_back' else 'failed', status=state if state == 'rolled_back' else 'failed',
                                              message='The change was not confirmed in time and the device undid it; the configuration from before is active.' if state == 'rolled_back'
                                              else 'Configuration was not changed; the configuration from before is active.')
                            self.event('design.apply.node', 'Not confirmed; the device undid the change.' if state == 'rolled_back' else 'The change did not take place.', lab_id, job_id, name, level='error'); return
                        present, absent = own.split_negations(kind, desired)
                        if present <= after and not (absent & after) and not (stale & after):
                            saved = driver.persist(client, **opts) if hasattr(driver, 'persist') else True
                            self._record_applied(job_id, lab_id, lab, name, target, after, desired, stale, added, removed_ancestors, saved); return
                        why = 'the active configuration matches neither the reviewed result nor the one from before'
                finally:
                    client.close()
            except RestoreError as exc: why = self._scrubbed(exc)
            except (OSError, EOFError, paramiko.SSHException) as exc: why = 'connectivity: ' + self._scrubbed(type(exc).__name__)
            except Exception as exc: why = 'internal error: ' + self._scrubbed(type(exc).__name__); break
            if time.time() > deadline + self.recovery_grace: break
            if self.stopping.wait(self.retry_interval): return
        self._release(driver, session)
        self._record_uncertain(job_id, lab_id, name, target, why)

    def _record_applied(self, job_id, lab_id, lab, name, target, after, desired, stale, added, removed_ancestors, saved):
        kept = set(target.get('_kept_manual') or [])
        missing, remaining = own.verify(target.get('kind') or '', after, desired, stale, removed_ancestors, kept)
        status = 'verified' if not missing and not remaining else 'verify_mismatch'
        kept_note = (' %d setting(s) stayed because manual configuration sits under them.' % len(kept & after)) if kept & after else ''
        with self.store.lock:
            job = self.get_job(job_id); current = next((t for t in job['targets'] if t['name'] == name), None)
            lab_record = self.store.lab(lab_id)
            if current is not None:
                current.update(status=status, stage='applied', persistence='saved' if saved else 'not_saved',
                               message=('Applied, confirmed and read back.' if status == 'verified' else 'Applied and confirmed, but the read-back differs: %d expected statement(s) missing, %d stale statement(s) remaining.' % (len(missing), len(remaining))) + kept_note,
                               verify={'missing': masked(missing), 'remaining': masked(remaining)}, kept_manual=masked(sorted(kept & after)))
                current.setdefault('timeline', {}).setdefault('applied', time.time()); current['timeline'].setdefault('settled', time.time())
                job['progress'] = {'settled': sum(1 for t in job['targets'] if 'settled' in t.get('timeline', {})), 'total': len(job['targets'])}
            if lab_record is not None:
                ledger = lab_record.setdefault('network_ownership', {})
                entry = ledger.get(name) or {}
                owned = own.after_apply(target.get('kind') or '', set(entry.get('statements') or []), added, after)
                # A container removed and re-created by the same apply (new leaves under the old path) stays created.
                recreated = {a for a in removed_ancestors if any(own._under(target.get('kind') or '', a, d) for d in desired)}
                ledger[name] = {'generation_id': job['generation_id'], 'applied_at': now(), 'statements': sorted(owned),
                                'ancestors': sorted((set(target.get('_ancestors') or []) - set(removed_ancestors)) | recreated), 'pending': None}
            try: self.store.save()
            except OSError: pass
        self.event('design.apply.node', 'Applied and confirmed on this device (' + status + ').', lab_id, job_id, name)

    def _record_uncertain(self, job_id, lab_id, name, target, why):
        with self.store.lock:
            job = self.get_job(job_id); current = next((t for t in job['targets'] if t['name'] == name), None)
            if current is not None:
                current.update(status='uncertain', stage='uncertain', message='The manager could not establish what this device is running (' + (why or 'unknown') + '). Check it before relying on it.')
                current.setdefault('timeline', {}).setdefault('settled', time.time())
                job['progress'] = {'settled': sum(1 for t in job['targets'] if 'settled' in t.get('timeline', {})), 'total': len(job['targets'])}
            lab_record = self.store.lab(lab_id)
            if lab_record is not None:
                entry = lab_record.setdefault('network_ownership', {}).setdefault(name, {'statements': [], 'ancestors': [], 'generation_id': '', 'applied_at': ''})
                entry['pending'] = {'job_id': job_id, 'added': list(target.get('_added') or []), 'desired': list(target.get('_desired') or []), 'ancestors': list(target.get('_ancestors') or [])}
            try: self.store.save()
            except OSError: pass
        self.event('design.apply.node', 'Outcome unknown: ' + (why or ''), lab_id, job_id, name, level='error')

    def _recheck(self, job_id, name):
        """A device a restart left in flight: read it back once and settle it the same way."""
        with self.store.lock:
            job = next((j for j in self.store.state.get('design_jobs', []) if j['id'] == job_id), None)
            lab = copy.deepcopy(self.store.lab(job['lab_id'])) if job else None
            target = copy.deepcopy(next((t for t in (job or {}).get('targets', []) if t['name'] == name), None))
        if not job or not lab or not target: return
        node = next((n for n in lab['nodes'] if (n.get('definition_node') or n.get('short_name') or n['name']) == name), None)
        if not node or (node.get('kind') or '') not in DRIVERS: self._record_uncertain(job_id, lab['id'], name, target, 'the device or its driver is gone'); return
        # One pass once the device's own timer has decided: a trial nobody can confirm any more (IOS XR after a
        # restart) is waited out, a pending EOS or Junos change is confirmed or found reverted at once.
        target['_deadline'] = max(float(target.get('_deadline') or 0), time.time())
        self._settle_and_record(job_id, lab['id'], lab, node, name, target, job.get('confirm_minutes', 5))

    def _finalize(self, job_id, lab_id):
        with self.store.lock:
            job = self.get_job(job_id)
            statuses = [t['status'] for t in job['targets']]
            good = {'verified', 'no_op'}; soft = {'verify_mismatch', 'applied'}
            if statuses and all(s == 'no_op' for s in statuses): status, message = 'succeeded', 'Every selected device already matched the plan; nothing was changed.'
            elif all(s in good for s in statuses): status, message = 'succeeded', 'The plan was applied and every device read back as planned.'
            elif any(s in ('uncertain', 'interrupted') for s in statuses): status, message = 'needs_attention', 'Some devices need a look: their outcome is unknown.'
            elif any(s in good | soft for s in statuses): status, message = 'partial', 'The plan was applied to some devices; others were not changed or were undone.'
            else: status, message = 'failed', 'The plan was not applied to any device.'
            if job.get('post_backup_note'): message += ' ' + job['post_backup_note']
            job.update(status=status, finished=now(), message=message)
            try: self.store.save()
            except OSError: pass
        self.event('design.apply.finished', message, lab_id, job_id, level='info' if status == 'succeeded' else 'warning')

    # --- routes -------------------------------------------------------------------------------------------

    def install(self, app):
        service = self

        class Review(BaseModel):
            model_config = ConfigDict(extra='forbid')
            targets: list[str] = Field(min_length=1, max_length=500)
            takeover: list[str] = Field(default_factory=list, max_length=500)

        class Apply(BaseModel):
            model_config = ConfigDict(extra='forbid')
            token: str = Field(min_length=32, max_length=32)
            confirm_minutes: int = Field(default=5, ge=2, le=30)
            request_id: str = Field(min_length=16, max_length=64, pattern=r'^[0-9a-f]+$')
            takeover: list[str] = Field(default_factory=list, max_length=500)
            acknowledged: bool = False

        @app.post('/api/labs/{lab_id}/design/generations/{generation_id}/review')
        def review(lab_id: str, generation_id: str, data: Review):
            if len(set(data.targets)) != len(data.targets): raise HTTPException(400, 'Select each device once.')
            return service.review(lab_id, generation_id, data.targets, data.takeover)

        @app.post('/api/labs/{lab_id}/design/apply')
        def apply(lab_id: str, data: Apply):
            if not data.acknowledged: raise HTTPException(400, 'Acknowledge that the selected devices will be changed.')
            return service.submit(lab_id, data.token, data.confirm_minutes, data.request_id, data.takeover)

        @app.get('/api/labs/{lab_id}/design/apply/jobs')
        def jobs(lab_id: str):
            with service.store.lock: return [public_job(j) for j in service.store.state.get('design_jobs', []) if j['lab_id'] == lab_id]

        @app.get('/api/design/apply/jobs/{job_id}')
        def job(job_id: str):
            with service.store.lock: return public_job(service.get_job(job_id))

        @app.get('/api/labs/{lab_id}/design/ownership')
        def ownership(lab_id: str):
            with service.store.lock:
                lab = service.store.lab(lab_id)
                if not lab: raise HTTPException(404, 'Lab not found.')
                ledger = lab.get('network_ownership') or {}
                return {'summary': public_ownership(lab),
                        'statements': {node: masked(entry.get('statements') or [], 400) for node, entry in ledger.items() if isinstance(entry, dict)}}


class _Fail(Exception):
    pass
