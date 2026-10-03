"""Read-only status probes for the dashboard (standard library only).

Every probe is bounded, changes nothing, and never prompts: privileged questions use
`sudo -n`, and a refused sudo is reported as "Needs authentication", not as absence.
A probe that cannot answer says so ("Unavailable"); only positive evidence such as a
missing command or data folder is reported as "Not installed". The manager's settings
file is read for its UI_BIND, UI_PORT and CAPTURE_PROVIDER keys only.
"""
from concurrent.futures import ThreadPoolExecutor
import grp
import json
import os
from pathlib import Path
import pwd
import shutil
import stat
import time
from urllib.request import ProxyHandler, build_opener

from . import core

NOT_CHECKED = 'Not checked'
CHECKING = 'Checking'
READY = 'Ready'
NEEDS_AUTH = 'Needs authentication'
ATTENTION = 'Attention'
FAILED = 'Failed'
UNAVAILABLE = 'Unavailable'
NOT_INSTALLED = 'Not installed'
NOT_SELECTED = 'Not set up'

DATA_DIR = Path('/srv/containerlab-node-manager/data')
HELPER_DIR = Path('/usr/local/sbin')


class Result:
    def __init__(self, key, label, state=NOT_CHECKED, summary='', detail='', value=None):
        self.key = key
        self.label = label
        self.state = state
        self.summary = summary
        self.detail = detail
        self.value = value      # a structured fact for the header (the running manager version)

    def __repr__(self):
        return f'Result({self.key!r}, {self.state!r}, {self.summary!r})'


def probe_sudo(ctx):
    """Whether sudo would run without a password prompt right now (cached or NOPASSWD)."""
    code, text = core.run_capture(['sudo', '-n', 'true'], ctx.env, ctx.source, timeout=8)
    if code == 0:
        return READY, 'credentials cached', ''
    if _sudo_refused(code, text):
        return NEEDS_AUTH, 'asks for your password when needed', ''
    return UNAVAILABLE, 'sudo not available', ''


COMPONENTS = [
    ('prereqs', 'Prerequisites'),
    ('manager', 'Manager'),
    ('access', 'VM connection account'),
    ('engineer', 'VS Code access'),
    ('git', 'Git'),
    ('capture', 'Browser Wireshark'),
    ('lazydocker', 'lazydocker'),
]


def placeholder():
    return {key: Result(key, label) for key, label in COMPONENTS + EXTRA}


def env_settings(source, keys=('UI_BIND', 'UI_PORT', 'CAPTURE_PROVIDER')):
    """Only the named keys of clab-backup-ui/.env (the file also holds a session token)."""
    path = Path(source) / 'clab-backup-ui' / '.env'
    values = {}
    try:
        if path.is_symlink() or path.stat().st_size > 65536:
            return values
        for line in path.read_text(errors='replace').splitlines():
            name, sep, value = line.partition('=')
            if sep and name.strip() in keys:
                values[name.strip()] = value.strip().strip('"\'')
    except OSError:
        pass
    return values


def manager_address(source):
    settings = env_settings(source)
    host = settings.get('UI_BIND') or '0.0.0.0'
    try:
        port = int(settings.get('UI_PORT') or 8081)
    except ValueError:
        port = 8081
    if host in ('0.0.0.0', '', 'localhost'):
        host = '127.0.0.1'
    elif host == '::':
        host = '[::1]'
    elif ':' in host and not host.startswith('['):
        host = f'[{host}]'
    return f'http://{host}:{port}/', port


def http_version(url, timeout=3):
    opener = build_opener(ProxyHandler({}))
    with opener.open(url + 'api/state', timeout=timeout) as response:
        data = response.read(8 * 1024 * 1024 + 1)
    if len(data) > 8 * 1024 * 1024:
        return None
    body = json.loads(data)
    return body.get('version') if isinstance(body, dict) else None


def _sudo_refused(code, text):
    return code is not None and code != 0 and bool(core.AUTH_SIGNATURE.search(text or ''))


def probe_prereqs(ctx):
    missing = [name for name in ('docker', 'containerlab', 'git') if not shutil.which(name, path=ctx.path)]
    if not Path('/usr/sbin/sshd').exists():
        missing.append('openssh-server')
    if 'docker' not in missing:
        code, _ = core.run_capture(['docker', 'compose', 'version'], ctx.env, ctx.source, timeout=8)
        if code != 0:
            missing.append('docker compose plugin')
    if not missing:
        return READY, 'Docker, Compose, containerlab, Git and SSH found', ''
    if {'docker', 'containerlab'} <= set(missing):
        return NOT_INSTALLED, 'Missing: ' + ', '.join(missing), 'Install/update installs them.'
    return ATTENTION, 'Missing: ' + ', '.join(missing), 'Install/update installs the missing ones.'


def probe_manager(ctx):
    url, port = manager_address(ctx.source)
    try:
        running = http_version(url)
    except (OSError, ValueError):
        running = None
    if running == ctx.version:
        return READY, f'Running {running} on port {port}', f'VM-local address {url} (verified on this VM only).', running
    if running:
        return ATTENTION, f'Running {running}; this checkout is {ctx.version}', 'Install/update rebuilds it from this checkout.', running
    try:
        exists = DATA_DIR.exists()
    except OSError:
        exists = False
    if not exists and not shutil.which('docker', path=ctx.path):
        return NOT_INSTALLED, 'No manager data folder and no Docker', ''
    code, text = core.run_capture(['sudo', '-n', 'docker', '--host', 'unix:///var/run/docker.sock', 'compose', '-f',
                                   str(Path(ctx.source) / 'clab-backup-ui/compose.yml'), 'ps', '--status', 'running',
                                   '--quiet', 'backup-ui'], ctx.env, ctx.source, timeout=10)
    if _sudo_refused(code, text):
        return NEEDS_AUTH, f'No answer on port {port}; container state needs sudo', 'Refresh after authenticating, or run Check installation.'
    if code == 0 and text.strip():
        return ATTENTION, f'Container running but no HTTP answer on port {port}', 'It may still be starting; refresh shortly.'
    if code == 0:
        if exists:
            return ATTENTION, 'Installed but not running', 'Install/update recreates it; data is retained.'
        return NOT_INSTALLED, 'Not installed', ''
    return UNAVAILABLE, 'Could not determine the container state', (text or '')[-200:]


def probe_access(ctx):
    try:
        pwd.getpwnam('clab-discovery')
    except KeyError:
        return NOT_INSTALLED, 'clab-discovery account not created yet', 'Install/update creates it and asks for its password.'
    if not (HELPER_DIR / 'clab-manager-gateway').exists():
        return ATTENTION, 'Account exists but its gateway helper is missing', 'Install/update reinstalls the helpers.'
    code, text = core.run_capture(['sudo', '-n', 'passwd', '-S', 'clab-discovery'], ctx.env, ctx.source, timeout=8)
    if _sudo_refused(code, text):
        return NEEDS_AUTH, 'Account and helpers present; password state needs sudo', ''
    fields = text.split()
    if code == 0 and len(fields) > 1:
        if fields[1] == 'P':
            return READY, 'Account, helpers and password ready', ''
        return ATTENTION, 'No usable password yet', 'Install/update asks you to create it.'
    return UNAVAILABLE, 'Could not read the password state', ''


def probe_engineer(ctx):
    user = ctx.env.get('USER', '')
    try:
        members = {name for name in ('docker', 'clab_admins') if user in grp.getgrnam(name).gr_mem}
    except KeyError:
        members = set()
        try:
            grp.getgrnam('docker')
            members |= {'docker'} if user in grp.getgrnam('docker').gr_mem else set()
        except KeyError:
            pass
    clab = shutil.which('containerlab', path=ctx.path)
    suid = False
    if clab:
        try:
            mode = os.stat(clab).st_mode
            suid = bool(mode & stat.S_ISUID)
        except OSError:
            pass
    if members >= {'docker', 'clab_admins'} and suid:
        session = set()
        for gid in os.getgroups():
            try:
                session.add(grp.getgrgid(gid).gr_name)
            except KeyError:
                pass
        if not {'docker', 'clab_admins'} <= session:
            return ATTENTION, f'Set up for {user}; reconnect SSH to use the new groups', 'Then restart the VS Code server on the host.'
        return READY, f'docker and clab_admins groups and containerlab access for {user}', ''
    if not members and not suid:
        return NOT_SELECTED, f'Not set up for {user}', 'VS Code/Containerlab access sets it up.'
    return ATTENTION, 'Partly set up: ' + (', '.join(sorted(members)) or 'no groups') + ('' if suid else '; containerlab not SUID'), ''


def probe_git(ctx):
    if not (HELPER_DIR / 'clab-manager-git').exists():
        return NOT_SELECTED, 'Git helper not installed yet', 'Install/update installs it; Git setup registers a checkout.'
    code, text = core.run_capture(['sudo', '-n', 'bash', str(Path(ctx.source) / 'deploy/setup-git.sh'), '--list'],
                                  ctx.env, ctx.source, timeout=15)
    if _sudo_refused(code, text):
        return NEEDS_AUTH, 'Helper installed; registrations need sudo to read', ''
    if code == 0:
        try:
            value = json.loads(text.strip().splitlines()[-1])
            repositories = value.get('result', {}).get('repositories', [])
        except (ValueError, IndexError, AttributeError):
            return UNAVAILABLE, 'Unexpected answer from the Git helper', ''
        if repositories:
            labels = ', '.join(str(item.get('label') or item.get('path') or '?')[:40] for item in repositories[:3])
            more = '' if len(repositories) <= 3 else f' and {len(repositories) - 3} more'
            return READY, f'{len(repositories)} registered checkout(s): {labels}{more}', ''
        return ATTENTION, 'No checkout registered yet', 'Git setup / repair registers one.'
    return UNAVAILABLE, 'Could not list Git registrations', ''


def probe_capture(ctx):
    provider = env_settings(ctx.source).get('CAPTURE_PROVIDER', '')
    if provider == 'disabled':
        return ATTENTION, 'Disabled in clab-backup-ui/.env', 'Browser Wireshark stack re-enables it.'
    try:
        opener = build_opener(ProxyHandler({}))
        with opener.open('http://127.0.0.1:5001/version', timeout=3) as response:
            edgeshark = response.status == 200
    except (OSError, ValueError):
        edgeshark = False
    if edgeshark and provider:
        return READY, f'Edgeshark answering on 127.0.0.1:5001 ({provider})', ''
    if edgeshark:
        return ATTENTION, 'Edgeshark answers but the manager settings do not name it', 'Browser Wireshark stack reconfigures it.'
    if provider:
        return ATTENTION, 'Configured but Edgeshark does not answer on 127.0.0.1:5001', 'Browser Wireshark stack restarts it.'
    return NOT_INSTALLED, 'Not set up yet', 'Install/update sets it up.'


def probe_lazydocker(ctx):
    path = Path(ctx.env.get('HOME', '')) / '.local' / 'bin' / 'lazydocker'
    if not path.exists():
        return NOT_INSTALLED, 'Not installed (optional)', ''
    code, text = core.run_capture([str(path), '--version'], ctx.env, ctx.source, timeout=5)
    version = next((line.split(':', 1)[1].strip() for line in text.splitlines() if line.lower().startswith('version')), '')
    return (READY, f'Installed {version}'.strip(), '') if code == 0 else (ATTENTION, 'Installed but does not run', '')


PROBES = {'prereqs': probe_prereqs, 'manager': probe_manager, 'access': probe_access, 'engineer': probe_engineer,
          'git': probe_git, 'capture': probe_capture, 'lazydocker': probe_lazydocker, 'sudo': probe_sudo}
EXTRA = [('sudo', 'Administrator')]


class Context:
    def __init__(self, env, source, version):
        self.env = env
        self.source = str(source)
        self.version = version
        self.path = env.get('PATH')


def run_all(ctx, keys=None, on_result=None):
    """Run the probes concurrently (each bounded); returns {key: Result} and the check time."""
    labels = dict(COMPONENTS + EXTRA)
    keys = list(keys or labels)

    def one(key):
        value = None
        try:
            answer = PROBES[key](ctx)
            state, summary, detail = answer[:3]
            value = answer[3] if len(answer) > 3 else None
        except Exception as error:  # a probe bug must not look like an absent component
            state, summary, detail = UNAVAILABLE, 'Check could not run', type(error).__name__
        result = Result(key, labels[key], state, summary, detail, value)
        if on_result:
            on_result(result)
        return result

    with ThreadPoolExecutor(max_workers=len(keys)) as pool:
        results = list(pool.map(one, keys))
    return {result.key: result for result in results}, time.time()
