"""Provision and start the full-screen installer (standard library only).

The pinned wheels in requirements.lock go into a private virtual environment of the
installing account, under ~/.local/share/clab-node-manager/installer-tui/, keyed by the
lock file's digest and the Python version: a changed pin provisions a new environment
once, and an unchanged one is never downloaded again. Nothing is installed as root,
system Python is never modified (the environment is created --without-pip, so the
python3-venv/ensurepip package is not needed either), and the manager image is not
involved. Each wheel is checked against its SHA-256 before a single file is unpacked;
a partly provisioned environment is never marked ready.
"""
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tempfile
import time
from urllib.request import urlopen
import zipfile

HERE = Path(__file__).resolve().parent
LOCK = HERE / 'requirements.lock'
LAUNCH = HERE / 'launch.py'
MAX_WHEEL = 16 * 1024 * 1024
MAX_UNPACKED = 96 * 1024 * 1024
MIN_PYTHON = (3, 10)
_PIN = re.compile(r'([A-Za-z0-9][A-Za-z0-9._-]*)==([A-Za-z0-9.+!-]+)\s+--hash=sha256:([0-9a-f]{64})\s*$')
_URL = re.compile(r'#\s*(https://files\.pythonhosted\.org/\S+\.whl)\s*$')


class ProvisionError(Exception):
    pass


def parse_lock(text):
    """[(name, version, url, sha256)] from requirements.lock; each pin preceded by its URL comment."""
    pins, url = [], None
    for number, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        match = _URL.fullmatch(line)
        if match:
            url = match[1]
            continue
        if line.startswith('#'):
            continue
        match = _PIN.fullmatch(line)
        if not match or url is None:
            raise ProvisionError(f'requirements.lock line {number} is not a pinned, hashed wheel with its URL.')
        pins.append((match[1], match[2], url, match[3]))
        url = None
    if not pins:
        raise ProvisionError('requirements.lock lists no packages.')
    return pins


def lock_digest(data=None):
    return hashlib.sha256(LOCK.read_bytes() if data is None else data).hexdigest()[:16]


def base_dir(env):
    root = os.environ.get('XDG_DATA_HOME') or os.path.join(env['HOME'], '.local', 'share')
    return Path(root) / 'clab-node-manager' / 'installer-tui'


def target_dir(env):
    return base_dir(env) / f'py{sys.version_info[0]}{sys.version_info[1]}-{lock_digest()}'


def venv_python(folder):
    return folder / 'venv' / 'bin' / 'python'


def ready(env):
    """True when this lock's environment was fully provisioned. Never downloads or imports."""
    try:
        folder = target_dir(env)
        marker = json.loads((folder / 'ready.json').read_text())
        return marker.get('lock') == lock_digest() and venv_python(folder).exists()
    except (OSError, ValueError, KeyError, AttributeError):
        return False


def fetch(url, timeout=30):
    # Ordinary HTTPS from the account's own environment (an https_proxy setting applies).
    with urlopen(url, timeout=timeout) as response:
        data = response.read(MAX_WHEEL + 1)
    if len(data) > MAX_WHEEL:
        raise ProvisionError(f'{url.rsplit("/", 1)[-1]} is larger than expected.')
    return data


def unpack_wheel(data, site, budget):
    """Unpack one verified pure-Python wheel into site-packages. Refuses absolute or
    parent-relative names, links and data directories; returns the remaining size budget."""
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for info in archive.infolist():
            name = info.filename
            parts = PurePosixPath(name).parts
            if not parts or name.startswith('/') or '\\' in name or '..' in parts or ':' in parts[0]:
                raise ProvisionError(f'Unsafe path in wheel: {name!r}')
            if parts[0].endswith('.data'):
                raise ProvisionError(f'Unexpected wheel data directory: {name!r}')
            kind = (info.external_attr >> 16) & 0o170000
            if kind not in (0, 0o100000, 0o040000):
                raise ProvisionError(f'Unexpected special file in wheel: {name!r}')
            if info.is_dir():
                continue
            budget -= info.file_size
            if budget < 0:
                raise ProvisionError('The wheels unpack to more than expected.')
            destination = site.joinpath(*parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source, open(destination, 'xb') as stream:
                shutil.copyfileobj(source, stream)
    return budget


def provision(env, say=print, fetcher=None, python=None):
    """Create the environment for the current lock. Returns 0 when ready, 1 with an explanation."""
    fetcher = fetcher or fetch
    python = python or sys.executable or '/usr/bin/python3'
    if sys.version_info[:2] < MIN_PYTHON:
        say('The full-screen installer needs Python %d.%d or later; use --plain.' % MIN_PYTHON)
        return 1
    if ready(env):
        say('The full-screen installer is already set up: ' + str(target_dir(env)))
        return 0
    try:
        pins = parse_lock(LOCK.read_text())
        base = base_dir(env)
        base.mkdir(parents=True, exist_ok=True, mode=0o700)
        target = target_dir(env)
    except (OSError, ProvisionError) as error:
        say(f'Full-screen installer setup failed: {error}')
        return 1
    staging = Path(tempfile.mkdtemp(prefix='.staging-', dir=str(base)))
    try:
        say('Setting up the full-screen installer for ' + env.get('USER', 'this account') + ' (one time; '
            'nothing outside ' + str(base) + ' is changed).')
        created = subprocess.run([python, '-m', 'venv', '--without-pip', str(staging / 'venv')],
                                 stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                 text=True, timeout=120)
        if created.returncode:
            raise ProvisionError('Python could not create a virtual environment: '
                                 + (created.stdout.strip().splitlines() or ['no details'])[-1][:300])
        version = f'python{sys.version_info[0]}.{sys.version_info[1]}'
        site = staging / 'venv' / 'lib' / version / 'site-packages'
        if not site.is_dir():
            raise ProvisionError('The new virtual environment has no site-packages folder.')
        budget = MAX_UNPACKED
        for name, pinned, url, digest in pins:
            say(f'  {name} {pinned}: downloading and verifying')
            try:
                data = fetcher(url)
            except ProvisionError:
                raise
            except Exception as error:
                raise ProvisionError(f'Could not download {name} {pinned} from files.pythonhosted.org ({error}). '
                                     'Check this VM\'s internet or proxy access.') from error
            if hashlib.sha256(data).hexdigest() != digest:
                raise ProvisionError(f'{name} {pinned} does not match its pinned SHA-256; nothing was installed.')
            budget = unpack_wheel(data, site, budget)
        textual_pin = next((pinned for name, pinned, _, _ in pins if name == 'textual'), None)
        check = subprocess.run([str(venv_python(staging)), '-I', '-c', 'import textual; print(textual.__version__)'],
                               stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               text=True, timeout=120)
        if check.returncode or check.stdout.strip() != textual_pin:
            raise ProvisionError('The provisioned packages did not import cleanly: '
                                 + (check.stdout.strip().splitlines() or ['no details'])[-1][:300])
        (staging / 'ready.json').write_text(json.dumps({'lock': lock_digest(), 'python': version,
                                                        'created': time.strftime('%Y-%m-%dT%H:%M:%S%z')}) + '\n')
        if target.exists():
            shutil.rmtree(target)
        os.rename(staging, target)
        for old in base.glob('py*-*'):
            if old != target and old.is_dir() and not old.is_symlink():
                shutil.rmtree(old, ignore_errors=True)
        say('The full-screen installer is ready. Start it with:  bash ' + str(HERE.parent / 'install.sh'))
        return 0
    except (OSError, ProvisionError, subprocess.SubprocessError, zipfile.BadZipFile) as error:
        say(f'Full-screen installer setup failed: {error}')
        say('Nothing on the VM was changed. The plain installer still works:  bash '
            + str(HERE.parent / 'install.sh') + ' --plain')
        return 1
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)


def launch(env, extra=()):
    """Run the full-screen installer from its environment and return its exit status. It
    exits 75 only if it stopped before changing anything (the caller may then offer the
    plain menu); every other status is final."""
    argv = [str(venv_python(target_dir(env))), '-I', str(LAUNCH), *extra]
    process = subprocess.Popen(argv)
    while True:
        try:
            return process.wait()
        except KeyboardInterrupt:
            # The full-screen installer owns Ctrl+C (its own confirmation, or the step's while
            # the terminal is handed over); this waiting parent must not exit underneath it.
            continue
