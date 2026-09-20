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
VERSION = '1.30.10'
LIMIT = 1024 * 1024
LIFECYCLE = ('deploy', 'redeploy', 'destroy', 'apply', 'start', 'stop', 'restart', 'save', 'inspect')
# The on-demand Grafana of the telemetry stack: deploy/compose.telemetry.yml names the container so
# the manager can start and stop it here by a fixed argv; nothing else of Docker is reachable.
GRAFANA_CONTAINER = 'clab-manager-grafana'
GRAFANA_ACTIONS = ('status', 'start', 'stop')
# The lab builder publishes a new lab folder (publish) and saves again over a lab that is not
# deployed (revise). Both texts travel in one request line, so each stays well inside it.
BUILDER_LIMIT = 512 * 1024
ANNOTATIONS_SUFFIX = '.annotations.json'
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
        actions['publish'] = {'available': True}; actions['revise'] = {'available': True}
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

    def grafana(self, action):
        """Start, stop or look at the on-demand Grafana container: fixed argv, no request input in it."""
        if action not in GRAFANA_ACTIONS: raise ValueError('Unsupported Grafana action.')
        if action != 'status':
            argv = [self.docker, 'start', GRAFANA_CONTAINER] if action == 'start' else [self.docker, 'stop', '-t', '10', GRAFANA_CONTAINER]
            code, _ = self.run(argv)
            if code: raise ValueError(f'Could not {action} the Grafana container {GRAFANA_CONTAINER}. Rerun sudo bash deploy/setup-telemetry.sh on the VM, then retry.')
        code, out = self.run([self.docker, 'inspect', '--type', 'container', '--format', '{{.State.Status}}', GRAFANA_CONTAINER])
        state = out.strip()
        return {'container': GRAFANA_CONTAINER, 'state': state if code == 0 and re.fullmatch(r'[a-z]+', state) else 'missing'}

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

    def builder_texts(self, options):
        """The YAML and the optional annotations of a builder request; None means no annotations."""
        text = options.get('text'); annotations = options.get('annotations')
        if not isinstance(text, str) or not text.strip() or len(text.encode()) > BUILDER_LIMIT: raise ValueError('The topology must be text smaller than 512 KiB.')
        if annotations is not None and (not isinstance(annotations, str) or len(annotations.encode()) > BUILDER_LIMIT):
            raise ValueError('The map layout must be text smaller than 512 KiB.')
        return text, annotations

    def owned_bytes(self, path):
        """Bytes of a regular, single-link file of this account, read without following a symlink."""
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.geteuid() or info.st_size > BUILDER_LIMIT: return None
            return os.read(fd, BUILDER_LIMIT + 1)
        finally: os.close(fd)

    def publish_state(self, folder, wanted):
        """new, reuse, resume or published. A folder is only ours to continue when everything in it is what
        this request would have written, in the order it writes: the annotations first, the YAML last."""
        if not folder.exists(): return 'new'
        if folder.is_symlink() or not folder.is_dir(): raise ValueError('The lab folder name is taken by something that is not a folder.')
        present = {}
        with os.scandir(folder) as listing: entries = list(listing)
        for entry in entries:
            # Left by this helper: temporaries of an interrupted run, and the recovery copies of a deleted lab.
            if entry.name.startswith('.clab-manager-') and not entry.is_symlink() and entry.stat(follow_symlinks=False).st_uid == os.geteuid() and (entry.is_file(follow_symlinks=False) or entry.name == '.clab-manager-history'): continue
            if entry.name not in wanted: raise ValueError('A lab folder with this name already exists on the VM: ' + str(folder) + '. Choose another lab name.')
            try: present[entry.name] = self.owned_bytes(entry.path)
            except OSError: present[entry.name] = None
            if present[entry.name] != wanted[entry.name]: raise ValueError('A lab folder with this name already exists on the VM: ' + str(folder) + '. Choose another lab name.')
        yaml_name = next(n for n in wanted if not n.endswith(ANNOTATIONS_SUFFIX))
        if yaml_name in present: 
            if len(present) != len(wanted): raise ValueError('A lab folder with this name already exists on the VM: ' + str(folder) + '. Choose another lab name.')
            return 'published'
        return 'resume' if present else 'reuse'  # reuse: only this helper's recovery copies are left in it

    def plan(self, req):
        action = req.get('action')
        if action not in (*LIFECYCLE, 'inspect-all', 'create', 'delete', 'clone', 'publish', 'revise'): raise ValueError('Unsupported lab operation.')
        options = req.get('options') or {}
        if not isinstance(options, dict) or set(options) - {'cleanup', 'graceful', 'url', 'project', 'text', 'annotations', 'root', 'base'}:
            raise ValueError('Unsupported operation options.')
        for key in ('cleanup', 'graceful'):
            if key in options and type(options[key]) is not bool: raise ValueError('Invalid boolean option.')
        name = identity(req.get('name', 'manager'))
        path = None; source_hash = ''; affected = []; argv = []; steps = []; warnings = []; extra = {}
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
        elif action == 'publish':
            # Every path is derived here from the lab name; the request only names a trusted root.
            root = options.get('root')
            if not isinstance(root, str) or Path(root) not in self.roots: raise ValueError('Choose one of the trusted lab folders for the new lab.')
            text, annotations = self.builder_texts(options)
            folder = self.path(str(Path(root) / name), exists=False); self.path(root)
            path = folder / (name + '.clab.yml')
            wanted = {path.name: text.encode()}
            if annotations is not None: wanted[path.name + ANNOTATIONS_SUFFIX] = annotations.encode()
            state = self.publish_state(folder, wanted)
            source_hash = 'new'
            extra = {'folder': str(folder), 'files': sorted(wanted), 'folder_mode': 0o2775 if Path(root).stat().st_mode & stat.S_ISGID else 0o755}
            if state in ('published', 'resume'): warnings.append('This lab is already saved on the VM with the same content; nothing will be written.' if state == 'published' else 'An earlier save of this lab stopped half way; this run completes it.')
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
                side = Path(str(path) + ANNOTATIONS_SUFFIX)
                if side.is_file() and not side.is_symlink():
                    extra = {'layout': str(side)}; warnings.append('The map layout file beside it is deleted as well. A recovery copy of both is kept.')
            elif action == 'revise':
                # Saving again is only for a lab that is not running: the running lab was built from the
                # file on disk, and the request must come from exactly the versions it names.
                running = rows or [r for g in groups.values() for r in g if (r.get('absLabPath') or r.get('labPath')) == str(path)]
                if running: raise ValueError('This lab is deployed. Destroy it before saving topology changes.')
                text, annotations = self.builder_texts(options)
                opened = options.get('base') or {}
                if not isinstance(opened, dict) or set(opened) - {'yaml', 'annotations'}: raise ValueError('Invalid saved-version reference.')
                side = Path(str(path) + ANNOTATIONS_SUFFIX)
                if side.is_symlink(): raise ValueError('Symlink paths are not supported.')
                current = hashlib.sha256(side.read_bytes()).hexdigest() if side.is_file() and side.stat().st_size <= LIMIT else ''
                if opened.get('yaml') != source_hash or (annotations is not None and opened.get('annotations', '') != current):
                    raise ValueError('The topology changed on the VM after it was opened. Open it again before saving.')
                extra = {'annotations_hash': current}
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
        if action == 'create':
            text = options.get('text')
            if not isinstance(text, str) or len(text.encode()) > LIMIT: raise ValueError('YAML must be smaller than 1 MiB.')
        base = {'action': action, 'name': name, 'source_name': req.get('source_name', name), 'path': str(path) if path else '', 'options': options,
                'source_hash': source_hash, 'affected': affected, 'argv': argv, 'steps': steps, **extra}
        return {**base, 'digest': digest(base), 'warnings': warnings}

    def place(self, folder_fd, name, data, mode, replace=False):
        """Write one file inside an open folder: private temporary, flushed to disk, then published
        under its name. A new file is linked (fails if the name exists); a revision replaces."""
        temp = '.clab-manager-' + uuid.uuid4().hex
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=folder_fd)
        try:
            with os.fdopen(fd, 'wb') as handle:
                handle.write(data); handle.flush(); os.fsync(handle.fileno()); os.fchmod(handle.fileno(), mode)
                inode = os.fstat(handle.fileno()).st_ino
            if replace: os.replace(temp, name, src_dir_fd=folder_fd, dst_dir_fd=folder_fd); temp = None
            else:
                try: os.link(temp, name, src_dir_fd=folder_fd, dst_dir_fd=folder_fd)
                except FileExistsError: raise ValueError('The lab file now exists on the VM. Nothing was overwritten; review the save again.') from None
            os.fsync(folder_fd)
            return inode
        finally:
            if temp:
                try: os.unlink(temp, dir_fd=folder_fd)
                except FileNotFoundError: pass

    def publish(self, plan, emit):
        """Create the lab folder with its map layout first and its topology last, so the lab only
        becomes visible to the file browser (which lists *.clab.yml) once it is complete."""
        folder = Path(plan['folder']); text, annotations = self.builder_texts(plan['options'])
        wanted = {n: (text if not n.endswith(ANNOTATIONS_SUFFIX) else annotations).encode() for n in plan['files']}
        state = self.publish_state(folder, wanted)
        if state == 'published':
            emit({'output': 'This lab is already saved on the VM. Nothing was written.\n'}); return {'already_published': True}
        made_folder = False; placed = {}
        mode = 0o664 if plan['folder_mode'] & stat.S_ISGID else 0o644
        try:
            if state == 'new':
                os.mkdir(folder, 0o700); made_folder = True
            folder_fd = os.open(folder, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                if made_folder:
                    os.fchmod(folder_fd, plan['folder_mode'])
                    root_fd = os.open(folder.parent, os.O_RDONLY | os.O_DIRECTORY)
                    try: os.fsync(root_fd)
                    finally: os.close(root_fd)
                existing = set(os.listdir(folder))
                for name in [n for n in existing if n.startswith('.clab-manager-') and n != '.clab-manager-history']:  # temporaries of an interrupted run
                    os.unlink(name, dir_fd=folder_fd)
                for name in sorted(wanted, key=lambda n: not n.endswith(ANNOTATIONS_SUFFIX)):
                    if name in existing: continue
                    placed[name] = self.place(folder_fd, name, wanted[name], mode)
            except BaseException:
                # Take back only what this run published, and only while it is still that file.
                for name, inode in placed.items():
                    try:
                        if os.stat(name, dir_fd=folder_fd, follow_symlinks=False).st_ino == inode: os.unlink(name, dir_fd=folder_fd)
                    except OSError: pass
                raise
            finally: os.close(folder_fd)
        except BaseException:
            if made_folder:
                try: os.rmdir(folder)
                except OSError: pass
            raise
        emit({'output': 'Lab folder saved on the VM: ' + str(folder) + '\n'})
        return {'published_path': plan['path'], 'resumed': state == 'resume'}

    def revise(self, plan, emit):
        path = Path(plan['path']); text, annotations = self.builder_texts(plan['options'])
        side = path.name + ANNOTATIONS_SUFFIX
        history = self.path(str(path.parent / '.clab-manager-history'), exists=False)
        history.mkdir(mode=0o700, exist_ok=True)
        folder_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            recovery = {}
            for name in (path.name, side) if annotations is not None else (path.name,):
                try: previous = self.owned_bytes_any(folder_fd, name)
                except FileNotFoundError: continue
                backup = history / (name + '.' + uuid.uuid4().hex)
                with open(backup, 'xb') as handle:
                    os.chmod(backup, 0o600); handle.write(previous); handle.flush(); os.fsync(handle.fileno())
                recovery[name] = str(backup)
            if hashlib.sha256(Path(path).read_bytes()).hexdigest() != plan['source_hash']: raise ValueError('The topology changed on the VM. Review the save again.')
            keep = stat.S_IMODE(os.stat(path.name, dir_fd=folder_fd, follow_symlinks=False).st_mode)
            if annotations is not None: self.place(folder_fd, side, annotations.encode(), keep, replace=True)
            self.place(folder_fd, path.name, text.encode(), keep, replace=True)
        finally: os.close(folder_fd)
        emit({'output': 'Topology saved on the VM. The previous version was kept.\n'})
        return {'published_path': str(path), 'recovery_path': recovery.get(path.name, ''), 'recovery_paths': recovery}

    def owned_bytes_any(self, folder_fd, name):
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=folder_fd)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_size > LIMIT: raise ValueError('The saved lab files cannot be replaced safely.')
            return os.read(fd, LIMIT + 1)
        finally: os.close(fd)

    def execute(self, req, emit):
        plan = self.plan(req)
        if req.get('digest') != plan['digest']: raise ValueError('The topology or deployment changed. Preview the operation again.')
        action = plan['action']; path = Path(plan['path']) if plan['path'] else None
        result = {}; code = 0
        if action == 'publish': result = self.publish(plan, emit)
        elif action == 'revise': result = self.revise(plan, emit)
        elif action in ('create', 'delete'):
            if action != 'create':
                history = self.path(str(path.parent / '.clab-manager-history'), exists=False)
                history.mkdir(mode=0o700, exist_ok=True)
                backup = history / (path.name + '.' + uuid.uuid4().hex)
                with open(backup, 'xb') as stream_file:
                    os.chmod(backup, 0o600); stream_file.write(path.read_bytes())
                result['recovery_path'] = str(backup)
            if action == 'delete' and plan.get('layout'):
                side = Path(plan['layout'])
                if side.is_file() and not side.is_symlink() and side.stat().st_size <= LIMIT:
                    kept = history / (side.name + '.' + uuid.uuid4().hex)
                    with open(kept, 'xb') as stream_file:
                        os.chmod(kept, 0o600); stream_file.write(side.read_bytes())
                    side.unlink(); result['layout_recovery_path'] = str(kept)
            if action == 'delete': path.unlink()
            else:
                temp = path.with_name('.clab-manager-' + uuid.uuid4().hex)
                try:
                    with open(temp, 'xb') as stream_file:
                        os.chmod(temp, 0o600); stream_file.write(plan['options']['text'].encode())
                    # Atomically publish only if the destination is still absent.
                    # Editors outside our flock may create it after plan().
                    try: os.link(temp, path)
                    except FileExistsError:
                        raise ValueError('The topology path now exists. Creation canceled; the existing file was retained.') from None
                    # The 0600 temporary guarded the partial write. The published file is
                    # shared with engineer tooling: group-editable inside a setgid
                    # engineer lab folder, otherwise readable like hand-uploaded files.
                    os.chmod(path, 0o664 if path.parent.stat().st_mode & stat.S_ISGID else 0o644)
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
        elif mode == 'grafana': result = host.grafana(req.get('action'))
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
