"""Print VIEWER_ASSETS for app/capture_sessions.py from a pinned image's noVNC folder.

The manager relays noVNC's core/rfb.js and every module it imports as same-origin
JavaScript, and refuses any byte that differs from this list. When the image pin
moves, copy the new image's /opt/noVNC out (never run it) and paste the output:

    id=$(sudo docker create IMAGE) && sudo docker cp "$id:/opt/noVNC" /tmp/novnc; sudo docker rm "$id"
    python3 "$HOME/projects/clab-manager/deploy/capture/viewer_assets.py" /tmp/novnc

Standard library only. The capture smoke test fetches every listed module from the
real image through the service, which enforces the same list.
"""
import hashlib
from pathlib import Path, PurePosixPath
import posixpath
import re
import sys

ENTRY = 'core/rfb.js'
# Static imports and re-exports, single or multi-line; noVNC's core uses no bare
# specifiers and no dynamic import(), which the scan refuses rather than skips.
STATIC = re.compile(r'''(?:^|[;\s])(?:import|export)\s*(?:[\w*{}\s,$]+?\s*from\s*)?['"]([^'"]+)['"]''', re.M)
DYNAMIC = re.compile(r'\bimport\s*\(')


def modules(root):
    """{relative path: sha256} for ENTRY and everything it imports under root."""
    root = Path(root);found = {};todo = [ENTRY]
    while todo:
        path = todo.pop()
        if path in found:
            continue
        if path.startswith('../') or PurePosixPath(path).is_absolute():
            raise ValueError('Import leaves the noVNC folder: ' + path)
        data = (root / path).read_bytes();text = data.decode()
        if DYNAMIC.search(text):
            raise ValueError('Dynamic import in ' + path + '; extend the scan before pinning this image.')
        found[path] = hashlib.sha256(data).hexdigest()
        for spec in STATIC.findall(text):
            if not spec.startswith('.'):
                raise ValueError('Bare import ' + spec + ' in ' + path)
            todo.append(posixpath.normpath(posixpath.join(posixpath.dirname(path), spec)))
    return found


def main():
    if len(sys.argv) != 2:
        sys.exit('Usage: viewer_assets.py NOVNC_FOLDER')
    print('VIEWER_ASSETS = {')
    for path, digest in sorted(modules(sys.argv[1]).items()):
        print("    '%s': '%s'," % (path, digest))
    print('}')


if __name__ == '__main__':
    main()
