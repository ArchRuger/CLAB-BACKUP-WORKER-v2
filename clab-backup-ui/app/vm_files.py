"""Validate VM file bundles and build an atomic, settings-preserving lab update."""
import base64
import copy
import hashlib
import json
from pathlib import PurePosixPath
import uuid

from .inventory import literal, parse_inventory, read_data
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


def prepare_lab(bundle, deployed_name, previous=None):
    from .discovery import parse_definition, stamp
    files = bundle['files']
    if not files.get('definition'): raise ValueError('Original lab YAML is unavailable')
    parsed = parse_definition(files['definition'], deployed_name)
    expected = {n['definition_node']: n for n in parsed['nodes']}
    aliases = {n['name']: n['definition_node'] for n in parsed['nodes']}
    aliases.update({short: short for short in expected})
    if files.get('topology'):
        topo = read_data(files['topology'])
        if not isinstance(topo.get('nodes'), dict): raise ValueError('Unsupported topology export')
        exported = {n.get('shortname') or aliases.get(key, key) for key, n in topo['nodes'].items() if isinstance(n, dict)}
        if exported != set(expected): raise ValueError('Topology export does not match lab definition')
    if files.get('inventory'):
        seen = set()
        for entry in parse_inventory(files['inventory'], files.get('topology')):
            short = aliases.get(entry['name'])
            if short is None or short in seen: raise ValueError('Inventory does not match lab definition')
            seen.add(short)
            target = expected[short]
            for key in ('address', 'port', 'username', 'password', 'enable_password', 'groups'):
                target[key] = entry[key]
            if entry['platform']:
                target.update(platform=entry['platform'], enabled=True)
            if entry['port'] != 22: target['endpoint_mode'] = 'manual'
    # YAML preserves native interface names. The export provides inventory names
    # and kind information; it is checked above before using it for credentials.
    drawing = parse_drawing(files.get('annotations') or b'{"nodeAnnotations":[]}', files['definition'])
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
            node.update(copy.deepcopy(saved))
            node['kind'] = current_kind
            node['endpoint_mode'] = saved.get('endpoint_mode', 'manual')
    if files.get('annotations') or not lab.get('drawing'):
        lab['drawing'] = drawing
    lab.update(nodes=parsed['nodes'], deployment_name=deployed_name, container_prefix=parsed['prefix'],
               definition_yaml=files['definition'].decode('utf-8-sig'), updated=stamp(),
               source=PurePosixPath(bundle['manifest']['definition']['path']).name)
    lab['vm_source'] = {**metadata(bundle), 'synced_digest': bundle['digest'], 'synced_at': stamp(),
                        'status': 'Up to date', 'can_sync': True}
    return lab
