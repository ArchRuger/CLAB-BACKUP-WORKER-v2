#!/usr/bin/env python3
"""Move every release marker to a new version.

    python3 deploy/set-release.py 1.26.0

Rewrites clab-backup-ui/VERSION, the runtime lockstep files (the FIELDS of verify-release.py)
and every mention of the current release in the living documentation. History phrases
("since 1.25.0", "1.25.0 or later") and third-party versions are left alone. The release
history itself is written by hand afterwards: a "## Changes in NEW" section at the top of
docs/CHANGELOG.md and a "# <title> — NEW" section at the top of clab-backup-ui/VALIDATION.md
and of "agent instructions.md". Finish with python3 deploy/verify-release.py.
"""
import importlib.util
from pathlib import Path
import re
import sys

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('release_check', HERE / 'verify-release.py')
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


def rewrite(path, old_text, new_text):
    if new_text == old_text:
        return False
    path.write_bytes(new_text.encode('utf-8'))
    return True


def set_release(root, new):
    if not re.fullmatch(r'\d+\.\d+\.\d+', new):
        raise ValueError('Give the new release as MAJOR.MINOR.PATCH, for example 1.26.0.')
    old = release.read_version(root)
    if new == old:
        raise ValueError('clab-backup-ui/VERSION already contains ' + new + '.')
    changed = []
    for name, pattern in release.FIELDS.items():
        path = root / name
        text = path.read_bytes().decode('utf-8')

        def swap(match):
            start = match.start(1) - match.start(0)
            return match.group(0)[:start] + new + match.group(0)[start + len(match.group(1)):]

        updated, count = re.subn(pattern, swap, text, flags=re.MULTILINE)
        if not count:
            raise ValueError(name + ': release metadata not found; verify-release.py would fail as well.')
        if rewrite(path, text, updated):
            changed.append(name)
    (root / 'clab-backup-ui/VERSION').write_bytes((new + '\n').encode('utf-8'))
    changed.append('clab-backup-ui/VERSION')
    for rel, path in release.living_docs(root):
        text = path.read_bytes().decode('utf-8')
        lines = text.split('\n')
        edits = [(number, start, end) for number, start, end, _token, kind in release.release_tokens(text, old) if kind == 'current']
        for number, start, end in sorted(edits, reverse=True):
            line = lines[number - 1]
            lines[number - 1] = line[:start] + new + line[end:]
        if rewrite(path, text, '\n'.join(lines)):
            changed.append(rel)
    return old, changed


if __name__ == '__main__':
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    try:
        previous, files = set_release(Path(__file__).resolve().parents[1], sys.argv[1])
    except (OSError, ValueError) as error:
        sys.exit(str(error))
    print(f'Release markers moved from {previous} to {sys.argv[1]} in {len(files)} files:\n  ' + '\n  '.join(files))
    print(f'Now write the release history by hand: "## Changes in {sys.argv[1]}" at the top of docs/CHANGELOG.md and a '
          f'"# <title> - {sys.argv[1]}" section at the top of clab-backup-ui/VALIDATION.md and of "agent instructions.md". '
          'Then run python3 deploy/verify-release.py.')
