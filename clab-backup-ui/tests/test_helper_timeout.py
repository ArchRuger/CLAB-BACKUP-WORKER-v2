"""The installed discovery helper must bound containerlab inspect by a realistic limit."""
import io
import json
import threading
import unittest
from unittest.mock import patch

from app import host_files


class FakeProcess:
    """Stand-in for Popen: stdout blocks until the watchdog kills the process."""
    def __init__(self, output=b'', finish=None):
        self.finished = threading.Event()
        self.output = output
        self.finish = finish
        self.returncode = None
        self.stdout = self

    def read(self, limit):
        if self.finish is not None: self.finish.wait()
        self.finished.wait(10)
        return self.output[:limit]

    def wait(self, timeout=None):
        self.finished.wait(timeout)
        return self.returncode

    def poll(self):
        return self.returncode

    def kill(self):
        self.returncode = -9
        self.finished.set()

    def close(self):
        pass


class HelperTimeoutTests(unittest.TestCase):
    def test_inspect_allows_more_than_eight_seconds_and_labels_stay_short(self):
        self.assertGreaterEqual(host_files.INSPECT_TIMEOUT, 20)
        self.assertLessEqual(host_files.INSPECT_TIMEOUT + 18, 60, 'helper budget must fit the manager deadline')
        self.assertLessEqual(host_files.LABEL_TIMEOUT, 10)

    def test_expired_watchdog_reports_timeout_not_permission_failure(self):
        process = FakeProcess()
        with patch.object(host_files.subprocess, 'Popen', return_value=process):
            with self.assertRaisesRegex(TimeoutError, 'exceeded 0.05 seconds'):
                host_files.command_json(['clab', 'inspect'], timeout=.05)
        self.assertEqual(process.returncode, -9)

    def test_completed_output_within_limit_is_parsed(self):
        finish = threading.Event()
        process = FakeProcess(json.dumps({'lab': []}).encode(), finish)
        process.returncode = 0
        finish.set(); process.finished.set()
        with patch.object(host_files.subprocess, 'Popen', return_value=process):
            self.assertEqual(host_files.command_json(['clab', 'inspect'], timeout=5), {'lab': []})

    def test_main_distinguishes_timeout_on_stderr_without_output(self):
        stderr = io.StringIO(); stdout = io.StringIO()
        with patch.object(host_files, 'command_json', side_effect=TimeoutError('slow')), \
             patch.object(host_files.sys, 'argv', ['helper', '/usr/bin/containerlab', '/usr/bin/docker']), \
             patch.object(host_files.sys, 'stderr', stderr), patch.object(host_files.sys, 'stdout', stdout):
            self.assertEqual(host_files.main(), 1)
        self.assertIn(str(host_files.INSPECT_TIMEOUT) + ' seconds', stderr.getvalue())
        self.assertIn('permissions are not indicated', stderr.getvalue())
        self.assertEqual(stdout.getvalue(), '')


if __name__ == '__main__':
    unittest.main()
