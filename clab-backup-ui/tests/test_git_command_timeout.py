import os
import sys
import time
import unittest
from unittest.mock import Mock, patch

from app.host_git import command


class GitCommandTimeoutTests(unittest.TestCase):
    def test_timeout_stops_descendants_even_after_parent_exits(self):
        process = Mock(pid=1234)
        process.poll.return_value = 0
        process.wait.return_value = 0
        callbacks = []
        def timer(seconds, callback):
            callbacks.append(callback)
            return Mock()
        def read(limit):
            callbacks[0]()  # Parent exited, but an inherited stdout is still open.
            return b''
        process.stdout.read.side_effect = read
        with patch('app.host_git.subprocess.Popen', return_value=process), \
             patch('app.host_git.threading.Timer', side_effect=timer), \
             patch('app.host_git.os.name', 'posix'), \
             patch('app.host_git.os.killpg', create=True) as killpg:
            with self.assertRaisesRegex(ValueError, 'timed out'):
                command(['git', 'status'], '.', {}, timeout=.1)
        killpg.assert_called()
        process.stdout.close.assert_called_once()

    @unittest.skipUnless(sys.platform == 'linux', 'Requires Linux process-group cleanup')
    def test_real_inherited_stdout_is_closed_at_deadline(self):
        script = 'import subprocess,sys; subprocess.Popen([sys.executable,"-c","import time; time.sleep(8)"])'
        started = time.monotonic()
        with self.assertRaisesRegex(ValueError, 'timed out'):
            command([sys.executable, '-c', script], '.', dict(os.environ), timeout=.3)
        self.assertLess(time.monotonic() - started, 3)
