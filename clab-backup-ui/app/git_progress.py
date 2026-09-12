"""Capture immutable lab snapshots and publish them through an owner-scoped VM helper."""
import base64
import copy
import hashlib
import io
import json
import re
import socket
import threading
import time
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote

import paramiko
from fastapi import HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field

from . import __version__
from .discovery import PinnedHostKey, vm_password
from .downloads import component, short_name, stored_path
from .inventory import PLATFORMS
from .lab_operations import operation_busy, scrub, GIT_BUSY
from .runner import now

PROTOCOL = 'clab-manager-git-v1'
MAX_FILE = 2 * 1024 * 1024
MAX_TOTAL = 16 * 1024 * 1024
MAX_WIRE = 24 * 1024 * 1024
FORMATS = {'juniper_cjunosevolved': 'junos-display-set', 'juniper_vqfx': 'junos-display-set',
           'juniper_vjunosswitch': 'junos-display-set', 'cisco_xrv9k': 'iosxr-running-config',
           'arista_ceos': 'eos-running-config'}
PUBLIC_JOB = ('id', 'lab_id', 'lab_name', 'created', 'finished', 'status', 'message', 'backup_job_id',
              'commit', 'pushed', 'target', 'checkpoint', 'changed_files', 'snapshot_path', 'note', 'review_before_push')


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def host_identity(host):
    return digest({k: host.get(k) for k in ('address', 'port', 'username', 'fingerprint')})


def public_job(job):
    return {k: copy.deepcopy(job[k]) for k in PUBLIC_JOB if k in job}


def repo_path(binding, value):
    """The browser uses logical snapshot paths, never arbitrary repository paths."""
    prefix = binding['repository'].get('prefix', '').strip('/')
    if prefix and value.startswith(prefix + '/'): value = value[len(prefix) + 1:]
    if value not in ('latest', 'baseline') and not re.fullmatch(r'checkpoints/[A-Za-z0-9][A-Za-z0-9_-]{0,99}', value):
        raise HTTPException(400, 'Choose latest, baseline or a named checkpoint.')
    return (prefix + '/' if prefix else '') + value


def pending_progress(state, lab_id=None):
    return any((not lab_id or j.get('lab_id') == lab_id) and
               j.get('status') not in ('synced', 'dismissed', 'capture_incomplete', 'failed') and
               not (j.get('status') == 'unchanged' and j.get('pushed'))
               for j in state.get('git_jobs', []))


def remote_git(host, request, stopping=None):
    """No shell, no credential forwarding; large artifacts travel only on this channel."""
    if not host.get('enabled') or not host.get('fingerprint'):
        raise ValueError('Connect the VM and verify its SSH host fingerprint first.')
    payload = (json.dumps(request, separators=(',', ':')) + '\n').encode()
    if len(payload) > MAX_WIRE: raise ValueError('Git snapshot exceeds the transfer limit.')
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(PinnedHostKey(host['fingerprint']))
    try:
        client.connect(hostname=host['address'], port=host['port'], username=host['username'],
                       password=vm_password(host), allow_agent=False, look_for_keys=False,
                       timeout=8, auth_timeout=8, banner_timeout=8)
        client.get_transport().set_keepalive(15)
        channel = client.get_transport().open_session(timeout=8)
        channel.settimeout(30)
        channel.exec_command('clab-manager-git')
        channel.sendall(payload); channel.shutdown_write()
        channel.settimeout(.2)
        data = bytearray(); until = time.monotonic() + 600; total = 0; eof = False
        while True:
            if time.monotonic() > until or (stopping and stopping.is_set()):
                raise ValueError('Git connection interrupted. Retry this saved operation to reconcile its result.')
            if channel.recv_stderr_ready(): total += len(channel.recv_stderr(65536))
            if total > MAX_WIRE: raise ValueError('Git helper response exceeded its limit.')
            if not eof:
                try: chunk = channel.recv(65536)
                except socket.timeout: continue
                eof = not chunk
                data.extend(chunk); total += len(chunk)
            if total > MAX_WIRE: raise ValueError('Git helper response exceeded its limit.')
            # Exit status can precede the last stdout packets; only stream EOF
            # proves the multi-megabyte envelope is complete.
            if eof and not channel.recv_stderr_ready() and channel.exit_status_ready(): break
            if eof: time.sleep(.03)
        try: envelope = json.loads(data)
        except (ValueError, UnicodeError): raise ValueError('Install or refresh the matching Git helper on the VM.')
        if not isinstance(envelope, dict): raise ValueError('Invalid Git helper response.')
        if 'error' in envelope: raise ValueError(str(envelope['error'])[:600])
        if channel.recv_exit_status() or not isinstance(envelope.get('result'), dict):
            raise ValueError('Git helper is unavailable. Run setup-git.sh on the VM.')
        return envelope['result']
    finally:
        client.close()


def captured_snapshot(store, backup, context=None):
    if backup.get('operation') != 'backup' or backup.get('status') not in ('succeeded', 'partial'):
        raise ValueError('Choose a completed configuration capture.')
    nodes = backup.get('nodes', [])
    if not nodes or len(nodes) > 500 or any(n.get('status') != 'succeeded' for n in nodes):
        raise ValueError('Capture incomplete. Every included device must have a successful file; latest is unchanged.')
    if len({n.get('name') for n in nodes}) != len(nodes): raise ValueError('Capture has ambiguous device identities.')
    context = context or backup.get('progress_context') or {}
    expected = context.get('node_names')
    if expected and set(expected) != {n['name'] for n in nodes}:
        raise ValueError('Capture device scope changed; save a new progress snapshot.')
    names = {}; files = {}; rows = []; total = 0
    for node in sorted(nodes, key=lambda n: n['name']):
        platform = node.get('platform')
        if platform not in FORMATS: raise ValueError('Capture is missing supported configuration-format metadata.')
        path = stored_path(store, backup, node)
        if path is None: raise ValueError('A captured file is missing or unsafe. The repository was not changed.')
        with path.open('rb') as stream: raw = stream.read(MAX_FILE + 1)
        total += len(raw)
        if not raw or len(raw) > MAX_FILE or total > MAX_TOTAL:
            raise ValueError('Use nonempty configs up to 2 MiB each and 16 MiB per snapshot.')
        try: raw.decode('utf-8')
        except UnicodeError: raise ValueError('Captured configuration is not valid UTF-8 text.')
        label = component(short_name(node, backup.get('lab_name', '')))
        suffix = PLATFORMS[platform]['suffix']
        name = f'{label}.{suffix}'
        names.setdefault(name.casefold(), []).append(node['name'])
        rows.append((node, name, raw))
    metadata = []
    for node, name, raw in rows:
        if len(names[name.casefold()]) > 1:
            base, suffix = name.rsplit('.', 1)
            name = f'{base}-{hashlib.sha256(node["name"].encode()).hexdigest()[:12]}.{suffix}'
        if name.casefold() == 'manifest.json' or name in files: raise ValueError('Capture filenames collide.')
        files[name] = base64.b64encode(raw).decode('ascii')
        metadata.append(dict(path=name, size=len(raw), sha256=hashlib.sha256(raw).hexdigest(),
                             node=node['name'], short_name=node.get('short_name', ''),
                             platform=node['platform'], format=FORMATS[node['platform']]))
    manifest = dict(schema=1, lab_id=backup['lab_id'], lab_name=backup.get('lab_name', ''),
                    backup_job_id=backup['id'], captured_at=backup.get('finished', backup.get('created')),
                    topology_digest=context.get('topology_digest'),
                    topology_provenance='captured' if context.get('topology_digest') else 'unknown',
                    node_names=sorted(n['name'] for n in nodes), excluded_nodes=context.get('excluded_nodes', []), files=metadata)
    return dict(manifest=manifest, files=files)


def decoded_snapshot(result):
    snapshot = result.get('snapshot')
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get('manifest'), dict) or not isinstance(snapshot.get('files'), dict):
        raise ValueError('The saved version has no supported snapshot manifest.')
    rows = snapshot['manifest'].get('files', [])
    if not isinstance(rows, list) or not rows or len(rows) > 500: raise ValueError('Invalid version manifest.')
    files = {}; total = 0
    for item in rows:
        if not isinstance(item, dict): raise ValueError('Invalid version manifest.')
        name = item.get('path', '')
        if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]{0,180}', name) or name.lower() == 'manifest.json':
            raise ValueError('Version contains an unsafe filename.')
        if name in files: raise ValueError('Version contains duplicate files.')
        try: raw = base64.b64decode(snapshot['files'][name], validate=True)
        except (KeyError, ValueError, TypeError): raise ValueError('Invalid version file encoding.')
        total += len(raw)
        if len(raw) > MAX_FILE or total > MAX_TOTAL or item.get('size') != len(raw) or item.get('sha256') != hashlib.sha256(raw).hexdigest():
            raise ValueError('Version integrity check failed.')
        try: raw.decode('utf-8')
        except UnicodeError: raise ValueError('Version configuration is not UTF-8 text.')
        files[name] = raw
    if set(files) != set(snapshot['files']): raise ValueError('Version files do not match the manifest.')
    return snapshot['manifest'], files


class GitProgress:
    def __init__(self, store, runner):
        self.store = store; self.runner = runner; self.stopping = threading.Event()
        self.pool = ThreadPoolExecutor(max_workers=1)
        with store.lock:
            for job in store.state.setdefault('git_jobs', []):
                child = next((b for b in store.state['jobs'] if b.get('progress_id') == job['id']), None)
                if child and not job.get('backup_job_id'):
                    job['backup_job_id'] = child['id']
                    if job['status'] == 'failed': job['status'] = 'interrupted'
                if job['status'] in GIT_BUSY:
                    if job.get('target') == 'update':
                        job.update(status='dismissed', message='Repository update interrupted. Check repository status before updating again.')
                        continue
                    job.update(status='interrupted', message='Manager restarted. Retry to reconcile the saved capture and Git result.')
            store.save()

    def close(self):
        self.stopping.set(); self.pool.shutdown(wait=False, cancel_futures=True)

    def invoke(self, request, binding=None):
        with self.store.lock:
            host = copy.deepcopy(self.store.state.get('host', {}))
        if binding:
            if binding.get('host_identity') != host_identity(host):
                raise ValueError('The VM identity changed. Return to the original VM or reconnect the repository.')
            request = dict(request, binding_id=binding['binding_id'], revision=binding['revision'])
        try: return remote_git(host, request, self.stopping)
        except ValueError as exc:
            with self.store.lock: message = scrub(str(exc), self.store.state)
            raise ValueError(message[:600])
        except Exception:
            raise ValueError('Cannot reach the VM Git helper. The local capture is retained; check VM setup and retry.')

    def repositories(self):
        result = self.invoke({'mode': 'list'})
        if result.get('protocol') != PROTOCOL or result.get('version') != __version__:
            raise ValueError('Update the VM Git helper to match manager ' + __version__ + ' using setup-git.sh --refresh.')
        if not isinstance(result.get('repositories'), list): raise ValueError('Invalid repository list.')
        return result

    def binding(self, lab_id):
        lab = self.store.lab(lab_id)
        if not lab: raise HTTPException(404, 'Lab not found.')
        if not lab.get('git_binding'): raise HTTPException(409, 'Connect this lab to a Git repository first.')
        return copy.deepcopy(lab['git_binding'])

    def idle(self, lab_id=None):
        if operation_busy(self.store.state) or any(j['status'] in ('queued', 'running') for j in self.store.state['jobs']):
            raise HTTPException(409, 'Wait for the active backup, Git save or lab operation to finish.')
        if self.store.reset_pending: raise HTTPException(409, 'Finish the storage reset first.')

    def guard_pending(self, lab_id=None):
        if pending_progress(self.store.state, lab_id):
            raise HTTPException(409, 'Finish pending Git saves, or choose Keep snapshot only in Git history before continuing.')

    def get_job(self, job_id):
        job = next((j for j in self.store.state['git_jobs'] if j['id'] == job_id), None)
        if not job: raise HTTPException(404, 'Git save not found.')
        return job

    def update(self, job_id, **fields):
        with self.store.lock:
            job = self.get_job(job_id); old = copy.deepcopy(job)
            job.update(fields)
            try: self.store.save()
            except OSError:
                job.clear(); job.update(old); raise

    def schedule(self, job):
        try: self.pool.submit(self.execute, job['id'])
        except RuntimeError:
            self.update(job['id'], status='interrupted', message='Manager is stopping. Retry after restarting.')
        return public_job(job)

    def execute(self, job_id):
        result = None
        try:
            with self.store.lock:
                job = copy.deepcopy(self.get_job(job_id))
                binding = self.binding(job['lab_id'])
                if digest(binding) != job['binding_digest']: raise ValueError('Repository settings changed; this save was not sent.')
            # A retry with a commit never recaptures or rewrites working files.
            if job.get('commit'):
                if job.get('retry_push'):
                    self.update(job_id, status='pushing', message='Pushing the saved commit.')
                    result = self.invoke({'mode': 'push', 'operation_id': job_id}, binding)
                else:
                    result = dict(status='committed', commit=job['commit'], pushed=False,
                                  changed_files=job.get('changed_files', []), snapshot_path=job.get('snapshot_path', ''))
                self.finish(job, result)
                return
            backup_id = job.get('backup_job_id', '')
            if not backup_id:
                if job.get('retry'):
                    raise ValueError('No complete capture is available for retry. Start a new Save progress capture.')
                self.update(job_id, status='capturing', message='Capturing the configured devices.')
                child = self.runner.submit(job['lab_id'], operation='backup', source='git-progress',
                                           node_names=job['node_names'], progress_id=job_id,
                                           progress_context=job['capture_context'])
                backup_id = child['id']; self.update(job_id, backup_job_id=backup_id)
            while True:
                with self.store.lock:
                    backup = next((copy.deepcopy(b) for b in self.store.state['jobs'] if b['id'] == backup_id), None)
                if not backup: raise ValueError('The original capture is unavailable; latest is unchanged.')
                if backup['status'] not in ('queued', 'running'): break
                if self.stopping.wait(.1): raise ValueError('Manager stopping. Retry after the capture result is available.')
            try: snapshot = captured_snapshot(self.store, backup)
            except ValueError as exc:
                self.update(job_id, status='capture_incomplete', message=str(exc), finished=now())
                return
            if set(snapshot['manifest']['node_names']) != set(job['node_names']):
                raise ValueError('This capture does not contain exactly the configured device scope.')
            fingerprint = digest(snapshot)
            if job.get('snapshot_digest') and fingerprint != job['snapshot_digest']:
                raise ValueError('The saved capture changed on disk. It will not replace the repository snapshot.')
            self.update(job_id, status='exporting', snapshot_digest=fingerprint, message='Saving captured configurations to the VM repository.')
            request = copy.deepcopy(job['request'])
            if 'expected_head' not in job:
                status = self.invoke({'mode': 'status'}, binding)
                if not status.get('ready'): raise ValueError(status.get('problem') or 'Repository needs attention before exporting.')
                expected_head = status.get('head', '')
                self.update(job_id, expected_head=expected_head)
            else: expected_head = job['expected_head']
            request.update(mode='publish', operation_id=job_id, expected_head=expected_head, snapshot=snapshot)
            result = self.invoke(request, binding)
            if result.get('commit'):
                self.update(job_id, commit=result['commit'], changed_files=result.get('changed_files', []),
                            snapshot_path=result.get('snapshot_path', ''))
            if (job.get('retry_push', job.get('want_push', False)) and result.get('commit')
                    and result.get('status') != 'needs_attention' and not result.get('pushed')):
                # The publication body is immutable for idempotency. Push is a
                # separate action after replay/reconciliation of a lost response.
                self.update(job_id, status='pushing', commit=result['commit'], message='Pushing the reconciled saved commit.')
                result = self.invoke({'mode': 'push', 'operation_id': job_id}, binding)
            self.finish(job, result)
        except Exception as exc:
            with self.store.lock:
                existing = copy.deepcopy(self.get_job(job_id))
                child = next((b for b in self.store.state['jobs'] if b.get('progress_id') == job_id), None)
                if child and not existing.get('backup_job_id'): existing['backup_job_id'] = child['id']
                if isinstance(result, dict) and re.fullmatch(r'[0-9a-f]{40,64}', str(result.get('commit', ''))):
                    existing['commit'] = result['commit']
                message = scrub(str(exc), self.store.state) if isinstance(exc, (ValueError, HTTPException)) else 'Git save interrupted. The local capture is retained; retry to reconcile.'
            status = 'interrupted' if self.stopping.is_set() else 'push_pending' if existing.get('commit') else 'export_pending' if existing.get('backup_job_id') else 'failed'
            recovery = dict(status=status, message=message[:600], finished=now(),
                            backup_job_id=existing.get('backup_job_id', ''), commit=existing.get('commit', ''))
            try: self.update(job_id, **recovery)
            except OSError:
                # The worker has ended. Do not retain a busy reservation in memory
                # until restart; retries after disk recovery reuse this capture.
                with self.store.lock: self.get_job(job_id).update(recovery)
        finally:
            try: self.store.event('git.progress', 'Git save stage completed; see its saved operation status.', lab_id=job.get('lab_id', '') if 'job' in locals() else '', job_id=job_id)
            except OSError: pass

    def finish(self, job, result):
        commit = result.get('commit', '')
        if commit and not re.fullmatch(r'[0-9a-f]{40,64}', commit): raise ValueError('Git helper returned an invalid commit identifier.')
        pushed = result.get('pushed') is True
        if pushed: status = 'synced'
        elif result.get('status') == 'needs_attention': status = 'push_pending' if commit else 'export_pending'
        elif job.get('review_before_push') and not job.get('retry_push'): status = 'review_pending'
        else: status = 'committed'
        message = result.get('message') or ('Saved to Git.' if pushed else 'Saved on VM; not pushed.')
        with self.store.lock: message = scrub(str(message), self.store.state)
        self.update(job['id'], status=status, commit=commit, pushed=pushed, message=message[:600],
                    changed_files=result.get('changed_files', []), snapshot_path=result.get('snapshot_path', ''), finished=now())
        if pushed:
            with self.store.lock:
                for previous in self.store.state['git_jobs']:
                    if (previous['id'] in result.get('synced_operations', []) and previous.get('binding_digest') == job.get('binding_digest')
                            and previous.get('status') != 'dismissed'):
                        previous.update(status='synced', pushed=True, message='Saved commit is included in the verified remote history.', finished=now())
                self.store.save()

    def install(self, app):
        class Link(BaseModel):
            model_config = ConfigDict(extra='forbid')
            binding_id: str = Field(min_length=1, max_length=120)
            node_names: list[str] = Field(min_length=1, max_length=500)
            review_before_push: bool = False

        class Save(BaseModel):
            model_config = ConfigDict(extra='forbid')
            request_id: str = Field(pattern=r'^[0-9a-f]{32}$')
            target: str = 'latest'
            checkpoint: str = Field(default='', max_length=100)
            push: bool = True
            note: str = Field(default='', max_length=500)
            backup_job_id: str = Field(default='', max_length=64)
            replace_baseline: bool = False
            expected_baseline: str = Field(default='', max_length=64)
            allow_removed: bool = False

        class Retry(BaseModel):
            model_config = ConfigDict(extra='forbid')
            push: bool = True

        class Dismiss(BaseModel):
            model_config = ConfigDict(extra='forbid')
            acknowledge: bool = False

        class Version(BaseModel):
            model_config = ConfigDict(extra='forbid')
            commit: str = Field(pattern=r'^[0-9a-f]{40,64}$')
            path: str = Field(min_length=1, max_length=250)

        class Comparison(BaseModel):
            model_config = ConfigDict(extra='forbid')
            job_id: str = Field(default='', max_length=64)
            commit: str = Field(default='', max_length=64)
            path: str = Field(default='', max_length=250)

        def call(request, binding=None):
            try: return self.invoke(request, binding)
            except ValueError as exc: raise HTTPException(409, str(exc))

        @app.get('/api/git/repositories')
        def repositories():
            try: return self.repositories()
            except ValueError as exc: raise HTTPException(409, str(exc))

        @app.get('/api/labs/{lab_id}/git')
        def settings(lab_id: str):
            with self.store.lock:
                lab = self.store.lab(lab_id)
                if not lab: raise HTTPException(404, 'Lab not found.')
                binding = copy.deepcopy(lab.get('git_binding'))
                jobs = [public_job(j) for j in reversed(self.store.state['git_jobs']) if j['lab_id'] == lab_id]
                supported = [{k: n.get(k, '') for k in ('name', 'short_name', 'platform')} for n in lab['nodes'] if n.get('platform') in PLATFORMS]
                unsupported = [n['name'] for n in lab['nodes'] if n.get('platform') not in PLATFORMS]
            status = {}
            if binding:
                try: status = self.invoke({'mode': 'status'}, binding)
                except ValueError as exc: status = {'ready': False, 'problem': str(exc)}
            return dict(binding=binding, repository_status=status, jobs=jobs, supported_nodes=supported, unsupported_nodes=unsupported)

        @app.put('/api/labs/{lab_id}/git')
        def link(lab_id: str, data: Link):
            with self.store.lock:
                self.idle(); self.guard_pending(lab_id)
                if not self.store.lab(lab_id): raise HTTPException(404, 'Lab not found.')
                before = host_identity(self.store.state.get('host', {}))
            result = repositories()
            repo = next((r for r in result['repositories'] if r['id'] == data.binding_id), None)
            if not repo: raise HTTPException(400, 'Choose a repository registered by the VM administrator.')
            binding = dict(binding_id=repo['id'], revision=repo['revision'], repository=repo,
                           host_identity=before, node_names=data.node_names, review_before_push=data.review_before_push)
            call({'mode': 'status'}, binding)
            with self.store.lock:
                self.idle(); self.guard_pending(lab_id)
                if before != host_identity(self.store.state.get('host', {})): raise HTTPException(409, 'VM connection changed. Connect again.')
                lab = self.store.lab(lab_id)
                if not lab: raise HTTPException(404, 'Lab was removed.')
                valid = {n['name'] for n in lab['nodes'] if n.get('platform') in PLATFORMS}
                if len(set(data.node_names)) != len(data.node_names) or not set(data.node_names) <= valid:
                    raise HTTPException(400, 'Select distinct supported devices from this lab.')
                for other in self.store.state['labs']:
                    if other['id'] != lab_id and other.get('git_binding', {}).get('binding_id') == repo['id']:
                        raise HTTPException(409, 'This registered destination is already connected to another lab. Register a separate prefix.')
                old = lab.get('git_binding'); lab['git_binding'] = binding
                try: self.store.save()
                except OSError:
                    if old is None: lab.pop('git_binding', None)
                    else: lab['git_binding'] = old
                    raise HTTPException(500, 'Could not save the repository connection.')
            self.store.event('git.connect', 'Lab connected to a registered VM repository.', lab_id=lab_id)
            return {'saved': True, 'binding': binding}

        @app.post('/api/labs/{lab_id}/git/unlink')
        def unlink(lab_id: str):
            with self.store.lock:
                self.idle(); self.guard_pending(lab_id)
                lab = self.store.lab(lab_id)
                if not lab: raise HTTPException(404, 'Lab not found.')
                old = lab.pop('git_binding', None)
                try: self.store.save()
                except OSError:
                    if old: lab['git_binding'] = old
                    raise HTTPException(500, 'Could not disconnect the repository.')
            return {'unlinked': True}

        @app.post('/api/labs/{lab_id}/git/save')
        def save(lab_id: str, data: Save):
            if data.target not in ('latest', 'checkpoint', 'baseline'): raise HTTPException(400, 'Choose latest, checkpoint or baseline.')
            if data.target == 'checkpoint' and not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,99}', data.checkpoint):
                raise HTTPException(400, 'Use a checkpoint name containing letters, numbers, hyphens or underscores.')
            if data.target == 'baseline' and not data.backup_job_id: raise HTTPException(400, 'Select a complete saved capture for the baseline.')
            if any(ord(c) < 32 for c in data.note): raise HTTPException(400, 'Use a single-line save note.')
            request_digest = digest(dict(lab_id=lab_id, **data.model_dump()))
            with self.store.lock:
                previous = next((j for j in self.store.state['git_jobs'] if j['id'] == data.request_id), None)
                if previous:
                    if previous.get('request_digest') != request_digest: raise HTTPException(409, 'Request ID already belongs to a different save.')
                    return public_job(previous)
                self.idle(); binding = self.binding(lab_id)
                lab = self.store.lab(lab_id)
                if binding['host_identity'] != host_identity(self.store.state.get('host', {})):
                    raise HTTPException(409, 'Reconnect the original VM before saving progress.')
                names = binding['node_names']; known = {n['name'] for n in lab['nodes'] if n.get('platform') in PLATFORMS}
                if not set(names) <= known: raise HTTPException(409, 'Configured devices changed. Review the Git repository device selection.')
                if data.backup_job_id:
                    backup = next((b for b in self.store.state['jobs'] if b['id'] == data.backup_job_id and b['lab_id'] == lab_id), None)
                    if not backup: raise HTTPException(404, 'Capture not found in this lab.')
                    try: snapshot = captured_snapshot(self.store, backup)
                    except ValueError as exc: raise HTTPException(400, str(exc))
                    if set(snapshot['manifest']['node_names']) != set(names): raise HTTPException(400, 'Capture must contain exactly the configured devices.')
                context = dict(node_names=sorted(names), excluded_nodes=sorted(n['name'] for n in lab['nodes'] if n['name'] not in names),
                               topology_digest=hashlib.sha256(lab['definition_yaml'].encode()).hexdigest() if lab.get('definition_yaml') else None)
                review = binding.get('review_before_push', False) and data.push
                request = dict(target=data.target, checkpoint=data.checkpoint, push=False,
                               replace_baseline=data.replace_baseline, expected_baseline=data.expected_baseline,
                               allow_removed=data.allow_removed, message=data.note.strip() or f'Save {lab["name"]} progress')
                job = dict(id=data.request_id, request_digest=request_digest, lab_id=lab_id, lab_name=lab['name'],
                           created=now(), status='queued', message='Save progress queued.', backup_job_id=data.backup_job_id,
                           target=data.target, checkpoint=data.checkpoint, note=data.note, pushed=False,
                           review_before_push=review, binding_digest=digest(binding), request=request,
                           want_push=data.push and not review,
                           node_names=copy.deepcopy(names), capture_context=context)
                self.store.state['git_jobs'].append(job)
                try: self.store.save()
                except OSError:
                    self.store.state['git_jobs'].remove(job); raise HTTPException(500, 'Could not save the request. No work was submitted.')
            return self.schedule(job)

        @app.get('/api/git/jobs/{job_id}')
        def job_status(job_id: str):
            with self.store.lock: return public_job(self.get_job(job_id))

        @app.post('/api/git/jobs/{job_id}/retry')
        def retry(job_id: str, data: Retry):
            with self.store.lock:
                self.idle(); job = self.get_job(job_id)
                if job['status'] in ('dismissed', 'capture_incomplete', 'failed'): raise HTTPException(409, 'Start a new save for this capture outcome.')
                if job['status'] == 'synced': return public_job(job)
                if digest(self.binding(job['lab_id'])) != job['binding_digest']: raise HTTPException(409, 'Repository settings changed. Reconnect the original destination.')
                self.update(job_id, status='queued', retry=True, retry_push=data.push, message='Retry queued; the saved capture will be reused.')
            return self.schedule(job)

        @app.post('/api/git/jobs/{job_id}/dismiss')
        def dismiss(job_id: str, data: Dismiss):
            if not data.acknowledge: raise HTTPException(400, 'Confirm keeping the snapshot without tracking its pending Git save.')
            with self.store.lock:
                self.idle(); self.get_job(job_id)
                self.update(job_id, status='dismissed', message='Snapshot kept; pending Git tracking dismissed. Existing commits are unchanged.')
            return public_job(self.get_job(job_id))

        @app.post('/api/labs/{lab_id}/git/update')
        def update_remote(lab_id: str):
            with self.store.lock:
                self.idle(); self.guard_pending(lab_id); binding = self.binding(lab_id)
                ident = uuid.uuid4().hex
                marker = dict(id=ident, lab_id=lab_id, status='exporting', created=now(), message='Updating repository from remote.', target='update')
                self.store.state['git_jobs'].append(marker)
                try: self.store.save()
                except OSError:
                    self.store.state['git_jobs'].remove(marker)
                    raise HTTPException(500, 'Could not save the update request. No work was submitted.')
            completed = False
            try:
                status = call({'mode': 'status'}, binding)
                result = call({'mode': 'update', 'expected_head': status['head']}, binding)
                completed = True
                return result
            finally:
                terminal = dict(status='dismissed', finished=now(), message='Repository updated from remote.' if completed else 'Repository update needs attention. Check status before retrying.')
                try: self.update(ident, **terminal)
                except OSError:
                    with self.store.lock: self.get_job(ident).update(terminal)
                    raise

        @app.get('/api/labs/{lab_id}/git/history')
        def history(lab_id: str):
            with self.store.lock: binding = self.binding(lab_id)
            result = call({'mode': 'history'}, binding)
            prefix = binding['repository'].get('prefix', '').strip('/')
            for row in result.get('versions', []):
                full = repo_path(binding, row['path'])
                row['path'] = full[len(prefix) + 1:] if prefix else full
            return result

        def version_data(lab_id, data):
            with self.store.lock: binding = self.binding(lab_id)
            result = call({'mode': 'read-version', 'commit': data.commit, 'path': repo_path(binding, data.path)}, binding)
            try: return decoded_snapshot(result)
            except ValueError as exc: raise HTTPException(409, str(exc))

        @app.post('/api/labs/{lab_id}/git/version')
        def version(lab_id: str, data: Version):
            manifest, files = version_data(lab_id, data)
            return dict(manifest=manifest, files=[dict(name=n, text=v.decode('utf-8')) for n, v in files.items()], restore_supported=False)

        @app.post('/api/labs/{lab_id}/git/version/download')
        def download(lab_id: str, data: Version):
            manifest, files = version_data(lab_id, data)
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as archive:
                archive.writestr('manifest.json', json.dumps(manifest, indent=2))
                for name, raw in files.items(): archive.writestr(name, raw)
            filename = component(manifest.get('lab_name', 'lab')) + '-' + data.commit[:12] + '.zip'
            return Response(buf.getvalue(), media_type='application/zip', headers={'Content-Disposition': "attachment; filename*=UTF-8''" + quote(filename, safe='')})

        @app.post('/api/labs/{lab_id}/git/compare')
        def compare(lab_id: str, data: Comparison):
            if data.job_id:
                with self.store.lock:
                    job = self.get_job(data.job_id)
                    if job['lab_id'] != lab_id: raise HTTPException(404, 'Git save not found in this lab.')
                    binding = self.binding(lab_id)
                    if digest(binding) != job.get('binding_digest'): raise HTTPException(409, 'Reconnect the original repository to review this save.')
                return call({'mode': 'compare', 'operation_id': data.job_id}, binding)
            if not re.fullmatch(r'[0-9a-f]{40,64}', data.commit): raise HTTPException(400, 'Choose a saved commit.')
            _, before = version_data(lab_id, data)
            with self.store.lock: binding = self.binding(lab_id)
            status = call({'mode': 'status'}, binding)
            path = repo_path(binding, 'latest')
            result = call({'mode': 'read-version', 'commit': status['head'], 'path': path}, binding)
            try: _, after = decoded_snapshot(result)
            except ValueError as exc: raise HTTPException(409, str(exc))
            return {'files': [dict(name=n, status='added' if n not in before else 'removed' if n not in after else 'changed',
                                   before=before.get(n, b'').decode('utf-8'), after=after.get(n, b'').decode('utf-8'))
                              for n in sorted(before.keys() | after.keys()) if before.get(n) != after.get(n)]}
