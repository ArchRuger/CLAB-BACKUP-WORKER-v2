"""Process, lock and result plumbing shared by the full-screen installer (standard library only).

Nothing here decides *what* the installer does: the plan, the helper argv and the
recovery rules come from install-manager.py, which the plain menu uses unchanged.
This module only runs a non-interactive step as a child process whose output is
streamed as inert text, keeps the one-installer-at-a-time lock, and records a
metadata-only summary of a run.
"""
import errno
import json
import os
from pathlib import Path
import re
import select
import stat
import subprocess
import threading
import time
from collections import deque

try:
    import fcntl
except ImportError:  # pragma: no cover - Linux only; plain mode reports the platform first
    fcntl = None

from . import sanitize

# `sudo -n` with expired credentials (or none cached for this terminal) prints this and exits 1.
AUTH_SIGNATURE = re.compile(r'sudo: (?:a password is required|a terminal is required)', re.I)
TAIL_LINES = 4000


class Busy(ValueError):
    """Another installer run holds the lock."""


class LockUnusable(OSError):
    """The installer lock file exists but cannot serve as the lock (planted symlink, unreadable or not a
    regular file). Nothing was changed; the message names the file an administrator can remove."""

    def __init__(self, path, why):
        super().__init__(errno.EACCES, f'{path} cannot be used as the installer lock ({why}); '
                         f'an administrator can remove it with: sudo rm -f {path}')

    def __str__(self):
        return self.strerror


class InstallerLock:
    """One mutating installer run per VM, whichever account or checkout starts it.

    An advisory flock on a fixed file under /run/lock (a root-owned sticky tmpfs on
    Ubuntu). The kernel drops it when every holder exits, so it is never stale; the
    full-screen installer passes the descriptor to its step processes so the lock
    also outlives an installer that is killed while a step is still running. It is
    not APT's lock and never touches /var/lib/dpkg.

    The directory is world-writable, so another account could plant the name first. A
    symlink is never followed. A file that cannot be opened, or is not a regular file, is
    reported as LockUnusable with the command that removes it. A privileged run replaces such
    a file (and takes over one an unprivileged account owns, so that account cannot remove it
    or squat the name again), but never one somebody holds. After every flock the path is
    checked to still name the locked file, so a swap between open and flock cannot leave two
    installers each holding "the" lock.
    """

    def __init__(self, path=None):
        self.path = Path(path) if path else default_lock_path()
        self.fd = None

    def acquire(self):
        if fcntl is None:
            return self
        for _ in range(5):
            fd, writable = self._open()
            if fd is None:
                continue   # a privileged run removed an unusable file: open a fresh one
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                holder = _read_holder(fd)
                os.close(fd)
                raise Busy('Another Containerlab Node Manager installer run is active'
                           + (f' ({holder})' if holder else '') + '. Wait for it to finish, then try again.')
            except BaseException:
                os.close(fd)
                raise
            if running_as_root() and os.fstat(fd).st_uid != 0:
                fd, writable = self._take_over(fd), True
                if fd is None:
                    continue
            if self._names(fd):
                break
            os.close(fd)   # the path was swapped after we opened it: lock the file that is there now
        else:
            raise LockUnusable(self.path, 'it keeps being replaced')
        if writable:
            try:
                os.ftruncate(fd, 0)
                os.write(fd, f'pid {os.getpid()}, account {_account()}, started {time.strftime("%H:%M:%S")}\n'.encode())
            except OSError:
                pass
        self.fd = fd
        return self

    def _open(self):
        """(fd, writable) for the lock file, creating it when missing; (None, False) after a privileged run
        removed an unusable file."""
        extra = getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_CLOEXEC', 0) | getattr(os, 'O_NONBLOCK', 0)   # a planted FIFO must not block the open
        try:
            try:
                fd, writable = os.open(self.path, os.O_RDWR | os.O_CREAT | extra, 0o644), True
                try:
                    os.fchmod(fd, 0o644)   # independent of umask, so every account can open it
                except OSError:
                    pass
            except PermissionError:
                # Created by another account: a read-only descriptor locks just as well.
                fd, writable = os.open(self.path, os.O_RDONLY | extra), False
        except OSError as error:
            return self._unusable(error.strerror or 'it cannot be opened'), False
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            os.close(fd)
            return self._unusable('it is not a regular file'), False
        return fd, writable

    def _unusable(self, why):
        if running_as_root():
            try:
                os.unlink(self.path)
                return None
            except OSError as error:
                why = error.strerror or why
        raise LockUnusable(self.path, why)

    def _take_over(self, old):
        """We hold the flock on a file an unprivileged account owns: put a root-owned file in its place
        (the account cannot delete it in the sticky directory) and lock that. Returns the new fd, or None
        when the name was raced and acquire should start over."""
        extra = getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_CLOEXEC', 0) | getattr(os, 'O_NONBLOCK', 0)   # a planted FIFO must not block the open
        try:
            os.unlink(self.path)
            fd = os.open(self.path, os.O_RDWR | os.O_CREAT | os.O_EXCL | extra, 0o644)
        except FileExistsError:
            os.close(old)
            return None
        os.close(old)
        try:
            os.fchmod(fd, 0o644)
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(fd)
            raise Busy('Another Containerlab Node Manager installer run is active. Wait for it to finish, then try again.')
        return fd

    def _names(self, fd):
        """Does the path still name the file this descriptor locks?"""
        try:
            now, mine = os.stat(self.path, follow_symlinks=False), os.fstat(fd)
        except OSError:
            return False
        return (now.st_dev, now.st_ino) == (mine.st_dev, mine.st_ino)

    def release(self, unlock=True):
        """Unlock and close. With unlock=False only this descriptor is closed: the kernel drops the
        lock when the last holder (for example a step child that inherited it) closes it."""
        if self.fd is not None:
            try:
                if unlock:
                    fcntl.flock(self.fd, fcntl.LOCK_UN)
            finally:
                os.close(self.fd)
                self.fd = None

    @property
    def held(self):
        return self.fd is not None

    def __enter__(self):
        return self.acquire()

    def __exit__(self, *exc):
        self.release()


def running_as_root():
    return hasattr(os, 'geteuid') and os.geteuid() == 0


def default_lock_path():
    base = Path('/run/lock')
    if not base.is_dir() or not os.access(base, os.W_OK | os.X_OK):
        base = Path('/tmp')   # fixed, not $TMPDIR: every invocation must agree on one file
    return base / 'clab-node-manager-installer.lock'


def _read_holder(fd):
    try:
        os.lseek(fd, 0, os.SEEK_SET)
        return sanitize.clean_line(os.read(fd, 200).decode('utf-8', 'replace').strip(), 120)
    except OSError:
        return ''


def _account():
    try:
        import pwd
        return pwd.getpwuid(os.geteuid()).pw_name
    except (ImportError, KeyError):
        return str(os.geteuid())


def noninteractive(argv):
    """The same command with `sudo -n`: on the piped path sudo must fail fast rather than
    open /dev/tty and prompt over the dashboard. Only the authentication mode changes;
    the helper, its options and its order are untouched."""
    argv = list(argv)
    if argv and argv[0] == 'sudo' and '-n' not in argv[1:2]:
        argv.insert(1, '-n')
    return argv


class StepProcess:
    """A non-interactive child: no terminal stdin, its own process group, output streamed.

    The process group keeps the child out of the shell's hangup and Ctrl+C delivery,
    so losing the SSH session lets the active step finish instead of killing an APT or
    Docker run halfway; it stays in this terminal's session so sudo's per-terminal
    credential cache still applies. Lines reach `on_lines` in batches (at most every
    `interval` seconds), already cleaned; a bounded tail is kept for inspection, and
    the lock/authentication signatures are recognised on the raw text as it passes.
    """

    def __init__(self, argv, env, cwd, on_lines=None, lock_signature=None, pass_fds=(), interval=0.1):
        self.argv = list(argv)
        self.env = env
        self.cwd = cwd
        self.on_lines = on_lines
        self.lock_signature = lock_signature
        self.pass_fds = tuple(fd for fd in pass_fds if fd is not None)
        self.interval = interval
        self.tail = deque(maxlen=TAIL_LINES)
        self.dropped = 0
        self.saw_lock = False
        self.saw_auth = False
        self.process = None
        self.returncode = None
        self.started = None
        self.finished = None

    def start(self):
        self.started = time.monotonic()
        self.process = subprocess.Popen(
            self.argv, cwd=self.cwd, env=self.env, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, process_group=0,
            pass_fds=self.pass_fds, bufsize=0)
        return self

    @property
    def pid(self):
        return self.process.pid if self.process else None

    def _emit(self, batch):
        if batch and self.on_lines:
            self.on_lines(batch)

    def _note(self, raw, batch):
        if self.lock_signature is not None and self.lock_signature.search(raw):
            self.saw_lock = True
        if AUTH_SIGNATURE.search(raw):
            self.saw_auth = True
        line = sanitize.clean_line(raw)
        if len(self.tail) == self.tail.maxlen:
            self.dropped += 1
        self.tail.append(line)
        batch.append(line)

    def wait(self):
        """Read until EOF, then reap. Returns the exit status; never raises on child output."""
        stream = self.process.stdout
        pending = b''
        batch = []
        last = time.monotonic()
        while True:
            # Wake at least every interval so a quiet child's last lines are not held back.
            ready, _, _ = select.select([stream], [], [], self.interval)
            if not ready:
                if batch:
                    self._emit(batch)
                    batch = []
                    last = time.monotonic()
                continue
            chunk = stream.read(65536)
            if not chunk:
                break
            pending += chunk
            *lines, pending = pending.split(b'\n')
            if len(pending) > 65536:
                # No newline in a long run of output (a progress meter): show it in pieces.
                lines.append(pending)
                pending = b''
            for raw in lines:
                self._note(sanitize.decode(raw), batch)
            now = time.monotonic()
            if batch and (now - last >= self.interval or len(batch) >= 500):
                self._emit(batch)
                batch = []
                last = now
        if pending:
            self._note(sanitize.decode(pending), batch)
        self._emit(batch)
        stream.close()
        self.returncode = self.process.wait()
        self.finished = time.monotonic()
        return self.returncode

    def run(self):
        self.start()
        return self.wait()


def run_capture(argv, env, cwd, timeout=10):
    """A bounded read-only probe: no stdin, own process group, output cleaned. Returns
    (returncode or None on timeout/missing command, cleaned text)."""
    try:
        result = subprocess.run(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, timeout=timeout, process_group=0)
    except subprocess.TimeoutExpired:
        return None, 'timed out'
    except OSError as error:
        return None, str(error)
    text = sanitize.decode(result.stdout[:262144])
    return result.returncode, '\n'.join(sanitize.clean_line(line) for line in text.splitlines())


def state_dir(env):
    base = os.environ.get('XDG_STATE_HOME') or os.path.join(env.get('HOME', ''), '.local', 'state')
    return Path(base) / 'clab-node-manager'


def write_run_record(env, record):
    """Metadata only (step keys, states, exit codes, times): never output, settings or paths
    beyond the checkout. Written atomically with private permissions; failure is ignored."""
    try:
        folder = state_dir(env)
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        target = folder / 'installer-last-run.json'
        temporary = folder / '.installer-last-run.json.tmp'
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        with os.fdopen(fd, 'w') as stream:
            json.dump(record, stream, indent=1, sort_keys=True)
        os.replace(temporary, target)
    except OSError:
        pass


def read_run_record(env):
    try:
        path = state_dir(env) / 'installer-last-run.json'
        if path.is_symlink() or path.stat().st_size > 65536:
            return None
        value = json.loads(path.read_text())
        return value if isinstance(value, dict) else None
    except (OSError, ValueError):
        return None


class Signal:
    """A one-shot flag the UI thread sets and the run thread polls (stop after step, hang-up)."""

    def __init__(self):
        self._event = threading.Event()
        self.reason = ''

    def set(self, reason=''):
        if not self._event.is_set():
            self.reason = reason
        self._event.set()

    def __bool__(self):
        return self._event.is_set()
