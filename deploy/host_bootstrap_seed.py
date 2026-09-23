#!/usr/bin/env python3
"""Write the one-time VM connection seed for the manager (standard library only).

Called by setup-password.sh as root right after it set the clab-discovery password:

    printf '%s\\n' "$password" | python3 host_bootstrap_seed.py --data-dir DIR --port N [--host-key PATH ...]

The password arrives on stdin only, never argv or the environment. The seed is
written atomically to DIR/host-bootstrap.json, mode 0600, owned by the manager
container's account (UID/GID 10001) so only root and the manager can read it. The
manager merges it into its encrypted settings on its next discovery cycle and
deletes it. Nothing secret is printed.

Exit status: 0 seed written, 2 skipped (data directory absent), 1 refused.
"""
import argparse
import base64
import hashlib
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
from datetime import datetime, timezone

SEED_NAME = 'host-bootstrap.json'
DEFAULT_DATA_DIR = '/srv/containerlab-node-manager/data'
MANAGER_UID = MANAGER_GID = 10001
ACCOUNT = 'clab-discovery'
# Paramiko, which the manager uses, prefers ed25519, then ECDSA, then RSA host keys.
KEY_PREFERENCE = ('ed25519', 'ecdsa', 'rsa')
DEFAULT_HOST_KEYS = tuple(f'/etc/ssh/ssh_host_{kind}_key.pub' for kind in KEY_PREFERENCE)
FINGERPRINT_LINE = re.compile(r'^\s*\d+\s+(SHA256:[A-Za-z0-9+/]{43})(?:\s|$)')


class SeedError(Exception):
    """A controlled refusal; the message never contains the password."""


def parse_keygen(output):
    """The SHA256 fingerprint from `ssh-keygen -lf` output, or '' when absent."""
    for line in str(output).splitlines():
        match = FINGERPRINT_LINE.match(line)
        if match: return match.group(1)
    return ''


def fingerprint_of_public_key(text):
    """The same SHA256 form ssh-keygen and the manager's PinnedHostKey print."""
    fields = str(text).split()
    if len(fields) < 2: return ''
    try: blob = base64.b64decode(fields[1], validate=True)
    except ValueError: return ''
    return 'SHA256:' + base64.b64encode(hashlib.sha256(blob).digest()).decode().rstrip('=')


def ordered_keys(paths):
    def rank(path):
        name = os.path.basename(path)
        return next((index for index, kind in enumerate(KEY_PREFERENCE) if f'_{kind}_' in name), len(KEY_PREFERENCE))
    return sorted(paths, key=rank)


def host_fingerprint(paths=DEFAULT_HOST_KEYS, run=subprocess.run):
    keygen = shutil.which('ssh-keygen') or '/usr/bin/ssh-keygen'
    for path in ordered_keys(paths):
        if not path.endswith('.pub'): path += '.pub'
        if not os.path.isfile(path): continue
        try:
            result = run([keygen, '-lf', path], capture_output=True, text=True, timeout=10, check=False)
            value = parse_keygen(result.stdout) if result.returncode == 0 else ''
        except (OSError, subprocess.SubprocessError):
            value = ''
        if not value:
            try:
                with open(path, encoding='ascii') as stream: value = fingerprint_of_public_key(stream.read(16384))
            except (OSError, UnicodeDecodeError): value = ''
        if value: return value
    return ''


def read_password(stream):
    raw = stream.read(4098)
    if raw.endswith('\n'): raw = raw[:-1]
    if not raw or len(raw) > 4096 or '\n' in raw or '\r' in raw or '\x00' in raw:
        raise SeedError('The password handed to the seed writer is not usable.')
    return raw


def build_seed(password, port, fingerprint, now=None):
    if type(port) is not int or not 1 <= port <= 65535: raise SeedError('The SSH port is not valid.')
    created = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat(timespec='seconds')
    return {'schema': 1, 'created': created,
            'host': {'address': '127.0.0.1', 'port': port, 'username': ACCOUNT, 'auth': 'password',
                     'command_mode': 'helper', 'enabled': True},
            'password': password, 'fingerprint': fingerprint}


def write_seed(data_dir, seed, uid=MANAGER_UID, gid=MANAGER_GID):
    """Atomically place the seed, mode 0600; chown only when running as root."""
    if not os.path.lexists(data_dir): return None
    if not os.path.isdir(data_dir) or os.path.islink(data_dir):
        raise SeedError('The manager data path is not a plain directory.')
    target = os.path.join(data_dir, SEED_NAME)
    if os.path.isdir(target) and not os.path.islink(target): raise SeedError('A directory is in the way of the seed file.')
    temp = os.path.join(data_dir, f'.{SEED_NAME}.{secrets.token_hex(8)}.tmp')
    payload = json.dumps(seed).encode()
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    try:
        try:
            os.fchmod(fd, 0o600)
            if os.geteuid() == 0: os.fchown(fd, uid, gid)
            view = memoryview(payload)
            while view: view = view[os.write(fd, view):]
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(temp, target)
    except BaseException:
        try: os.unlink(temp)
        except OSError: pass
        raise
    try:
        directory = os.open(data_dir, os.O_RDONLY)
        try: os.fsync(directory)
        finally: os.close(directory)
    except OSError:
        pass
    return target


def main(argv=None, stdin=None):
    parser = argparse.ArgumentParser(description='Write the one-time VM connection seed (password on stdin).')
    parser.add_argument('--data-dir', default=DEFAULT_DATA_DIR)
    parser.add_argument('--port', type=int, default=22)
    parser.add_argument('--host-key', action='append', default=[])
    args = parser.parse_args(argv)
    try:
        password = read_password(stdin or sys.stdin)
        if not os.path.lexists(args.data_dir):
            print(f'Manager data directory {args.data_dir} does not exist yet; the VM connection is not prefilled. Enter it in VM connection.')
            return 2
        seed = build_seed(password, args.port, host_fingerprint(tuple(args.host_key) or DEFAULT_HOST_KEYS))
        if write_seed(args.data_dir, seed) is None:
            print(f'Manager data directory {args.data_dir} does not exist yet; the VM connection is not prefilled. Enter it in VM connection.')
            return 2
    except (SeedError, OSError) as exc:
        message = str(exc) if isinstance(exc, SeedError) else 'The VM connection seed could not be written; enter the connection in VM connection.'
        print(message, file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
