import importlib.util
import io
from pathlib import Path
import subprocess
import unittest
from unittest.mock import MagicMock, patch


spec = importlib.util.spec_from_file_location(
    'apt_update', Path(__file__).resolve().parents[2] / 'deploy/apt_update.py')
apt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(apt)


FUTURE_ERROR = (
    'E: Release file for http://us.archive.ubuntu.com/ubuntu/dists/noble-updates/InRelease '
    'is not valid yet (invalid for another 3h 2min 52s). '
    'Updates for this repository will not be applied.\n'
)
EXPIRED_ERROR = (
    'E: Release file for http://archive.ubuntu.com/ubuntu/dists/noble-updates/InRelease '
    'is expired (invalid since 1d 2h 3min 4s). '
    'Updates for this repository will not be applied.\n'
)
SYNCED = {'CanNTP': 'yes', 'NTP': 'yes', 'NTPSynchronized': 'yes'}
SYNCING = {'CanNTP': 'yes', 'NTP': 'yes', 'NTPSynchronized': 'no'}


class FakeClock:
    """Advance only when the preflight sleeps; no test waits in real time."""

    def __init__(self):
        self.now = 100.0
        self.sleeps = []

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        if seconds <= 0:
            raise AssertionError('Clock polling must use a positive bounded sleep')
        self.sleeps.append(seconds)
        self.now += seconds


class AptClockTests(unittest.TestCase):
    def test_read_clock_uses_read_only_timedatectl_with_timeout(self):
        result = subprocess.CompletedProcess([], 0, stdout=(
            'CanNTP=yes\nNTP=yes\nNTPSynchronized=no\n'), stderr='')
        with patch.object(apt.subprocess, 'run', return_value=result) as run:
            self.assertEqual(apt.read_clock(timeout=2), SYNCING)
        command = run.call_args.args[0]
        self.assertEqual(command[:2], ['timedatectl', 'show'])
        self.assertEqual(run.call_args.kwargs['timeout'], 2)
        self.assertNotIn('set-ntp', command)
        self.assertNotIn('set-time', command)

    def test_unavailable_failed_or_timed_out_clock_query_is_advisory(self):
        failures = [FileNotFoundError('no timedatectl'),
                    subprocess.TimeoutExpired(['timedatectl', 'show'], 3)]
        for failure in failures:
            with self.subTest(failure=type(failure).__name__), \
                    patch.object(apt.subprocess, 'run', side_effect=failure):
                self.assertEqual(apt.read_clock(), {})
        result = subprocess.CompletedProcess([], 1, stdout='NTP=yes\n', stderr='No system bus')
        with patch.object(apt.subprocess, 'run', return_value=result):
            self.assertEqual(apt.read_clock(), {})

    def test_synchronized_clock_does_not_delay_setup(self):
        with patch.object(apt, 'read_clock', return_value=SYNCED) as read, \
                patch.object(apt.time, 'sleep') as sleep, \
                patch('sys.stdout', new=io.StringIO()) as printed:
            apt.check_clock(wait_seconds=30)
        read.assert_called_once()
        sleep.assert_not_called()
        self.assertIn('UTC', printed.getvalue())

    def test_active_sync_waits_until_synchronized(self):
        clock = FakeClock()
        with patch.object(apt, 'read_clock', side_effect=[SYNCING, SYNCED]) as read, \
                patch.object(apt.time, 'monotonic', side_effect=clock.monotonic), \
                patch.object(apt.time, 'sleep', side_effect=clock.sleep), \
                patch('sys.stdout', new=io.StringIO()):
            apt.check_clock(wait_seconds=7)
        self.assertEqual(read.call_count, 2)
        self.assertTrue(clock.sleeps)
        self.assertLessEqual(sum(clock.sleeps), 7)

    def test_unsynchronized_clock_timeout_is_bounded_and_does_not_abort(self):
        clock = FakeClock()
        with patch.object(apt, 'read_clock', return_value=SYNCING) as read, \
                patch.object(apt.time, 'monotonic', side_effect=clock.monotonic), \
                patch.object(apt.time, 'sleep', side_effect=clock.sleep), \
                patch('sys.stdout', new=io.StringIO()):
            apt.check_clock(wait_seconds=3)
        self.assertGreater(read.call_count, 1)
        self.assertLessEqual(sum(clock.sleeps), 3)
        self.assertGreaterEqual(clock.now, 103)

    def test_disabled_unavailable_and_manual_clock_do_not_wait(self):
        states = [{}, {'CanNTP': 'no', 'NTP': 'no', 'NTPSynchronized': 'no'},
                  {'CanNTP': 'yes', 'NTP': 'no', 'NTPSynchronized': 'no'},
                  {'CanNTP': 'yes', 'NTP': 'no', 'NTPSynchronized': 'yes'}]
        for state in states:
            with self.subTest(state=state), \
                    patch.object(apt, 'read_clock', return_value=state), \
                    patch.object(apt.time, 'sleep') as sleep, \
                    patch('sys.stdout', new=io.StringIO()):
                apt.check_clock(wait_seconds=30)
            sleep.assert_not_called()

    def test_poll_query_timeout_is_limited_to_remaining_wait_budget(self):
        clock = FakeClock()
        queries = []

        def read_clock(timeout=3):
            if queries:
                self.assertLessEqual(timeout, 103 - clock.now)
                clock.now += timeout
            queries.append(timeout)
            return SYNCING

        with patch.object(apt, 'read_clock', side_effect=read_clock), \
                patch.object(apt.time, 'monotonic', side_effect=clock.monotonic), \
                patch.object(apt.time, 'sleep', side_effect=clock.sleep), \
                patch('sys.stdout', new=io.StringIO()):
            apt.check_clock(wait_seconds=3)
        self.assertGreater(len(queries), 1)
        self.assertLessEqual(clock.now, 103)

    def test_zero_wait_does_not_sleep_even_if_sync_is_pending(self):
        with patch.object(apt, 'read_clock', return_value=SYNCING), \
                patch.object(apt.time, 'sleep') as sleep, \
                patch('sys.stdout', new=io.StringIO()):
            apt.check_clock(wait_seconds=0)
        sleep.assert_not_called()


class AptUpdateTests(unittest.TestCase):
    def test_classifies_actual_future_release_error_and_expired_metadata(self):
        for line, expected in [(FUTURE_ERROR, 'future'), (EXPIRED_ERROR, 'expired'),
                               (FUTURE_ERROR.replace('E:', 'W:', 1), 'future')]:
            with self.subTest(line=line):
                self.assertEqual(apt.classify_error(line), expected)

    def test_classifies_media_error_without_mistaking_network_mirrors(self):
        line = "E: The repository 'file:/cdrom noble Release' no longer has a Release file.\n"
        self.assertEqual(apt.classify_error(line), 'media')
        self.assertIsNone(apt.classify_error(
            "E: The repository 'https://mirror.example/ubuntu noble Release' does not have a Release file.\n"))

    def test_unrelated_local_repository_is_not_classified_as_installer_media(self):
        self.assertIsNone(apt.classify_error(
            "E: The repository 'file:/cdrom-cache noble Release' does not have a Release file.\n"))

    def test_unrelated_failures_are_not_reported_as_clock_errors(self):
        lines = [
            'E: Could not get lock /var/lib/apt/lists/lock. It is held by process 42 (apt-get)',
            "E: The repository 'https://example.org noble InRelease' is not signed.",
            'W: GPG error: https://example.org noble InRelease: NO_PUBKEY 12345678',
            "W: Failed to fetch https://example.org/InRelease Temporary failure resolving 'example.org'",
            'Hit:1 http://archive.ubuntu.com/ubuntu noble InRelease',
            'Example: Release file is not valid yet',
        ]
        for line in lines:
            with self.subTest(line=line):
                self.assertIsNone(apt.classify_error(line))

    @staticmethod
    def process(output, status):
        process = MagicMock()
        process.stdout = io.StringIO(output)
        process.wait.return_value = status
        process.__enter__.return_value = process
        return process

    def test_update_streams_original_output_and_preserves_failure_status(self):
        output = 'Reading package lists... Done\n' + FUTURE_ERROR
        process = self.process(output, 100)
        with patch.object(apt, 'check_clock') as clock, \
                patch.object(apt.subprocess, 'Popen', return_value=process) as start, \
                patch.object(apt.subprocess, 'run', side_effect=AssertionError('Unexpected command')), \
                patch.object(apt, 'print_recovery') as recovery, \
                patch('sys.stdout', new=io.StringIO()) as printed:
            result = apt.update(wait_seconds=4)
        self.assertEqual(result, 100)
        self.assertIn(output, printed.getvalue())
        clock.assert_called_once()
        process.wait.assert_called_once()
        start.assert_called_once()
        self.assertEqual(start.call_args.args[0], ['apt-get', 'update', '--error-on=any'])
        self.assertEqual(start.call_args.kwargs['stderr'], subprocess.STDOUT)
        self.assertEqual(start.call_args.kwargs['stdout'], subprocess.PIPE)
        self.assertTrue(start.call_args.kwargs['text'])
        self.assertEqual(start.call_args.kwargs['env']['LC_ALL'], 'C.UTF-8')
        recovery.assert_called_once()
        self.assertIn('future', recovery.call_args.args[0])

    def test_failed_update_keeps_multiple_error_kinds_for_recovery(self):
        output = FUTURE_ERROR + "E: The repository 'file:/cdrom noble Release' no longer has a Release file.\n"
        with patch.object(apt, 'check_clock'), \
                patch.object(apt.subprocess, 'Popen', return_value=self.process(output, 100)), \
                patch.object(apt, 'print_recovery') as recovery, \
                patch('sys.stdout', new=io.StringIO()):
            self.assertEqual(apt.update(), 100)
        self.assertEqual(set(recovery.call_args.args[0]), {'future', 'media'})

    def test_unavailable_or_manual_clock_still_allows_valid_apt_update(self):
        for state in [{}, {'CanNTP': 'no', 'NTP': 'no', 'NTPSynchronized': 'no'}]:
            with self.subTest(state=state), \
                    patch.object(apt, 'read_clock', return_value=state), \
                    patch.object(apt.time, 'sleep') as sleep, \
                    patch.object(apt.subprocess, 'Popen', return_value=self.process('Reading package lists... Done\n', 0)), \
                    patch.object(apt, 'print_recovery') as recovery, \
                    patch('sys.stdout', new=io.StringIO()):
                self.assertEqual(apt.update(), 0)
            sleep.assert_not_called()
            recovery.assert_not_called()

    def test_generic_failure_preserves_exit_status_without_clock_classification(self):
        output = 'E: Could not get lock /var/lib/apt/lists/lock\n'
        with patch.object(apt, 'check_clock'), \
                patch.object(apt.subprocess, 'Popen', return_value=self.process(output, 42)), \
                patch.object(apt, 'print_recovery') as recovery, \
                patch('sys.stdout', new=io.StringIO()) as printed:
            self.assertEqual(apt.update(), 42)
        self.assertIn(output, printed.getvalue())
        self.assertFalse(set(recovery.call_args.args[0]) & {'future', 'expired'})

    def test_clock_recovery_names_time_tools_and_does_not_recommend_disabling_checks(self):
        for kind in ('future', 'expired'):
            with self.subTest(kind=kind), patch('sys.stdout', new=io.StringIO()) as printed:
                apt.print_recovery({kind})
            text = printed.getvalue()
            self.assertIn('timedatectl', text)
            self.assertNotIn('Check-Valid-Until=false', text)
            self.assertNotIn('Check-Date=false', text)
            self.assertNotIn('--allow-unauthenticated', text)


if __name__ == '__main__':
    unittest.main()
