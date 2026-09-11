"""Root-owned, fixed-command discovery helper. Python stdlib only; no shell input.

The installed wrapper supplies trusted binary paths. SSH callers cannot supply
paths or commands. Only four files named by verified deployment metadata are read.
"""
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import time

PROTOCOL = 'clab-manager-files-v1'
FILE_LIMIT = 1024 * 1024
TOTAL_LIMIT = 8 * FILE_LIMIT
COMMAND_LIMIT = 4 * FILE_LIMIT


def command_json(args):
    # A pipe avoids disk copies of credentials; a reader bounds memory while the
    # watchdog also terminates commands that stop producing output.
    import threading
    process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                               env={'PATH': '/usr/local/bin:/usr/bin:/bin', 'HOME': '/root'}, cwd='/')
    timer = threading.Timer(8, process.kill)
    timer.start()
    try:
        data = process.stdout.read(COMMAND_LIMIT + 1)
        if len(data) > COMMAND_LIMIT:
            raise ValueError('Command output limit exceeded')
        if process.wait(timeout=1) != 0:
            raise ValueError('Read-only inspection failed')
        return json.loads(data)
    finally:
        timer.cancel()
        if process.poll() is None: process.kill()
        process.wait()
        process.stdout.close()


def read_regular(path):
    """Reject symlinks in every component, including directory replacement races.

    Linux uses openat/O_NOFOLLOW for each component. The portable branch exists
    solely for unit tests on development machines; production is Linux only.
    """
    path = Path(path)
    if not path.is_absolute() or '..' in path.parts or len(str(path)) > 4096:
        raise ValueError('Invalid deployment path')
    if os.name == 'posix':
        fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
        try:
            for part in path.parts[1:-1]:
                next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd); fd = next_fd
            file_fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        finally:
            os.close(fd)
    else:
        if any(p.is_symlink() for p in (path, *path.parents)):
            raise ValueError('Symlinks are not supported')
        file_fd = os.open(path, os.O_RDONLY | getattr(os, 'O_BINARY', 0))
    with os.fdopen(file_fd, 'rb') as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_size > FILE_LIMIT:
            raise ValueError('Not a regular file smaller than 1 MiB')
        raw = stream.read(FILE_LIMIT + 1)
        after = os.fstat(stream.fileno())
        if len(raw) > FILE_LIMIT or (before.st_mtime_ns, before.st_size) != (after.st_mtime_ns, after.st_size):
            raise ValueError('File changed during reading or exceeded limit')
        return raw


def groups_of(inspection):
    groups = {}; total = 0
    buckets = [(None, inspection)] if isinstance(inspection, list) else inspection.items()
    for group, rows in buckets:
        if not isinstance(rows, list): raise ValueError('Invalid inspection rows')
        for row in rows:
            name = row.get('lab_name') or group or ''
            if not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]{0,119}', name) or (group and name != group):
                raise ValueError('Invalid lab name')
            groups.setdefault(name, []).append(row)
            total += 1
            if total > 10000: raise ValueError('Too many containers')
    return groups


def collect(inspection, labels_for=None, reader=read_regular, path_type=Path, deadline=None):
    sources = {}; remaining = TOTAL_LIMIT
    deadline = min(deadline or float('inf'), time.monotonic() + 18)
    for index, (name, rows) in enumerate(groups_of(inspection).items()):
        source = sources[name] = {'files': {}, 'warnings': [], 'reports': {}}
        if index >= 100 or time.monotonic() > deadline:
            source['warnings'].append('File discovery limit reached; use manual import for this lab.')
            continue
        try:
            # The absolute topology path from inspect is authoritative. Some
            # versions only provide an absolute labPath, or omit it on later rows.
            paths = {row.get('absLabPath') or row.get('labPath') for row in rows if row.get('absLabPath') or row.get('labPath')}
            absolute = {path_type(p) for p in paths if isinstance(p, str) and path_type(p).is_absolute()}
            if len(absolute) != 1: raise ValueError('No unique absolute topology path')
            definition = absolute.pop()
            if '..' in definition.parts or definition.suffix.lower() not in ('.yaml', '.yml'):
                raise ValueError('Invalid topology path')
        except (ValueError, TypeError):
            source['warnings'].append('Inspection did not provide one absolute YAML path.')
            source['reports']['definition'] = {'status': 'path_unavailable', 'paths': []}
            continue
        # Read the original and annotations even when Docker labels are absent.
        # Verified labels can locate a custom generated directory; otherwise use
        # the standard clab-<lab-name> folder beside the original YAML.
        lab_dirs = []
        ident = rows[0].get('container_id', '')
        if labels_for and isinstance(ident, str) and re.fullmatch(r'[a-fA-F0-9]{12,64}', ident):
            try:
                labels = labels_for(ident)
                if isinstance(labels, dict) and labels.get('containerlab') == name and labels.get('clab-topo-file') == str(definition):
                    node_dir = path_type(labels.get('clab-node-lab-dir', ''))
                    if node_dir.is_absolute() and '..' not in node_dir.parts and node_dir.name == labels.get('clab-node-name'):
                        lab_dirs.append(node_dir.parent)
            except (ValueError, TypeError, KeyError, OSError, subprocess.SubprocessError):
                pass
        standard = definition.parent / ('clab-' + name)
        if standard not in lab_dirs: lab_dirs.append(standard)
        candidates = {'definition': [definition], 'annotations': [path_type(str(definition) + '.annotations.json')],
                      'inventory': [d / 'ansible-inventory.yml' for d in lab_dirs],
                      'topology': [d / 'topology-data.json' for d in lab_dirs]}
        for kind, paths in candidates.items():
            report = source['reports'][kind] = {'status': 'missing', 'paths': [str(p) for p in paths]}
            for path in paths:
                try:
                    if time.monotonic() > deadline: raise TimeoutError()
                    raw = reader(path)
                    if len(raw) > FILE_LIMIT or len(raw) > remaining: raise ValueError('Size limit')
                    remaining -= len(raw)
                    source['files'][kind] = {'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest(),
                                             'content': base64.b64encode(raw).decode('ascii')}
                    report.update(status='found', paths=[str(path)])
                    break
                except FileNotFoundError:
                    pass
                except PermissionError:
                    report['status'] = 'permission_denied'
                except TimeoutError:
                    report['status'] = 'timeout'
                    break
                except (OSError, ValueError):
                    report['status'] = 'unreadable'
            if kind not in source['files']:
                source['warnings'].append(kind + ': ' + report['status'])
    return {'protocol': PROTOCOL, 'helper_version': '1.13.0', 'inspect': inspection, 'sources': sources}


def main():
    if len(sys.argv) != 3: return 64
    clab, docker = sys.argv[1:]
    try:
        inspection = command_json([clab, 'inspect', '--all', '--format', 'json'])
        result = collect(inspection, lambda ident: command_json(
            [docker, 'inspect', '--type', 'container', '--format', '{{json .Config.Labels}}', ident]))
        sys.stdout.write(json.dumps(result, separators=(',', ':')))
        return 0
    except Exception:
        sys.stderr.write('Containerlab discovery helper failed. Check installation and Docker service.\n')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
