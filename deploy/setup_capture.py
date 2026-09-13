"""Preserve unrelated dotenv settings and the service token during setup.

Never evaluate dotenv as shell code. Only migrate the known local capture stack.
"""
import os
from pathlib import Path
import re
import secrets
import stat
import sys
import tempfile


def configure(path):
    path = Path(path)
    if path.is_symlink():
        raise ValueError('Refusing a symlinked .env. Configure capture settings manually; see docs/CAPTURE.md.')
    old = path.read_text(encoding='utf-8') if path.exists() else ''
    metadata = path.stat() if path.exists() else path.parent.stat()
    values = {}
    for line in old.splitlines():
        match = re.match(r'^\s*(CAPTURE_[A-Z_]+)\s*=(.*)$', line)
        if match:
            values[match[1]] = match[2].strip().strip('\"\'')
    for key, expected in [('CAPTURE_EDGESHARK_URL', 'http://127.0.0.1:5001'),
                          ('CAPTURE_SESSION_URL', 'http://127.0.0.1:5801')]:
        if values.get(key, '').rstrip('/') not in ('', expected):
            raise ValueError('Custom capture URL detected. Retain your settings and follow the manual configuration in docs/CAPTURE.md.')
    token = values.get('CAPTURE_SESSION_TOKEN') or secrets.token_hex(32)
    if not re.fullmatch(r'[0-9a-f]{64}', token):
        raise ValueError('Existing CAPTURE_SESSION_TOKEN is invalid; it was not replaced.')
    updates = {'CAPTURE_PROVIDER': 'edgeshark', 'CAPTURE_EDGESHARK_URL': 'http://127.0.0.1:5001',
               'CAPTURE_SESSION_URL': 'http://127.0.0.1:5801', 'CAPTURE_SESSION_TOKEN': token}
    keys = set(updates) | {'CAPTURE_EDGESHARK_PUBLIC_URL'}
    lines = [line for line in old.splitlines()
             if not any(re.match(r'^\s*' + key + r'\s*=', line) for key in keys)]
    lines.extend(key + '=' + value for key, value in updates.items())
    fd, temporary = tempfile.mkstemp(prefix='.capture-env-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as stream:
            stream.write('\n'.join(lines) + '\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, stat.S_IRUSR | stat.S_IWUSR)
        if hasattr(os, 'chown'):
            os.chown(temporary, metadata.st_uid, metadata.st_gid)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


if __name__ == '__main__':
    try:
        configure(sys.argv[1])
    except (OSError, ValueError) as error:
        sys.exit(str(error))
    print('Browser capture settings saved; unrelated settings and existing token retained.')
