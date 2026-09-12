"""Bounded, metadata-only development diagnostics. Never serialize raw state."""
from collections import deque
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
import platform
import re
import threading
import time
import uuid

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field

from . import __version__
from .lab_operations import remote

# The capabilities probe runs up to nine containerlab --help commands of 15 s
# each on the VM; the normal UI allows 180 s. Keep the panel responsive but
# do not report a slow VM as a broken one.
PROBE_TIMEOUT = 90


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def numeric_version(value):
    return value if isinstance(value, str) and re.fullmatch(r'\d+\.\d+\.\d+', value) else 'unknown'


def failure_hint(exc):
    # Inspect diagnostics only to classify them; raw SSH errors can contain secrets.
    text = str(exc).lower()
    for fragment, code, message in (
        ('fingerprint', 'host-trust', 'Refresh discovery and verify the VM host fingerprint.'),
        ('configure and enable', 'vm-disabled', 'Configure and enable the VM connection.'),
        # Paramiko reports a rejected VM password as "Authentication failed."
        ('authentication failed', 'authentication', 'Check the saved VM password and restricted account setup.'),
        ('password', 'authentication', 'Check the saved VM password and restricted account setup.'),
        ('sudo permission', 'gateway-permission', 'Run sudo bash deploy/start-manager.sh --enable-operations from matching source on the VM.'),
        ('not using the operations gateway', 'gateway-account', 'Use the clab-discovery account in VM connection settings.'),
        ('outside the trusted', 'untrusted-folder', 'Add this project root using --lab-root during operations setup.'),
        ('no longer exists', 'missing-folder', 'Select an existing folder on the VM.'),
        ('project directory', 'not-directory', 'Select a directory rather than a topology file.'),
        ('symlink', 'symlink-folder', 'Select the real folder inside a trusted lab root.'),
        ('interrupted', 'timeout', 'The helper timed out. Run bash deploy/check-install.sh on the VM.'),
    ):
        if fragment in text:
            return {'code': code, 'message': message}
    return {'code': 'helper-unavailable', 'message': 'Check VM connection settings, then run bash deploy/check-install.sh on the VM.'}


class ProbeRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    path: str = Field(default='', max_length=4096)


class Diagnostics:
    def __init__(self, store, discovery, operations):
        self.store, self.discovery, self.operations = store, discovery, operations
        self.started = time.monotonic()
        self.requests = deque(maxlen=200)
        self.lock = threading.Lock()
        self.probe_lock = threading.Lock()

    def snapshot(self):
        public = self.discovery.public()
        packages = {}
        for name in ('fastapi', 'paramiko', 'ansible-core', 'cryptography'):
            try: packages[name] = version(name)
            except PackageNotFoundError: packages[name] = 'not installed'
        with self.store.lock:
            state = self.store.state
            host = state.get('host', {})
            counts = {name: len(state.get(name, [])) for name in ('labs', 'jobs', 'operations', 'git_jobs')}
            connection = {'configured': bool(host), 'enabled': bool(host.get('enabled')),
                          'password_saved': bool(host.get('password')), 'fingerprint_saved': bool(host.get('fingerprint'))}
        connection.update({key: bool(public.get(key)) for key in ('connected', 'checking', 'file_import_supported')})
        connection['discovery_helper_version'] = numeric_version(public.get('helper_version'))
        with self.lock: requests = list(reversed(self.requests))
        return {'schema': 1, 'generated_at': timestamp(), 'manager_version': __version__,
                'python_version': platform.python_version(), 'packages': packages,
                'uptime_seconds': int(time.monotonic() - self.started), 'vm': connection,
                'audit_log_available': not self.store.event_error,
                'saved_counts': counts, 'requests': requests,
                'scope': 'Metadata only. Latest 200 API requests except successful state/debug polling; resets on restart. No credentials, paths, file contents or raw logs.'}

    def install(self, app):
        @app.middleware('http')
        async def requests(request, call_next):
            if not request.url.path.startswith('/api/'):
                return await call_next(request)
            started = time.monotonic()
            request_id = uuid.uuid4().hex[:12]
            status = 500
            try:
                response = await call_next(request)
                status = response.status_code
                response.headers['X-Request-ID'] = request_id
                return response
            finally:
                route = getattr(request.scope.get('route'), 'path', '/api/unknown')
                if status >= 400 or route not in ('/api/state', '/api/debug', '/api/debug/probe'):
                    with self.lock:
                        self.requests.append({'time': timestamp(), 'id': request_id,
                            'method': request.method if request.method in ('GET','POST','PUT','PATCH','DELETE','OPTIONS','HEAD') else 'OTHER',
                            'route': route, 'status': status,
                            'duration_ms': round((time.monotonic() - started) * 1000)})

        @app.get('/api/debug')
        def snapshot():
            return self.snapshot()

        @app.post('/api/debug/probe')
        def probe(data: ProbeRequest):
            if not self.probe_lock.acquire(blocking=False):
                raise HTTPException(409, 'A diagnostic check is already running. Wait for it to finish.')
            try:
                host = self.operations.host()
                checks = []
                # Browse independently, even when capability checks fail. These
                # requests never read topology contents or run lifecycle commands.
                for mode in ('browse', 'capabilities'):
                    started = time.monotonic()
                    item = {'check': mode}
                    try:
                        req = {'mode': mode}
                        if mode == 'browse': req['path'] = data.path
                        result = remote(host, req, timeout=PROBE_TIMEOUT)
                        if mode == 'browse':
                            entries = result.get('entries')
                            if not isinstance(entries, list): raise ValueError('Invalid helper response')
                            item.update(status='pass', entry_count=len(entries))
                        else:
                            helper_version = numeric_version(result.get('version'))
                            if result.get('protocol') != 'clab-manager-operations-v1': raise ValueError('Invalid helper response')
                            item.update(status='pass' if helper_version == __version__ else 'warning',
                                        helper_version=helper_version,
                                        message='Helper matches the manager.' if helper_version == __version__ else 'Install helpers and manager from the same source release.')
                    except Exception as exc:
                        item.update(status='fail', **failure_hint(exc))
                    item['duration_ms'] = round((time.monotonic() - started) * 1000)
                    checks.append(item)
                if host.get('revision') != self.operations.host().get('revision'):
                    raise HTTPException(409, 'VM settings changed during the check. Run it again.')
                return {'generated_at': timestamp(), 'checks': checks}
            finally:
                self.probe_lock.release()
