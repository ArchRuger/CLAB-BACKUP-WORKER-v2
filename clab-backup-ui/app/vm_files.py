"""Validate VM file bundles and build an atomic, settings-preserving lab update."""
import base64
import copy
import hashlib
import json
from pathlib import PurePosixPath
import uuid
import stat
import time
import threading

import paramiko

from .inventory import JUNOS_SWITCHES, literal, parse_inventory, read_data
from .topology import parse_drawing

PROTOCOL = 'clab-manager-files-v1'
KINDS = ('definition', 'annotations', 'inventory', 'topology')
LIMIT = 1024 * 1024


def decode_bundle(source):
    if not isinstance(source, dict) or not isinstance(source.get('files'), dict):
        raise ValueError('Invalid file bundle')
    files = {}; manifest = {}
    for kind in KINDS:
        item = source['files'].get(kind)
        if item is None: continue
        if not isinstance(item, dict) or not isinstance(item.get('content'), str) or len(item['content']) > 4 * ((LIMIT + 2) // 3):
            raise ValueError('Invalid file size')
        raw = base64.b64decode(item['content'], validate=True)
        digest = hashlib.sha256(raw).hexdigest()
        if len(raw) > LIMIT or digest != item.get('sha256'):
            raise ValueError('Invalid file digest or size')
        path = literal(item.get('path'), 'Source path', 4096)
        if not path.startswith('/') or any(ord(c) < 32 for c in path):
            raise ValueError('Invalid source path')
        files[kind] = raw
        manifest[kind] = {'path': path, 'sha256': digest}
    digest = hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()
    return {'files': files, 'manifest': manifest, 'digest': digest}


def metadata(bundle):
    missing = [k for k in KINDS if k not in bundle['files']]
    return dict(digest=bundle['digest'], files=bundle['manifest'], missing=missing,
                message=('Unavailable VM files: ' + ', '.join(missing) + '. Saved settings are retained.') if missing else '')


class FileImportError(ValueError):
    """Controlled file-specific message; never includes file contents."""


def prepare_lab(bundle, deployed_name, previous=None):
    from .discovery import parse_definition, stamp
    files = dict(bundle['files']); issues = []
    if not files.get('definition'): raise FileImportError('Original lab YAML is unavailable. Check Discovery file details or upload it manually.')
    try: parsed = parse_definition(files['definition'], deployed_name)
    except (ValueError, TypeError, AttributeError, RecursionError):
        raise FileImportError('Original lab YAML is invalid or uses unsupported templates/anchors. Upload a resolved definition.')
    def optional_error(kind, message):
        if previous is not None: raise FileImportError(message + ' Saved workspace retained; correct the file or upload manually.')
        files.pop(kind, None)
        issues.append(message + ' Imported the available YAML data; correct this file and Sync from VM later.')
    expected = {n['definition_node']: n for n in parsed['nodes']}
    aliases = {n['name']: n['definition_node'] for n in parsed['nodes']}
    aliases.update({short: short for short in expected})
    if files.get('topology'):
        try:
            topo = read_data(files['topology'])
            if not isinstance(topo.get('nodes'), dict): raise ValueError('Unsupported export')
            exported = {n.get('shortname') or aliases.get(key, key) for key, n in topo['nodes'].items() if isinstance(n, dict)}
            if exported != set(expected): raise ValueError('Different node identities')
        except (ValueError, TypeError, AttributeError, RecursionError):
            optional_error('topology', 'topology-data.json is invalid or does not match the original YAML.')
    if files.get('inventory'):
        try:
            entries = parse_inventory(files['inventory'], files.get('topology'),
                                      kind_hints={alias: expected[short]['platform'] for alias, short in aliases.items()})
            seen = set()
            for entry in entries:
                short = aliases.get(entry['name'])
                if short is None or short in seen: raise ValueError('Different node identities')
                seen.add(short)
        except (ValueError, TypeError, AttributeError, RecursionError):
            optional_error('inventory', 'ansible-inventory.yml is invalid or contains nodes outside this lab.')
            entries = []
        for entry in entries:
            target = expected[aliases[entry['name']]]
            for key in ('address', 'port', 'username', 'password', 'enable_password', 'groups'):
                target[key] = entry[key]
            if entry['platform']:
                target.update(platform=entry['platform'], enabled=True)
            if entry['port'] != 22: target['endpoint_mode'] = 'manual'
    try:
        drawing = parse_drawing(files.get('annotations') or b'{"nodeAnnotations":[]}', files['definition'])
    except (ValueError, TypeError, AttributeError, RecursionError):
        if files.get('annotations'):
            optional_error('annotations', 'The annotations JSON could not be imported.')
        try: drawing = parse_drawing(b'{"nodeAnnotations":[]}', files['definition'])
        except (ValueError, TypeError, AttributeError, RecursionError):
            raise FileImportError('The YAML wiring could not be imported. Upload a supported lab definition.')
    lab = copy.deepcopy(previous) if previous else dict(
        id=uuid.uuid4().hex, name=deployed_name, profiles=[], defaults={}, interval=0,
        next_run=None, created=stamp(), nodes=[])
    old = {n.get('definition_node') or n.get('short_name') or n['name'].removeprefix('clab-' + lab['name'] + '-'): n for n in lab['nodes']}
    for node in parsed['nodes']:
        saved = old.get(node['definition_node'])
        if saved:
            # Preserve saved identities, credentials (including deliberately blank
            # ones), profile assignments, selection, driver and manual endpoints.
            current_kind = node['kind']
            inferred_platform = node['platform']
            node.update(copy.deepcopy(saved))
            node['kind'] = current_kind
            # Explicit sync may recognize a previously unsupported kind, but
            # must not enable it or replace a user's existing driver selection.
            if not saved.get('platform') and inferred_platform in JUNOS_SWITCHES:
                node['platform'] = inferred_platform
            node['endpoint_mode'] = saved.get('endpoint_mode', 'manual')
    if files.get('annotations') or not lab.get('drawing'):
        lab['drawing'] = drawing
    lab.update(nodes=parsed['nodes'], deployment_name=deployed_name, container_prefix=parsed['prefix'],
               definition_yaml=files['definition'].decode('utf-8-sig'), updated=stamp(),
               source=PurePosixPath(bundle['manifest']['definition']['path']).name)
    lab['vm_source'] = {**metadata(bundle), 'synced_digest': bundle['digest'], 'synced_at': stamp(),
                        'status': 'Imported with warnings' if issues else 'Up to date', 'can_sync': not issues, 'warnings': issues}
    if issues: lab['vm_source']['message'] = ' '.join(issues)
    return lab


REPORT_MESSAGES = {
    'found': 'Found', 'missing': 'Not found', 'permission_denied': 'Permission denied',
    'timeout': 'Read timed out', 'unreadable': 'Unreadable, symlink, changed file, or size limit',
    'path_unavailable': 'Inspection did not provide one absolute YAML path',
    'sftp_unavailable': 'SFTP unavailable for this account; select and update the installed helper',
}


def source_reports(source):
    """Only known status codes and literal paths may reach the UI, never contents."""
    result = {}
    if not isinstance(source, dict): return result
    reports = source.get('reports', {})
    if not isinstance(reports, dict): return result
    for kind in KINDS:
        report = reports.get(kind)
        if not isinstance(report, dict): continue
        code = report.get('status')
        if code not in REPORT_MESSAGES: continue
        paths = report.get('paths', [])
        if not isinstance(paths, list): paths = []
        paths = [p for p in paths[:4] if isinstance(p, str) and p.startswith('/') and len(p) <= 4096 and not any(ord(c) < 32 for c in p)]
        result[kind] = {'status': code, 'message': REPORT_MESSAGES[code], 'paths': paths}
    return result


def collect_sftp(client, inspection, deadline):
    from .host_files import collect, groups_of
    channel = None; sftp = None; watchdog = None
    deadline = min(deadline, time.monotonic() + 18)
    try:
        channel = client.get_transport().open_session(timeout=5)
        channel.settimeout(5)
        watchdog = threading.Timer(max(.01, deadline - time.monotonic()), channel.close)
        watchdog.daemon = True
        watchdog.start()
        channel.invoke_subsystem('sftp')
        sftp = paramiko.SFTPClient(channel)
        def reader(path):
            if time.monotonic() > deadline: raise TimeoutError()
            path = PurePosixPath(path)
            for parent in reversed(path.parents):
                info = sftp.lstat(str(parent))
                if not stat.S_ISDIR(info.st_mode): raise ValueError('Not a regular directory')
            before = sftp.lstat(str(path))
            if not stat.S_ISREG(before.st_mode) or before.st_size > LIMIT:
                raise ValueError('Not a regular bounded file')
            with sftp.open(str(path), 'rb') as stream:
                raw = stream.read(LIMIT + 1)
                after = stream.stat()
            if len(raw) > LIMIT or (before.st_size, before.st_mtime) != (after.st_size, after.st_mtime):
                raise ValueError('File changed while reading')
            return raw
        return collect(inspection, reader=reader, path_type=PurePosixPath, deadline=deadline)
    except (OSError, EOFError, paramiko.SSHException):
        return {'protocol': PROTOCOL, 'inspect': inspection, 'sources': {
            name: {'files': {}, 'reports': {'definition': {'status': 'sftp_unavailable', 'paths': []}}}
            for name in groups_of(inspection)}}
    finally:
        if watchdog: watchdog.cancel()
        if sftp: sftp.close()
        elif channel: channel.close()
