"""Apply a saved configuration to a running node as a managed, safe restore job.

A restore takes a saved *desired state* (a Git version, a repository folder or a local backup)
and drives a running node to exactly that state without a reboot or a containerlab redeploy.
It reuses the manager's existing direct node-SSH path (no new host helper) and the
Runner for durable pre- and post-restore backups, and it serialises against backups,
Git saves and lab operations through ``operation_busy``.

Flow: preflight -> mandatory pre-restore backup -> per node, several nodes side by side (replace the whole configuration
inside the NOS's own transaction with its timed recovery armed, reconnect to prove management,
confirm) -> post backup and desired-state comparison. What a platform needs for that (Junos
``load override`` + ``commit confirmed``, EOS session + ``commit timer``, ...) lives in its driver;
:mod:`restore_drivers` is the contract and the registry, and this module knows no NOS command.

A change that was armed but could not be confirmed is never *assumed* to have been undone: the
service keeps trying to reconnect and confirm for the whole recovery window, and when that fails
it reads the node back and reports what is active (``rolled_back``, ``applied``) or that it could
not tell (``uncertain``). The same check runs after a manager restart.

Nothing here writes raw configuration or secrets to logs or the API: the review shows
counts and masked sample lines, and every message is scrubbed.
"""
import base64
import copy
import os
import re
import threading
import time
import uuid
from concurrent.futures import FIRST_COMPLETED, CancelledError, ThreadPoolExecutor, wait
from functools import partial

import paramiko
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field

from . import restore_drivers as drivers
from . import restore_junos as junos  # noqa: F401  (tests and older callers patch the Junos driver through this name)
from .discovery import discovery_fresh, node_available
from .git_progress import captured_snapshot, decoded_snapshot, host_identity, resolve_version_path
from .lab_operations import RESTORE_BUSY, operation_busy, scrub
from .node_services import connect
from .restore_compare import compare_junos, set_lines  # noqa: F401  (set_lines is part of this module's API)
from .restore_shell import RestoreError, SessionLost
from .runner import effective_credentials, now

PUBLIC_JOB = ('id', 'lab_id', 'lab_name', 'created', 'finished', 'status', 'message', 'source',
              'confirm_minutes', 'pre_backup_job_id', 'post_backup_job_id', 'targets', 'progress')

NO_ARTIFACT = 'This saved configuration has no restore data for this node.'
UNUSABLE = 'The saved restore data for this node is not usable: '
FOREIGN_PENDING = 'Another change is waiting for confirmation on this node.'
BAD_LOGIN = 'The node rejected the login credentials.'
# Target states that mean "a driver may have armed a change and nobody confirmed it".
IN_FLIGHT = ('applying', 'confirming')
# What a target is doing, for the progress view. `stage` is a label written beside `status`, never instead
# of it: the restart classification (IN_FLIGHT), _verify and _finalize read `status` only, and jobs stored
# before stages existed have none. `timeline` maps a stage to the epoch second it was first entered, plus
# `settled` (the first final outcome) and `checked` (after the post-restore comparison).
#   queued -> backing_up -> backed_up -> connecting -> applying -> armed -> verifying -> confirming ->
#   replaced | matched  (then checking -> replaced | matched while the post-restore backup compares)
#   skipped | failed | rolled_back | uncertain  (final, at whichever point the node stopped)
# `matched` is `applied` with `no_op`: the device reported nothing to change. It is a label only.
STAGES = ('queued', 'backing_up', 'backed_up', 'connecting', 'applying', 'armed', 'verifying', 'confirming',
          'replaced', 'matched', 'skipped', 'failed', 'rolled_back', 'uncertain', 'checking')
SETTLED_STAGES = ('replaced', 'matched', 'skipped', 'failed', 'rolled_back', 'uncertain')
# Nodes changed at the same time inside one restore job (RESTORE_NODE_WORKERS, 1..8). 1 is the one-after-
# another behaviour of releases before parallel restore.
DEFAULT_NODE_WORKERS = 4
MAX_NODE_WORKERS = 8
# Lines of the review diff sent to the browser per node; the rest is cut and flagged `truncated`.
DIFF_MAX_LINES = 400
# A configuration line is shown only up to its first secret keyword. What follows differs per NOS (a
# quoted hash on Junos; `secret sha512 <hash>`, `password 7 <hash>`, `key-string 7 <hash>` on EOS and
# IOS XR), so nothing after the keyword is kept: not the type token, not the hash. SNMPv3 users carry their
# keys after `localized`, `auth`, `priv` or `encrypted` (`snmp-server user u g v3 localized <engine> auth sha <key>
# priv aes <key>`), SSH public keys follow `authentication` (Junos) or `sshkey` (EOS).
SECRET_WORD = re.compile(r'(?i)\b(secret|encrypted-password|password|passphrase|authentication-key|pre-shared-key|'
                         r'community|key-string|key-chain|key|md5|sha|sha1|sha256|sha512|hash|certificate|private|'
                         r'encrypted|localized|auth|authentication|priv|sshkey|psk)\b')


def public_job(job):
    value = {k: copy.deepcopy(job[k]) for k in PUBLIC_JOB if k in job}
    # Keys starting with "_" (driver token, recovery deadline) are the service's own.
    value['targets'] = [{k: v for k, v in target.items() if not k.startswith('_')}
                        for target in value.get('targets', [])]
    value['server_time'] = time.time()   # the clock the timeline was written with; the page measures against it
    return value


def mask_line(line):
    """A statement safe to show: cut at the first secret keyword (see SECRET_WORD)."""
    match = SECRET_WORD.search(line)
    if match:
        line = line[:match.end()] + ' [redacted]'
    return line[:200]


def compare_states(desired_set, actual_set):
    """Compare desired vs running display-set. Returns (missing, extra, converged).

    missing: desired statements not present after restore (must be empty).
    extra:   statements present but not desired (must be empty), except the mandatory
             root-authentication the driver may synthesise and volatile version lines.
    """
    missing, extra = compare_junos(desired_set, actual_set)
    return missing, extra, not missing and not extra


def backup_failure(message):
    """Why a node's safety backup failed, as a fixed phrase. The backup job keeps Ansible's own (scrubbed)
    words; a restore outcome carries controlled text only, so the reason is classified, never copied."""
    text = str(message or '').lower()
    if re.search(r'authenticat|permission denied|invalid/incorrect password|bad password', text):
        return ' (the device rejected the login)'
    if re.search(r'timed out|timeout|unreachable|refused|no route|connect', text):
        return ' (the device did not answer)'
    return ''


def node_worker_count(value=None):
    """How many nodes one restore changes at the same time: `value`, else RESTORE_NODE_WORKERS, else 4; 1..8."""
    if value is None:
        value = os.environ.get('RESTORE_NODE_WORKERS', '')
    try:
        count = int(value)
    except (TypeError, ValueError):
        count = DEFAULT_NODE_WORKERS
    return max(1, min(MAX_NODE_WORKERS, count))


def node_endpoint(node):
    """The SSH endpoint the manager connects to (node_services.connect). Two targets behind one endpoint are
    changed one after another: the IOS XR driver recognises its held arming session by the peer address alone."""
    return (str(node.get('address') or ''), str(node.get('port') or ''))


def saved_label(desc):
    """The saved side's name in a review diff: the folder, the commit or the backup it was read from."""
    desc = desc or {}
    if desc.get('type') == 'folder':
        return desc.get('folder') or 'the repository root'
    if desc.get('type') == 'git':
        return str(desc.get('commit') or '')[:10] or str(desc.get('path') or '')
    if desc.get('type') == 'backup':
        return 'backup ' + str(desc.get('backup_job_id') or '')[:10]
    return 'saved configuration'


def _diff_text(text):
    """The lines a review diff shows: blank lines and comment lines (`!` banners and separators, `#`) carry no
    configuration and are left out, as the comparison leaves them out."""
    return '\n'.join(line.rstrip() for line in (text or '').splitlines()
                     if line.strip() and not line.lstrip().startswith(('!', '#')))


def _unified(before, after):
    from . import textdiff   # the manager's shared unified-diff helper (also used by the Git version view)
    return textdiff.unified(before, after, context=3)


def review_diff(saved, running, converged, label):
    """What the review shows for one node before anything is submitted: the saved configuration against the
    running one the probe just captured, in the comparison form (`display set` on Junos, running-config on EOS
    and IOS XR). Every line is cut at its first secret keyword (mask_line), exactly like `diff_sample`; at most
    DIFF_MAX_LINES lines are sent. A node the comparison calls converged is `identical` with no hunks."""
    labels = {'old': 'Saved (' + label + ')', 'new': 'Running now'}
    if converged:
        return {'hunks': [], 'added': 0, 'removed': 0, 'truncated': False, 'identical': True, 'labels': labels}
    diff = _unified(_diff_text(saved), _diff_text(running))
    if not diff.get('hunks'):
        # The comparison sees a difference the filtered texts hide (it lives in a left-out line): show it all.
        diff = _unified(saved or '', running or '')
    hunks, sent, truncated = [], 0, bool(diff.get('truncated'))
    for hunk in diff.get('hunks', []):
        lines = hunk.get('lines', [])
        room = DIFF_MAX_LINES - sent
        if room <= 0:
            truncated = True
            break
        if len(lines) > room:
            truncated, lines = True, lines[:room]
        sent += len(lines)
        hunks.append(dict(hunk, lines=[dict(line, text=mask_line(str(line.get('text', '')))) for line in lines]))
    result = {'hunks': hunks, 'added': int(diff.get('added', 0)), 'removed': int(diff.get('removed', 0)),
              'truncated': truncated, 'identical': False, 'labels': labels}   # never "identical" when not converged
    if not hunks:
        result['reason'] = ('The comparison found differences in spacing or layout that this line view cannot show. '
                            'Replacing the configuration still makes the device match the saved one.')
    return result


def compare_for(platform, desired, actual):
    """(missing, extra, converged) in the comparable form of the node's platform."""
    driver = drivers.for_platform(platform)
    if driver is None:
        return [], [], False   # never "converged" by another platform's rules
    missing, extra = driver.compare(desired, actual)
    return missing, extra, not missing and not extra


def _enter_stage(job, target, stage, stamp):
    """Set a target's stage and first-entry time; count its first final outcome in the job's progress. The caller
    holds the store lock and saves."""
    timeline = target.setdefault('timeline', {})
    timeline.setdefault(stage, stamp)
    target['stage'] = stage
    if stage in SETTLED_STAGES and 'settled' not in timeline:
        timeline['settled'] = stamp
        progress = job.setdefault('progress', {'settled': 0, 'total': len(job.get('targets', []))})
        progress['settled'] = progress.get('settled', 0) + 1


class RestoreService:
    def __init__(self, store, runner, git_progress, connector=None, node_workers=None):
        self.store = store
        self.runner = runner
        self.git = git_progress
        self.connect = connector or connect
        self.stopping = threading.Event()
        # One restore job at a time (the Runner refuses a second job's backups anyway). Inside a job the
        # nodes run on their own pool: submitting them to `pool`, which runs execute() itself, would deadlock.
        self.pool = ThreadPoolExecutor(max_workers=1)
        self.node_workers = node_worker_count(node_workers)
        self.node_pool = ThreadPoolExecutor(max_workers=self.node_workers, thread_name_prefix='restore-node')
        self.retry_interval = 10      # seconds between reconnect attempts inside the recovery window
        self.recovery_grace = 90      # seconds past the window before giving up: Junos was seen rolling back 35 s late
        self.window_seconds = lambda minutes: int(minutes) * 60
        self.connect_pause = 3        # seconds between the attempts to open a connection
        self.unchecked = []           # (job id, node name) of changes a restart left in flight
        self.rechecks = {}            # job id -> nodes still to be read back after that restart
        with store.lock:
            for job in store.state.setdefault('restore_jobs', []):
                if job['status'] in RESTORE_BUSY:
                    job.update(status='interrupted', finished=now(),
                               message='Manager restarted during a restore. It is checking the devices that were being '
                                       'changed; a change it had not confirmed is undone by the device itself.')
                    for target in job.get('targets', []):
                        if target.get('status') in IN_FLIGHT:
                            self.unchecked.append((job['id'], target['name']))
                            target.update(status='interrupted', message='Restore interrupted while this node was being '
                                          'changed. The manager is checking what is active on it now.')
                        elif target.get('status') in ('backing_up', 'pending', 'ready', 'preflight'):
                            target.update(status='interrupted', message='Restore interrupted before this node was changed.')
                            _enter_stage(job, target, 'failed', time.time())   # settled: not changed, and not rechecked
            store.save()

    def start(self):
        """Read back every node a restart left in flight. Called once the application is up.

        The read-backs run side by side on the node pool, scheduled from the job pool so that a restore
        submitted meanwhile still waits until every interrupted node has been looked at."""
        pending, self.unchecked = self.unchecked, []
        for job_id, _name in pending:
            self.rechecks[job_id] = self.rechecks.get(job_id, 0) + 1
        if pending:
            try:
                self.pool.submit(self._recheck_all, pending)
            except RuntimeError:
                pass

    def _recheck_all(self, pending):
        with self.store.lock:
            endpoints = {}
            for job_id, name in pending:
                job = next((j for j in self.store.state['restore_jobs'] if j['id'] == job_id), None)
                lab = self.store.lab(job['lab_id']) if job else None
                node = next((n for n in (lab or {}).get('nodes', []) if n['name'] == name), None)
                endpoints[(job_id, name)] = node_endpoint(node) if node else ('', job_id + '/' + name)
        groups = {}
        for item in pending:
            groups.setdefault(endpoints[item], []).append(item)
        self._run_groups(list(groups.values()),
                         lambda group: [self._recheck_interrupted(job_id, name) for job_id, name in group])

    def close(self):
        self.stopping.set()
        self.pool.shutdown(wait=False, cancel_futures=True)
        # A node task that has not started is dropped: its target keeps the state it had, and the next start
        # marks it "interrupted before this node was changed". A running one returns at its next wait.
        self.node_pool.shutdown(wait=False, cancel_futures=True)

    def _run_groups(self, groups, work):
        """Run `work(group)` for every group, at most `node_workers` groups at the same time, and return when
        all have finished. The items of one group run one after another inside it. With one worker (or one
        group) everything runs right here, in order, as restores always did before parallel nodes."""
        if min(self.node_workers, len(groups)) <= 1:
            for group in groups:
                if self.stopping.is_set():
                    return
                work(group)
            return
        futures = []
        for group in groups:
            try:
                futures.append(self.node_pool.submit(work, group))
            except RuntimeError:
                break   # shutting down: the groups not handed over keep their state for the next start
        # A future that shutdown(cancel_futures=True) cancels before it ran never wakes as_completed() or
        # wait(), so the remaining futures are polled and the cancelled ones dropped.
        remaining = set(futures)
        while remaining:
            done, remaining = wait(remaining, timeout=0.5, return_when=FIRST_COMPLETED)
            remaining = {future for future in remaining if not future.cancelled()}
            for future in done:
                try:
                    future.result()
                except (CancelledError, Exception):
                    pass    # every node task records its own outcome; nothing from one reaches the others

    @staticmethod
    def _endpoint_groups(nodes):
        """Target nodes grouped by SSH endpoint, groups and members in target order."""
        groups = {}
        for node in nodes:
            groups.setdefault(node_endpoint(node), []).append(node['name'])
        return list(groups.values())

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

    def stage_target(self, job_id, name, stage, stamp_also=(), **fields):
        """Move one target to `stage` in one locked write: the stage, the time it was first entered, any other
        fields, and the job's settled count when this is the target's first final outcome. Only that target's
        dict is changed in place, never the job as a whole, so node workers cannot overwrite each other."""
        with self.store.lock:
            job = self.get_job(job_id)
            target = next((t for t in job.get('targets', []) if t['name'] == name), None)
            if target is None:
                return
            stamp = time.time()
            timeline = target.setdefault('timeline', {})
            for key in stamp_also:
                timeline.setdefault(key, stamp)
            target.update(fields)
            _enter_stage(job, target, stage, stamp)
            try:
                self.store.save()
            except OSError:
                pass

    def _stager(self, job_id, name):
        return lambda stage, **fields: self.stage_target(job_id, name, stage, **fields)

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
                    {'mode': 'read-version', 'commit': source['commit'], 'path': resolve_version_path(binding, source['path'])},
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
        elif stype == 'folder':
            # Apply a saved state directly from any snapshot folder of the connected repository,
            # without first pointing the lab at it (rule 6). `path` is the exact repository-relative
            # snapshot folder ('/' for the repository root). Preflight without a commit reads HEAD
            # and returns it as `source.commit`; a submit that carries `commit` reads that exact
            # commit, so the bytes the student reviewed are the bytes applied (the helper refuses a
            # commit outside the branch history, surfaced here as 409).
            with self.store.lock:
                binding = self.git.binding(lab_id)
            raw_path = source.get('path')
            if not raw_path:
                raise HTTPException(400, 'Choose a saved folder to apply.')
            path = resolve_version_path(binding, raw_path)
            given_commit = source.get('commit') or ''
            if given_commit and not re.fullmatch(r'[0-9a-f]{40,64}', given_commit):
                raise HTTPException(400, 'Choose a saved commit.')
            try:
                if given_commit:
                    commit = given_commit
                else:
                    status = self.git.invoke({'mode': 'status'}, binding)
                    if not status.get('ready'):
                        raise ValueError(status.get('problem') or 'Repository needs attention before applying a saved state.')
                    commit = status.get('head', '')
                result = self.git.invoke({'mode': 'read-version', 'commit': commit, 'path': path}, binding)
                manifest, files = decoded_snapshot(result)
            except ValueError as exc:
                raise HTTPException(409, str(exc))
            text = {name: raw.decode('utf-8') for name, raw in files.items()}
            folder = '' if not path else (path[:-len('/latest')] if path.endswith('/latest') else path)
            # desc['path'] is the normalised wire form ('/' + exact path, '/' for the repository
            # root) whatever shape the request came in as (a bare compatibility name, an exact
            # path, a leading slash already); desc['folder'] stays the display folder, without a
            # leading slash and without a trailing '/latest'.
            desc = {'type': 'folder', 'path': '/' + path, 'folder': folder, 'commit': commit,
                    'captured_at': manifest.get('captured_at', ''), 'lab_name': manifest.get('lab_name', '')}
        else:
            raise HTTPException(400, 'Choose a saved Git version, a saved folder or a saved capture as the restore source.')

        candidates = {}
        for entry in manifest.get('files', []):
            artifact = entry.get('restore_artifact')
            if not artifact or artifact not in text or entry.get('path') not in text:
                # Saved before this platform was restore-capable, or the artifact is gone. Never
                # relabel the backup text as a candidate: the node is listed with the reason.
                if entry.get('node'):
                    candidates[entry['node']] = {'candidate': '', 'desired_set': '', 'platform': entry.get('platform', ''),
                                                 'restore_format': '', 'short_name': entry.get('short_name', ''),
                                                 'unusable': NO_ARTIFACT}
                continue
            candidates[entry['node']] = {
                'candidate': text[artifact], 'desired_set': text[entry['path']],
                'platform': entry.get('platform', ''), 'restore_format': entry.get('restore_format', ''),
                'short_name': entry.get('short_name', '')}
        desc['restore_capable_nodes'] = sum(1 for c in candidates.values() if not c.get('unusable'))
        desc['saved_nodes'] = manifest.get('node_names', [])
        return desc, candidates

    # --- eligibility (no device access) ----------------------------------------

    def map_targets(self, lab, candidates, requested):
        """Match saved node names to running lab nodes and decide per-node eligibility."""
        rows = []
        for name in sorted(candidates):
            cand = candidates[name]
            node = next((n for n in lab['nodes'] if n['name'] == name), None)
            driver = drivers.for_platform(node.get('platform')) if node else None
            reason = ''
            eligible = False
            if node is None:
                reason = 'No running node in this lab matches this saved node.'
            elif driver is None:
                reason = 'Live restore is not supported for this platform yet.'
            elif node.get('platform') != cand['platform']:
                reason = 'The saved platform does not match the running node.'
            elif cand.get('unusable'):
                reason = cand['unusable']
            elif self._unusable(driver, cand):
                reason = UNUSABLE + self._unusable(driver, cand)
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

    @staticmethod
    def _unusable(driver, cand):
        """Why a candidate must not be sent to a node: wrong format for the driver, or the driver's
        own completeness check fails (empty, another NOS's text, visibly truncated)."""
        expected = getattr(driver, 'RESTORE_FORMAT', '')
        if expected and cand.get('restore_format') != expected:
            return 'it is not in the format this kind of device loads.'
        try:
            driver.validate_candidate(cand['candidate'])
        except RestoreError as exc:
            return str(exc)
        return ''

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
                refusal, current = self._probe(node, creds, capture=True)
                if refusal:
                    row.update(reachable=True, eligible=False, reason=refusal)
                    continue
                desired = candidates[row['name']]['desired_set']
                missing, extra, converged = compare_for(node['platform'], desired, current)
                row.update(reachable=True, matches_saved=converged,
                           pending_changes=len(missing) + len(extra))
                try:
                    row['diff'] = review_diff(desired, current, converged, saved_label(desc))
                except Exception:
                    row['diff_reason'] = 'The differences could not be shown for this device.'
            except paramiko.AuthenticationException:
                row.update(reachable=True, eligible=False, reason=BAD_LOGIN)
            except Exception as exc:
                row.update(reachable=False, eligible=False,
                           reason=scrub(f'SSH probe failed: {type(exc).__name__}', self.store.state))
        return {'source': desc, 'targets': rows,
                'eligible_count': sum(1 for r in rows if r['eligible'] and r['requested'])}

    def _open(self, node, creds):
        """A connected SSH client. A refused or silent connection is tried again a few times: nothing
        has been sent yet, and IOS XR turns away connections that follow each other too quickly (seen
        live). Rejected credentials are not retried."""
        for attempt in range(3):
            client = paramiko.SSHClient()
            try:
                self.connect(client, node, creds)
                return client
            except paramiko.AuthenticationException:
                client.close()
                raise
            except (OSError, EOFError, paramiko.SSHException):
                client.close()
                if attempt == 2 or self.stopping.wait(self.connect_pause):
                    raise

    def _session(self, node, creds, call):
        """Open one SSH connection to the node, run `call(client, driver, options)`, close it."""
        driver = drivers.for_platform(node['platform'])
        client = self._open(node, creds)
        try:
            return call(client, driver, drivers.options(driver, creds))
        finally:
            client.close()

    def _capture(self, node, creds):
        return self._session(node, creds, lambda client, driver, opts: driver.capture(client, **opts))

    def _probe(self, node, creds, capture=False):
        """Look at a node over ONE connection. Returns (refusal, active configuration or None).

        `refusal` says why a restore must not start on this node right now although it is reachable:
        somebody's change awaits confirmation, or the driver names another blocker (Junos: uncommitted
        edits in the shared candidate; IOS XR: an open configuration session). '' when nothing stands in
        the way; then, with `capture`, the active configuration is read too. Connectivity errors propagate."""
        def look(client, driver, opts):
            if driver.pending(client, **opts):
                return FOREIGN_PENDING, None
            blocked = driver.blocked(client, **opts) if hasattr(driver, 'blocked') else ''
            if blocked:
                return blocked, None
            return '', driver.capture(client, **opts) if capture else None
        return self._session(node, creds, look)

    def _live_refusal(self, node, creds):
        return self._probe(node, creds)[0]

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
        # The review looked at the devices some time ago. Look again before anything starts (not even
        # the safety backup): a node where somebody's change now awaits confirmation, or where somebody
        # is editing, refuses the whole request. An unreachable node does not: it gets its own outcome
        # in the job, and the driver repeats these refusals itself at the moment it would change a node.
        busy = []
        for row in chosen:
            node = next(n for n in lab['nodes'] if n['name'] == row['name'])
            try:
                refusal = self._live_refusal(node, effective_credentials(lab, node))
            except Exception:
                refusal = ''
            if refusal:
                busy.append(f"{row['name']}: {refusal}")
        if busy:
            raise HTTPException(409, 'Some selected nodes cannot be restored right now: ' + '; '.join(busy[:6]))
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
                             'status': 'pending', 'message': 'Waiting to restore.', 'stage': 'queued',
                             'timeline': {'queued': time.time()}, 'attempts': 0} for r in chosen],
                'progress': {'settled': 0, 'total': len(chosen)},
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
                    self.stage_target(job_id, name, 'skipped', status='ineligible', message='Node is not currently running.')
            live = [name for name in targets if name not in ineligible]
            if not live:
                raise _Fail('None of the selected nodes are currently running; no configuration was changed.')

            # 2. Mandatory pre-restore backup of every live target (durable, referenced below).
            self.update(job_id, status='backing_up', message='Backing up the current configuration first.')
            for name in live:
                self.stage_target(job_id, name, 'backing_up', status='backing_up', message='Capturing current configuration.')
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
            before = {n['name']: self._stored_text(backup, n) for n in backup.get('nodes', []) if n['name'] in backed_up}
            for name in live:
                if name in backed_up:
                    self.stage_target(job_id, name, 'backed_up')
            self.event('restore.prebackup', f'Pre-restore backup {pre["id"]}: {len(backed_up)}/{len(live)} nodes captured.',
                       lab_id, job_id)

            # 3. Apply the candidate per live node with a confirmed commit, then reconnect + confirm. Nodes run
            # side by side, at most node_workers at once, each with its own token, deadline and settle loop;
            # nodes that share one SSH endpoint run one after another inside one task.
            self.update(job_id, status='applying', message='Applying the saved configuration.')

            def run(group):
                for name in group:
                    self._node_task(job_id, lab_id, lab, name, candidates, confirm_minutes, before.get(name),
                                    name in backed_up, backup)
            self._run_groups(self._endpoint_groups([nodes[name] for name in live]), run)

            if self.stopping.is_set():
                return   # shutting down: leave the job in flight; the next start marks it interrupted and reads the nodes back
            # The post-restore backup's node list comes from the recorded outcomes, in target order, however
            # the nodes finished.
            with self.store.lock:
                applied = [t['name'] for t in self.get_job(job_id)['targets'] if t['status'] == 'applied']
            # 4. Post-restore backup + desired-state comparison for the applied nodes. A
            # failure to start it leaves the nodes applied-but-unverified, never "failed".
            if applied:
                self.update(job_id, status='verifying', message='Verifying the restored configuration.')
                for name in applied:
                    self.stage_target(job_id, name, 'checking')
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

    def _stored_text(self, backup, outcome):
        from .downloads import stored_path
        path = stored_path(self.store, backup, outcome) if outcome.get('file') else None
        try:
            return path.read_text('utf-8', 'replace') if path else None
        except OSError:
            return None

    def _scrubbed(self, text):
        with self.store.lock:
            return scrub(str(text), self.store.state)

    def _node_task(self, job_id, lab_id, lab, name, candidates, confirm_minutes, before, backed_up, backup):
        """One node's whole restore, on a node worker. It records its own outcome and never raises: an error here
        must neither reach execute() (which would mark the whole job) nor touch another node, not even the
        next one behind the same endpoint."""
        if self.stopping.is_set():
            return   # nothing is recorded; the next start marks this node "interrupted before it was changed"
        node = creds = cand = None
        try:
            node = next(n for n in lab['nodes'] if n['name'] == name)
            creds = effective_credentials(lab, node)
            cand = candidates[name]
            if not backed_up:
                outcome = next((n for n in (backup or {}).get('nodes', []) if n.get('name') == name), {})
                self.stage_target(job_id, name, 'failed', status='failed', message='Pre-restore backup failed for this node'
                                  + backup_failure(outcome.get('message', '')) + '; it was not changed.')
                return
            self._apply_one(job_id, lab_id, node, creds, cand, confirm_minutes, None, before)
        except Exception as exc:
            self._contain(job_id, lab_id, node or {'name': name}, creds, cand, before, exc)

    def _contain(self, job_id, lab_id, node, creds, cand, before, exc):
        """An unexpected error inside one node's task. A node that may hold an armed change is read back (one more
        settle, confirming only under its own token); a node not yet touched is "not changed"; one already
        settled keeps its outcome. If even that fails, the node is `uncertain`, never `failed`."""
        name = node['name']
        why = self._scrubbed(type(exc).__name__)
        try:
            with self.store.lock:
                target = copy.deepcopy(next(t for t in self.get_job(job_id)['targets'] if t['name'] == name))
            status = target.get('status')
            if status in IN_FLIGHT:
                armed = True if target.get('_handle') is not None else None
                deadline = target.get('_deadline') or time.time()
                state, detail = self._settle(node, creds, cand, target.get('_token', ''), target.get('_handle'), armed,
                                             deadline, before, on_stage=self._stager(job_id, name))
                self._record_settled(job_id, lab_id, name, state, detail, armed, None)
            elif status in ('pending', 'backing_up'):
                self.stage_target(job_id, name, 'failed', status='failed',
                                  message='Configuration was not changed: internal error (' + why + ').')
            self.event('restore.node', 'Internal error while restoring this node: ' + why, lab_id, job_id, name, level='error')
        except Exception:
            try:
                self.stage_target(job_id, name, 'uncertain', status='uncertain',
                                  message='The manager could not establish what this device is running (internal error: '
                                          + why + '). Check it before relying on it.')
            except Exception:
                pass

    def _apply_one(self, job_id, lab_id, node, creds, cand, confirm_minutes, applied, before):
        """Replace one node's configuration. `before` is its pre-restore capture (the rollback proof)."""
        name = node['name']
        driver = drivers.for_platform(node['platform'])
        opts = drivers.options(driver, creds)
        token = 'clabmgr-' + uuid.uuid4().hex[:8]
        deadline = time.time() + self.window_seconds(confirm_minutes)
        self.stage_target(job_id, name, 'connecting', status='applying', _token=token, _deadline=deadline,
                          worker=threading.current_thread().name,
                          message='Replacing the configuration; the device undoes it by itself unless the manager confirms.')
        # Where only the arming CLI session can confirm (IOS XR), the driver keeps this connection
        # after a successful apply and confirms on it once a fresh connection has proven management.
        holds = getattr(driver, 'HOLDS_SESSION', False)
        result, lost = None, ''
        try:
            client = self._open(node, creds)
        except Exception as exc:
            message = BAD_LOGIN if isinstance(exc, paramiko.AuthenticationException) else 'Connectivity: ' + self._scrubbed(type(exc).__name__)
            self.stage_target(job_id, name, 'failed', status='failed', message='Configuration was not changed. ' + message)
            self.event('restore.node', 'Not changed: the node could not be reached. ' + message, lab_id, job_id, name, level='error')
            return
        try:
            # The driver validates, loads and arms in one call; the service cannot see the moment of arming.
            self.stage_target(job_id, name, 'applying')
            try:
                result = driver.apply_candidate(client, cand['candidate'], confirm_minutes, token=token, **opts)
            except SessionLost as exc:
                result, lost = None, self._scrubbed(exc)
            except RestoreError as exc:
                # The driver refused or the node rejected the candidate, and the candidate was discarded.
                message = self._scrubbed(exc)
                self.stage_target(job_id, name, 'failed', status='failed', message='Configuration was not changed: ' + message)
                self.event('restore.node', message, lab_id, job_id, name, level='error')
                return
            except Exception as exc:
                result, lost = None, self._scrubbed(type(exc).__name__)
        finally:
            if not (holds and result is not None):
                client.close()
        try:
            if result is None:
                # The session died somewhere inside the transaction: whether a change was armed is unknown.
                self.update_target(job_id, name, status='confirming',
                                   message='The session to the device was lost during the change; checking what is active. ' + lost)
                self.event('restore.node', 'Session lost during the change; reading the node back. ' + lost, lab_id, job_id, name, level='warning')
                armed, handle = None, None
            else:
                armed, handle = True, result.get('handle') or {}
                sample = [mask_line(l) for l in result.get('diff', '').splitlines() if l.strip()][:40]
                self.stage_target(job_id, name, 'armed', status='confirming', diff_sample=sample, no_op=result.get('no_op', False),
                                  _handle=handle, message='Configuration loaded; reconnecting to confirm.',
                                  **({'root_authentication': result['root_authentication']} if 'root_authentication' in result else {}))
            state, detail = self._settle(node, creds, cand, token, handle, armed, deadline, before,
                                         on_stage=self._stager(job_id, name))
        finally:
            if holds:
                # Confirmed or not, the held session ends here. Unconfirmed, the node undoes the change itself.
                try:
                    driver.release(token)
                except Exception:
                    pass
        self._record_settled(job_id, lab_id, name, state, detail, armed, applied)

    def _settle(self, node, creds, cand, token, handle, armed, deadline, before, on_stage=None):
        """Confirm the armed change, or establish what the node runs. Returns (state, detail).

        Reconnecting is retried for the whole recovery window: a whole-configuration change can
        drop management for a while, and one failed attempt must not doom a good restore. A pending
        change is confirmed only when the node shows it under this job's token; "a change is pending"
        alone proves nothing about whose it is.
        `state` is 'applied', 'rolled_back' (armed by this call, then read back as undone),
        'unchanged' (the previous configuration is active and arming was never observed) or 'uncertain'.
        `on_stage(stage, **fields)` is told of each fresh-connection pass (`verifying`, with `attempts`) and
        of the moment before a confirmation is sent (`confirming`).
        """
        driver = drivers.for_platform(node['platform'])
        opts = drivers.options(driver, creds)

        seen = {'ours': False}

        def once(client, _driver, _opts):
            pending = driver.pending(client, **opts)
            if pending:
                # Ours only by identity: the token this job armed the change with (a Junos commit
                # comment, an EOS session name). A pending change without it is somebody else's.
                if pending != token and not (handle and pending in handle.values()):
                    return None   # not ours to confirm: wait for the node's own timer
                seen['ours'] = True
                if on_stage:
                    on_stage('confirming')
                confirmed = driver.confirm(client, {**(handle or {}), 'token': token}, **opts)
                matches = None
                try:
                    matches = compare_for(node['platform'], cand['desired_set'], driver.capture(client, **opts))[2]
                except Exception:
                    pass   # the confirmation stands; verification is the post-restore backup's job
                return 'applied', {'persistence': 'not_saved' if confirmed.get('saved') is False else 'saved', 'matches': matches}
            if hasattr(driver, 'cleanup'):
                driver.cleanup(client, **opts)   # our own abandoned transaction, if the session died inside it
            actual = driver.capture(client, **opts)
            if compare_for(node['platform'], cand['desired_set'], actual)[2]:
                # Active and nothing pending: the confirmation got through (or nothing had to change).
                saved = driver.persist(client, **opts) if hasattr(driver, 'persist') else True
                return 'applied', {'persistence': 'saved' if saved else 'not_saved', 'matches': True}
            if before is not None and compare_for(node['platform'], before, actual)[2]:
                # "Undone" only when this job's change was seen armed (by this call, or on the node
                # under our token). Otherwise all that is known is that the previous configuration runs.
                return ('rolled_back' if armed or seen['ours'] else 'unchanged'), {}
            return 'uncertain', {'why': 'the active configuration matches neither the saved nor the previous one'}

        why = ''
        attempts = 0
        while True:
            attempts += 1
            if on_stage:
                on_stage('verifying', attempts=attempts)
            try:
                outcome = self._session(node, creds, once)
                if outcome:
                    return outcome
                why = 'a change that is not this restore\'s was waiting for confirmation'
            except RestoreError as exc:
                why = self._scrubbed(exc)
            except (OSError, EOFError, paramiko.SSHException) as exc:
                why = 'connectivity: ' + self._scrubbed(type(exc).__name__)
            except Exception as exc:
                # Not a reachability problem: retrying for the whole window would only hide it.
                return 'uncertain', {'why': 'internal error: ' + self._scrubbed(type(exc).__name__)}
            if time.time() > deadline + self.recovery_grace:
                return 'uncertain', {'why': why}
            if self.stopping.wait(self.retry_interval):
                # The manager is shutting down inside the undo window. Say nothing about the node now:
                # it stays marked as being changed, and the next start reads it back (`start()`).
                return 'stopping', {}

    def _record_settled(self, job_id, lab_id, name, state, detail, armed, applied):
        if state == 'stopping':
            return
        if state == 'applied':
            with self.store.lock:
                target = next((t for t in self.get_job(job_id)['targets'] if t['name'] == name), {})
                stage = 'matched' if target.get('no_op') else 'replaced'
            self.stage_target(job_id, name, stage, status='applied', persistence=detail.get('persistence', ''),
                              message='Configuration replaced and the change confirmed.')
            if applied is not None:
                applied.append(name)
            self.event('restore.node', 'Configuration replaced and confirmed on this node.', lab_id, job_id, name)
        elif state == 'rolled_back':
            self.stage_target(job_id, name, 'rolled_back', status='rolled_back',
                              message='The change was not confirmed in time and the device undid it. Checked: the '
                                      'configuration from before the restore is active.')
            self.event('restore.node', 'Not confirmed; the node rolled back and its previous configuration was read back.',
                       lab_id, job_id, name, level='error')
        elif state == 'unchanged':
            # The session was lost inside the transaction and nobody saw the change armed: the saved
            # configuration may have been active for a while before the device undid it. Say so.
            self.stage_target(job_id, name, 'failed', status='failed',
                              message='Configuration was not changed. Checked: the configuration from before the restore is active. '
                                      'The session to the device was lost during the change, so the saved configuration may have '
                                      'been active for a short time before the device undid it.')
            self.event('restore.node', 'The change did not take place; the previous configuration was read back.',
                       lab_id, job_id, name, level='error')
        else:
            self.stage_target(job_id, name, 'uncertain', status='uncertain',
                              message='The manager could not establish what this device is running ('
                                      + detail.get('why', 'unknown') + '). Check it before relying on it.')
            self.event('restore.node', 'Outcome unknown: ' + detail.get('why', ''), lab_id, job_id, name, level='error')

    def _recheck_interrupted(self, job_id, name):
        """After a manager restart: find out what a node that was mid-change is running now.

        Nothing is re-applied. A pending change is confirmed only when the node shows it under this
        job's own token; otherwise the node's timer is left to run and the result is read back.
        """
        try:
            with self.store.lock:
                job = copy.deepcopy(self.get_job(job_id))
                lab = copy.deepcopy(self.store.lab(job['lab_id']))
            target = next(t for t in job['targets'] if t['name'] == name)
            node = next((n for n in (lab or {}).get('nodes', []) if n['name'] == name), None)
            cand = job.get('_candidates', {}).get(name)
            if not node or not cand or not drivers.for_platform(node.get('platform')):
                raise LookupError('the lab or the saved candidate is no longer available')
            with self.store.lock:
                backup = next((copy.deepcopy(b) for b in self.store.state['jobs'] if b['id'] == job.get('pre_backup_job_id')), None)
            outcome = next((n for n in (backup or {}).get('nodes', []) if n['name'] == name and n.get('status') == 'succeeded'), None)
            before = self._stored_text(backup, outcome) if outcome else None
            deadline = target.get('_deadline') or (time.time() + job.get('confirm_minutes', 5) * 60)
            # The handle is stored only after a successful apply, so its presence proves the change was
            # armed before the restart: the previous configuration coming back is then a rollback.
            armed = True if target.get('_handle') is not None else None
            state, detail = self._settle(node, effective_credentials(lab, node), cand, target.get('_token', ''),
                                         target.get('_handle'), armed, deadline, before, on_stage=self._stager(job_id, name))
            self._record_settled(job_id, job['lab_id'], name, state, detail, armed, None)
            if state == 'applied' and detail.get('matches'):
                self.update_target(job_id, name, status='verified', message='Checked after the manager restart: the saved '
                                   'configuration is active on this device and nothing is waiting for confirmation.')
            elif state == 'applied':
                self.update_target(job_id, name, status='applied_unverified', message='After the manager restart the pending '
                                   'change was confirmed, but the device could not be compared with the saved configuration.')
        except Exception as exc:
            self.stage_target(job_id, name, 'uncertain', status='uncertain', message='The manager restarted during this change and could '
                              'not check the device afterwards (' + self._scrubbed(type(exc).__name__) + '). Check it by hand.')
        finally:
            with self.store.lock:
                self.rechecks[job_id] = self.rechecks.get(job_id, 1) - 1
                last = self.rechecks[job_id] <= 0
            if last:
                try:
                    # The job stops being "interrupted": its nodes were looked at, so say what they run.
                    self._finalize(job_id, '', prefix='Checked after a manager restart. ')
                except Exception:
                    pass

    def _verify(self, job_id, lab_id, post_backup, candidates):
        outcomes = {n['name']: n for n in (post_backup or {}).get('nodes', [])} if post_backup else {}
        with self.store.lock:
            job = copy.deepcopy(self.get_job(job_id))
        for target in job['targets']:
            name = target['name']
            if target['status'] != 'applied':
                continue
            # The outcome label stays what the device reported; `status` carries the comparison's verdict.
            done = partial(self.stage_target, job_id, name, 'matched' if target.get('no_op') else 'replaced',
                           stamp_also=('checked',))
            outcome = outcomes.get(name)
            if not post_backup or not outcome or outcome.get('status') != 'succeeded' or not outcome.get('file'):
                done(status='applied_unverified',
                     message='Configuration replaced, but the post-restore backup did not confirm it. Re-check by hand.')
                continue
            from .downloads import stored_path
            path = stored_path(self.store, post_backup, outcome)
            if not path:
                done(status='applied_unverified', message='Configuration replaced, but its verification capture is unavailable.')
                continue
            try:
                actual = path.read_text('utf-8', 'replace')
            except OSError:
                done(status='applied_unverified', message='Verification capture unreadable.')
                continue
            missing, extra, converged = compare_for(target.get('platform', ''), candidates[name]['desired_set'], actual)
            if converged:
                done(status='verified', message='Configuration replaced and verified against the saved desired state.',
                     missing_statements=0, extra_statements=0)
            else:
                done(status='verify_mismatch',
                     missing_statements=len(missing), extra_statements=len(extra),
                     missing_sample=[mask_line(l) for l in missing[:20]],
                     extra_sample=[mask_line(l) for l in extra[:20]],
                     message=f'Configuration replaced, but {len(missing)} desired statement(s) are missing '
                             f'and {len(extra)} unexpected statement(s) remain.')

    def _finalize(self, job_id, lab_id, prefix=''):
        with self.store.lock:
            job = self.get_job(job_id)
            lab_id = lab_id or job['lab_id']
            statuses = [t['status'] for t in job['targets']]
            total = len(statuses)
            verified = sum(s == 'verified' for s in statuses)
            needs_review = sum(s in ('verify_mismatch', 'applied_unverified', 'uncertain') for s in statuses)
            # A node whose configuration was replaced, whether or not verification was clean.
            restored = verified + sum(s in ('verify_mismatch', 'applied_unverified', 'applied') for s in statuses)
            bad = sum(s in ('failed', 'rolled_back', 'rollback_expected', 'ineligible', 'interrupted') for s in statuses)
            if verified == total:
                status = 'succeeded'
                message = f'All {total} node(s) restored and verified against the saved state.'
            elif restored == 0 and not needs_review:
                status = 'failed'
                message = 'No node was restored. Existing configurations were preserved by the safety backup.'
            elif needs_review:
                status = 'needs_attention'
                message = (f'{verified}/{total} node(s) verified; {needs_review} need attention (not verified, '
                           f'or their state could not be established). Review each node.')
            else:
                status = 'partial'
                message = f'{restored}/{total} node(s) restored and verified; {bad} did not complete.'
            message = prefix + message
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
                supported = [n['name'] for n in lab['nodes'] if drivers.for_platform(n.get('platform'))]
                unsupported = [n['name'] for n in lab['nodes'] if not drivers.for_platform(n.get('platform'))]
            backups = []
            for job in jobs:
                capable = [n['name'] for n in job.get('nodes', []) if n.get('status') == 'succeeded' and n.get('restore_file')]
                if capable:
                    backups.append({'backup_job_id': job['id'], 'created': job.get('created'),
                                    'finished': job.get('finished'), 'nodes': capable})
            return {'backups': backups, 'supported_nodes': supported, 'unsupported_nodes': unsupported,
                    'restore_supported_platforms': list(drivers.supported_kinds())}

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
