#!/usr/bin/env python3
"""Installation health report. Probe existing services; never install or repair.

Only fixed read/query operations are submitted. Normal service/SSH audit logging
and optional credential-helper cache activity may occur during these probes.
"""
import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shlex
import signal
import subprocess
import sys
import threading
import time
from urllib.error import HTTPError
from urllib.request import Request, ProxyHandler, HTTPRedirectHandler, build_opener

SOURCE = Path(__file__).resolve().parents[1]
MIB = 1024 * 1024
PATH = '/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'
STATUSES = ('PASS', 'FAIL', 'WARN', 'SKIP', 'INFO')


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def module(name):
    spec = importlib.util.spec_from_file_location(name, SOURCE / 'deploy' / (name + '.py'))
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def safe_text(value, limit=1000):
    return ''.join(c if c.isprintable() or c == '\n' else '?' for c in str(value))[:limit]


@dataclass
class Result:
    code: int = 1
    stdout: str = ''
    stderr: str = ''
    reason: str = ''

    @property
    def ok(self):
        return self.code == 0 and not self.reason


class Context:
    def __init__(self, args, owner='', privileged=False):
        self.source = SOURCE
        self.owner = owner
        self.privileged = privileged
        self.version = ''
        self.require_git = args.require_git
        self.git_remote = args.git_remote
        self.require_admin_sftp = args.require_admin_sftp
        self.require_kvm = args.require_kvm
        self.discovery_only = args.discovery_only
        self.lab_paths = args.lab_path
        self.max_folders = args.max_folders
        self.checks = []
        self.started = datetime.now(timezone.utc).isoformat()
        self.deadline = time.monotonic() + args.deadline
        self.base_url = ''
        self.container = ''
        self.host = {}
        self.trusted_helpers = {'inspect': False, 'operate': False, 'git': False}
        self.manual = [
            'From the workstation: open the manager using the VM LAN address and configured port.',
            'WinSCP: authenticate as the normal VM user, upload and download a small file; '
            'for administrative SFTP test the intended destination.',
            'Devices: verify a real login and configuration capture on the intended NOS nodes.',
            'Git: use Save progress and confirm Pushed plus the expected files on the remote. '
            'Remote-read checks cannot prove push permission or branch-rule acceptance.',
        ]

    def add(self, ident, status, title, detail, fix=''):
        if status not in STATUSES:
            raise ValueError('Invalid report status')
        self.checks.append(dict(id=safe_text(ident), status=status, title=safe_text(title),
                                detail=safe_text(detail), fix=safe_text(fix)))

    def progress(self, text):
        print(text, file=sys.stderr, flush=True)

    def run(self, args, input_text=None, timeout=15, limit=MIB, privileged=False):
        if privileged and not self.privileged:
            return Result(reason='administrator access unavailable')
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            return Result(reason='report time limit reached')
        duration = min(timeout, remaining)
        if privileged and os.geteuid() != 0:
            # Root descendants cannot all be signalled by the ordinary caller.
            # Give them their own root-owned timeout as well as our watchdog.
            args = ['sudo', '-n', '--', '/usr/bin/timeout', '--kill-after=2s',
                    str(duration) + 's', *args]
        env = {'PATH': PATH, 'HOME': os.path.expanduser('~'), 'LANG': 'C.UTF-8',
               'LC_ALL': 'C.UTF-8', 'SYSTEMD_PAGER': '', 'GIT_TERMINAL_PROMPT': '0'}
        process = None
        expired = threading.Event()

        def stop():
            if process is not None:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    pass

        def expire():
            expired.set()
            stop()

        try:
            # Keep the caller's session and controlling terminal: sudo's normal
            # timestamp is bound to that session. setsid/start_new_session would
            # make sudo -n reject an otherwise valid sudo -v authentication.
            # A separate process group still lets the watchdog stop descendants.
            process = subprocess.Popen(args, stdin=subprocess.PIPE if input_text is not None else subprocess.DEVNULL,
                                       stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                       env=env, process_group=0)
            timer = threading.Timer(duration + (2 if privileged and os.geteuid() != 0 else 0), expire)
            timer.start()
            try:
                if input_text is not None:
                    process.stdin.write(input_text.encode('utf-8'))
                    process.stdin.close()
                raw = process.stdout.read(limit + 1)
                if len(raw) > limit:
                    stop()
                    return Result(reason='response exceeded size limit')
                code = process.wait()
                return Result(code, raw.decode('utf-8', errors='replace'),
                              reason='command timed out' if expired.is_set() else '')
            finally:
                timer.cancel()
                stop()
                process.wait()
                process.stdout.close()
                if process.stdin and not process.stdin.closed:
                    process.stdin.close()
        except OSError:
            return Result(reason='command unavailable or could not run')

    def http(self, path, payload=None, limit=8*MIB):
        if not self.base_url:
            return Result(reason='manager HTTP unavailable'), None
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            return Result(reason='report time limit reached'), None
        data = None if payload is None else json.dumps(payload).encode()
        request = Request(self.base_url + path, data=data,
                          headers={'Content-Type': 'application/json'} if data else {})
        opener = build_opener(ProxyHandler({}), NoRedirect())
        until = min(self.deadline, time.monotonic() + 20)
        try:
            with opener.open(request, timeout=max(.001, until - time.monotonic())) as response:
                chunks = []
                size = 0
                while size <= limit:
                    left = until - time.monotonic()
                    if left <= 0:
                        return Result(reason='HTTP request time limit reached'), None
                    # urllib's HTTPResponse keeps its socket inside the buffered
                    # reader, even when Connection: close detaches it from the
                    # connection. Bound each read by the same request deadline.
                    sock = getattr(getattr(getattr(response, 'fp', None), 'raw', None), '_sock', None)
                    if sock is not None:
                        sock.settimeout(max(.001, left))
                    chunk = response.read1(min(65536, limit + 1 - size))
                    if time.monotonic() >= until:
                        return Result(reason='HTTP request time limit reached'), None
                    if not chunk:
                        break
                    chunks.append(chunk)
                    size += len(chunk)
                raw = b''.join(chunks)
            if len(raw) > limit:
                return Result(reason='HTTP response exceeded size limit'), None
            value = json.loads(raw)
            return Result(0), value
        except HTTPError as error:
            # Do not include error bodies: host messages and proxy URLs can
            # include private paths, contents or configuration values.
            return Result(error.code, reason='HTTP ' + str(error.code)), None
        except (OSError, ValueError):
            return Result(reason='HTTP unavailable, timed out or invalid JSON'), None

    def repair(self, script, *args):
        return shlex.join(['sudo', 'bash', str(self.source / 'deploy' / script), *args])


def parse_json(result):
    if not result.ok:
        return None
    try:
        return json.loads(result.stdout)
    except (ValueError, TypeError):
        return None


def version_matches(ctx, value):
    return bool(ctx.version) and value == ctx.version


def check_source(ctx):
    try:
        ctx.version = module('verify-release').verify(ctx.source)
        ctx.add('source', 'PASS', 'Source release', 'Matching source metadata: ' + ctx.version)
    except (OSError, ValueError):
        ctx.add('source', 'FAIL', 'Source release', 'Source files are missing or contain mixed release versions.',
                'Obtain a complete matching source checkout; run python3 deploy/verify-release.py.')


def check_docker(ctx):
    docker = ['docker', '--host', 'unix:///var/run/docker.sock']
    result = ctx.run([*docker, 'info', '--format', '{{json .ServerVersion}}'], privileged=True)
    if not result.ok:
        ctx.add('docker', 'FAIL', 'Docker daemon', 'The local rootful Docker daemon could not be queried.',
                'Check sudo systemctl status docker; rerun the installer if Docker is missing.')
        ctx.add('manager', 'SKIP', 'Manager container and HTTP', 'Docker access is required for these checks.')
        return
    ctx.add('docker', 'PASS', 'Docker daemon', 'Local rootful Docker responds on /var/run/docker.sock.')
    compose = [*docker, 'compose', '-f', str(ctx.source / 'clab-backup-ui/compose.yml')]
    result = ctx.run([*compose, 'version'], privileged=True)
    if not result.ok:
        ctx.add('compose', 'FAIL', 'Docker Compose', 'The Compose plugin is unavailable.', 'Rerun bash deploy/install.sh.')
        return
    ctx.add('compose', 'PASS', 'Docker Compose', 'Compose plugin is available.')
    result = ctx.run([*compose, 'ps', '--all', '--quiet', 'backup-ui'], privileged=True)
    ids = result.stdout.strip().splitlines() if result.ok else []
    if len(ids) != 1 or not re.fullmatch(r'[0-9a-f]{12,64}', ids[0]):
        ctx.add('manager', 'FAIL', 'Manager container', 'Exactly one Compose backup-ui container was not found.',
                'Run bash deploy/install.sh from this checkout. Review any earlier failed installation phase.')
        return
    ctx.container = ids[0]
    fmt = '{"state":{{json .State}},"mounts":{{json .Mounts}},"command":{{json .Config.Cmd}},' \
          '"network":{{json .HostConfig.NetworkMode}},"restart":{{json .HostConfig.RestartPolicy.Name}}}'
    details = parse_json(ctx.run([*docker, 'inspect', '--format', fmt, ctx.container], privileged=True))
    if not isinstance(details, dict):
        ctx.add('manager', 'FAIL', 'Manager container', 'Container inspection returned no valid metadata.')
        return
    if not isinstance(details.get('state'), dict) or details['state'].get('Running') is not True:
        ctx.add('manager', 'FAIL', 'Manager container', 'The manager container is not running.',
                'Inspect sudo docker compose -f clab-backup-ui/compose.yml logs --tail=80 backup-ui locally.')
        return
    ctx.add('manager', 'PASS', 'Manager container', 'The backup-ui container is running.')
    ctx.add('restart', 'PASS' if details.get('restart') in ('unless-stopped', 'always') else 'WARN',
            'Restart policy', 'Automatic restart configured.' if details.get('restart') in ('unless-stopped', 'always')
            else 'Manager may not restart after the VM reboots.', 'Retain the supplied Compose restart policy.')
    ctx.add('manager-network', 'PASS' if details.get('network') == 'host' else 'FAIL', 'Manager network',
            'Host networking is configured.' if details.get('network') == 'host' else 'Expected host networking is missing.',
            'Use the standalone Compose settings; loopback VM connections require host networking.')
    result = ctx.run([*docker, 'exec', ctx.container, 'python', '-c',
                      'from app import __version__; print(__version__)'], privileged=True)
    ctx.add('manager-version', 'PASS' if result.ok and version_matches(ctx, result.stdout.strip()) else 'FAIL',
            'Running application version', 'Matches this source release.' if result.ok and version_matches(ctx, result.stdout.strip())
            else 'Running application version does not match this source checkout.', 'Rebuild using bash deploy/install.sh.')
    check_storage(ctx, docker, details.get('mounts'))
    try:
        url = module('install-manager').health_url(details.get('command'))
        ctx.base_url = url.removesuffix('/api/state')
    except (ValueError, TypeError):
        ctx.add('http', 'FAIL', 'Manager HTTP', 'Could not determine its actual configured bind address and port.')
        return
    result, state = ctx.http('/api/state')
    if not result.ok or not isinstance(state, dict) or not version_matches(ctx, state.get('version')):
        ctx.add('http', 'FAIL', 'Manager HTTP', 'HTTP/version readiness failed: ' + (result.reason or 'unexpected version/response'),
                'Check the running image, UI_BIND/UI_PORT and local service logs.')
        ctx.base_url = ''
        return
    ctx.add('http', 'PASS', 'Manager HTTP', 'Version response passed at ' + ctx.base_url + '. Workstation access is a separate check.')


STORAGE_PROBE = '''import json, os
from pathlib import Path
from cryptography.fernet import Fernet
p=Path(os.environ.get('DATA_DIR','/data'))
r={'path':str(p),'uid':os.geteuid(),'writable':os.access(p,os.W_OK|os.X_OK),
   'key':(p/'state.key').is_file(),'state':(p/'state.enc').is_file(),'decryptable':False}
try:
    with (p/'state.key').open('rb') as f: key=f.read(4097)
    with (p/'state.enc').open('rb') as f: data=f.read(64*1024*1024+1)
    if len(data)<=64*1024*1024:
        state=json.loads(Fernet(key).decrypt(data))
        r['decryptable']=isinstance(state,dict) and isinstance(state.get('labs'),list)
except Exception: pass
print(json.dumps(r))
'''


def check_storage(ctx, docker, mounts):
    value = parse_json(ctx.run([*docker, 'exec', ctx.container, 'python', '-c', STORAGE_PROBE], privileged=True))
    if not isinstance(value, dict):
        ctx.add('storage', 'FAIL', 'Persistent data', 'Could not inspect storage as the container user.',
                'Check the /data mount and UID 10001 permissions. Preserve state.enc and state.key.')
        return
    selected = [m for m in mounts if isinstance(m, dict) and m.get('Destination') == value.get('path')] if isinstance(mounts, list) else []
    mounted = len(selected) == 1 and selected[0].get('Type') in ('bind', 'volume') and selected[0].get('RW') is True
    requirements = {'persistent writable mount': mounted, 'container UID 10001': value.get('uid') == 10001,
                    'data directory write access': value.get('writable') is True,
                    'saved state.key': value.get('key') is True, 'saved state.enc': value.get('state') is True,
                    'state decryption': value.get('decryptable') is True}
    missing = [name for name, passed in requirements.items() if not passed]
    ready = not missing
    ctx.add('storage', 'PASS' if ready else 'FAIL', 'Persistent data and encryption key',
            'Persistent writable mount, UID 10001 and decryptable saved state verified; no data was written.' if ready
            else 'Not verified: ' + '; '.join(missing) + '.',
            'Inspect the existing data mount and ownership. Retain both state.enc and state.key; do not reset or delete data.')


def check_containerlab(ctx):
    result = ctx.run(['containerlab', 'version'], privileged=True)
    if not result.ok:
        ctx.add('containerlab', 'FAIL', 'Containerlab', 'Containerlab could not report its version.', 'Rerun bash deploy/install.sh.')
        return
    ctx.add('containerlab', 'PASS', 'Containerlab', 'Installed CLI responds.')
    data = parse_json(ctx.run(['containerlab', 'inspect', '--all', '--format', 'json'], privileged=True, limit=8*MIB))
    if isinstance(data, dict) and all(isinstance(rows, list) for rows in data.values()):
        rows = [row for group in data.values() for row in group]
    elif isinstance(data, list):
        rows = data
    else:
        ctx.add('labs', 'FAIL', 'Deployed lab inspection', 'Containerlab did not return a valid lab inventory.')
        return
    if any(not isinstance(row, dict) for row in rows):
        ctx.add('labs', 'FAIL', 'Deployed lab inspection', 'Unexpected node inventory structure.')
        return
    stopped = sum(str(row.get('state', '')).lower() != 'running' for row in rows)
    ctx.add('labs', 'WARN' if stopped else 'PASS', 'Deployed lab inspection',
            f'{len(rows)} node(s) discovered; {stopped} not reported running. '
            + ('No deployed labs is normal before the first deployment.' if not rows else 'A running container does not prove NOS login/backup readiness.'),
            'Review intended stopped labs or device boot failures; no lab was started by this check.' if stopped else '')


def helper_request(ctx, helper, request=None, delegated=True, timeout=30, limit=16*MIB):
    if ctx.trusted_helpers.get(helper) is not True:
        return Result(reason='installed helper files are missing or unsafe')
    if delegated:
        original = {'inspect': 'sudo -n /usr/local/sbin/clab-manager-inspect',
                    'operate': 'clab-manager-operations', 'git': 'clab-manager-git'}[helper]
        args = ['sudo', '-n', '-H', '-u', 'clab-discovery', '--', '/usr/bin/env', '-i', 'PATH=' + PATH,
                'HOME=/home/clab-discovery', 'SSH_ORIGINAL_COMMAND=' + original,
                '/usr/local/sbin/clab-manager-gateway']
    else:
        args = ['/usr/local/sbin/clab-manager-' + helper]
    return ctx.run(args, input_text=None if request is None else json.dumps(request) + '\n',
                   privileged=True, timeout=timeout, limit=limit)


FILE_PROBE = '''import hashlib,json,os,pathlib,stat,sys
out=[]
for name in sys.argv[1:]:
    p=pathlib.Path(name)
    r={'path':name,'safe':False,'mode':0,'sha256':''}
    try:
        m=p.lstat()
        safe=stat.S_ISREG(m.st_mode) and m.st_uid==0 and not m.st_mode&0o022
        for parent in p.parents:
            pm=parent.lstat()
            safe=safe and stat.S_ISDIR(pm.st_mode) and pm.st_uid==0 and not pm.st_mode&0o022
        r.update(safe=safe,mode=stat.S_IMODE(m.st_mode))
        if safe and m.st_size<=1024*1024:
            r['sha256']=hashlib.sha256(p.read_bytes()).hexdigest()
    except OSError: pass
    out.append(r)
print(json.dumps(out))
'''


def check_helper_files(ctx):
    gateway = '/usr/local/sbin/clab-manager-gateway'
    specifications = {
        gateway: ('deploy/clab-manager-gateway', 0o755),
        '/usr/local/sbin/clab-manager-inspect': (None, 0o755),
        '/usr/local/lib/clab-manager/clab_manager_files.py': ('clab-backup-ui/app/host_files.py', 0o644),
        '/etc/sudoers.d/clab-manager-discovery': (None, 0o440),
        '/usr/local/sbin/clab-manager-operate': (None, 0o755),
        '/usr/local/lib/clab-manager/host_operations.py': ('clab-backup-ui/app/host_operations.py', 0o644),
        '/etc/clab-manager/operations.json': (None, 0o600),
        '/usr/local/sbin/clab-manager-git': (None, 0o755),
        '/usr/local/lib/clab-manager/host_git.py': ('clab-backup-ui/app/host_git.py', 0o644),
        '/etc/sudoers.d/clab-manager-git': (None, 0o440),
    }
    payload = parse_json(ctx.run(['/usr/bin/python3', '-I', '-c', FILE_PROBE, *specifications], privileged=True))
    records = {r['path']: r for r in payload if isinstance(r, dict) and isinstance(r.get('path'), str)} if isinstance(payload, list) else {}
    passed = {}
    for name, (source, mode) in specifications.items():
        record = records.get(name, {})
        good = record.get('safe') is True and record.get('mode') == mode
        if source:
            try:
                good = good and record.get('sha256') == hashlib.sha256((ctx.source / source).read_bytes()).hexdigest()
            except OSError:
                good = False
        passed[name] = good
    groups = {
        'inspect': [gateway, '/usr/local/sbin/clab-manager-inspect', '/usr/local/lib/clab-manager/clab_manager_files.py', '/etc/sudoers.d/clab-manager-discovery'],
        'operate': [gateway, '/usr/local/sbin/clab-manager-operate', '/usr/local/lib/clab-manager/host_operations.py', '/etc/clab-manager/operations.json', '/etc/sudoers.d/clab-manager-discovery'],
        'git': [gateway, '/usr/local/sbin/clab-manager-git', '/usr/local/lib/clab-manager/host_git.py', '/etc/sudoers.d/clab-manager-git'],
    }
    for name, paths in groups.items():
        good = all(passed[p] for p in paths)
        ctx.trusted_helpers[name] = good
        severity = 'INFO' if name == 'operate' and ctx.discovery_only else 'WARN' if name == 'git' and not ctx.require_git else 'FAIL'
        ctx.add('helper-files-' + name, 'PASS' if good else severity, name + ' helper installation',
                'Root ownership, permissions, regular files and source content match.' if good
                else 'Missing, unsafe or stale helper files; privileged helper execution will be skipped: ' + ', '.join(p for p in paths if not passed[p]),
                ctx.repair('setup-git.sh', '--refresh') if name == 'git' else ctx.repair('setup-operations.sh') if name == 'operate'
                else ctx.repair('start-manager.sh', '--enable-operations'))
    sudoers = ctx.run(['visudo', '-c'], privileged=True)
    ctx.add('sudoers', 'PASS' if sudoers.ok else 'FAIL', 'Sudoers syntax',
            'Sudoers validation passed.' if sudoers.ok else 'Sudoers validation failed or could not run.',
            'Run sudo visudo -c and correct its reported error before retrying.')


def check_helpers(ctx):
    repair = ctx.repair('setup-operations.sh')
    data = parse_json(helper_request(ctx, 'inspect'))
    ready = isinstance(data, dict) and data.get('protocol') == 'clab-manager-files-v1' \
        and version_matches(ctx, data.get('helper_version')) and isinstance(data.get('inspect'), (dict, list)) \
        and isinstance(data.get('sources'), dict)
    ctx.add('discovery-helper', 'PASS' if ready else 'FAIL', 'Discovery helper through restricted account',
            'Gateway and passwordless helper execution succeeded as clab-discovery; protocol/version are valid.' if ready
            else 'Discovery failed through the restricted account or returned an incompatible response.',
            ctx.repair('start-manager.sh', '--enable-operations'))
    response = parse_json(helper_request(ctx, 'operate', {'mode': 'capabilities'}))
    caps = response.get('result') if isinstance(response, dict) else None
    ready = isinstance(caps, dict) and caps.get('protocol') == 'clab-manager-operations-v1' \
        and version_matches(ctx, caps.get('version')) and isinstance(caps.get('actions'), dict)
    if not ready:
        root = parse_json(helper_request(ctx, 'operate', {'mode': 'capabilities'}, delegated=False))
        root_ok = isinstance(root, dict) and isinstance(root.get('result'), dict) and root['result'].get('protocol') == 'clab-manager-operations-v1'
        detail = 'Helper responds as root but not correctly through clab-discovery; check gateway/sudoers.' if root_ok \
            else 'Operations helper is missing, unavailable or incompatible with this source.'
        ctx.add('operations-helper', 'INFO' if ctx.discovery_only else 'FAIL', 'Operations helper through restricted account',
                detail + (' Operations are optional in discovery-only mode.' if ctx.discovery_only else ''), repair)
        return
    ctx.add('operations-helper', 'PASS', 'Operations helper through restricted account',
            'Actual gateway/sudo execution as clab-discovery returned matching capabilities.')
    absent = [name for name in ('deploy', 'destroy', 'inspect') if not isinstance(caps['actions'].get(name), dict)
              or caps['actions'][name].get('available') is not True]
    ctx.add('operations-actions', 'WARN' if ctx.discovery_only and absent else 'FAIL' if absent else 'PASS',
            'Core lab commands', 'Unavailable: ' + ', '.join(absent) if absent else 'Deploy, destroy and inspect are available.',
            'Check the installed Containerlab version and configured binary; rerun ' + repair if absent else '')
    ctx.add('downloads', 'INFO', 'Online lab downloads',
            'Enabled by host configuration.' if caps.get('network') else 'Disabled intentionally by default; this does not break folder browsing.')


def check_manager_routes(ctx):
    if not ctx.base_url:
        ctx.add('vm-connection', 'SKIP', 'Saved VM connection', 'Manager HTTP is unavailable; saved-connection tests could not run.')
        return
    result, discovery = ctx.http('/api/discovery')
    if not result.ok or not isinstance(discovery, dict):
        ctx.add('vm-connection', 'FAIL', 'Saved VM connection', 'Manager discovery status is unavailable or malformed.')
        return
    host = discovery.get('host') or {}
    if not isinstance(host, dict):
        ctx.add('vm-connection', 'FAIL', 'Saved VM connection', 'Manager discovery settings are malformed.')
        return
    ctx.host = host
    configured = discovery.get('configured') is True and host.get('enabled') is True and bool(host.get('fingerprint'))
    if not configured:
        ctx.add('vm-connection', 'WARN', 'Saved VM connection', 'Enabled VM connection and saved host fingerprint are not ready.',
                'In VM connection, enter the clab-discovery password, Save and test, then verify the saved host fingerprint.')
        ctx.add('http-browse', 'SKIP', 'Topology browser over saved SSH connection', 'Complete VM connection setup before this check can run.')
        return
    ctx.add('vm-connection', 'PASS', 'Saved VM connection settings', 'An enabled connection and host fingerprint are saved; no password was read or printed.')
    local = host.get('address') in ('localhost', '127.0.0.1', '::1')
    if not local:
        addresses = parse_json(ctx.run(['ip', '-j', 'address'], limit=MIB))
        locals_ = {item.get('local') for nic in addresses if isinstance(nic, dict)
                   for item in nic.get('addr_info', []) if isinstance(item, dict)} if isinstance(addresses, list) else set()
        local = host.get('address') in locals_
    if not local:
        ctx.add('vm-target', 'WARN', 'Saved VM target',
                'Saved SSH address was not confirmed as this VM. Local host checks may describe a different machine.',
                'For standalone setup use 127.0.0.1, or verify that the configured hostname resolves to this VM.')
    if host.get('auth') != 'password' or host.get('command_mode') != 'helper' or host.get('username') != 'clab-discovery':
        ctx.add('vm-mode', 'WARN', 'Saved VM account/mode', 'Saved settings differ from the standalone password/helper setup.',
                'Use clab-discovery, password authentication and Installed discovery and file helper for this installation.')
    if discovery.get('connected') is not True:
        ctx.add('discovery-status', 'WARN', 'Last discovery result', 'The manager last reported discovery disconnected.',
                'Refresh discovery and inspect VM connection settings. The live operations check below is separate.')
    else:
        ctx.add('discovery-status', 'PASS', 'Last discovery result', 'The manager reports discovery connected.')
    if ctx.trusted_helpers.get('operate') is not True:
        ctx.add('http-browse', 'INFO' if ctx.discovery_only else 'SKIP', 'Topology browser over saved SSH connection',
                'Repair the local operations helper files before submitting SSH requests.', ctx.repair('setup-operations.sh'))
        return
    result, roots = ctx.http('/api/operations/browse', {'path': ''})
    if not result.ok or not isinstance(roots, dict) or not isinstance(roots.get('entries'), list):
        ctx.add('http-browse', 'INFO' if ctx.discovery_only else 'FAIL', 'Topology browser over saved SSH connection',
                'The uncached browser request failed: ' + (result.reason or 'invalid response'),
                ctx.repair('setup-operations.sh') + '; then close and reopen the failed folder. Verify VM password/fingerprint if local helper checks pass.')
        return
    ctx.add('http-browse', 'PASS', 'Topology browser over saved SSH connection',
            'An uncached request reached the operations helper using the manager saved SSH connection.')
    queue = list(ctx.lab_paths)
    for entry in roots['entries']:
        if isinstance(entry, dict) and entry.get('directory') is True and valid_path(entry.get('path')):
            queue.append(entry['path'])
    seen = set()
    while queue and len(seen) < ctx.max_folders:
        path = queue.pop(0)
        if path in seen:
            continue
        seen.add(path)
        result, value = ctx.http('/api/operations/browse', {'path': path}, limit=3*MIB)
        valid = result.ok and isinstance(value, dict) and value.get('path') == path and isinstance(value.get('entries'), list)
        ctx.add('folder-' + str(len(seen)), 'PASS' if valid else 'FAIL', 'Browse folder: ' + path,
                f"{len(value['entries'])} visible entry/entries; empty folders are valid." if valid
                else 'The actual folder request failed: ' + (result.reason or 'invalid response'),
                'Confirm the folder exists within a trusted root, has no symlink components, and is accessible. '
                'If the helper checks failed, first run ' + ctx.repair('setup-operations.sh') if not valid else '')
        if valid:
            entries = value['entries']
            if len(entries) >= 500:
                ctx.add('folder-limit-' + str(len(seen)), 'WARN', 'Folder listing limit',
                        'A listing reached the helper 500-entry limit; additional contents may be unverified.')
            for entry in entries:
                child = entry.get('path') if isinstance(entry, dict) else None
                if isinstance(entry, dict) and entry.get('directory') is True and valid_path(child) \
                        and Path(child).parent == Path(path) and child not in seen:
                    queue.append(child)
    if any(path not in seen for path in queue):
        ctx.add('folder-budget', 'WARN', 'Folder coverage', f'Stopped after {ctx.max_folders} folders; more folders remain unchecked.',
                'Rerun with --lab-path /absolute/problem/folder or increase --max-folders.')
    if not seen:
        ctx.add('folders', 'WARN', 'Trusted lab folders', 'No valid trusted roots were returned.', ctx.repair('setup-operations.sh'))


def check_git_route(ctx):
    if not ctx.base_url or not ctx.host.get('enabled') or not ctx.host.get('fingerprint'):
        ctx.add('git-http', 'SKIP', 'Git registry through saved SSH connection', 'A working manager and saved VM connection are required.')
        return
    if ctx.trusted_helpers.get('git') is not True:
        ctx.add('git-http', 'SKIP' if ctx.require_git else 'INFO', 'Git registry through saved SSH connection',
                'Local Git helper files are missing or unverified; the SSH request was skipped.')
        return
    result, repositories = ctx.http('/api/git/repositories')
    if result.ok and isinstance(repositories, dict) and isinstance(repositories.get('repositories'), list) \
            and repositories.get('protocol') == 'clab-manager-git-v1' and version_matches(ctx, repositories.get('version')):
        ctx.add('git-http', 'PASS', 'Git registry through saved SSH connection',
                f"{len(repositories['repositories'])} registration(s) listed; no checkout was changed.")
    else:
        ctx.add('git-http', 'FAIL' if ctx.require_git else 'WARN', 'Git registry through saved SSH connection',
                'Git registry could not be listed through the manager.',
                'Run bash deploy/install.sh --git as the ordinary checkout owner.')


def valid_path(path):
    return isinstance(path, str) and len(path) <= 4096 and path.startswith('/') \
        and '..' not in Path(path).parts and not any(ord(c) < 32 or ord(c) == 127 for c in path)


def summarize(ctx):
    counts = {status: sum(check['status'] == status for check in ctx.checks) for status in STATUSES}
    code = 1 if counts['FAIL'] else 2 if counts['WARN'] or counts['SKIP'] else 0
    return dict(schema='clab-manager-health-v1', source_version=ctx.version, started=ctx.started,
                overall='FAILURES FOUND' if code == 1 else 'NEEDS ATTENTION' if code == 2 else 'AUTOMATED CHECKS PASSED',
                exit_code=code, counts=counts, checks=ctx.checks, manual_checks=ctx.manual)


def render(report):
    lines = ['Containerlab Node Manager - installation health report',
             '=' * 62, report['overall'],
             ' | '.join(f'{key}: {count}' for key, count in report['counts'].items()),
             'Source: ' + (report['source_version'] or 'unknown'), '']
    for check in report['checks']:
        lines += [f"[{check['status']}] {check['title']}", '  ' + check['detail']]
        if check['fix'] and check['status'] in ('FAIL', 'WARN', 'SKIP'):
            lines.append('  Next: ' + check['fix'])
    lines += ['', 'MANUAL VERIFICATION STILL REQUIRED']
    lines += ['  - ' + value for value in report['manual_checks']]
    lines += ['', report['overall'] + f" (exit {report['exit_code']})",
              'This report did not install packages, change configuration, start labs or push Git commits.']
    return '\n'.join(lines)


def arguments(argv=None):
    parser = argparse.ArgumentParser(description='Read-only VM installation checks with a clear report and repair guidance.')
    parser.add_argument('--json', action='store_true', help='Print a structured report instead of text')
    parser.add_argument('--owner', default='', help='Normal VM account, needed when root has no SUDO_USER')
    parser.add_argument('--lab-path', action='append', default=[], help='Prioritize a particular absolute lab folder; repeatable')
    parser.add_argument('--max-folders', type=int, default=20, help='Maximum folders to browse (default 20, maximum 500)')
    parser.add_argument('--deadline', type=int, default=300, help='Overall command budget in seconds (30-1800; default 300)')
    parser.add_argument('--require-git', action='store_true', help='Missing Git setup is a failure')
    parser.add_argument('--git-remote', action='store_true', help='Also test Git remote branch reads as its owner; never push')
    parser.add_argument('--require-admin-sftp', action='store_true', help='Require the optional administrative WinSCP sudo rule')
    parser.add_argument('--require-kvm', action='store_true', help='Require /dev/kvm for VM-backed NOS images')
    parser.add_argument('--discovery-only', action='store_true', help='Operations disabled intentionally; do not require deployment features')
    args = parser.parse_args(argv)
    if not 1 <= args.max_folders <= 500 or not 30 <= args.deadline <= 1800:
        parser.error('Use --max-folders 1-500 and --deadline 30-1800.')
    if any(not valid_path(path) for path in args.lab_path):
        parser.error('--lab-path requires an absolute folder without traversal or control characters.')
    return args


def main(argv=None):
    args = arguments(argv)
    if sys.platform != 'linux':
        print('Run bash deploy/check-install.sh inside the Ubuntu VM.', file=sys.stderr)
        return 1
    import pwd
    owner = args.owner or (os.environ.get('SUDO_USER', '') if os.geteuid() == 0 else pwd.getpwuid(os.getuid()).pw_name)
    if owner:
        try:
            account = pwd.getpwnam(owner)
            if account.pw_uid == 0 or owner == 'clab-discovery':
                owner = ''
        except KeyError:
            owner = ''
    privileged = os.geteuid() == 0
    if not privileged:
        try:
            privileged = subprocess.run(['sudo', '-n', 'true'], stdout=subprocess.DEVNULL,
                                        stderr=subprocess.DEVNULL, timeout=15).returncode == 0
            if not privileged and sys.stdin.isatty():
                print('Administrator access is needed to inspect host services and permissions.', file=sys.stderr)
                privileged = subprocess.run(['sudo', '-v']).returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            pass
    ctx = Context(args, owner, privileged)
    # Exercise the same subprocess path used by the checks before claiming that
    # administrator inspection is available. A successful interactive sudo probe
    # alone says nothing about authentication in a detached child session.
    privileged = privileged and ctx.run(['/usr/bin/true'], privileged=True, timeout=5).ok
    ctx.privileged = privileged
    ctx.add('privileges', 'PASS' if privileged else 'FAIL', 'Administrator inspection access',
            'The health-check command runner can execute administrator queries.' if privileged else
            'Administrator queries could not run through the health-check command runner; service health has not been established.',
            'Rerun sudo bash deploy/check-install.sh --owner YOUR_VM_USER with the same check options, or approve sudo when prompted.')
    if not owner:
        ctx.add('owner', 'WARN', 'Normal VM account', 'Account-specific SSH/SFTP checks need a normal account.',
                'Run without sudo as your ordinary account, or supply --owner YOUR_VM_USER.')
    groups = [('Source release', check_source), ('Ubuntu, clock and SSH/SFTP', lambda c: module('check_host').check_host(c)),
              ('Docker, manager and persistent storage', check_docker), ('Containerlab', check_containerlab),
              ('Installed helper files and sudoers', check_helper_files), ('Restricted helper execution', check_helpers),
              ('Manager SSH and topology folders', check_manager_routes), ('Git helper over saved SSH', check_git_route),
              ('Registered Git checkouts', lambda c: module('check_git').check_git(c))]
    for title, fn in groups:
        if time.monotonic() >= ctx.deadline:
            ctx.add('deadline', 'SKIP', 'Remaining checks', 'Overall report time budget expired.',
                    'Resolve slow/unreachable services or rerun with a larger --deadline.')
            break
        if not ctx.privileged and title not in ('Source release', 'Ubuntu, clock and SSH/SFTP'):
            ctx.add('privilege-skip-' + str(len(ctx.checks)), 'SKIP', title,
                    'Administrator inspection access is unavailable; this is not evidence of a broken or missing service.',
                    'Resolve the Administrator inspection access failure and rerun the report.')
            continue
        ctx.progress('Checking ' + title + '...')
        try:
            fn(ctx)
        except KeyboardInterrupt:
            ctx.add('interrupted', 'SKIP', 'Remaining checks', 'Check cancelled before all checks completed.')
            break
        except Exception:
            # Never print unexpected exception text or command output from a
            # credential-bearing source. A failed check must not hide the rest.
            ctx.add('check-error-' + str(len(ctx.checks)), 'FAIL', title,
                    'This check could not complete; no successful result is assumed.',
                    'Verify a complete source checkout and rerun this check.')
    report = summarize(ctx)
    print(json.dumps(report, indent=2) if args.json else render(report))
    return report['exit_code']


if __name__ == '__main__':
    sys.exit(main())
