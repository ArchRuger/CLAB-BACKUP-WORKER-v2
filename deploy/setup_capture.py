"""Preserve unrelated dotenv settings and the service token during capture setup.

Never evaluate dotenv as shell code. Only migrate the known local capture stack.
``--remove`` keeps every setting but writes CAPTURE_PROVIDER=disabled, so a later
start-manager.sh leaves the stack alone until setup-capture.sh runs again.
"""
import os
from pathlib import Path
import re
import secrets
import stat
import sys
import tempfile


def read_env(path):
    path = Path(path)
    if path.is_symlink():
        raise ValueError('Refusing a symlinked .env. Configure capture settings manually; see docs/CAPTURE.md.')
    old = path.read_text(encoding='utf-8') if path.exists() else ''
    metadata = path.stat() if path.exists() else path.parent.stat()
    return path, old, metadata


def write_env(path, lines, metadata):
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


def without(lines, keys):
    return [line for line in lines if not any(re.match(r'^\s*' + key + r'\s*=', line) for key in keys)]


def configure(path):
    path, old, metadata = read_env(path)
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
    lines = without(old.splitlines(), set(updates) | {'CAPTURE_EDGESHARK_PUBLIC_URL'})
    lines.extend(key + '=' + value for key, value in updates.items())
    write_env(path, lines, metadata)


def disable(path):
    """Keep the token and URLs for a later reinstall; only the provider switches off."""
    path, old, metadata = read_env(path)
    lines = without(old.splitlines(), ['CAPTURE_PROVIDER'])
    lines.append('CAPTURE_PROVIDER=disabled')
    write_env(path, lines, metadata)


if __name__ == '__main__':
    try:
        if '--remove' in sys.argv[2:]:
            disable(sys.argv[1])
            print('Browser capture disabled in .env; the session token and URLs were retained for a later reinstall.')
            sys.exit(0)
        configure(sys.argv[1])
    except (OSError, ValueError, IndexError) as error:
        sys.exit(str(error) or 'Usage: setup_capture.py ENV_FILE [--remove]')
    print('Browser capture settings saved; unrelated settings and existing token retained.')
