"""Reviewed lab-level actions with review tokens and persistent job output."""
import copy
import json
import re
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote

import paramiko
from fastapi import HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field

from .discovery import PinnedHostKey, read_key, parse_definition, stamp
from .topology import parse_drawing
from .drawio_export import drawio

BUSY = ('queued', 'running')


def operation_busy(state, lab_id=None):
    return any(j['status'] in BUSY and (not lab_id or not j.get('lab_id') or j['lab_id'] == lab_id)
               for j in state.get('operations', []))


def remote(host, request, output=None, stopping=None):
    if not host or not host.get('enabled'): raise ValueError('Configure and enable the VM connection first.')
    if not host.get('fingerprint'): raise ValueError('Refresh discovery to establish the VM fingerprint first.')
    client = paramiko.SSHClient(); client.set_missing_host_key_policy(PinnedHostKey(host['fingerprint']))
    opts = dict(hostname=host['address'], port=host['port'], username=host['username'], timeout=8,
                auth_timeout=8, banner_timeout=8, allow_agent=False, look_for_keys=False)
    if host['auth'] == 'key': opts['pkey'] = read_key(host['private_key'], host.get('passphrase', ''))
    else: opts['password'] = host.get('password', '')
    try:
        client.connect(**opts)
        client.get_transport().set_keepalive(15)
        channel = client.get_transport().open_session(timeout=8); channel.settimeout(15)
        channel.exec_command('clab-manager-operations')
        channel.sendall((json.dumps(request) + '\n').encode()); channel.shutdown_write()
        until = time.monotonic() + (1250 if request.get('mode') == 'run' else 180)
        pending = b''; result = None; total = 0
        while True:
            if time.monotonic() > until or (stopping and stopping.is_set()):
                raise ValueError('Operation connection interrupted. Inspect the lab before retrying.')
            if channel.recv_ready():
                chunk = channel.recv(65536); pending += chunk; total += len(chunk)
                if len(pending) > 3 * 1024 * 1024 or total > 5 * 1024 * 1024: raise ValueError('Host operation response exceeded its limit.')
                while b'\n' in pending:
                    line, pending = pending.split(b'\n', 1)
                    try: item = json.loads(line)
                    except ValueError: raise ValueError('Operations helper is unavailable or outdated. Run start-manager.sh --enable-operations on the VM.')
                    if not isinstance(item, dict): raise ValueError('Invalid operations helper response.')
                    if 'error' in item: raise ValueError(str(item['error'])[:1000])
                    if output and 'output' in item: output(str(item['output']))
                    if 'result' in item: result = item['result']
            if channel.recv_stderr_ready(): channel.recv_stderr(65536)
            if channel.exit_status_ready() and not channel.recv_ready(): break
            time.sleep(.03)
        if channel.recv_exit_status() != 0 or not isinstance(result, dict):
            raise ValueError('Operations helper is unavailable. Run sudo bash deploy/start-manager.sh --enable-operations on the VM.')
        return result
    finally: client.close()


def scrub(text, state):
    secrets = []
    host = state.get('host', {})
    secrets += [host.get(k, '') for k in ('password', 'passphrase', 'private_key')]
    for lab in state['labs']:
        for item in lab.get('nodes', []) + lab.get('profiles', []):
            secrets += [item.get(k, '') for k in ('password', 'passphrase', 'private_key', 'enable_password')]
    for secret in sorted(filter(None, secrets), key=len, reverse=True): text = text.replace(secret, '[redacted]')
    text = re.sub(r'\x1b\[[0-9;]*[A-Za-z]', '', text)
    text = re.sub(r'(?s)-----BEGIN [^-]*PRIVATE KEY-----.*?(?:-----END [^-]*PRIVATE KEY-----|$)', '[private key omitted]', text)
    text = re.sub(r'(?im)^.*(?:password|passphrase|private.key|community|secret)\s*[:= ].*$', '[sensitive output omitted]', text)
    return text[-512 * 1024:]


class LabOperations:
    def __init__(self, store, discovery):
        self.store = store; self.discovery = discovery; self.previews = {}; self.stopping = threading.Event()
        self.pool = ThreadPoolExecutor(max_workers=1); self.cap_cache = None; self.active = set()
        with store.lock:
            for job in store.state.setdefault('operations', []):
                if job['status'] in BUSY:
                    job.update(status='interrupted', message='Manager restarted; inspect the VM before retrying.')
            store.save()

    def close(self):
        self.stopping.set(); self.pool.shutdown(wait=False, cancel_futures=True)

    def host(self):
        with self.store.lock: return copy.deepcopy(self.store.state.get('host', {}))

    def guard(self, lab_id=''):
        if self.active or operation_busy(self.store.state): raise HTTPException(409, 'Wait for the current lab operation to finish.')
        if any(j['status'] in BUSY and (not lab_id or j['lab_id'] == lab_id) for j in self.store.state['jobs']):
            raise HTTPException(409, 'Wait for the lab backup or login job to finish.')

    def invoke(self, req):
        try: return remote(self.host(), req)
        except Exception as exc:
            message = str(exc) if type(exc) is ValueError else 'Cannot reach the VM operations helper. Check setup and SSH settings.'
            raise HTTPException(409, message)

    def install(self, app):
        class Request(BaseModel):
            model_config = ConfigDict(extra='forbid')
            action: str = Field(default='', max_length=60)
            lab_id: str = Field(default='', max_length=64)
            path: str = Field(default='', max_length=4096)
            name: str = Field(default='', max_length=120)
            options: dict = Field(default_factory=dict)

        @app.get('/api/operations/capabilities')
        def capabilities():
            host = self.host(); key = host.get('revision')
            if self.cap_cache and self.cap_cache[0] == key and self.cap_cache[1] > time.monotonic(): return self.cap_cache[2]
            result = self.invoke({'mode': 'capabilities'})
            self.cap_cache = (key, time.monotonic() + 60, result)
            return result

        @app.post('/api/operations/browse')
        def browse(data: Request): return self.invoke({'mode': 'browse', 'path': data.path})

        @app.post('/api/operations/read')
        def read(data: Request): return self.invoke({'mode': 'read', 'path': data.path})

        @app.get('/api/operations/popular')
        def popular(): return self.invoke({'mode': 'popular'})

        @app.post('/api/operations/parse-yaml')
        def parse_yaml(data: Request):
            try:
                raw = str(data.options.get('text', '')).encode()
                parsed = parse_definition(raw)
                return {'name': parsed['name'], 'drawing': parse_drawing(b'{"nodeAnnotations":[]}', raw)}
            except (ValueError, TypeError, AttributeError, RecursionError): raise HTTPException(400, 'Enter a valid literal Containerlab topology.')

        @app.post('/api/operations/preview')
        def preview(data: Request):
            if data.action not in ("deploy", "redeploy", "destroy", "apply", "start", "stop", "restart", "save", "inspect", "inspect-all", "create", "delete", "clone"):
                raise HTTPException(400, "This lab operation has been removed or is unsupported.")
            with self.store.lock:
                self.guard(data.lab_id)
                lab = copy.deepcopy(self.store.lab(data.lab_id)) if data.lab_id else None
                if data.lab_id and not lab: raise HTTPException(404, 'Lab not found.')
                host_revision = self.store.state.get('host', {}).get('revision')
            path = data.path or (lab.get('vm_project_path') or lab.get('vm_source', {}).get('files', {}).get('definition', {}).get('path', '') if lab else '')
            name = (lab.get('deployment_name') or lab['name']) if lab else data.name or 'manager'
            options = copy.deepcopy(data.options)
            source_name = name
            source = None
            if data.action not in ('create', 'clone', 'inspect-all'):
                source = self.invoke({'mode': 'read', 'path': path})
                try: source_name = parse_definition(source['text'].encode())['name']
                except (ValueError, TypeError, AttributeError, RecursionError): raise HTTPException(400, 'The VM file must contain a valid literal Containerlab topology.')
                if not lab: name = source_name
            if data.action == 'create':
                try:
                    parsed = parse_definition(str(options.get('text', '')).encode())
                    if not lab or data.action == 'create': name = parsed['name']
                except (ValueError, TypeError, AttributeError, RecursionError): raise HTTPException(400, 'Use valid literal Containerlab YAML for the new project.')
            req = dict(mode='preview', action=data.action, path=path, name=name, source_name=source_name, options=options)
            result = self.invoke(req)
            if source and result.get('source_hash') != source['sha256']: raise HTTPException(409, 'Source changed during review; retry.')
            with self.store.lock:
                if self.store.state.get('host', {}).get('revision') != host_revision: raise HTTPException(409, 'VM connection changed. Preview again.')
                self.previews = {k:v for k,v in self.previews.items() if v['expires'] > time.monotonic()}
                if len(self.previews) >= 50: self.previews.pop(next(iter(self.previews)))
                token = uuid.uuid4().hex
                self.previews[token] = {'request': req, 'digest': result['digest'], 'revision': host_revision,
                                        'lab_id': data.lab_id, 'expires': time.monotonic() + 300}
            return {**result, 'token': token}

        class Confirmation(BaseModel):
            model_config = ConfigDict(extra='forbid')
            token: str = Field(min_length=32, max_length=32)

        @app.post('/api/operations/confirm')
        def confirm(data: Confirmation):
            with self.store.lock:
                preview = self.previews.get(data.token)
                if not preview or preview['expires'] < time.monotonic(): raise HTTPException(409, 'Review expired; preview the operation again.')
                if preview['revision'] != self.store.state.get('host', {}).get('revision'): raise HTTPException(409, 'VM changed. Preview again.')
                if preview['lab_id'] and not self.store.lab(preview['lab_id']): raise HTTPException(409, 'Saved lab was removed. Preview again.')
                self.guard(preview['lab_id'])
                req = {**preview['request'], 'mode': 'run', 'digest': preview['digest']}
                job = {'id': uuid.uuid4().hex, 'lab_id': preview['lab_id'], 'name': req['name'], 'action': req['action'],
                       'path': req['path'], 'created': stamp(), 'status': 'queued', 'output': '', 'message': 'Queued', 'exit_code': None}
                previous_jobs = self.store.state['operations']
                self.store.state['operations'] = (previous_jobs + [job])[-200:]
                try: self.store.save()
                except OSError:
                    self.store.state['operations'] = previous_jobs; raise HTTPException(500, 'Could not save the operation; nothing was submitted.')
                self.previews.pop(data.token)
                try: self.pool.submit(self.execute, job['id'], self.host(), req)
                except RuntimeError:
                    job.update(status='interrupted', message='Manager is shutting down. Preview again after restart.'); self.store.save()
                    raise HTTPException(409, job['message'])
                return copy.deepcopy(job)

        @app.get('/api/operations')
        def history():
            with self.store.lock: return [{k:v for k,v in j.items() if k != 'output'} for j in reversed(self.store.state['operations'][-200:])]

        @app.get('/api/operations/{job_id}')
        def job(job_id: str):
            with self.store.lock:
                found = next((j for j in self.store.state['operations'] if j['id'] == job_id), None)
                if not found: raise HTTPException(404, 'Operation not found.')
                return copy.deepcopy(found)

        class LabSettings(BaseModel):
            model_config = ConfigDict(extra='forbid')
            favorite: bool | None = None
            path: str | None = Field(default=None, max_length=4096)

        @app.put('/api/labs/{lab_id}/operations-settings')
        def settings(lab_id: str, data: LabSettings):
            with self.store.lock:
                lab = self.store.lab(lab_id)
                if not lab: raise HTTPException(404, 'Lab not found.')
                self.guard(lab_id)
                name = parse_definition(lab['definition_yaml'].encode())['name'] if lab.get('definition_yaml') else lab['name']
                revision = self.store.state.get('host', {}).get('revision')
            if data.path:
                value = self.invoke({'mode': 'read', 'path': data.path})
                try:
                    parsed = parse_definition(value['text'].encode())
                    if parsed['name'] != name: raise ValueError()
                except (ValueError, TypeError): raise HTTPException(400, 'The selected VM YAML does not match this lab name.')
            with self.store.lock:
                self.guard(lab_id); lab = self.store.lab(lab_id)
                if not lab: raise HTTPException(404, 'Lab was removed.')
                if revision != self.store.state.get('host', {}).get('revision'): raise HTTPException(409, 'VM connection changed. Select the project again.')
                if data.favorite is not None: lab['favorite'] = data.favorite
                if data.path is not None: lab['vm_project_path'] = data.path
                self.store.save()
            return {'saved': True}

        @app.get('/api/labs/{lab_id}/drawio')
        def export(lab_id: str, layout: str = 'interactive'):
            if layout != 'interactive': raise HTTPException(400, 'Choose a supported layout.')
            with self.store.lock:
                lab = self.store.lab(lab_id)
                if not lab: raise HTTPException(404, 'Lab not found.')
                content = drawio(lab, layout); filename = lab['name'] + '.drawio'
            return Response(content, media_type='application/xml', headers={'Content-Disposition': "attachment; filename=topology.drawio; filename*=UTF-8''" + quote(filename, safe='')})

        class Layout(BaseModel):
            positions: dict

        def positioned(lab, positions):
            if not lab or not lab.get('drawing'): raise HTTPException(404, 'Import a topology map first.')
            drawing = copy.deepcopy(lab['drawing'])
            aliases = {n['id']: n for n in drawing['nodes']}
            if set(positions) - set(aliases): raise HTTPException(400, 'Unknown map nodes.')
            for alias, point in positions.items():
                if not isinstance(point, list) or len(point) != 2 or any(type(v) not in (int, float) or not -100000 <= v <= 100000 for v in point): raise HTTPException(400, 'Invalid node coordinates.')
                aliases[alias].update(x=point[0], y=point[1])
            return drawing

        @app.put('/api/labs/{lab_id}/layout')
        def layout(lab_id: str, data: Layout):
            with self.store.lock:
                self.guard(lab_id); lab = self.store.lab(lab_id)
                drawing = positioned(lab, data.positions)
                previous = lab['drawing']; lab['drawing'] = drawing
                try: self.store.save()
                except OSError:
                    lab['drawing'] = previous
                    raise HTTPException(500, 'Could not save the layout. Try again.')
            return {'saved': True}

        @app.post('/api/labs/{lab_id}/drawio')
        def export_current(lab_id: str, data: Layout):
            with self.store.lock:
                lab = copy.deepcopy(self.store.lab(lab_id))
                drawing = positioned(lab, data.positions)
                lab['drawing'] = drawing
                content = drawio(lab)
            return Response(content, media_type='application/xml', headers={'Content-Disposition': "attachment; filename=topology.drawio; filename*=UTF-8''" + quote(lab['name']+'.drawio', safe='')})

    def execute(self, ident, host, req):
        with self.store.lock: self.active.add(ident)
        raw_output = ''; last_save = 0
        def update(**fields):
            with self.store.lock:
                job = next(j for j in self.store.state['operations'] if j['id'] == ident)
                job.update(fields); self.store.save()
        def output(chunk):
            nonlocal raw_output, last_save
            raw_output = (raw_output + chunk)[-512 * 1024:]
            if time.monotonic() - last_save > .25:
                # Publish complete lines so split credential values cannot leak mid-chunk.
                with self.store.lock: clean = scrub(raw_output.rpartition('\n')[0], self.store.state)
                update(output=clean); last_save = time.monotonic()
        try:
            update(status='running', started=stamp(), message='Executing on the VM')
            result = remote(host, req, output, self.stopping)
            with self.store.lock: clean = scrub(raw_output, self.store.state)
            update(status='succeeded' if result.get('exit_code') == 0 else 'failed', exit_code=result.get('exit_code'),
                   finished=stamp(), output=clean, result=result, message='Operation completed' if result.get('exit_code') == 0 else 'Host command returned an error')
        except Exception as exc:
            message = str(exc) if type(exc) is ValueError else 'SSH connection or operation failed. Inspect the VM before retrying.'
            with self.store.lock: clean = scrub(raw_output, self.store.state); message = scrub(message, self.store.state)
            update(status='interrupted' if self.stopping.is_set() else 'failed', finished=stamp(), output=clean, message=message)
        finally:
            self.store.event('lab.operation', 'Lab operation finished; review its operation record', lab_id=next(j['lab_id'] for j in self.store.state['operations'] if j['id'] == ident))
            try:
                if not self.stopping.is_set(): self.discovery.refresh()
            finally:
                with self.store.lock: self.active.discard(ident)
