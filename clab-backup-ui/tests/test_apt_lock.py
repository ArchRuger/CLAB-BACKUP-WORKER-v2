import importlib.util
import io
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('apt_lock', Path(__file__).resolve().parents[2] / 'deploy/apt_lock.py')
apt_lock = importlib.util.module_from_spec(spec)
spec.loader.exec_module(apt_lock)


def make_proc(root, pid, comm='unattended-upgr', cmdline=('/usr/bin/unattended-upgrade',), fds=()):
    """Build a fake /proc/<pid> with a comm file, a cmdline file and fd symlinks."""
    proc_dir = Path(root) / str(pid)
    fd_dir = proc_dir / 'fd'
    fd_dir.mkdir(parents=True)
    (proc_dir / 'comm').write_text(comm + '\n')
    (proc_dir / 'cmdline').write_bytes(b'\0'.join(part.encode() for part in cmdline) + b'\0')
    for index, target in enumerate(fds):
        os.symlink(target, fd_dir / str(index))
    return proc_dir


class HoldersTests(unittest.TestCase):
    def test_finds_current_holder_of_a_tracked_lock(self):
        with tempfile.TemporaryDirectory() as root:
            make_proc(root, 2230, comm='unattended-upgr', fds=['/var/lib/dpkg/lock-frontend', '/dev/null'])
            found = apt_lock.holders(proc_root=root)
        self.assertEqual(found, [{'pid': 2230, 'comm': 'unattended-upgr',
                                  'cmdline': '/usr/bin/unattended-upgrade', 'path': '/var/lib/dpkg/lock-frontend'}])

    def test_ignores_unrelated_open_files(self):
        with tempfile.TemporaryDirectory() as root:
            make_proc(root, 100, fds=['/etc/hostname', '/dev/null'])
            self.assertEqual(apt_lock.holders(proc_root=root), [])

    def test_never_hard_codes_a_pid_reports_whichever_pid_actually_holds_it(self):
        for pid in (111, 99999):
            with tempfile.TemporaryDirectory() as root:
                make_proc(root, pid, comm='apt-get', fds=['/var/lib/dpkg/lock'])
                found = apt_lock.holders(proc_root=root)
            self.assertEqual(found[0]['pid'], pid)

    def test_multiple_holders_across_different_locks(self):
        with tempfile.TemporaryDirectory() as root:
            make_proc(root, 10, comm='apt-get', fds=['/var/lib/dpkg/lock'])
            make_proc(root, 20, comm='unattended-upgr', fds=['/var/lib/apt/lists/lock'])
            found = apt_lock.holders(proc_root=root)
        self.assertEqual({(h['pid'], h['path']) for h in found},
                         {(10, '/var/lib/dpkg/lock'), (20, '/var/lib/apt/lists/lock')})

    def test_unreadable_fd_directory_is_skipped_not_fatal(self):
        with tempfile.TemporaryDirectory() as root:
            proc_dir = Path(root) / '5'
            proc_dir.mkdir()  # no fd subdirectory: simulates a permission-denied listdir
            (proc_dir / 'comm').write_text('other\n')
            self.assertEqual(apt_lock.holders(proc_root=root), [])

    def test_missing_proc_root_returns_empty_not_an_exception(self):
        self.assertEqual(apt_lock.holders(proc_root='/no/such/proc/root'), [])


class WaitForReleaseTests(unittest.TestCase):
    def test_returns_true_immediately_when_already_free(self):
        with patch.object(apt_lock, 'holders', return_value=[]), patch.object(apt_lock, 'time') as mocked_time:
            ok = apt_lock.wait_for_release(timeout_seconds=60, report=lambda *_: None)
        self.assertTrue(ok)
        mocked_time.sleep.assert_not_called()

    def test_reports_the_current_holder_pid_and_comm_and_a_time_left(self):
        reports = []
        holder_sequence = [[{'pid': 2230, 'comm': 'unattended-upgr', 'cmdline': '', 'path': '/var/lib/dpkg/lock-frontend'}], []]
        with patch.object(apt_lock, 'holders', side_effect=holder_sequence), patch.object(apt_lock.time, 'sleep'):
            ok = apt_lock.wait_for_release(timeout_seconds=300, poll_seconds=1, report=reports.append)
        self.assertTrue(ok)
        self.assertEqual(len(reports), 1)
        self.assertIn('pid 2230', reports[0])
        self.assertIn('unattended-upgr', reports[0])
        self.assertIn('/var/lib/dpkg/lock-frontend', reports[0])
        self.assertIn('left)', reports[0])

    def test_changed_pid_between_polls_is_reported_as_the_new_holder(self):
        reports = []
        holder_sequence = [
            [{'pid': 111, 'comm': 'apt-get', 'cmdline': '', 'path': '/var/lib/dpkg/lock-frontend'}],
            [{'pid': 222, 'comm': 'dpkg', 'cmdline': '', 'path': '/var/lib/dpkg/lock-frontend'}],
            [],
        ]
        with patch.object(apt_lock, 'holders', side_effect=holder_sequence), patch.object(apt_lock.time, 'sleep'):
            ok = apt_lock.wait_for_release(timeout_seconds=300, poll_seconds=1, report=reports.append)
        self.assertTrue(ok)
        self.assertEqual(len(reports), 2)
        self.assertIn('pid 111', reports[0])
        self.assertIn('pid 222', reports[1])

    def test_timeout_returns_false_without_releasing(self):
        holder = [{'pid': 1, 'comm': 'apt-get', 'cmdline': '', 'path': '/var/lib/dpkg/lock'}]
        with patch.object(apt_lock, 'holders', return_value=holder), patch.object(apt_lock.time, 'sleep'):
            ok = apt_lock.wait_for_release(timeout_seconds=0, poll_seconds=1, report=lambda *_: None)
        self.assertFalse(ok)

    def test_keyboard_interrupt_cancels_cleanly_and_calls_on_cancel(self):
        holder = [{'pid': 1, 'comm': 'apt-get', 'cmdline': '', 'path': '/var/lib/dpkg/lock'}]
        cancelled = []
        with patch.object(apt_lock, 'holders', return_value=holder), \
                patch.object(apt_lock.time, 'sleep', side_effect=KeyboardInterrupt):
            ok = apt_lock.wait_for_release(timeout_seconds=300, poll_seconds=1, report=lambda *_: None,
                                           on_cancel=lambda: cancelled.append(True))
        self.assertFalse(ok)
        self.assertEqual(cancelled, [True])

    def test_pause_timers_stops_only_active_ones_and_always_restores_them(self):
        calls = []

        def runner(args, **kwargs):
            calls.append(list(args))
            if args[1] == 'is-active':
                active = args[2] == 'apt-daily.timer'
                return subprocess.CompletedProcess(args, 0, stdout='active\n' if active else 'inactive\n')
            return subprocess.CompletedProcess(args, 0, stdout='')

        holder_sequence = [[{'pid': 1, 'comm': 'apt-get', 'cmdline': '', 'path': '/var/lib/dpkg/lock'}], []]
        with patch.object(apt_lock, 'holders', side_effect=holder_sequence), patch.object(apt_lock.time, 'sleep'):
            ok = apt_lock.wait_for_release(timeout_seconds=300, poll_seconds=1, report=lambda *_: None,
                                           pause_timers=True, runner=runner)
        self.assertTrue(ok)
        stop_calls = [c for c in calls if c[1] == 'stop']
        start_calls = [c for c in calls if c[1] == 'start']
        self.assertEqual(stop_calls, [['systemctl', 'stop', 'apt-daily.timer']])
        self.assertEqual(start_calls, [['systemctl', 'start', 'apt-daily.timer']])

    def test_pause_timers_restores_on_timeout(self):
        started = []

        def runner(args, **kwargs):
            if args[1] == 'is-active':
                return subprocess.CompletedProcess(args, 0, stdout='active\n')
            if args[1] == 'start':
                started.append(args[2])
            return subprocess.CompletedProcess(args, 0, stdout='')

        holder = [{'pid': 1, 'comm': 'apt-get', 'cmdline': '', 'path': '/var/lib/dpkg/lock'}]
        with patch.object(apt_lock, 'holders', return_value=holder), patch.object(apt_lock.time, 'sleep'):
            ok = apt_lock.wait_for_release(timeout_seconds=0, poll_seconds=1, report=lambda *_: None,
                                           pause_timers=True, runner=runner)
        self.assertFalse(ok)
        self.assertEqual(started, ['apt-daily.timer', 'apt-daily-upgrade.timer'])

    def test_pause_timers_restores_on_keyboard_interrupt(self):
        started = []

        def runner(args, **kwargs):
            if args[1] == 'is-active':
                return subprocess.CompletedProcess(args, 0, stdout='active\n')
            if args[1] == 'start':
                started.append(args[2])
            return subprocess.CompletedProcess(args, 0, stdout='')

        holder = [{'pid': 1, 'comm': 'apt-get', 'cmdline': '', 'path': '/var/lib/dpkg/lock'}]
        with patch.object(apt_lock, 'holders', return_value=holder), \
                patch.object(apt_lock.time, 'sleep', side_effect=KeyboardInterrupt):
            ok = apt_lock.wait_for_release(timeout_seconds=300, poll_seconds=1, report=lambda *_: None,
                                           pause_timers=True, runner=runner)
        self.assertFalse(ok)
        self.assertEqual(started, ['apt-daily.timer', 'apt-daily-upgrade.timer'])


class FormatDurationTests(unittest.TestCase):
    def test_formats_minutes_and_seconds(self):
        self.assertEqual(apt_lock._format_duration(130), '2m10s')
        self.assertEqual(apt_lock._format_duration(5), '0m05s')
        self.assertEqual(apt_lock._format_duration(-4), '0m00s')


class CliTests(unittest.TestCase):
    def test_show_prints_holder_and_never_waits(self):
        holder = [{'pid': 2230, 'comm': 'unattended-upgr', 'cmdline': '', 'path': '/var/lib/dpkg/lock-frontend'}]
        with patch.object(apt_lock, 'holders', return_value=holder), \
                patch.object(apt_lock, 'wait_for_release') as wait, \
                patch('sys.stdout', new=io.StringIO()) as out:
            code = apt_lock.main(['--show'])
        self.assertEqual(code, 0)
        wait.assert_not_called()
        self.assertIn('pid 2230', out.getvalue())
        self.assertIn('unattended-upgr', out.getvalue())

    def test_show_warns_about_never_killing_or_deleting_when_a_holder_exists(self):
        holder = [{'pid': 2230, 'comm': 'unattended-upgr', 'cmdline': '', 'path': '/var/lib/dpkg/lock-frontend'}]
        with patch.object(apt_lock, 'holders', return_value=holder), patch('sys.stdout', new=io.StringIO()) as out:
            apt_lock.main(['--show'])
        self.assertIn('Never stop unattended-upgrades.service', out.getvalue())
        self.assertIn('kill', out.getvalue().lower())
        self.assertIn('delete', out.getvalue().lower())

    def test_wait_already_released_exits_zero_without_waiting(self):
        with patch.object(apt_lock, 'holders', return_value=[]), \
                patch.object(apt_lock, 'wait_for_release') as wait, patch('sys.stdout', new=io.StringIO()):
            code = apt_lock.main(['--wait'])
        self.assertEqual(code, 0)
        wait.assert_not_called()

    def test_wait_reaching_timeout_exits_one(self):
        holder = [{'pid': 1, 'comm': 'apt-get', 'cmdline': '', 'path': '/var/lib/dpkg/lock'}]
        with patch.object(apt_lock, 'holders', return_value=holder), \
                patch.object(apt_lock, 'wait_for_release', return_value=False), patch('sys.stdout', new=io.StringIO()):
            code = apt_lock.main(['--wait', '--timeout', '1'])
        self.assertEqual(code, 1)

    def test_wait_released_exits_zero(self):
        holder = [{'pid': 1, 'comm': 'apt-get', 'cmdline': '', 'path': '/var/lib/dpkg/lock'}]
        with patch.object(apt_lock, 'holders', return_value=holder), \
                patch.object(apt_lock, 'wait_for_release', return_value=True), patch('sys.stdout', new=io.StringIO()):
            code = apt_lock.main(['--wait'])
        self.assertEqual(code, 0)

    def test_wait_cancelled_exits_130(self):
        holder = [{'pid': 1, 'comm': 'apt-get', 'cmdline': '', 'path': '/var/lib/dpkg/lock'}]

        def fake_wait(*args, on_cancel=None, **kwargs):
            on_cancel()
            return False

        with patch.object(apt_lock, 'holders', return_value=holder), \
                patch.object(apt_lock, 'wait_for_release', side_effect=fake_wait), patch('sys.stdout', new=io.StringIO()):
            code = apt_lock.main(['--wait'])
        self.assertEqual(code, 130)

    def test_pause_timers_flag_is_forwarded(self):
        holder = [{'pid': 1, 'comm': 'apt-get', 'cmdline': '', 'path': '/var/lib/dpkg/lock'}]
        with patch.object(apt_lock, 'holders', return_value=holder), \
                patch.object(apt_lock, 'wait_for_release', return_value=True) as wait, patch('sys.stdout', new=io.StringIO()):
            apt_lock.main(['--wait', '--pause-timers', '--timeout', '30'])
        self.assertEqual(wait.call_args.kwargs['pause_timers'], True)
        self.assertEqual(wait.call_args.kwargs['timeout_seconds'], 30)

    def test_requires_wait_or_show(self):
        with patch('sys.stderr', new=io.StringIO()):
            with self.assertRaises(SystemExit):
                apt_lock.main([])


if __name__ == '__main__':
    unittest.main()
