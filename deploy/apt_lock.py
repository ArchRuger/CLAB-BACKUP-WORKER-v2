#!/usr/bin/env python3
"""dpkg/APT package-lock inspection and a bounded wait for its release.

Usable as a module (`holders()`, `wait_for_release()`) or as a command, normally
run with sudo so the /proc scan can see another account's file descriptors.
Nothing here kills a process, deletes a lock file, or stops
unattended-upgrades.service; `--pause-timers` only stops the daily *timers* for
the duration of the wait (never starting a new run during it) and, once the
wait ends, starts again exactly the ones it stopped: on release, on a timeout,
on Ctrl+C, on a terminal hangup (SIGHUP, for example a dropped SSH session) and
on SIGTERM, even when such a signal arrives while the restore itself is running
(the restore holds those signals back, keeps starting the remaining timers after
an interruption and re-raises it only when all are started). Every retry is
bounded: a call interrupted again and again is tried three times, so a signal
sent without pause (a held-down Ctrl+C) can still defeat it, though only before
the signals are held back. What it cannot cover: SIGKILL (also the kernel's
out-of-memory kill) and SIGQUIT, whose default action ends the process without
running any Python, a power loss or a crash of the VM, and a `systemctl start`
that itself fails (its exit status is not checked). A timer left stopped that way
is only stopped, not disabled, so it returns at the next boot.
"""
import argparse
import os
import signal
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

# Set up once at import so that the restore needs no call before its first guarded line; every retry loop
# below is bounded by this tuple (a loop over a constant tuple runs no call that could be interrupted).
_HELD = frozenset({signal.SIGHUP, signal.SIGTERM, signal.SIGINT})
_ATTEMPTS = (1, 2, 3)

WARNING = ('Never stop unattended-upgrades.service, kill this process, or delete the lock '
           'file: let the current run finish, or wait it out here.')
# Advice only: nothing here restarts anything. Right after a VM snapshot rollback (or a reboot) the
# restored system's own unattended upgrade is usually the holder, and a normal restart of the VM is
# the other way out of it; the installer keeps every completed step and can simply be run again.
RESTART_HINT = ('If this appears right after a VM snapshot rollback or a reboot, a normal restart of the VM '
                'also clears it (Ubuntu lets the running upgrade finish before it shuts down); every completed '
                'setup step is kept, so run the installer again afterwards.')


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
    """Start every name again. A KeyboardInterrupt (a signal handler's way of ending the run) does not skip a
    timer: the one being started is tried again, at most three attempts per timer (the interrupted systemctl
    may not have finished), and the first interruption is re-raised only after every timer has had its start."""
    interrupted = None
    for name in names:
        for _attempt in _ATTEMPTS:
            try:
                _systemctl(['start', name], runner=runner)
            except OSError:
                pass
            except KeyboardInterrupt as error:
                interrupted = interrupted or error
                continue
            break
    if interrupted is not None:
        raise interrupted


def _restore_timers(names, runner=None):
    """Start the paused timers with SIGHUP, SIGTERM and SIGINT held back; returns the first KeyboardInterrupt
    that arrived while it ran (or None) instead of raising it, so the caller knows every timer was started.
    A handler that runs before the block takes effect (CPython also checks pending signals inside
    pthread_sigmask itself) raises KeyboardInterrupt there, so the block is repeated (three attempts); one
    that arrives before this function's first guarded line escapes, and the caller calls it again."""
    masked = hasattr(signal, 'pthread_sigmask')
    interrupted = None
    if masked:
        for _attempt in _ATTEMPTS:
            try:
                signal.pthread_sigmask(signal.SIG_BLOCK, _HELD)
            except KeyboardInterrupt as error:
                interrupted = interrupted or error   # the mask may or may not be set yet: block again (harmless)
                continue
            break
    try:
        start_timers(names, runner=runner)
    except KeyboardInterrupt as error:
        interrupted = interrupted or error
    finally:
        if masked:
            # Delivers a signal that was held meanwhile (its handler raises KeyboardInterrupt here, after the
            # mask was already lifted, so the call is not repeated once it has returned or raised).
            try:
                signal.pthread_sigmask(signal.SIG_UNBLOCK, _HELD)
            except KeyboardInterrupt as error:
                interrupted = interrupted or error
    return interrupted


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
    tell a cancellation apart from a timeout. A signal that arrives after the wait
    ended, while the timers are being restored, still has every timer started
    first and is then raised as KeyboardInterrupt instead of the return value.
    Each retry is bounded (three attempts per call, see the module notes), and
    SIGKILL, SIGQUIT and a crash are not covered at all.
    """
    paused = []
    deadline = time.monotonic() + max(0, timeout_seconds)
    try:
        # Inside the try: an interruption half way through stopping the timers still restores them
        # (starting a timer that was never stopped is harmless).
        if pause_timers:
            paused = active_timers(runner=runner)
            if paused:
                report('Pausing while waiting (future starts only; restored after the wait): ' + ', '.join(paused))
                stop_timers(paused, runner=runner)
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
            # Nothing but a try comes before the first call, and the call sits inside it: an interruption
            # at the callee's entry or in its unguarded first line is caught here and the restore is run
            # again (starting a timer twice is harmless). The first interruption is raised once the restore
            # has run to its end.
            interrupted = None
            for _attempt in _ATTEMPTS:
                try:
                    outcome = _restore_timers(paused, runner=runner)
                except KeyboardInterrupt as error:
                    interrupted = interrupted or error
                    continue
                interrupted = interrupted or outcome
                break
            if interrupted is not None:
                raise interrupted


def _hangup_as_interrupt(signum, frame):
    # The first hangup/terminate ends the wait like Ctrl+C, so the finally in wait_for_release restores the
    # timers; a repeat must not cut that restore short.
    signal.signal(signal.SIGHUP, signal.SIG_IGN)
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    raise KeyboardInterrupt


def _describe(found):
    lines = []
    if not found:
        lines.append('No current holder found for the tracked package locks.')
        return lines
    for holder in found:
        lines.append(f"Package lock held by pid {holder['pid']} ({holder['comm'] or 'unknown'}) on {holder['path']}.")
    lines.append(WARNING)
    lines.append(RESTART_HINT)
    return lines


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--wait', action='store_true', help='Wait until the tracked package locks are free.')
    action.add_argument('--show', action='store_true', help='Print the current holder(s) and exit.')
    parser.add_argument('--timeout', type=int, default=900, help='Seconds to wait (default 900).')
    parser.add_argument('--pause-timers', action='store_true',
                        help='Stop the active apt-daily timer(s) for the wait; started again afterwards (see the module notes for what '
                             'cannot be covered: SIGKILL, SIGQUIT, a crash).')
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
    previous = {name: signal.signal(name, _hangup_as_interrupt) for name in (signal.SIGHUP, signal.SIGTERM)}
    try:
        try:
            ok = wait_for_release(timeout_seconds=args.timeout, pause_timers=args.pause_timers,
                                  on_cancel=lambda: cancelled.append(True))
        except KeyboardInterrupt:
            ok = False   # a signal held back while the timers were restored: the timers are back, the run is cancelled
            cancelled.append(True)
    finally:
        for name, handler in previous.items():
            signal.signal(name, handler)
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
