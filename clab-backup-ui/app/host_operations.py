"""Installed host operations service. Structured stdin, fixed argv, no shell.

Stdlib only. Deployment is privileged and restricted to explicitly trusted roots.
Topology hooks and mounts retain Containerlab semantics; this is not a sandbox.
"""
import hashlib
import json
import os
from pathlib import Path
import queue
import re
import signal
import stat
import subprocess
import sys
import threading
import time
import uuid
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

PROTOCOL = 'clab-manager-operations-v1'
VERSION = '1.15.0'
LIMIT = 1024 * 1024
LIFECYCLE = ('deploy', 'redeploy', 'destroy', 'apply', 'start', 'stop', 'restart', 'save', 'inspect')
ENV = {'PATH': '/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin', 'HOME': '/root',
       'GIT_TERMINAL_PROMPT': '0', 'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': '/dev/null', 'NO_COLOR': '1'}


def identity(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]{0,119}', value):
        raise ValueError('Choose a literal lab/project name.')
    return value


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def capture(argv, cwd='/', timeout=15):
    # JSON inspection must not be contaminated by Containerlab's stderr log lines.
    process = subprocess.Popen(argv, cwd=cwd, env=ENV, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    timer = threading.Timer(timeout, process.kill); timer.start()
    try:
        output = process.stdout.read(LIMIT + 1)
        if len(output) > LIMIT: raise ValueError('Command output exceeded 1 MiB.')
        code = process.wait(timeout=2)
        return code, output.decode('utf8', errors='replace')
    finally:
        timer.cancel()
        if process.poll() is None: process.kill()
        process.wait(); process.stdout.close()


def stream(argv, cwd, emit, timeout=1200):
    process = subprocess.Popen(argv, cwd=cwd, env=ENV, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               start_new_session=True)
    chunks = queue.Queue(maxsize=32)
    def reader():
        try:
            while True:
                raw = process.stdout.read1(4096)
                if not raw: break
                chunks.put(raw)
        finally: chunks.put(None)
    threading.Thread(target=reader, daemon=True).start()
    until = time.monotonic() + timeout; count = 0; finished = False; last_ping = time.monotonic()
    try:
        while not finished:
            if time.monotonic() > until: raise ValueError('Operation timed out. Inspect the lab before retrying.')
            if time.monotonic() - last_ping > 1:
                emit({'heartbeat': True}); last_ping = time.monotonic()
            try: chunk = chunks.get(timeout=1)
            except queue.Empty:
                emit({'heartbeat': True}); continue
            if chunk is None: finished = True; continue
            count += len(chunk)
            if count <= LIMIT: emit({'output': chunk.decode('utf8', errors='replace')})
            elif count - len(chunk) <= LIMIT: emit({'output': '\n[Further output omitted after 1 MiB.]\n'})
        return process.wait(timeout=5)
    finally:
        if process.poll() is None:
            if os.name == 'posix': os.killpg(process.pid, signal.SIGTERM)
            else: process.terminate()
            try: process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                if os.name == 'posix': os.killpg(process.pid, signal.SIGKILL)
                else: process.kill()
                process.wait()
        process.stdout.close()


class HostOperations:
    def __init__(self, config, run=capture):
        self.config = config; self.run = run
        self.clab = config['clab']; self.docker = config['docker']
        self.roots = [Path(p) for p in config['roots']]

    def path(self, value, exists=True):
        if not isinstance(value, str) or len(value) > 4096 or any(ord(c) < 32 for c in value):
            raise ValueError('Invalid project path.')
        path = Path(value)
        if not path.is_absolute() or '..' in path.parts: raise ValueError('Use an absolute project path without traversal.')
        if any(p.is_symlink() for p in (path, *path.parents)): raise ValueError('Symlink paths are not supported.')
        if not any(path == root or root in path.parents for root in self.roots):
            raise ValueError('This path is outside the trusted lab roots. Add its project root during operations setup.')
        if exists and not path.exists(): raise ValueError('The selected VM path no longer exists.')
        return path

    def read(self, value):
        path = self.path(value)
        if not path.is_file() or path.stat().st_size > LIMIT: raise ValueError('Select a regular file smaller than 1 MiB.')
        if path.suffix.lower() not in ('.yaml', '.yml', '.json', '.drawio', '.txt', '.cfg', '.conf', '.set'):
            raise ValueError('This file type cannot be viewed in the manager.')
        raw = path.read_bytes()
        if len(raw) > LIMIT: raise ValueError('File exceeded the read limit.')
        return {'path': str(path), 'text': raw.decode('utf-8-sig'), 'sha256': hashlib.sha256(raw).hexdigest()}

    def browse(self, value=''):
        if not value: return {'path': '', 'entries': [{'name': str(p), 'path': str(p), 'directory': True} for p in self.roots]}
        path = self.path(value)
        if not path.is_dir(): raise ValueError('Choose a project directory.')
        entries = []
        for p in sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
            if p.name.startswith('.') or p.is_symlink(): continue
            if not p.is_dir() and not (p.is_file() and p.name.lower().endswith(('.clab.yaml', '.clab.yml'))): continue
            entries.append({'name': p.name, 'path': str(p), 'directory': p.is_dir()})
            if len(entries) >= 500: break
        return {'path': str(path), 'parent': str(path.parent) if path not in self.roots else '', 'entries': entries}

    def help(self, *parts):
        code, out = self.run([self.clab, *parts, '--help'])
        return out if code == 0 and 'unknown command' not in out.lower() else ''

    def capabilities(self):
        actions = {}
        for action in LIFECYCLE:
            help_text = self.help(action)
            actions[action] = {'available': bool(help_text), 'cleanup': '--cleanup' in help_text,
                               'graceful': '--graceful' in help_text}
        if not actions['redeploy']['available'] and actions['deploy']['available'] and actions['destroy']['available']:
            actions['redeploy'] = {**actions['destroy'], 'fallback': True}
        actions['clone'] = {'available': bool(self.config.get('network')) and os.access(self.config.get('git', '/usr/bin/git'), os.X_OK)}
        return {'protocol': PROTOCOL, 'version': VERSION, 'actions': actions, 'roots': [str(p) for p in self.roots],
                'network': bool(self.config.get('network'))}

    def popular(self):
        if not self.config.get('network'): raise ValueError('Enable --allow-downloads on the VM to browse the online popular-lab catalog.')
        request = Request('https://api.github.com/search/repositories?q=topic:clab-topo+org:srl-labs+fork:true&sort=stars&order=desc', headers={'User-Agent': 'Containerlab-Node-Manager', 'Accept': 'application/vnd.github+json'})
        try:
            with urlopen(request, timeout=12) as response: raw = response.read(LIMIT + 1)
            if len(raw) > LIMIT: raise ValueError()
            items = json.loads(raw).get('items', [])
            return {'items': [{'name': str(i['name'])[:120], 'url': i['html_url'], 'description': str(i.get('description') or '')[:300]} for i in items[:30] if str(i.get('html_url', '')).startswith('https://github.com/srl-labs/')]}
        except Exception: raise ValueError('The GitHub catalog is unavailable. Retry when online or select an existing VM project.')

    def deployed(self):
        code, out = self.run([self.clab, 'inspect', '--all', '--format', 'json'])
        if code: raise ValueError('Could not inspect deployed labs before the operation.')
        value = json.loads(out)
        groups = {}
        if not isinstance(value, (dict, list)): raise ValueError('Unsupported Containerlab inspection response.')
        iterable = [(None, value)] if isinstance(value, list) else value.items()
        for group, rows in iterable:
            if not isinstance(rows, list): raise ValueError('Unsupported Containerlab inspection response.')
            for row in rows:
                if not isinstance(row, dict): raise ValueError('Unsupported Containerlab inspection response.')
                name = row.get('lab_name') or group
                groups.setdefault(name, []).append(row)
        return groups

    def plan(self, req):
        action = req.get('action')
        if action not in (*LIFECYCLE, 'inspect-all', 'create', 'delete', 'clone'): raise ValueError('Unsupported lab operation.')
        options = req.get('options') or {}
        if not isinstance(options, dict) or set(options) - {'cleanup', 'graceful', 'url', 'project', 'text'}:
            raise ValueError('Unsupported operation options.')
        for key in ('cleanup', 'graceful'):
            if key in options and type(options[key]) is not bool: raise ValueError('Invalid boolean option.')
        name = identity(req.get('name', 'manager'))
        path = None; source_hash = ''; affected = []; argv = []; steps = []; warnings = []
        if action == 'clone':
            if not self.config.get('network'): raise ValueError('Repository downloads are disabled in host operations setup.')
            url = options.get('url', '')
            if not isinstance(url, str) or len(url) > 2000 or any(ord(c) < 33 for c in url): raise ValueError('Invalid repository URL.')
            parsed = urlsplit(url)
            if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
                raise ValueError('Use a plain HTTPS repository URL without embedded credentials.')
            project = identity(options.get('project'))
            path = self.path(str(Path(self.config['projects']) / project), exists=False)
            if path.exists(): raise ValueError('Choose a new project directory; existing projects are never overwritten.')
            argv = [self.config.get('git', '/usr/bin/git'), '-c', 'protocol.file.allow=never', '-c', 'protocol.ext.allow=never',
                    'clone', '--depth', '1', '--', url, str(path)]
            warnings.append('Downloads a repository into the trusted project area. Review its YAML, hooks and mounts before deployment.')
        elif action == 'create':
            path = self.path(req.get('path'), exists=False)
            if path.exists() or path.suffix not in ('.yaml', '.yml'): raise ValueError('Choose a new YAML filename in a trusted project directory.')
            self.path(str(path.parent))
            source_hash = 'new'
        elif action == 'inspect-all':
            argv = [self.clab, 'inspect', '--all', '--format', 'json']
        else:
            path = self.path(req.get('path'))
            if path.suffix.lower() not in ('.yaml', '.yml'): raise ValueError('Select the original lab YAML.')
            source_hash = self.read(str(path))['sha256']
            groups = self.deployed(); rows = groups.get(name, [])
            affected = [{'name': r.get('name'), 'id': r.get('container_id'), 'state': r.get('state')} for r in rows]
            for row in rows:
                original = row.get('absLabPath') or row.get('labPath')
                if original and Path(original).is_absolute() and Path(original) != path:
                    raise ValueError('The deployed lab name belongs to a different topology path.')
            if action in ('delete',):
                if action == 'delete' and rows: raise ValueError('Destroy the deployment before deleting its source YAML.')
            elif action in LIFECYCLE:
                help_text = self.help(action)
                if not help_text and action == 'redeploy':
                    if not self.help('destroy') or not self.help('deploy'): raise ValueError('Deploy and destroy are required for redeploy.')
                    steps = [[self.clab, 'destroy', '-t', str(path)], [self.clab, 'deploy', '-t', str(path)]]
                elif not help_text: raise ValueError('This Containerlab version does not support ' + action + '.')
                else: argv = [self.clab, action, '-t', str(path)]
                for command in steps or [argv]:
                    if '--name' in self.help(command[1]): command.extend(['--name', name])
                    elif req.get('source_name', name) != name: raise ValueError('This version cannot target the overridden lab name.')
                if action == 'inspect': argv += ['--format', 'json']
                for flag in ('cleanup', 'graceful'):
                    if options.get(flag):
                        if flag == 'cleanup' and action not in ('deploy', 'redeploy', 'destroy'): raise ValueError('Cleanup is only available for lifecycle recreation/removal.')
                        if steps:
                            if '--' + flag not in self.help('destroy'): raise ValueError('Installed destroy command lacks this option.')
                            steps[0].append('--' + flag)
                        else:
                            if '--' + flag not in help_text: raise ValueError('Installed command lacks --' + flag + '.')
                            argv.append('--' + flag)
                if action in ('deploy', 'redeploy', 'apply'):
                    warnings.append('Runs this trusted topology with host privileges, including its configured hooks, mounts and image pulls.')
                if options.get('cleanup'):
                    directories = sorted({str(r.get('labdir') or (r.get('labels') or {}).get('clab-node-lab-dir') or path.parent / ('clab-' + name)) for r in rows}) or [str(path.parent / ('clab-' + name))]
                    warnings.append('Cleanup removes generated lab artifacts. Expected lab directory: ' + ', '.join(directories) + '. Check any custom lab directory configured on the VM.')
            else: raise ValueError('Unknown lab operation.')
        if action in ('create',):
            text = options.get('text')
            if not isinstance(text, str) or len(text.encode()) > LIMIT: raise ValueError('YAML must be smaller than 1 MiB.')
        base = {'action': action, 'name': name, 'source_name': req.get('source_name', name), 'path': str(path) if path else '', 'options': options,
                'source_hash': source_hash, 'affected': affected, 'argv': argv, 'steps': steps}
        return {**base, 'digest': digest(base), 'warnings': warnings}

    def execute(self, req, emit):
        plan = self.plan(req)
        if req.get('digest') != plan['digest']: raise ValueError('The topology or deployment changed. Preview the operation again.')
        action = plan['action']; path = Path(plan['path']) if plan['path'] else None
        result = {}; code = 0
        if action in ('create', 'delete'):
            if action != 'create':
                history = self.path(str(path.parent / '.clab-manager-history'), exists=False)
                history.mkdir(mode=0o700, exist_ok=True)
                backup = history / (path.name + '.' + uuid.uuid4().hex)
                with open(backup, 'xb') as stream_file:
                    os.chmod(backup, 0o600); stream_file.write(path.read_bytes())
                result['recovery_path'] = str(backup)
            if action == 'delete': path.unlink()
            else:
                temp = path.with_name('.clab-manager-' + uuid.uuid4().hex)
                try:
                    with open(temp, 'xb') as stream_file:
                        os.chmod(temp, 0o600); stream_file.write(plan['options']['text'].encode())
                    if path.exists():
                        info = path.stat(); os.chmod(temp, stat.S_IMODE(info.st_mode))
                        if os.name == 'posix': os.chown(temp, info.st_uid, info.st_gid)
                    os.replace(temp, path)
                finally:
                    if temp.exists(): temp.unlink()
            emit({'output': 'VM source ' + ('removed' if action == 'delete' else 'saved') + '.\n'})
        else:
            cwd = str(path.parent) if path else '/'
            for argv in plan['steps'] or [plan['argv']]:
                code = stream(argv, cwd, emit)
                if code: break
            if action == 'clone' and code == 0: result['project_path'] = str(path)
        return {'exit_code': code, **result}


def main():
    def interrupted(signum, frame): raise KeyboardInterrupt()
    for name in ('SIGTERM', 'SIGINT', 'SIGHUP'):
        if hasattr(signal, name): signal.signal(getattr(signal, name), interrupted)
    def emit(value):
        print(json.dumps(value, separators=(',', ':')), flush=True)
    try:
        config = json.loads(Path('/etc/clab-manager/operations.json').read_text())
        raw = sys.stdin.buffer.readline(2 * LIMIT + 1)
        if len(raw) > 2 * LIMIT: raise ValueError('Request is too large.')
        req = json.loads(raw)
        if not isinstance(req, dict): raise ValueError('Invalid operation request.')
        host = HostOperations(config)
        mode = req.get('mode')
        if mode == 'capabilities': result = host.capabilities()
        elif mode == 'read': result = host.read(req.get('path'))
        elif mode == 'browse': result = host.browse(req.get('path', ''))
        elif mode == 'popular': result = host.popular()
        elif mode in ('preview', 'run'):
            import fcntl
            with open('/run/clab-manager-operations.lock', 'a') as lock:
                try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError: raise ValueError('Another host lab operation is running.')
                result = host.plan(req) if mode == 'preview' else host.execute(req, emit)
                if mode == 'preview': result.pop('options', None)
        else: raise ValueError('Unknown request mode.')
        emit({'result': result}); return 0
    except (BrokenPipeError, KeyboardInterrupt): return 1
    except Exception as exc:
        message = str(exc) if type(exc) is ValueError and not isinstance(exc, json.JSONDecodeError) else 'Host operation failed. Check setup, paths and installed tools.'
        emit({'error': message}); return 1


if __name__ == '__main__': raise SystemExit(main())
