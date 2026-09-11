#!/usr/bin/env python3
"""Review or narrowly disable Ubuntu installer-media APT sources.

No network source or authentication option is changed. The installer obtains
approval before --repair; --check and scan_media_sources are read-only.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile


def media_uri(value):
    return bool(re.match(r'^(?:cdrom:|file:/{1,3}cdrom(?:/|$))', value, re.I))


def _list_text(text):
    changed = 0
    lines = []
    for line in text.splitlines(keepends=True):
        match = re.match(r'^\s*deb(?:-src)?\s+(?:\[[^\]\r\n]*\]\s+)?(\S+)', line)
        if match and media_uri(match[1]):
            line = '# Disabled installer media by clab-manager: ' + line
            changed += 1
        lines.append(line)
    return ''.join(lines), changed


def _fields(lines):
    fields = {}
    current = None
    for index, line in enumerate(lines):
        if line.lstrip().startswith('#'):
            continue
        match = re.match(r'^([A-Za-z][A-Za-z0-9-]*):[ \t]*(.*?)(?:\r?\n)?$', line)
        if match:
            key = match[1].lower()
            fields.setdefault(key, []).append({'indexes': [index], 'value': match[2]})
            current = fields[key][-1]
        elif line[:1] in (' ', '\t') and current is not None:
            current['indexes'].append(index)
            current['value'] += ' ' + line.strip()
        else:
            current = None
    return fields


def _paragraph(lines):
    fields = _fields(lines)
    uri_fields = fields.get('uris', [])
    enabled = fields.get('enabled', [])
    if len(enabled) == 1 and enabled[0]['value'].strip().lower() == 'no':
        return lines, 0
    if not any(any(media_uri(uri) for uri in re.findall(r'cdrom:\[[^\]]*\]\S*|\S+', field['value']))
               for field in uri_fields):
        return lines, 0
    if len(uri_fields) != 1 or len(enabled) > 1:
        raise ValueError('Ambiguous installer-media stanza: duplicate URIs or Enabled fields; edit it manually.')
    field = uri_fields[0]
    uris = re.findall(r'cdrom:\[[^\]]*\]\S*|\S+', field['value'])
    retained = [uri for uri in uris if not media_uri(uri)]
    ending = '\r\n' if any(line.endswith('\r\n') for line in lines) else '\n'
    output = list(lines)
    if retained:
        indexes = set(field['indexes'])
        first = field['indexes'][0]
        output = [('URIs: ' + ' '.join(retained) + ending) if i == first else line
                  for i, line in enumerate(lines) if i == first or i not in indexes]
    elif enabled:
        indexes = set(enabled[0]['indexes'])
        first = enabled[0]['indexes'][0]
        output = [('Enabled: no' + ending) if i == first else line
                  for i, line in enumerate(lines) if i == first or i not in indexes]
    else:
        if output and not output[-1].endswith('\n'):
            output[-1] += ending
        output.append('Enabled: no' + ending)
    return output, len(uris) - len(retained)


def repair_text(text, suffix):
    if suffix == '.list':
        return _list_text(text)
    if suffix != '.sources':
        raise ValueError('Only .list and .sources files are supported.')
    output, paragraph, changed = [], [], 0
    for line in text.splitlines(keepends=True):
        if line.strip():
            paragraph.append(line)
            continue
        repaired, count = _paragraph(paragraph)
        output.extend(repaired)
        output.append(line)
        changed += count
        paragraph = []
    repaired, count = _paragraph(paragraph)
    output.extend(repaired)
    return ''.join(output), changed + count


def _source_paths(apt_root):
    if apt_root.is_symlink() or (apt_root / 'sources.list.d').is_symlink():
        raise ValueError('APT source directory is a symlink; review it manually.')
    paths = [apt_root / 'sources.list'] if (apt_root / 'sources.list').exists() else []
    folder = apt_root / 'sources.list.d'
    if folder.exists():
        paths.extend(sorted(path for path in folder.iterdir() if path.suffix in ('.list', '.sources')))
    return paths


def _read_source(path):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or path.is_symlink():
        raise ValueError(f'APT source is not a regular file: {path}; review it manually.')
    if info.st_size > 1024 * 1024:
        raise ValueError(f'APT source exceeds 1 MiB: {path}; review it manually.')
    return path.read_bytes(), info


def _plan(apt_root):
    result = []
    for path in _source_paths(apt_root):
        original, info = _read_source(path)
        try:
            repaired, changes = repair_text(original.decode('utf-8'), path.suffix)
        except (UnicodeError, ValueError) as exc:
            raise ValueError(f'{path}: {exc}') from exc
        if changes:
            result.append((path, original, repaired.encode('utf-8'), info, changes))
    return result


def scan_media_sources(apt_root=Path('/etc/apt')):
    return [{'path': str(path), 'changes': changes}
            for path, _, _, _, changes in _plan(Path(apt_root))]


def _docker_uri(value):
    return bool(re.fullmatch(r'https?://download\.docker\.com/linux/ubuntu/?', value))


def _docker_states(text, suffix):
    states = set()
    if suffix == '.list':
        for line in text.splitlines():
            line = line.lstrip()
            commented = line.startswith('#')
            if commented:
                line = line[1:].lstrip()
            match = re.match(r'^(deb(?:-src)?)\s+(?:\[[^\]]*\]\s+)?(\S+)', line)
            if match and _docker_uri(match[2]):
                states.add('blocked' if commented or match[1] != 'deb' else 'enabled')
        return states
    for paragraph in re.split(r'\r?\n[ \t]*\r?\n', text):
        lines = paragraph.splitlines()
        # Fully commented stanzas also express the operator's disabled choice.
        variants = [(_fields(lines), False),
                    (_fields([line.lstrip()[1:].lstrip() for line in lines
                              if line.lstrip().startswith('#')]), True)]
        for fields, commented in variants:
            uris = fields.get('uris', [])
            if not any(_docker_uri(uri) for field in uris for uri in field['value'].split()):
                continue
            enabled = fields.get('enabled', [])
            types = fields.get('types', [])
            if len(uris) != 1 or len(enabled) > 1 or len(types) != 1:
                raise ValueError('Ambiguous Docker APT stanza; review URIs, Types and Enabled fields manually.')
            value = enabled[0]['value'].strip().lower() if enabled else 'yes'
            if value not in ('yes', 'no'):
                raise ValueError('Docker APT Enabled must be yes or no; review the source manually.')
            states.add('blocked' if commented or value == 'no' or 'deb' not in types[0]['value'].split()
                       else 'enabled')
    return states


def docker_source_status(apt_root=Path('/etc/apt')):
    """Return enabled/absent; a deliberately disabled source needs operator review."""
    enabled, blocked = [], []
    for path in _source_paths(Path(apt_root)):
        original, _ = _read_source(path)
        try:
            states = _docker_states(original.decode('utf-8'), path.suffix)
        except (UnicodeError, ValueError) as error:
            raise ValueError(f'{path}: {error}') from error
        if 'enabled' in states:
            enabled.append(str(path))
        if 'blocked' in states:
            blocked.append(str(path))
    if enabled:
        return 'enabled'
    if blocked:
        raise ValueError('Docker APT sources are disabled or source-only in ' + ', '.join(blocked)
                         + '. Review that choice and configure an enabled binary-package source before rerunning; '
                         'setup will not enable it or add a duplicate automatically.')
    return 'absent'


def _unchanged(left, right):
    return all(getattr(left, field) == getattr(right, field)
               for field in ('st_dev', 'st_ino', 'st_mode', 'st_uid', 'st_gid', 'st_size', 'st_mtime_ns'))


def repair_media_sources(apt_root=Path('/etc/apt'), backup_root=Path('/var/backups/clab-manager/apt-sources')):
    """Caller must hold root authority for production /etc/apt writes."""
    apt_root, backup_root = Path(apt_root), Path(backup_root)
    plan = _plan(apt_root)
    if not plan:
        return {'changed': [], 'backup': None}
    for parent in [backup_root, *backup_root.parents]:
        if parent.is_symlink():
            raise ValueError('APT backup location has a symlink; review it manually.')
    backup_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ-')
    backup = Path(tempfile.mkdtemp(prefix=stamp, dir=backup_root))
    # Back up every affected file before the first replacement.
    for path, original, _, info, _ in plan:
        if path.read_bytes() != original or not _unchanged(path.lstat(), info):
            raise ValueError('APT sources changed during review; rerun setup.')
        destination = backup / path.relative_to(apt_root)
        destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        # Write the reviewed bytes, rather than reopening a potentially changed
        # source while making the backup.
        with destination.open('xb') as output:
            output.write(original)
            output.flush()
            os.fsync(output.fileno())
        os.chmod(destination, stat.S_IMODE(info.st_mode))
        os.utime(destination, ns=(info.st_atime_ns, info.st_mtime_ns))
    changed = []
    for path, original, repaired, info, _ in plan:
        current, latest = _read_source(path)
        if current != original or not _unchanged(latest, info):
            raise ValueError(f'APT source changed during repair: {path}. Backups: {backup}')
        descriptor, temporary = tempfile.mkstemp(prefix='.clab-manager-', dir=path.parent)
        try:
            with os.fdopen(descriptor, 'wb') as output:
                output.write(repaired)
                output.flush()
                os.fsync(output.fileno())
                os.chmod(temporary, stat.S_IMODE(info.st_mode))
                if hasattr(os, 'chown'):
                    os.chown(temporary, info.st_uid, info.st_gid)
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        changed.append(str(path))
    return {'changed': changed, 'backup': str(backup)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--check', action='store_true', help='List active installer-media sources without editing.')
    action.add_argument('--repair', action='store_true', help='Back up and disable only installer-media entries (root).')
    action.add_argument('--docker-source-status', action='store_true', help='Read Docker source state: enabled/absent, or explain a disabled source.')
    args = parser.parse_args(argv)
    if args.docker_source_status:
        print(docker_source_status())
        return
    if args.repair:
        if not hasattr(os, 'geteuid') or os.geteuid() != 0:
            raise ValueError('APT source repair requires sudo/root; use the guided installer.')
        result = repair_media_sources()
    else:
        result = scan_media_sources()
    print(json.dumps(result))


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError) as error:
        print(f'APT source check stopped: {error}', file=sys.stderr)
        sys.exit(1)
