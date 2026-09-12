"""Single-VM, read-only containerlab discovery and persistent lab registration."""
import base64
import copy
import hashlib
import ipaddress
import json
import re
import socket
import threading
import time
import uuid
from datetime import datetime, timezone

import paramiko
from fastapi import File, Form, HTTPException, UploadFile
from pydantic import BaseModel, ConfigDict, Field

from .inventory import ALIASES, PLATFORMS, address, literal, port, read_data

COMMANDS = {'helper': 'sudo -n /usr/local/sbin/clab-manager-inspect',
            'direct': 'containerlab inspect --all --format json'}
INTERVAL = 30
MAX_AGE = 90
MAX_OUTPUT = 16 * 1024 * 1024
# The installed helper allows 25 s for containerlab inspect plus 18 s of file
# reads; leave headroom for SSH connection setup and a loaded VM.
INSPECT_DEADLINE = 60
REFRESH_WAIT = INSPECT_DEADLINE + 15


def stamp():
    return datetime.now(timezone.utc).isoformat()


def identifier(value, label):
    value = literal(value, label, 120)
    if not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]*', value):
        raise ValueError(label + ' must be a literal name using letters, numbers, _, . or -')
    return value


def parse_definition(raw, deployed_name=''):
    data = read_data(raw)
    name = identifier(data.get('name', ''), 'Topology name')
    deployed_name = identifier(deployed_name or name, 'Deployed lab name')
    body = data.get('topology')
    if not isinstance(body, dict) or not isinstance(body.get('nodes'), dict) or not body['nodes']:
        raise ValueError('The lab YAML must contain topology.nodes')
    if len(body['nodes']) > 2000:
        raise ValueError('Upload no more than 2000 nodes')
    defaults = body.get('defaults') or {}
    kinds = body.get('kinds') or {}
    if not isinstance(defaults, dict) or not isinstance(kinds, dict):
        raise ValueError('Topology defaults and kinds must be mappings')
    prefix = data.get('prefix', 'clab')
    if prefix != '': prefix = identifier(prefix, 'Container prefix')
    nodes = []
    for short, settings in body['nodes'].items():
        short = identifier(short, 'Node name')
        settings = settings or {}
        if not isinstance(settings, dict): raise ValueError('Node settings must be mappings')
        kind = literal(settings.get('kind', defaults.get('kind', '')), 'Node kind', 120)
        kind_settings = kinds.get(kind) or {}
        if not isinstance(kind_settings, dict): raise ValueError('Kind settings must be mappings')
        effective = {**defaults, **kind_settings, **settings}
        # Containerlab's empty prefix uses the bare node name.
        full = f'{prefix}-{deployed_name}-{short}' if prefix else short
        fixed = effective.get('mgmt-ipv4') or effective.get('mgmt-ipv6')
        endpoint = str(ipaddress.ip_interface(fixed).ip) if fixed else full
        platform = ALIASES.get(kind, '')
        nodes.append(dict(name=full, short_name=short, definition_node=short,
                          address=address(endpoint), port=22, platform=platform, kind=kind,
                          enabled=bool(platform), profile_id='', username='', password='',
                          enable_password='', groups=[], endpoint_mode='auto',
                          discovered=False, runtime_state='unknown'))
    return dict(name=name, deployed_name=deployed_name, prefix=prefix, nodes=nodes)


def parse_inspect(raw):
    if len(raw) > MAX_OUTPUT: raise ValueError('Inspection output exceeded 16 MiB')
    value = json.loads(raw)
    groups = {}
    if isinstance(value, list):
        iterable = [(None, value)]
    elif isinstance(value, dict):
        iterable = value.items()
    else:
        raise ValueError('Expected containerlab JSON object or array')
    total = 0
    for group, rows in iterable:
        if not isinstance(rows, list): raise ValueError('Unsupported containerlab JSON schema')
        for row in rows:
            if not isinstance(row, dict): raise ValueError('Invalid container entry')
            name = identifier(row.get('lab_name') or group or '', 'Discovered lab name')
            if group and name != group: raise ValueError('Conflicting lab identity in inspection')
            container = literal(row.get('name', ''), 'Container name', 253)
            if not container: raise ValueError('Missing container name')
            ip = row.get('ipv4_address') or row.get('ipv6_address') or ''
            if ip in ('N/A', '-'): ip = ''
            ip = str(ipaddress.ip_interface(ip).ip) if ip else ''
            entry = dict(name=container, address=ip,
                         state=literal(row.get('state', 'unknown'), 'Container state', 40),
                         kind=literal(row.get('kind', ''), 'Container kind', 120))
            bucket = groups.setdefault(name, [])
            if any(n['name'] == container for n in bucket): raise ValueError('Duplicate container identity')
            bucket.append(entry)
            total += 1
            if total > 10000: raise ValueError('Too many discovered nodes')
    return groups


class Inspection(dict):
    """Normal lab mapping with optional versioned helper file bundles."""
    def __init__(self, labs, sources=None, raw=None, reader="inspect-only"):
        super().__init__(labs)
        self.sources = sources
        self.raw = raw
        self.reader = reader
        self.helper_version = None


def parse_snapshot(raw):
    from .vm_files import PROTOCOL
    if len(raw) > MAX_OUTPUT: raise ValueError('Inspection response exceeds limit')
    value = json.loads(raw)
    if isinstance(value, dict) and value.get('protocol') == PROTOCOL:
        labs = parse_inspect(json.dumps(value.get('inspect')).encode())
        sources = value.get('sources')
        if not isinstance(sources, dict) or not set(sources).issubset(labs):
            raise ValueError('Invalid file discovery response')
        snapshot = Inspection(labs, sources, value['inspect'], 'helper')
        version = value.get('helper_version')
        snapshot.helper_version = version if isinstance(version, str) and re.fullmatch(r'[0-9.]{1,24}', version) else None
        return snapshot
    return Inspection(parse_inspect(raw), raw=value)


def discovery_fresh(state):
    host = state.get('host', {})
    info = state.get('discovery', {})
    return bool(host.get('enabled') and info.get('ok') and
                time.time() - info.get('checked_epoch', 0) < MAX_AGE)


def lab_status(state, lab):
    if not lab.get('deployment_name'):
        return dict(status='Unlinked', message='Import a lab YAML or link this workspace to discovery.')
    info = state.get('discovery', {})
    common = dict(last_success=info.get('last_success'), checked_at=info.get('checked_at'))
    if not discovery_fresh(state):
        return dict(**common, status='Unknown', message=info.get('error') or 'Configure the VM connection and refresh discovery.')
    rows = info.get('labs', {}).get(lab['deployment_name'], [])
    if not rows: return dict(**common, status='Not deployed', message='No matching containers found on the VM.')
    running = sum(n['state'] == 'running' for n in rows)
    expected = len(lab['nodes'])
    all_saved = all(n.get('discovered') and n.get('runtime_state') == 'running' for n in lab['nodes'])
    status = 'Running' if running == len(rows) and all_saved else 'Partially running' if running else 'Stopped'
    return dict(**common, status=status, message=f'{running}/{len(rows)} discovered containers running; {expected} saved nodes. Container state does not verify NOS readiness.')


def automatic_ready(state, lab):
    if not lab.get('deployment_name'): return True
    return discovery_fresh(state) and lab_status(state, lab)['status'] == 'Running'


def node_available(state, lab, node):
    if not lab.get('deployment_name'): return True
    if not discovery_fresh(state): return False
    return bool(node.get('discovered') and node.get('runtime_state') == 'running' and
                (node.get('endpoint_mode') == 'manual' or node.get('discovered_address')))


def reconcile(state):
    groups = state.get('discovery', {}).get('labs', {})
    for lab in state['labs']:
        if not lab.get('deployment_name'): continue
        rows = {n['name']: n for n in groups.get(lab['deployment_name'], [])}
        for node in lab['nodes']:
            short = node.get('definition_node') or node.get('short_name')
            prefix = lab.get('container_prefix', 'clab')
            expected = f'{prefix}-{lab["deployment_name"]}-{short}' if prefix and short else short
            found = rows.get(expected) if expected else rows.get(node['name'])
            node.update(discovered=bool(found), runtime_state=found['state'] if found else 'absent',
                        discovered_address=found['address'] if found else '')
            if found and found['address'] and node.get('endpoint_mode') == 'auto':
                node.update(address=found['address'], port=22)


def vm_password(host):
    if host.get('auth') != 'password' or not host.get('password'):
        raise ValueError('VM password setup required. Run sudo bash deploy/setup-discovery.sh on the VM, then save its password in VM connection.')
    return host['password']


class PinnedHostKey(paramiko.MissingHostKeyPolicy):
    def __init__(self, expected):
        self.expected = expected
        self.fingerprint = ''

    def missing_host_key(self, client, hostname, key):
        self.fingerprint = 'SHA256:' + base64.b64encode(hashlib.sha256(key.asbytes()).digest()).decode().rstrip('=')
        if self.expected and self.expected != self.fingerprint:
            raise ValueError('VM SSH host key changed. Verify the VM and reset the saved fingerprint in connection settings.')
        client.get_host_keys().add(hostname, key.get_name(), key)


def inspect_host(host, stopping=None):
    password = vm_password(host)
    client = paramiko.SSHClient()
    policy = PinnedHostKey(host.get('fingerprint', ''))
    client.set_missing_host_key_policy(policy)
    opts = dict(hostname=host['address'], port=host['port'], username=host['username'],
                timeout=8, auth_timeout=8, banner_timeout=8, allow_agent=False, look_for_keys=False)
    opts['password'] = password
    try:
        client.connect(**opts)
        transport = client.get_transport()
        channel = transport.open_session(timeout=8)
        channel.settimeout(8)
        channel.exec_command(COMMANDS[host['command_mode']])
        channel.settimeout(.2)
        output = bytearray(); size = 0; deadline = time.monotonic() + INSPECT_DEADLINE; eof = False
        while True:
            if time.monotonic() > deadline or (stopping and stopping.is_set()):
                raise ValueError('VM inspection timed out or was interrupted')
            if channel.recv_stderr_ready(): size += len(channel.recv_stderr(65536))
            if not eof:
                try: chunk = channel.recv(65536)
                except socket.timeout: continue
                eof = not chunk
                output.extend(chunk); size += len(chunk)
            if size > MAX_OUTPUT: raise ValueError('VM inspection output exceeded 16 MiB')
            # Exit status is channel metadata, not end-of-output: OpenSSH can send
            # it while the helper's final stdout bytes are still in its pipe. Wait
            # for stream EOF before accepting the status, as the operations
            # transport does.
            if eof and not channel.recv_stderr_ready() and channel.exit_status_ready(): break
            if eof: time.sleep(.03)
        if channel.recv_exit_status() != 0:
            raise ValueError('Inspection command failed. Verify containerlab and the discovery account/helper permissions on the VM.')
        snapshot = parse_snapshot(bytes(output))
        if host['command_mode'] == 'direct' and snapshot.sources is None:
            from .vm_files import collect_sftp
            envelope = collect_sftp(client, snapshot.raw, deadline)
            snapshot = parse_snapshot(json.dumps(envelope).encode())
            snapshot.reader = 'sftp'
        return snapshot, policy.fingerprint
    finally:
        client.close()


class Discovery:
    def __init__(self, store):
        self.store = store
        self.lock = threading.Lock()
        self.stopping = threading.Event()
        self.wake = threading.Event()
        self.thread = None
        self.sources = {}
        self.import_previews = {}
        # A previous process's snapshot is not evidence of current deployment.
        with store.lock:
            if store.state.get('discovery'):
                store.state['discovery'].update(ok=False, error='Waiting for a fresh VM inspection.')

    def start(self):
        self.thread = threading.Thread(target=self.loop, daemon=True)
        self.thread.start()

    def close(self):
        self.stopping.set(); self.wake.set()
        if self.thread: self.thread.join(timeout=2)

    def loop(self):
        while not self.stopping.is_set():
            self.refresh()
            self.wake.wait(INTERVAL); self.wake.clear()

    def refresh(self, wait=False):
        if not self.lock.acquire(timeout=REFRESH_WAIT if wait else 0): return self.public()
        try:
            with self.store.lock:
                if self.store.reset_pending: return self.public()
                host = copy.deepcopy(self.store.state.get('host', {}))
            if not host.get('enabled'): return self.public()
            error = ''; labs = None; fingerprint = ''
            try:
                labs, fingerprint = inspect_host(host, self.stopping)
            except paramiko.AuthenticationException:
                error = 'VM SSH authentication failed. Check the discovery account credentials.'
            except ValueError as exc:
                # Only controlled error messages; never return remote output or JSON decoder excerpts.
                error = str(exc) if type(exc) is ValueError and str(exc).startswith(('VM ', 'Inspection ')) else 'Invalid containerlab inspection response. Check the installed version and helper.'
            except Exception:
                error = 'Cannot reach the VM SSH service. Check its address, port, SSH service, and connection settings.'
            with self.store.lock:
                if self.store.state.get('host', {}).get('revision') != host.get('revision'): return self.public()
                previous = self.store.state.get('discovery', {})
                info = {**previous, 'ok': not error, 'error': error, 'checked_at': stamp(), 'checked_epoch': time.time()}
                if not error:
                    info.update(labs=dict(labs), last_success=info['checked_at'], file_reader=getattr(labs, 'reader', 'inspect-only'), helper_version=getattr(labs, 'helper_version', None))
                    self.store.state['host']['fingerprint'] = fingerprint
                self.store.state['discovery'] = info
                self.sources = {}
                if not error:
                    self.update_sources(getattr(labs, 'sources', None))
                    reconcile(self.store.state)
                    file_errors = info.get('file_errors', {})
                    if previous.get('file_errors', {}) != file_errors:
                        self.store.event('discovery.files',
                            f'{len(file_errors)} deployed labs need file correction or manual import' if file_errors else 'VM file discovery recovered',
                            level='warning' if file_errors else 'info')
                else:
                    for lab in self.store.state['labs']:
                        if lab.get('vm_source'): lab['vm_source'].update(can_sync=False, status='VM unavailable')
                if previous.get('ok') != info['ok'] or previous.get('error') != error:
                    self.store.event('discovery.status', error or 'VM inspection succeeded', level='warning' if error else 'info')
                self.store.save()
            result = self.public()
            result['checking'] = False
            return result
        finally:
            self.lock.release()

    def update_sources(self, sources):
        from .vm_files import decode_bundle, metadata, prepare_lab, source_reports, FileImportError
        state = self.store.state
        state['discovery']['file_import_supported'] = sources is not None
        state['discovery']['file_errors'] = {}
        state['discovery']['file_reports'] = {}
        state['discovery']['pending_imports'] = {}
        for lab in state['labs']:
            if lab.get('vm_source'):
                lab['vm_source'].update(can_sync=False, status='Files unavailable')
        if sources is None: return
        for name, source in sources.items():
            if name in state.get('ignored_labs', []):
                try: self.sources[name] = decode_bundle(source)
                except (ValueError, TypeError, AttributeError, KeyError): pass
                continue
            state['discovery']['file_reports'][name] = source_reports(source)
            lab = next((l for l in state['labs'] if l.get('deployment_name') == name), None)
            # Reuse a unique legacy inventory workspace, but never overwrite it
            # automatically. Its first file import remains an explicit sync.
            if lab is None:
                legacy = [l for l in state['labs'] if not l.get('deployment_name') and l['name'] == name]
                if len(legacy) > 1:
                    state['discovery']['file_errors'][name] = 'Several saved workspaces match. Link the intended workspace first.'
                    continue
                if legacy:
                    state['discovery']['file_errors'][name] = 'A saved inventory workspace matches. Use Link deployment there, then Sync from VM.'
                    continue
            try:
                bundle = decode_bundle(source)
                # Validate before advertising an available sync. Preparation is
                # side-effect-free; a bad optional file cannot half-update a lab.
                candidate = prepare_lab(bundle, name, lab)
            except (ValueError, TypeError, AttributeError, KeyError, RecursionError) as exc:
                message = str(exc) if isinstance(exc, FileImportError) else 'VM file transfer was invalid. Check Discovery file details or upload manually.'
                state['discovery']['file_errors'][name] = message
                if lab:
                    lab.setdefault('vm_source', {}).update(status='Files unavailable', can_sync=False, message=message)
                continue
            self.sources[name] = bundle
            if lab is None:
                state['discovery']['pending_imports'][name] = dict(nodes=len(candidate['nodes']), files=list(bundle['files']))
            else:
                previous = lab.get('vm_source', {})
                lab['vm_source'] = {**previous, **metadata(bundle), 'can_sync': True,
                    'status': 'Up to date' if previous.get('synced_digest') == bundle['digest'] else 'Updates available'}

    def public(self):
        with self.store.lock:
            state = self.store.state; host = state.get('host', {}); info = state.get('discovery', {})
            public_host = {k: host.get(k) for k in ('address','port','username','auth','command_mode','enabled','fingerprint')}
            linked = {l.get('deployment_name') for l in state['labs']}
            return dict(host=public_host if host else None, configured=bool(host),
                        connected=discovery_fresh(state), checking=self.lock.locked(),
                        checked_at=info.get('checked_at'), last_success=info.get('last_success'),
                        error=info.get('error', ''), interval=INTERVAL,
                        file_import_supported=bool(info.get('file_import_supported')),
                        file_reader=info.get('file_reader', 'inspect-only'),
                        helper_version=info.get('helper_version'),
                        helper_update_required=bool(discovery_fresh(state) and host.get('command_mode') == 'helper' and not info.get('file_import_supported')),
                        pending_imports=info.get('pending_imports', {}) if discovery_fresh(state) else {},
                        file_reports=info.get('file_reports', {}),
                        file_errors=info.get('file_errors', {}),
                        ignored_labs=state.get('ignored_labs', []),
                        discovered=[dict(name=name, nodes=len(nodes), running=sum(n['state']=='running' for n in nodes),
                                         imported=name in linked, excluded=name in state.get('ignored_labs', [])) for name,nodes in info.get('labs', {}).items()])

    def install(self, app, public_lab):
        def idle(lab_id=None):
            from .lab_operations import operation_busy
            if operation_busy(self.store.state,lab_id): raise HTTPException(409, 'Wait for the lab operation to finish.')

        class HostSettings(BaseModel):
            model_config = ConfigDict(extra='forbid')
            address: str = Field(max_length=253)
            port: int = Field(default=22, ge=1, le=65535)
            username: str = Field(min_length=1,max_length=128)
            auth: str = 'password'
            password: str = Field(default='',max_length=4096)
            command_mode: str = 'helper'
            enabled: bool = True
            reset_fingerprint: bool = False

        @app.get('/api/discovery')
        def status(): return self.public()

        @app.put('/api/host')
        def save_host(data: HostSettings):
            try:
                if data.auth != 'password': raise ValueError('VM connections require password authentication')
                if data.command_mode not in COMMANDS: raise ValueError('Choose a valid inspection mode')
                endpoint = address(data.address.strip()); username = literal(data.username.strip(), 'VM username',128)
                if not username: raise ValueError('Enter a VM username')
                with self.store.lock:
                    idle()
                    old = self.store.state.get('host', {})
                    same = (old.get('address'),old.get('port'),old.get('username'),old.get('auth')) == (endpoint,data.port,username,data.auth)
                    host = dict(address=endpoint,port=data.port,username=username,auth=data.auth,
                                enabled=data.enabled,command_mode=data.command_mode,revision=uuid.uuid4().hex)
                    host['password'] = data.password or (old.get('password','') if same else '')
                    if not host['password']: raise ValueError('Enter the VM password')
                    host['fingerprint'] = old.get('fingerprint','') if (old.get('address'),old.get('port')) == (endpoint,data.port) and not data.reset_fingerprint else ''
                    from .git_progress import pending_progress, host_identity
                    if pending_progress(self.store.state) and host_identity(old) != host_identity(host):
                        raise HTTPException(409, 'Finish pending Git saves or choose Keep snapshot only before changing the VM identity.')
                    self.sources = {}
                    self.store.state['host'] = host
                    self.store.state['discovery'] = dict(ok=False,error='Waiting for a fresh VM inspection.')
                    self.store.save(); self.store.event('discovery.configure','VM connection settings saved; automatic discovery '+('enabled' if data.enabled else 'paused'))
                self.wake.set()
                return self.public()
            except ValueError as exc: raise HTTPException(400,str(exc))

        @app.post('/api/discovery/refresh')
        def refresh(): return self.refresh(wait=True)

        class AllowImport(BaseModel):
            model_config = ConfigDict(extra='forbid')
            name: str = Field(min_length=1, max_length=120)

        def import_candidate(name):
            from .vm_files import prepare_lab, FileImportError
            state = self.store.state
            if not discovery_fresh(state):
                raise HTTPException(409, 'A fresh VM connection is required. Refresh discovery and try again.')
            if any(l.get('deployment_name') == name for l in state['labs']):
                raise HTTPException(409, 'This deployment already has a saved workspace. Open it or use Sync from VM.')
            if any(l['name'] == name for l in state['labs']):
                raise HTTPException(409, 'A saved workspace has this name. Link its deployment and use Sync from VM.')
            info = state.get('discovery', {})
            bundle = self.sources.get(name)
            if not bundle or name not in info.get('labs', {}):
                message = info.get('file_errors', {}).get(name)
                raise HTTPException(409, message or ('The VM helper needs updating. Run sudo bash deploy/start-manager.sh from the current source on the VM.'
                    if not info.get('file_import_supported') else 'The deployed files are unavailable. Check Discovery file details or upload manually.'))
            try: candidate = prepare_lab(bundle, name)
            except (ValueError, TypeError, AttributeError, KeyError, RecursionError) as exc:
                raise HTTPException(409, str(exc) if isinstance(exc, FileImportError) else 'The VM file bundle is invalid. Upload manually or correct the files.')
            return candidate, bundle

        @app.post('/api/discovery/import-preview')
        def preview_import(data: AllowImport):
            self.refresh(wait=True)
            with self.store.lock:
                candidate, bundle = import_candidate(data.name)
                state = self.store.state
                # Previews contain no secrets and do not save a workspace. The
                # token binds confirmation to these files, VM and exclusion state.
                now = time.monotonic()
                self.import_previews = {k:v for k,v in self.import_previews.items() if v['expires'] > now}
                if len(self.import_previews) >= 100: self.import_previews.pop(next(iter(self.import_previews)))
                token = uuid.uuid4().hex
                excluded = data.name in state.get('ignored_labs', [])
                self.import_previews[token] = dict(name=data.name, digest=bundle['digest'],
                    revision=state['host']['revision'], excluded=excluded, expires=now + 300)
                return dict(name=data.name, token=token, nodes=len(candidate['nodes']),
                            links=len(candidate['drawing'].get('links', [])),
                            files=bundle['manifest'], missing=candidate['vm_source']['missing'],
                            warnings=candidate['vm_source'].get('warnings', []), excluded=excluded)

        class ConfirmImport(AllowImport):
            token: str = Field(min_length=32, max_length=32)

        @app.post('/api/discovery/import')
        def import_discovered(data: ConfirmImport):
            self.refresh(wait=True)
            with self.store.lock:
                idle()
                state = self.store.state
                preview = self.import_previews.get(data.token)
                if not preview or preview['name'] != data.name or preview['expires'] < time.monotonic():
                    raise HTTPException(409, 'Import confirmation expired. Preview the lab again.')
                candidate, bundle = import_candidate(data.name)
                if (preview['revision'] != state['host']['revision'] or preview['digest'] != bundle['digest'] or
                        preview['excluded'] != (data.name in state.get('ignored_labs', []))):
                    raise HTTPException(409, 'The VM, lab files or import setting changed. Preview the lab again before confirming.')
                ignored = state.get('ignored_labs', [])
                state['labs'].append(candidate)
                state['ignored_labs'] = [n for n in ignored if n != data.name]
                reconcile(state)
                try: self.store.save()
                except OSError:
                    state['labs'].remove(candidate); state['ignored_labs'] = ignored
                    raise HTTPException(500, 'Could not save the imported lab. Your confirmation can be retried.')
                self.import_previews.pop(data.token, None)
                state['discovery'].get('pending_imports', {}).pop(data.name, None)
                self.store.event('lab.auto_import', 'Imported VM lab files after user confirmation', lab_id=candidate['id'])
                return public_lab(candidate)

        @app.post('/api/discovery/forget-exclusion')
        def forget_exclusion(data: AllowImport):
            with self.store.lock:
                previous = self.store.state.get('ignored_labs', [])
                self.store.state['ignored_labs'] = [name for name in previous if name != data.name]
                try: self.store.save()
                except OSError:
                    self.store.state['ignored_labs'] = previous
                    raise HTTPException(500, 'Could not save the change. Exclusion retained.')
                self.import_previews = {k:v for k,v in self.import_previews.items() if v['name'] != data.name}
            self.wake.set()
            return {'cleared': data.name}

        @app.post('/api/discovery/allow-import')
        def allow_import(data: AllowImport):
            # Old clients cannot bypass confirmation or silently clear exclusions.
            raise HTTPException(409, 'Import again now requires a preview and confirmation. Refresh the browser and choose Import again.')

        @app.post('/api/labs/{lab_id}/sync')
        def sync(lab_id: str):
            from .vm_files import prepare_lab
            # Fetch once more so an explicit sync never applies an older cached
            # source after the VM or its files have changed.
            self.refresh(wait=True)
            with self.store.lock:
                idle(lab_id)
                lab = self.store.lab(lab_id)
                if not lab: raise HTTPException(404, 'Lab not found')
                bundle = self.sources.get(lab.get('deployment_name'))
                if not discovery_fresh(self.store.state) or not bundle:
                    raise HTTPException(409, 'Fresh VM files are unavailable. Refresh discovery, upgrade the helper, or import manually.')
                try: candidate = prepare_lab(bundle, lab['deployment_name'], lab)
                except (ValueError, TypeError, AttributeError, KeyError, RecursionError):
                    raise HTTPException(400, 'VM files are invalid or inconsistent; the saved workspace was retained.')
                lab.clear(); lab.update(candidate)
                reconcile(self.store.state); self.store.save()
                self.store.event('lab.sync', 'Synced VM files; saved node settings and backup history retained', lab_id=lab_id)
                return public_lab(lab)

        class Binding(BaseModel):
            model_config = ConfigDict(extra='forbid')
            deployed_name: str = Field(default='',max_length=120)
            prefix: str = Field(default='clab',max_length=120)

        @app.put('/api/labs/{lab_id}/deployment')
        def bind(lab_id: str, data: Binding):
            try:
                name = identifier(data.deployed_name,'Deployed lab name') if data.deployed_name else ''
                prefix = identifier(data.prefix,'Container prefix') if data.prefix else ''
            except ValueError as exc: raise HTTPException(400,str(exc))
            with self.store.lock:
                idle(lab_id)
                lab = self.store.lab(lab_id)
                if not lab: raise HTTPException(404,'Lab not found')
                if name and any(l['id']!=lab_id and l.get('deployment_name')==name for l in self.store.state['labs']):
                    raise HTTPException(409,'That deployment is already linked to another workspace')
                self.store.state['ignored_labs'] = [n for n in self.store.state.get('ignored_labs', []) if n != name]
                lab.pop('vm_source', None)
                lab.update(deployment_name=name,container_prefix=prefix)
                # Legacy inventory endpoints stay manual until explicitly switched.
                for node in lab['nodes']: node.setdefault('endpoint_mode','manual')
                reconcile(self.store.state); self.store.save()
                return public_lab(lab)

        @app.post('/api/lab-definitions')
        async def register(definition: UploadFile=File(...), lab_id: str=Form(''),
                           deployed_name: str=Form(''), annotations: UploadFile|None=File(None)):
            from .topology import parse_drawing
            try:
                raw = await definition.read(1024*1024+1)
                parsed = parse_definition(raw,deployed_name)
                ann = await annotations.read(1024*1024+1) if annotations and annotations.filename else None
                # Store normalized topology for maps; retain original YAML only in encrypted state.
                drawing = parse_drawing(ann or b'{"nodeAnnotations":[]}',raw)
            except (ValueError,TypeError,AttributeError,RecursionError) as exc:
                raise HTTPException(400,str(exc))
            finally:
                await definition.close()
                if annotations: await annotations.close()
            with self.store.lock:
                idle(lab_id)
                lab = self.store.lab(lab_id) if lab_id else next((l for l in self.store.state['labs'] if l.get('deployment_name')==parsed['deployed_name']),None)
                if lab_id and not lab: raise HTTPException(404,'Lab not found')
                if not lab_id and lab is None:
                    legacy = [l for l in self.store.state['labs'] if not l.get('deployment_name') and l['name'] in (parsed['name'],parsed['deployed_name'])]
                    if len(legacy)>1: raise HTTPException(409,'Several saved workspaces match this name. Open the intended workspace and use Update lab YAML.')
                    if legacy: lab=legacy[0]
                if any(l is not lab and l.get('deployment_name')==parsed['deployed_name'] for l in self.store.state['labs']):
                    raise HTTPException(409,'Deployment already linked to another workspace')
                if lab is None:
                    lab = dict(id=uuid.uuid4().hex,name=parsed['name'],profiles=[],defaults={},interval=0,next_run=None,created=stamp(),nodes=[])
                    self.store.state['labs'].append(lab)
                old = {n.get('definition_node') or n.get('short_name') or n['name'].removeprefix('clab-'+lab['name']+'-'):n for n in lab['nodes']}
                for n in parsed['nodes']:
                    previous = old.get(n['definition_node'])
                    if previous:
                        # Keep identity stable: historical jobs and saved node actions use it.
                        n.update({k:copy.deepcopy(v) for k,v in previous.items() if k not in ('kind','groups','definition_node')})
                        n['endpoint_mode']=previous.get('endpoint_mode','manual')
                lab.update(nodes=parsed['nodes'],deployment_name=parsed['deployed_name'],container_prefix=parsed['prefix'],
                           definition_yaml=raw.decode('utf-8-sig'),updated=stamp(),source=definition.filename or 'lab.clab.yaml')
                self.store.state['ignored_labs'] = [n for n in self.store.state.get('ignored_labs', []) if n != parsed['deployed_name']]
                if ann or not lab.get('drawing'): lab['drawing']=drawing
                reconcile(self.store.state); self.store.save()
                self.store.event('lab.register',f'Registered lab definition with {len(lab["nodes"])} nodes',lab_id=lab['id'])
                return public_lab(lab)
