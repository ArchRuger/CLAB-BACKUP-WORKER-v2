#!/usr/bin/env python3
"""dpkg/APT package-lock inspection and a bounded wait for its release.

Usable as a module (`holders()`, `wait_for_release()`) or as a command, normally
run with sudo so the /proc scan can see another account's file descriptors.
Nothing here kills a process, deletes a lock file, or stops
unattended-upgrades.service; `--pause-timers` only stops the daily *timers* for
the duration of the wait (never starting a new run during it) and always
restores exactly the ones it stopped, including on a timeout or Ctrl+C.
"""
import argparse
import os
import subprocess
import sys
import time

DEFAULT_LOCKS = (
    '/var/lib/dpkg/lock-frontend',
    '/var/lib/dpkg/lock',
    '/var/lib/apt/lists/lock',
    '/var/cache/apt/archives/lock',
)

TIMERS = ('apt-daily.timer', 'apt-daily-upgrade.timer')

WARNING = ('Never stop unattended-upgrades.service, kill this process, or delete the lock '
           'file: let the current run finish, or wait it out here.')


def _read_text(path):
    try:
        with open(path, 'r', errors='replace') as stream:
            return stream.read()
    except OSError:
        return ''


def _comm(proc_root, pid):
    return _read_text(os.path.join(proc_root, pid, 'comm')).strip()


def _cmdline(proc_root, pid):
    try:
        with open(os.path.join(proc_root, pid, 'cmdline'), 'rb') as stream:
            raw = stream.read()
    except OSError:
        return ''
    return ' '.join(part.decode('utf-8', 'replace') for part in raw.split(b'\0') if part)


def running_as_root():
    return hasattr(os, 'geteuid') and os.geteuid() == 0


def holders(paths=DEFAULT_LOCKS, proc_root='/proc'):
    """Current holders of any of paths: [{pid, comm, cmdline, path}], never a hard-coded PID.

    Reading another account's open files needs root; without it this returns
    only what this account's own /proc access allows (usually nothing useful
    for the dpkg locks, since they are held by a root-owned apt/dpkg process).
    """
    wanted = {os.path.normpath(path) for path in paths}
    found = []
    try:
        pids = sorted((name for name in os.listdir(proc_root) if name.isdigit()), key=int)
    except OSError:
        return found
    for pid in pids:
        fd_dir = os.path.join(proc_root, pid, 'fd')
        try:
            fd_names = os.listdir(fd_dir)
        except OSError:
            continue  # not readable: another account's process, or it has already exited
        matched = set()
        for fd_name in fd_names:
            try:
                target = os.readlink(os.path.join(fd_dir, fd_name))
            except OSError:
                continue
            normalized = os.path.normpath(target)
            if normalized in wanted:
                matched.add(normalized)
        for path in sorted(matched):
            found.append({'pid': int(pid), 'comm': _comm(proc_root, pid),
                          'cmdline': _cmdline(proc_root, pid), 'path': path})
    return found


def _systemctl(args, runner=None):
    runner = runner or subprocess.run
    return runner(['systemctl', *args], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)


def active_timers(names=TIMERS, runner=None):
    active = []
    for name in names:
        try:
            result = _systemctl(['is-active', name], runner=runner)
        except OSError:
            continue
        if result.returncode == 0 and result.stdout.strip() == 'active':
            active.append(name)
    return active


def stop_timers(names, runner=None):
    for name in names:
        try:
            _systemctl(['stop', name], runner=runner)
        except OSError:
            pass


def start_timers(names, runner=None):
    for name in names:
        try:
            _systemctl(['start', name], runner=runner)
        except OSError:
            pass


def _format_duration(seconds):
    seconds = max(0, int(seconds))
    minutes, secs = divmod(seconds, 60)
    return f'{minutes}m{secs:02d}s'


def wait_for_release(timeout_seconds=900, poll_seconds=2, report=print, paths=DEFAULT_LOCKS,
                      proc_root='/proc', pause_timers=False, runner=None, on_cancel=None):
    """Bounded wait for every lock in paths to have no holder.

    Returns True once released, False on timeout. A KeyboardInterrupt during the
    wait is cancelled cleanly: any paused timers are restored and False is
    returned; on_cancel(), when given, is called first so a caller (the CLI) can
    tell a cancellation apart from a timeout.
    """
    paused = []
    if pause_timers:
        paused = active_timers(runner=runner)
        if paused:
            report('Pausing while waiting (future starts only; restored after the wait): ' + ', '.join(paused))
            stop_timers(paused, runner=runner)
    deadline = time.monotonic() + max(0, timeout_seconds)
    try:
        while True:
            found = holders(paths, proc_root=proc_root)
            if not found:
                return True
            current = found[0]
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            report(f"Waiting for pid {current['pid']} ({current['comm']}) to release "
                   f"{current['path']} ({_format_duration(remaining)} left)")
            time.sleep(min(max(0, poll_seconds), max(0, remaining)))
    except KeyboardInterrupt:
        if on_cancel is not None:
            on_cancel()
        return False
    finally:
        if paused:
            start_timers(paused, runner=runner)


def _describe(found):
    lines = []
    if not found:
        lines.append('No current holder found for the tracked package locks.')
        return lines
    for holder in found:
        lines.append(f"Package lock held by pid {holder['pid']} ({holder['comm'] or 'unknown'}) on {holder['path']}.")
    lines.append(WARNING)
    return lines


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--wait', action='store_true', help='Wait until the tracked package locks are free.')
    action.add_argument('--show', action='store_true', help='Print the current holder(s) and exit.')
    parser.add_argument('--timeout', type=int, default=900, help='Seconds to wait (default 900).')
    parser.add_argument('--pause-timers', action='store_true',
                        help='Stop the active apt-daily timer(s) for the wait; always restored afterwards.')
    args = parser.parse_args(argv)
    if not running_as_root():
        print('Not running as root: only locks held by this account are visible here; use sudo for a complete view.')
    found = holders()
    for line in _describe(found):
        print(line)
    if args.show:
        return 0
    if not found:
        print('The package lock is already released.')
        return 0
    cancelled = []
    ok = wait_for_release(timeout_seconds=args.timeout, pause_timers=args.pause_timers,
                          on_cancel=lambda: cancelled.append(True))
    if cancelled:
        print('Cancelled; any paused timer was restored.')
        return 130
    if ok:
        print('The package lock is released.')
        return 0
    print(f'Timed out after {args.timeout}s waiting for the package lock to release.')
    return 1


if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
