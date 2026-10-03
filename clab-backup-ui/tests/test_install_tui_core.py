"""Tests for the standard-library half of the full-screen installer (deploy/installer_tui).

Covers sanitize, core, bootstrap, probes and engine with real behaviour where it is cheap
(real child processes running tiny shell scripts, real flock, real zip files, a real
`python3 -m venv --without-pip`), and checks that the plan the engine runs is the plan
the plain install-manager menu runs. Standard library only; Textual is never imported.

Isolation: HOME, XDG_STATE_HOME and XDG_DATA_HOME point at a temp dir for every test, the
installer lock lives in a temp dir, `sudo` is never executed (credentials are patched, step
scripts are local `sh` scripts), and nothing touches the network or /srv.
"""
import importlib.util
import inspect
import io
import itertools
import json
import os
from pathlib import Path
import re
import shlex
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import zipfile

REPO = Path(__file__).resolve().parents[2]
DEPLOY = REPO / 'deploy'
if str(DEPLOY) not in sys.path:
    sys.path.insert(0, str(DEPLOY))

from installer_tui import bootstrap, core, engine, probes, sanitize  # noqa: E402

spec = importlib.util.spec_from_file_location('install_manager_for_tui_core', DEPLOY / 'install-manager.py')
install = importlib.util.module_from_spec(spec)
spec.loader.exec_module(install)

LOCK_TEXT = 'E: Could not get lock /var/lib/dpkg/lock-frontend. It is held by process 2230'


def wait_for(predicate, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


class IsolatedCase(unittest.TestCase):
    """A temp dir plus HOME / XDG_STATE_HOME / XDG_DATA_HOME inside it, for every test."""

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.tmp = Path(folder.name)
        (self.tmp / 'home').mkdir()
        patcher = patch.dict(os.environ, {'HOME': str(self.tmp / 'home'), 'XDG_STATE_HOME': str(self.tmp / 'state'),
                                          'XDG_DATA_HOME': str(self.tmp / 'data')})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.env = {'HOME': str(self.tmp / 'home'), 'USER': 'tester', 'PATH': os.environ.get('PATH', '/usr/bin:/bin')}

    def script(self, name, body):
        path = self.tmp / f'{name}.sh'
        path.write_text('#!/bin/sh\n' + body + '\n')
        path.chmod(0o755)
        return str(path)


# ---------------------------------------------------------------------------------------------
# 1. sanitize
# ---------------------------------------------------------------------------------------------
class SanitizeTests(unittest.TestCase):
    def test_csi_sequences_removed(self):
        self.assertEqual(sanitize.clean_line('\x1b[31mred\x1b[0m plain'), 'red plain')
        self.assertEqual(sanitize.clean_line('\x1b[2K\x1b[1Gprogress\x1b[?25l'), 'progress')
        self.assertEqual(sanitize.clean_line('\x1b[38;2;1;2;3mtrue\x1b[m'), 'true')

    def test_osc_title_set_removed_with_bel_and_with_string_terminator(self):
        self.assertEqual(sanitize.clean_line('\x1b]0;pwned title\x07visible'), 'visible')
        self.assertEqual(sanitize.clean_line('\x1b]2;pwned title\x1b\\visible'), 'visible')

    def test_osc_8_hyperlink_removed_keeping_only_the_link_text(self):
        line = '\x1b]8;;http://evil.example/\x1b\\click here\x1b]8;;\x1b\\ done'
        self.assertEqual(sanitize.clean_line(line), 'click here done')
        line = '\x1b]8;id=1;http://evil.example/\x07click\x1b]8;;\x07'
        self.assertEqual(sanitize.clean_line(line), 'click')

    def test_dcs_and_apc_strings_removed(self):
        self.assertEqual(sanitize.clean_line('\x1bPq#0;2;0;0;0\x1b\\after'), 'after')
        self.assertEqual(sanitize.clean_line('a\x1b_Gf=100;AAAA\x1b\\b'), 'ab')

    def test_eight_bit_c1_escapes_removed(self):
        self.assertEqual(sanitize.clean_line('\x9b31mred\x9b0m'), 'red')
        self.assertEqual(sanitize.clean_line('\x9d0;title\x9cok'), 'ok')
        self.assertEqual(sanitize.clean_line('\x9d0;title\x07ok'), 'ok')
        self.assertEqual(sanitize.clean_line('\x90qdata\x9cafter'), 'after')
        self.assertEqual(sanitize.clean_line('a\x85b\x80c'), 'abc')
        self.assertEqual(sanitize.clean_line('a\x9fapc-data\x9cb'), 'ab')

    def test_lone_escape_removed(self):
        self.assertEqual(sanitize.clean_line('abc\x1b'), 'abc')
        self.assertEqual(sanitize.clean_line('a\x1b\x01b'), 'ab')
        for text in ('\x1b', '\x1b\x1b\x1b', 'x\x1b é', '\x1b[', 'a\x1b]b'):
            with self.subTest(text=text):
                self.assertNotIn('\x1b', sanitize.clean_line(text))

    def test_c0_controls_except_tab_removed(self):
        self.assertEqual(sanitize.clean_line('a\x00b\x07c\x08d\x0be\x0cf\x7fg'), 'abcdefg')
        self.assertEqual(sanitize.clean_line('a\x01\x02\x03b\x1c\x1d\x1e\x1fc'), 'abc')
        out = sanitize.clean_line('a\tb')
        self.assertNotIn('\x07', out)
        self.assertEqual(out, 'a   b', 'a tab is kept as plain spacing, not removed')
        for code in itertools.chain(range(0, 9), range(11, 32), [0x7f]):
            if code in (0x0d, 0x1b):   # CR is the progress rule, ESC is covered by the escape tests
                continue
            with self.subTest(code=code):
                self.assertEqual(sanitize.clean_line('<' + chr(code) + '>'), '<>')

    def test_bidirectional_overrides_and_zero_width_characters_removed(self):
        for char in ('\u202e', '\u202d', '\u202a', '\u202c', '\u2066', '\u2067', '\u2068', '\u2069',
                     '\u200b', '\u200e', '\u200f', '\ufeff'):
            with self.subTest(char=hex(ord(char))):
                self.assertEqual(sanitize.clean_line('ab' + char + 'cd'), 'abcd')
        self.assertEqual(sanitize.clean_line('\u202eevil.txt\u202c'), 'evil.txt')

    def test_carriage_return_progress_keeps_the_final_segment(self):
        self.assertEqual(sanitize.clean_line('Downloading 10%\rDownloading 50%\rDownloading 100%'), 'Downloading 100%')
        self.assertEqual(sanitize.clean_line('abc\r'), 'abc')
        self.assertEqual(sanitize.clean_line('first\rsecond\r  \r'), 'second')
        self.assertEqual(sanitize.clean_line('\r'), '')
        self.assertEqual(sanitize.clean_line('done\n'), 'done')

    def test_long_line_cut_with_explicit_marker(self):
        out = sanitize.clean_line('x' * 3000)
        self.assertTrue(out.startswith('x' * sanitize.MAX_LINE))
        self.assertEqual(out[sanitize.MAX_LINE:], ' [... 1000 more characters not shown]')
        exact = 'y' * sanitize.MAX_LINE
        self.assertEqual(sanitize.clean_line(exact), exact)
        self.assertEqual(sanitize.clean_line('z' * 15, limit=10), 'z' * 10 + ' [... 5 more characters not shown]')

    def test_rich_and_textual_markup_stays_literal_text(self):
        for text in ('[bold red]x[/]', '[link=http://evil.example]click[/link]', '[on red]x[/on red]',
                     '[@click=app.quit]Quit[/]', 'array[0] = [1, 2]', '[/]'):
            with self.subTest(text=text):
                self.assertEqual(sanitize.clean_line(text), text)

    def test_tokens_passwords_and_private_keys_scrubbed(self):
        token = 'ghp_' + 'A1b2C3d4' * 5
        self.assertEqual(sanitize.clean_line(f'login with {token} now'), 'login with [token removed] now')
        pat = 'github_pat_' + 'Z9' * 20
        self.assertNotIn('Z9Z9', sanitize.clean_line('x ' + pat))
        self.assertEqual(sanitize.clean_line('token=abc123'), 'token=[removed]')
        self.assertEqual(sanitize.clean_line('Password: hunter2'), 'Password: [removed]')
        self.assertEqual(sanitize.clean_line('api_key = XYZ trailing'), 'api_key = [removed] trailing')
        self.assertEqual(sanitize.clean_line('API-KEY: k'), 'API-KEY: [removed]')
        self.assertEqual(sanitize.clean_line('secret=s'), 'secret=[removed]')
        self.assertEqual(sanitize.clean_line('-----BEGIN OPENSSH PRIVATE KEY-----b3BlbnNzaC1rZXk'),
                         '[private key removed]')
        self.assertEqual(sanitize.clean_line('prefix -----BEGIN PRIVATE KEY-----MIIE'), 'prefix [private key removed]')

    def test_scrubbing_happens_after_escape_removal_and_leaves_ordinary_text(self):
        self.assertEqual(sanitize.clean_line('pass\x1b[0mword=hunter2'), 'password=[removed]')
        for text in ('passwords are hard', 'tokenizer: fast', 'the secret garden', 'ghp_short'):
            with self.subTest(text=text):
                self.assertEqual(sanitize.clean_line(text), text)

    def test_decode_never_raises(self):
        self.assertIn('ok', sanitize.decode(b'\xff\xfeok'))
        self.assertEqual(sanitize.decode('héllo'.encode()), 'héllo')


# ---------------------------------------------------------------------------------------------
# 2. core.noninteractive
# ---------------------------------------------------------------------------------------------
class NoninteractiveTests(unittest.TestCase):
    def assert_same_but_n(self, argv):
        original = list(argv)
        result = core.noninteractive(argv)
        self.assertEqual(argv, original, 'the input list is never modified')
        self.assertIsNot(result, argv)
        self.assertEqual(len(result), len(original) + 1)
        self.assertEqual(result[0], 'sudo')
        self.assertEqual(result[1], '-n')
        for index, item in enumerate(original[1:], 2):
            self.assertEqual(result[index], item)

    def test_inserts_n_only_after_a_leading_sudo(self):
        self.assert_same_but_n(['sudo', '-v'])
        self.assert_same_but_n(['sudo', 'bash', '/x/deploy/setup-git.sh', '--owner', 'me'])
        self.assert_same_but_n(['sudo', 'env', 'DOCKER_HOST=unix:///var/run/docker.sock', 'bash', 'x.sh'])
        self.assertEqual(core.noninteractive(['sudo']), ['sudo', '-n'])

    def test_never_duplicates_n(self):
        for argv in (['sudo', '-n', 'true'], ['sudo', '-n', '-v'], ['sudo', '-n']):
            with self.subTest(argv=argv):
                self.assertEqual(core.noninteractive(argv), argv)
                self.assertEqual(core.noninteractive(core.noninteractive(argv)).count('-n'), argv.count('-n'))
        once = core.noninteractive(['sudo', 'bash', 'x'])
        self.assertEqual(core.noninteractive(once), once)

    def test_leaves_other_argv_untouched(self):
        for argv in ([], ['bash', 'x.sh'], ['bash', 'x', 'sudo'], ['env', 'sudo', 'x'], ['/usr/bin/sudo', 'x'],
                     ['python3', '-n', 'x'], ['sh', '-c', 'sudo true']):
            with self.subTest(argv=argv):
                result = core.noninteractive(argv)
                self.assertEqual(len(result), len(argv))
                for index, item in enumerate(argv):
                    self.assertEqual(result[index], item)


# ---------------------------------------------------------------------------------------------
# 3. core.InstallerLock
# ---------------------------------------------------------------------------------------------
CHILD_ACQUIRE = '''
import sys
sys.path.insert(0, sys.argv[1])
from installer_tui import core
try:
    core.InstallerLock(sys.argv[2]).acquire()
except core.Busy as error:
    print('BUSY', error)
    sys.exit(7)
print('ACQUIRED')
'''

CHILD_HOLD = '''
import sys
sys.path.insert(0, sys.argv[1])
from installer_tui import core
lock = core.InstallerLock(sys.argv[2]).acquire()
print('ready', flush=True)
sys.stdin.read()
'''


class InstallerLockTests(IsolatedCase):
    def setUp(self):
        super().setUp()
        self.path = self.tmp / 'installer.lock'

    def child(self, code=CHILD_ACQUIRE, **kwargs):
        return subprocess.Popen([sys.executable, '-c', code, str(DEPLOY), str(self.path)],
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, **kwargs)

    def test_acquire_and_release(self):
        lock = core.InstallerLock(self.path)
        self.assertFalse(lock.held)
        self.assertIs(lock.acquire(), lock)
        self.assertTrue(lock.held)
        self.assertIn(f'pid {os.getpid()}', self.path.read_text())
        lock.release()
        self.assertFalse(lock.held)
        lock.release()   # releasing twice is harmless
        again = core.InstallerLock(self.path).acquire()
        self.assertTrue(again.held)
        again.release()

    def test_context_manager_releases(self):
        with core.InstallerLock(self.path) as lock:
            self.assertTrue(lock.held)
            with self.assertRaises(core.Busy):
                core.InstallerLock(self.path).acquire()
        self.assertFalse(lock.held)
        core.InstallerLock(self.path).acquire().release()

    def test_busy_is_a_value_error(self):
        self.assertTrue(issubclass(core.Busy, ValueError))

    def test_second_acquire_in_a_child_process_fails_with_the_holder_line(self):
        with core.InstallerLock(self.path):
            child = self.child()
            output, _ = child.communicate(timeout=20)
        self.assertEqual(child.returncode, 7, output)
        self.assertTrue(output.startswith('BUSY Another Containerlab Node Manager installer run is active'), output)
        self.assertIn(f'pid {os.getpid()}', output)
        self.assertIn('account', output)
        self.assertIn('started', output)

    def test_child_can_acquire_when_nobody_holds_it(self):
        child = self.child()
        output, _ = child.communicate(timeout=20)
        self.assertEqual((child.returncode, output.strip()), (0, 'ACQUIRED'))

    def test_lock_is_released_when_the_holder_exits(self):
        holder = self.child(CHILD_HOLD)
        try:
            self.assertEqual(holder.stdout.readline().strip(), 'ready')
            with self.assertRaises(core.Busy) as caught:
                core.InstallerLock(self.path).acquire()
            self.assertIn(f'pid {holder.pid}', str(caught.exception))
            holder.stdin.close()
            holder.wait(timeout=20)
        finally:
            if holder.poll() is None:
                holder.kill()
            holder.stdout.close()
        again = core.InstallerLock(self.path).acquire()
        self.assertTrue(again.held)
        again.release()

    def test_lock_created_by_another_account_falls_back_to_a_read_only_descriptor(self):
        self.path.write_text('')
        self.path.chmod(0o444)
        lock = core.InstallerLock(self.path).acquire()
        self.assertTrue(lock.held)
        if os.geteuid() != 0:
            self.assertEqual(self.path.read_text(), '', 'a read-only holder writes no holder line')
        child = self.child()
        output, _ = child.communicate(timeout=20)
        self.assertEqual(child.returncode, 7, output)
        if os.geteuid() != 0:
            self.assertNotIn('pid ', output)
        lock.release()
        self.assertFalse(lock.held)
        again = core.InstallerLock(self.path).acquire()
        again.release()

    def test_default_path_is_a_fixed_name_and_not_apts_lock(self):
        path = core.default_lock_path()
        self.assertEqual(path.name, 'clab-node-manager-installer.lock')
        self.assertNotIn('dpkg', str(path))


# ---------------------------------------------------------------------------------------------
# 4. core.StepProcess
# ---------------------------------------------------------------------------------------------
class StepProcessTests(IsolatedCase):
    def make(self, body=None, argv=None, **kwargs):
        if argv is None:
            argv = ['sh', self.script('step', body)]
        self.batches = []
        self.stamps = []

        def on_lines(batch):
            self.batches.append(list(batch))
            self.stamps.append((time.monotonic(), list(batch)))
        kwargs.setdefault('on_lines', on_lines)
        return core.StepProcess(argv, self.env, str(self.tmp), **kwargs)

    @property
    def delivered(self):
        return [line for batch in self.batches for line in batch]

    def test_streams_lines_in_order_and_returns_the_exit_status(self):
        step = self.make('for i in 1 2 3 4 5; do echo line$i; done; exit 7')
        self.assertEqual(step.run(), 7)
        self.assertEqual(step.returncode, 7)
        want = [f'line{i}' for i in range(1, 6)]
        self.assertEqual(self.delivered, want)
        self.assertEqual(list(step.tail), want)
        self.assertEqual(step.dropped, 0)
        self.assertIsNotNone(step.finished)

    def test_success_status_zero(self):
        self.assertEqual(self.make('echo hi').run(), 0)

    def test_stderr_is_merged_into_the_stream(self):
        step = self.make('echo out; echo err 1>&2')
        step.run()
        self.assertEqual(sorted(self.delivered), ['err', 'out'])

    def test_lines_arrive_in_batches_through_on_lines(self):
        step = self.make('echo a; echo b; sleep 0.4; echo c')
        step.run()
        self.assertTrue(all(isinstance(batch, list) and batch for batch in self.batches))
        self.assertGreaterEqual(len(self.batches), 2, 'a pause flushes what has arrived')
        self.assertEqual(self.delivered, ['a', 'b', 'c'])

    def test_runs_in_its_own_process_group(self):
        step = self.make(argv=[sys.executable, '-c', 'import os; print(os.getpgrp(), os.getpid())'])
        self.assertEqual(step.run(), 0)
        group, pid = (int(value) for value in self.delivered[0].split())
        self.assertNotEqual(group, os.getpgrp())
        self.assertEqual(group, pid, 'the child leads a new process group')

    def test_stays_in_the_parents_session_for_sudos_terminal_credential_cache(self):
        step = self.make(argv=[sys.executable, '-c', 'import os; print(os.getsid(0))'])
        step.run()
        self.assertEqual(int(self.delivered[0]), os.getsid(0))

    def test_stdin_is_dev_null(self):
        step = self.make('if read x; then echo got-input; else echo eof; fi')
        self.assertEqual(step.run(), 0)
        self.assertEqual(self.delivered, ['eof'])
        step = self.make(argv=[sys.executable, '-c', 'import os,sys; print(os.fstat(0).st_rdev == os.stat("/dev/null").st_rdev)'])
        step.run()
        self.assertEqual(self.delivered, ['True'])

    def test_saw_lock_only_when_a_signature_is_given_and_matched(self):
        body = f'echo "{LOCK_TEXT}"; exit 100'
        matched = self.make(body, lock_signature=install.LOCK_SIGNATURE)
        self.assertEqual(matched.run(), 100)
        self.assertTrue(matched.saw_lock)
        unsigned = self.make(body)
        unsigned.run()
        self.assertFalse(unsigned.saw_lock)
        other = self.make('echo network unreachable; exit 1', lock_signature=install.LOCK_SIGNATURE)
        other.run()
        self.assertFalse(other.saw_lock)

    def test_lock_signature_is_matched_on_the_raw_text(self):
        step = self.make("printf 'E: Could not \\033[1mget lock\\033[0m x\\n'", lock_signature=re_compile_raw())
        step.run()
        self.assertTrue(step.saw_lock)
        self.assertEqual(self.delivered, ['E: Could not get lock x'])

    def test_saw_auth_on_a_sudo_password_requirement(self):
        step = self.make('echo "sudo: a password is required"; exit 1')
        step.run()
        self.assertTrue(step.saw_auth)
        step = self.make('echo "sudo: a terminal is required to read the password"; exit 1')
        step.run()
        self.assertTrue(step.saw_auth)
        step = self.make('echo "sudo: unknown user"; exit 1')
        step.run()
        self.assertFalse(step.saw_auth)

    def test_output_escape_sequences_are_cleaned(self):
        step = self.make("printf '\\033[31mred\\033[0m \\033]0;title\\007ok\\n'")
        step.run()
        self.assertEqual(self.delivered, ['red ok'])
        self.assertEqual(list(step.tail), ['red ok'])

    def test_carriage_return_progress_keeps_the_final_state(self):
        step = self.make("printf 'x 10%%\\rx 60%%\\rx 100%%\\n'")
        step.run()
        self.assertEqual(self.delivered, ['x 100%'])

    def test_invalid_utf8_does_not_break_the_stream(self):
        step = self.make("printf 'a\\377\\376b\\n'")
        self.assertEqual(step.run(), 0)
        self.assertEqual(len(self.delivered), 1)
        self.assertTrue(self.delivered[0].startswith('a') and self.delivered[0].endswith('b'))

    def test_a_long_output_without_a_newline_is_delivered_in_pieces_without_hanging(self):
        code = ('import sys, time\n'
                'for _ in range(4):\n'
                '    sys.stdout.write("x" * 25600); sys.stdout.flush(); time.sleep(0.05)\n')
        step = self.make(argv=[sys.executable, '-c', code])
        result = {}
        worker = threading.Thread(target=lambda: result.update(code=step.run()), daemon=True)
        worker.start()
        worker.join(30)
        self.assertFalse(worker.is_alive(), 'the reader must not wait for a newline')
        self.assertEqual(result['code'], 0)
        self.assertGreaterEqual(len(self.delivered), 2, 'delivered in pieces, not as one 100 KiB line')
        total = 0
        for line in self.delivered:
            self.assertLessEqual(len(line), sanitize.MAX_LINE + 60)
            self.assertTrue(line.startswith('x' * sanitize.MAX_LINE))
            extra = re.search(r'\[\.\.\. (\d+) more characters not shown\]$', line)
            total += sanitize.MAX_LINE + (int(extra[1]) if extra else 0)
        self.assertEqual(total, 4 * 25600, 'every byte is accounted for as shown or counted as cut')

    def test_tail_is_bounded_at_tail_lines_with_dropped_counted(self):
        step = self.make('seq 1 4100')
        self.assertEqual(step.run(), 0)
        self.assertEqual(core.TAIL_LINES, 4000)
        self.assertEqual(len(step.tail), core.TAIL_LINES)
        self.assertEqual(step.dropped, 100)
        self.assertEqual(step.tail[0], '101')
        self.assertEqual(step.tail[-1], '4100')
        self.assertEqual(len(self.delivered), 4100, 'the screen still received every line')

    def test_tail_limit_follows_the_module_setting(self):
        with patch.object(core, 'TAIL_LINES', 5):
            step = self.make('seq 1 12')
            step.run()
        self.assertEqual(list(step.tail), ['8', '9', '10', '11', '12'])
        self.assertEqual(step.dropped, 7)

    def test_a_quiet_childs_last_line_is_delivered_before_it_exits(self):
        step = self.make('echo first-line; sleep 0.5; echo last-line')
        step.run()
        arrival = {line: when for when, batch in self.stamps for line in batch}
        self.assertEqual(sorted(arrival), ['first-line', 'last-line'])
        self.assertGreater(step.finished - arrival['first-line'], 0.25,
                           'the line was shown while the process was still running')

    def test_pass_fds_are_inherited_and_none_is_ignored(self):
        read_fd, write_fd = os.pipe()
        try:
            step = self.make(f'if [ -e /proc/$$/fd/{write_fd} ]; then echo has-fd; else echo no-fd; fi',
                             pass_fds=(write_fd, None))
            step.run()
            self.assertEqual(self.delivered, ['has-fd'])
            step = self.make(f'if [ -e /proc/$$/fd/{write_fd} ]; then echo has-fd; else echo no-fd; fi')
            step.run()
            self.assertEqual(self.delivered, ['no-fd'])
        finally:
            os.close(read_fd)
            os.close(write_fd)

    def test_environment_and_cwd_are_the_ones_given(self):
        self.env['PROBE_VALUE'] = 'from-env'
        step = self.make('echo "$PROBE_VALUE"; pwd')
        step.run()
        self.assertEqual(self.delivered[0], 'from-env')
        self.assertEqual(os.path.realpath(self.delivered[1]), os.path.realpath(self.tmp))


def re_compile_raw():
    import re as regex
    return regex.compile(r'Could not \x1b\[1mget lock')


# ---------------------------------------------------------------------------------------------
# 5. core.run_capture
# ---------------------------------------------------------------------------------------------
class RunCaptureTests(IsolatedCase):
    def test_timeout_returns_none_and_timed_out(self):
        started = time.monotonic()
        self.assertEqual(core.run_capture(['sleep', '5'], self.env, str(self.tmp), timeout=0.2), (None, 'timed out'))
        self.assertLess(time.monotonic() - started, 4)

    def test_missing_command_returns_none_and_a_message(self):
        code, text = core.run_capture(['/nonexistent/definitely-not-here'], self.env, str(self.tmp))
        self.assertIsNone(code)
        self.assertTrue(text)

    def test_returns_status_and_cleaned_text(self):
        script = self.script('probe', "printf '\\033[31mone\\033[0m\\ntwo\\n'; echo err 1>&2; exit 3")
        code, text = core.run_capture(['sh', script], self.env, str(self.tmp))
        self.assertEqual(code, 3)
        self.assertEqual(text.splitlines(), ['one', 'two', 'err'])

    def test_stdin_is_not_the_terminal(self):
        script = self.script('probe', 'if read x; then echo got; else echo eof; fi')
        self.assertEqual(core.run_capture(['sh', script], self.env, str(self.tmp)), (0, 'eof'))


# ---------------------------------------------------------------------------------------------
# 6. run records
# ---------------------------------------------------------------------------------------------
class RunRecordTests(IsolatedCase):
    RECORD = {'schema': 'clab-node-manager-installer-run-v1', 'action': 'install', 'outcome': 'completed',
              'phases': [{'key': 'prereqs', 'state': 'Completed', 'exit_status': 0, 'attempts': 1, 'seconds': 1.2}]}

    def folder(self):
        return core.state_dir(self.env)

    def test_state_dir_follows_xdg_then_home(self):
        self.assertEqual(self.folder(), self.tmp / 'state' / 'clab-node-manager')
        with patch.dict(os.environ):
            os.environ.pop('XDG_STATE_HOME')
            self.assertEqual(core.state_dir(self.env), self.tmp / 'home' / '.local' / 'state' / 'clab-node-manager')

    def test_written_with_private_modes_and_read_back(self):
        core.write_run_record(self.env, self.RECORD)
        target = self.folder() / 'installer-last-run.json'
        self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.folder().stat().st_mode), 0o700)
        self.assertEqual(core.read_run_record(self.env), self.RECORD)
        self.assertEqual(sorted(p.name for p in self.folder().iterdir()), ['installer-last-run.json'],
                         'no temporary file is left behind')

    def test_write_is_atomic_a_failed_replace_keeps_the_previous_record(self):
        core.write_run_record(self.env, self.RECORD)
        newer = dict(self.RECORD, outcome='failed')
        with patch.object(core.os, 'replace', side_effect=OSError('disk full')):
            core.write_run_record(self.env, newer)   # failure is ignored
        self.assertEqual(core.read_run_record(self.env)['outcome'], 'completed')
        core.write_run_record(self.env, newer)
        self.assertEqual(core.read_run_record(self.env)['outcome'], 'failed')

    def test_write_never_follows_a_symlinked_temporary_name(self):
        folder = self.folder()
        folder.mkdir(parents=True, mode=0o700)
        victim = self.tmp / 'victim.txt'
        victim.write_text('precious')
        os.symlink(victim, folder / '.installer-last-run.json.tmp')
        core.write_run_record(self.env, self.RECORD)
        self.assertEqual(victim.read_text(), 'precious')

    def test_read_rejects_a_symlink(self):
        core.write_run_record(self.env, self.RECORD)
        target = self.folder() / 'installer-last-run.json'
        other = self.tmp / 'other.json'
        other.write_text(json.dumps(self.RECORD))
        target.unlink()
        os.symlink(other, target)
        self.assertIsNone(core.read_run_record(self.env))

    def test_read_rejects_more_than_64_kib_and_bad_content(self):
        folder = self.folder()
        folder.mkdir(parents=True, mode=0o700)
        target = folder / 'installer-last-run.json'
        target.write_text(json.dumps({'pad': 'x' * 70000}))
        self.assertGreater(target.stat().st_size, 65536)
        self.assertIsNone(core.read_run_record(self.env))
        target.write_text('{"ok": 1}')
        self.assertEqual(core.read_run_record(self.env), {'ok': 1})
        for text in ('[1, 2]', 'not json', '"string"', ''):
            target.write_text(text)
            with self.subTest(text=text):
                self.assertIsNone(core.read_run_record(self.env))
        target.unlink()
        self.assertIsNone(core.read_run_record(self.env))

    def test_the_file_holds_only_the_record_given(self):
        core.write_run_record(self.env, self.RECORD)
        text = (self.folder() / 'installer-last-run.json').read_text()
        self.assertEqual(json.loads(text), self.RECORD)

    def test_signal_flag(self):
        flag = core.Signal()
        self.assertFalse(flag)
        flag.set('first')
        flag.set('second')
        self.assertTrue(flag)
        self.assertEqual(flag.reason, 'first')


# ---------------------------------------------------------------------------------------------
# 7. bootstrap
# ---------------------------------------------------------------------------------------------
def make_wheel(files):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return buffer.getvalue()


def make_zip(entries):
    """entries: [(name, content, external_attr or None)]"""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        for name, content, attr in entries:
            info = zipfile.ZipInfo(name)
            if attr is not None:
                info.external_attr = attr
            archive.writestr(info, content)
    return buffer.getvalue()


class LockFileTests(unittest.TestCase):
    def test_real_requirements_lock(self):
        pins = bootstrap.parse_lock((DEPLOY / 'installer_tui' / 'requirements.lock').read_text())
        self.assertEqual(len(pins), 9)
        by_name = {name: version for name, version, _, _ in pins}
        self.assertEqual(by_name['textual'], '8.2.8')
        self.assertEqual(len(by_name), 9, 'no package is pinned twice')
        for name, version, url, digest in pins:
            with self.subTest(name=name):
                self.assertTrue(url.startswith('https://files.pythonhosted.org/'), url)
                self.assertTrue(url.endswith('.whl'), url)
                self.assertRegex(digest, r'^[0-9a-f]{64}$')
                self.assertIn(version, url)

    def test_malformed_lock_lines_raise_provision_error(self):
        digest = 'a' * 64
        url = '# https://files.pythonhosted.org/packages/aa/x-1.0-py3-none-any.whl'
        cases = {
            'missing URL comment': f'x==1.0 --hash=sha256:{digest}\n',
            'missing hash': f'{url}\nx==1.0\n',
            'not pinned': f'{url}\nx>=1.0 --hash=sha256:{digest}\n',
            'short hash': f'{url}\nx==1.0 --hash=sha256:{"a" * 63}\n',
            'upper-case hash': f'{url}\nx==1.0 --hash=sha256:{"A" * 64}\n',
            'URL from another host': f'# https://evil.example/x-1.0-py3-none-any.whl\nx==1.0 --hash=sha256:{digest}\n',
            'URL not a wheel': f'# https://files.pythonhosted.org/packages/aa/x-1.0.tar.gz\nx==1.0 --hash=sha256:{digest}\n',
            'URL used twice': f'{url}\nx==1.0 --hash=sha256:{digest}\ny==1.0 --hash=sha256:{digest}\n',
            'extra option': f'{url}\nx==1.0 --hash=sha256:{digest} --index-url http://evil\n',
            'empty': '',
            'comments only': '# nothing here\n',
        }
        for label, text in cases.items():
            with self.subTest(label), self.assertRaises(bootstrap.ProvisionError):
                bootstrap.parse_lock(text)

    def test_wellformed_lock_parses(self):
        digest = 'b' * 64
        text = ('# comment\n\n# https://files.pythonhosted.org/packages/aa/x-1.0-py3-none-any.whl\n'
                f'x==1.0 --hash=sha256:{digest}\n')
        self.assertEqual(bootstrap.parse_lock(text),
                         [('x', '1.0', 'https://files.pythonhosted.org/packages/aa/x-1.0-py3-none-any.whl', digest)])


class UnpackWheelTests(IsolatedCase):
    def setUp(self):
        super().setUp()
        self.site = self.tmp / 'site'
        self.site.mkdir()

    def refuse(self, entries, budget=10_000_000):
        with self.assertRaises(bootstrap.ProvisionError):
            bootstrap.unpack_wheel(make_zip(entries), self.site, budget)
        return self.site

    def test_accepts_a_normal_pure_wheel(self):
        data = make_zip([('pkg/__init__.py', 'X = 1\n', None), ('pkg/sub/', '', 0o040755 << 16),
                         ('pkg/sub/mod.py', 'Y = 2\n', None), ('pkg-1.0.dist-info/METADATA', 'Name: pkg\n', None)])
        left = bootstrap.unpack_wheel(data, self.site, 1000)
        self.assertEqual((self.site / 'pkg/__init__.py').read_text(), 'X = 1\n')
        self.assertEqual((self.site / 'pkg/sub/mod.py').read_text(), 'Y = 2\n')
        self.assertTrue((self.site / 'pkg-1.0.dist-info/METADATA').is_file())
        self.assertEqual(left, 1000 - len('X = 1\n') - len('Y = 2\n') - len('Name: pkg\n'))

    def test_refuses_absolute_names(self):
        self.refuse([('/etc/evil.py', 'x', None)])
        self.assertFalse(Path('/etc/evil.py').exists())

    def test_refuses_parent_traversal(self):
        self.refuse([('pkg/../../evil.py', 'x', None)])
        self.assertFalse((self.tmp / 'evil.py').exists())
        self.refuse([('../evil.py', 'x', None)])
        self.assertFalse((self.tmp / 'evil.py').exists())

    def test_refuses_backslashes(self):
        self.refuse([('pkg\\evil.py', 'x', None)])
        self.refuse([('..\\evil.py', 'x', None)])

    def test_refuses_drive_letter_style_names(self):
        self.refuse([('C:/evil.py', 'x', None)])

    def test_refuses_data_directories(self):
        self.refuse([('pkg-1.0.data/scripts/run', 'x', None)])
        self.refuse([('pkg-1.0.data/purelib/pkg/__init__.py', 'x', None)])

    def test_refuses_symlink_entries(self):
        self.refuse([('pkg/__init__.py', 'x', None), ('pkg/link', '/etc/passwd', 0o120777 << 16)])
        self.assertFalse((self.site / 'pkg/link').exists())

    def test_refuses_other_special_files(self):
        self.refuse([('pkg/fifo', '', 0o010644 << 16)])
        self.refuse([('pkg/device', '', 0o020644 << 16)])

    def test_enforces_the_size_budget(self):
        self.refuse([('pkg/big.bin', 'x' * 100, None)], budget=10)
        self.refuse([('pkg/a.bin', 'x' * 60, None), ('pkg/b.bin', 'x' * 60, None)], budget=100)
        left = bootstrap.unpack_wheel(make_zip([('pkg/a.bin', 'x' * 100, None)]), self.tmp / 'site2', 100)
        self.assertEqual(left, 0, 'exactly the budget is allowed')

    def test_never_overwrites_an_existing_file(self):
        bootstrap.unpack_wheel(make_zip([('pkg/__init__.py', 'one', None)]), self.site, 1000)
        with self.assertRaises(OSError):
            bootstrap.unpack_wheel(make_zip([('pkg/__init__.py', 'two', None)]), self.site, 1000)
        self.assertEqual((self.site / 'pkg/__init__.py').read_text(), 'one')


class ProvisionTests(IsolatedCase):
    TEXTUAL = '1.2.3'

    def setUp(self):
        super().setUp()
        self.wheels = {
            'textual': make_wheel({'textual/__init__.py': f'__version__ = "{self.TEXTUAL}"\n',
                                   'textual-1.2.3.dist-info/METADATA': 'Name: textual\n'}),
            'rich': make_wheel({'rich/__init__.py': 'MARK = "rich"\n'}),
        }
        self.versions = {'textual': self.TEXTUAL, 'rich': '9.9.9'}
        self.urls = {name: f'https://files.pythonhosted.org/packages/00/{name}-{self.versions[name]}-py3-none-any.whl'
                     for name in self.wheels}
        self.write_lock({name: bootstrap.hashlib.sha256(data).hexdigest() for name, data in self.wheels.items()})
        self.served = []
        self.messages = []
        patcher = patch.object(bootstrap, 'LOCK', self.lock_path)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.base = self.tmp / 'data' / 'clab-node-manager' / 'installer-tui'

    def write_lock(self, digests):
        lines = []
        for name in ('textual', 'rich'):
            lines.append(f'# {self.urls[name]}')
            lines.append(f'{name}=={self.versions[name]} --hash=sha256:{digests[name]}')
        self.lock_path = self.tmp / 'requirements.lock'
        self.lock_path.write_text('\n'.join(lines) + '\n')

    def fetcher(self, overrides=None):
        by_url = {self.urls[name]: data for name, data in self.wheels.items()}
        by_url.update(overrides or {})

        def fetch(url):
            self.served.append(url)
            value = by_url[url]
            if isinstance(value, Exception):
                raise value
            return value
        return fetch

    def provision(self, **kwargs):
        return bootstrap.provision(self.env, say=self.messages.append, **kwargs)

    def leftovers(self):
        return sorted(p.name for p in self.base.iterdir()) if self.base.exists() else []

    def test_success_creates_the_target_with_a_ready_marker(self):
        self.assertFalse(bootstrap.ready(self.env))
        self.assertEqual(self.provision(fetcher=self.fetcher()), 0, self.messages)
        target = bootstrap.target_dir(self.env)
        self.assertTrue(target.is_dir())
        self.assertTrue(str(target).startswith(str(self.base)))
        marker = json.loads((target / 'ready.json').read_text())
        self.assertEqual(marker['lock'], bootstrap.lock_digest())
        self.assertTrue(bootstrap.ready(self.env))
        self.assertEqual(sorted(self.served), sorted(self.urls.values()))
        self.assertEqual(self.leftovers(), [target.name], 'the staging folder is gone')
        site = target / 'venv' / 'lib' / f'python{sys.version_info[0]}.{sys.version_info[1]}' / 'site-packages'
        self.assertTrue((site / 'rich' / '__init__.py').is_file())
        # The finished environment really imports the pinned package.
        check = subprocess.run([str(bootstrap.venv_python(target)), '-I', '-c', 'import textual, rich; print(textual.__version__)'],
                               capture_output=True, text=True, timeout=30)
        self.assertEqual(check.stdout.strip(), self.TEXTUAL, check.stderr)
        # Nothing outside the private data folder changed.
        self.assertEqual(sorted(p.name for p in (self.tmp / 'home').iterdir()), [])

    def test_an_already_ready_environment_is_not_downloaded_again(self):
        self.assertEqual(self.provision(fetcher=self.fetcher()), 0)
        self.served.clear()
        self.assertEqual(self.provision(fetcher=self.fetcher()), 0)
        self.assertEqual(self.served, [])
        self.assertTrue(any('already set up' in message for message in self.messages))

    def test_ready_is_false_when_the_marker_digest_differs_or_the_lock_changes(self):
        self.assertEqual(self.provision(fetcher=self.fetcher()), 0)
        target = bootstrap.target_dir(self.env)
        marker = target / 'ready.json'
        original = marker.read_text()
        marker.write_text(json.dumps({'lock': 'deadbeefdeadbeef'}))
        self.assertFalse(bootstrap.ready(self.env))
        marker.write_text('not json')
        self.assertFalse(bootstrap.ready(self.env))
        marker.unlink()
        self.assertFalse(bootstrap.ready(self.env))
        marker.write_text(original)
        self.assertTrue(bootstrap.ready(self.env))
        # A changed pin changes the digest, so the old environment no longer counts as ready.
        self.lock_path.write_text(self.lock_path.read_text() + '# another line\n')
        self.assertFalse(bootstrap.ready(self.env))

    def test_hash_mismatch_returns_1_creates_no_target_and_removes_staging(self):
        tampered = make_wheel({'rich/__init__.py': 'MARK = "tampered"\n'})
        self.assertEqual(self.provision(fetcher=self.fetcher({self.urls['rich']: tampered})), 1)
        text = '\n'.join(self.messages)
        self.assertIn('rich', text)
        self.assertIn('SHA-256', text)
        self.assertFalse(bootstrap.target_dir(self.env).exists())
        self.assertFalse(bootstrap.ready(self.env))
        self.assertEqual(self.leftovers(), [], 'staging is removed and nothing else is left')

    def test_a_fetch_exception_returns_1_and_names_the_package(self):
        def fake_venv(argv, **kwargs):
            site = Path(argv[-1]) / 'lib' / f'python{sys.version_info[0]}.{sys.version_info[1]}' / 'site-packages'
            site.mkdir(parents=True)
            return subprocess.CompletedProcess(argv, 0, stdout='')
        failing = self.fetcher({self.urls['textual']: OSError('network is unreachable')})
        with patch.object(bootstrap.subprocess, 'run', side_effect=fake_venv):
            code = self.provision(fetcher=failing)
        self.assertEqual(code, 1)
        text = '\n'.join(self.messages)
        self.assertIn('textual 1.2.3', text)
        self.assertIn('network is unreachable', text)
        self.assertFalse(bootstrap.target_dir(self.env).exists())
        self.assertEqual(self.leftovers(), [])

    def test_a_wheel_that_does_not_import_as_the_pinned_version_is_not_marked_ready(self):
        # Hash matches the lock (the lock is regenerated for the wrong package) but textual reports another version.
        wrong = make_wheel({'textual/__init__.py': '__version__ = "0.0.1"\n'})
        self.wheels['textual'] = wrong
        self.write_lock({name: bootstrap.hashlib.sha256(data).hexdigest() for name, data in self.wheels.items()})
        self.assertEqual(self.provision(fetcher=self.fetcher()), 1)
        self.assertIn('did not import cleanly', '\n'.join(self.messages))
        self.assertFalse(bootstrap.target_dir(self.env).exists())
        self.assertEqual(self.leftovers(), [])


# ---------------------------------------------------------------------------------------------
# 10. probes
# ---------------------------------------------------------------------------------------------
class ProbeTests(IsolatedCase):
    def source(self, text=None, symlink=False):
        root = self.tmp / 'checkout'
        (root / 'clab-backup-ui').mkdir(parents=True, exist_ok=True)
        target = root / 'clab-backup-ui' / '.env'
        if target.exists() or target.is_symlink():
            target.unlink()
        if symlink:
            other = self.tmp / 'elsewhere.env'
            other.write_text(text)
            os.symlink(other, target)
        elif text is not None:
            target.write_text(text)
        return root

    def test_env_settings_reads_only_the_three_keys_never_the_token(self):
        root = self.source('UI_BIND=10.0.0.5\nUI_PORT=9001\nCAPTURE_PROVIDER=edgeshark\n'
                           'CAPTURE_SESSION_TOKEN=secret\nOTHER=value\n# UI_PORT=1\n')
        values = probes.env_settings(root)
        self.assertEqual(values, {'UI_BIND': '10.0.0.5', 'UI_PORT': '9001', 'CAPTURE_PROVIDER': 'edgeshark'})
        self.assertNotIn('secret', repr(values))
        self.assertNotIn('secret', json.dumps(values))
        self.assertNotIn('CAPTURE_SESSION_TOKEN', values)
        self.assertNotIn('secret', repr(probes.manager_address(root)))
        self.assertEqual(probes.env_settings(root, keys=('UI_PORT',)), {'UI_PORT': '9001'})

    def test_env_settings_strips_quotes_and_tolerates_a_missing_file(self):
        root = self.source('UI_BIND="127.0.0.1"\nUI_PORT=\'8099\'\n')
        self.assertEqual(probes.env_settings(root), {'UI_BIND': '127.0.0.1', 'UI_PORT': '8099'})
        self.assertEqual(probes.env_settings(self.tmp / 'nowhere'), {})
        self.assertEqual(probes.env_settings(self.source(None)), {})

    def test_env_settings_refuses_a_symlinked_env_and_an_oversized_one(self):
        root = self.source('UI_PORT=9001\nCAPTURE_SESSION_TOKEN=secret\n', symlink=True)
        self.assertEqual(probes.env_settings(root), {})
        self.assertEqual(probes.manager_address(root), ('http://127.0.0.1:8081/', 8081))
        root = self.source('UI_PORT=9001\n' + '#' * 70000)
        self.assertEqual(probes.env_settings(root), {})

    def test_manager_address_mapping(self):
        cases = [
            (None, ('http://127.0.0.1:8081/', 8081)),
            ('UI_BIND=0.0.0.0\nUI_PORT=8099\n', ('http://127.0.0.1:8099/', 8099)),
            ('UI_BIND=::\n', ('http://[::1]:8081/', 8081)),
            ('UI_BIND=localhost\n', ('http://127.0.0.1:8081/', 8081)),
            ('UI_BIND=\n', ('http://127.0.0.1:8081/', 8081)),
            ('UI_BIND=fd00::5\nUI_PORT=9000\n', ('http://[fd00::5]:9000/', 9000)),
            ('UI_BIND=[fd00::5]\n', ('http://[fd00::5]:8081/', 8081)),
            ('UI_BIND=10.1.2.3\n', ('http://10.1.2.3:8081/', 8081)),
            ('UI_PORT=not-a-number\n', ('http://127.0.0.1:8081/', 8081)),
            ('UI_PORT=\n', ('http://127.0.0.1:8081/', 8081)),
            ('UI_PORT=80.5\n', ('http://127.0.0.1:8081/', 8081)),
        ]
        for text, expected in cases:
            with self.subTest(text=text):
                self.assertEqual(probes.manager_address(self.source(text)), expected)

    def test_sudo_refused_only_with_the_sudo_signature(self):
        self.assertTrue(probes._sudo_refused(1, 'sudo: a password is required'))
        self.assertTrue(probes._sudo_refused(1, 'sudo: a terminal is required to read the password'))
        self.assertFalse(probes._sudo_refused(0, 'sudo: a password is required'))
        self.assertFalse(probes._sudo_refused(None, 'sudo: a password is required'))
        self.assertFalse(probes._sudo_refused(1, 'docker: command not found'))
        self.assertFalse(probes._sudo_refused(1, ''))
        self.assertFalse(probes._sudo_refused(1, None))

    def test_probe_sudo_distinguishes_ready_needs_auth_and_unavailable(self):
        ctx = probes.Context(self.env, self.tmp, '1.0.0')
        with patch.object(core, 'run_capture', return_value=(0, '')):
            self.assertEqual(probes.probe_sudo(ctx)[0], probes.READY)
        with patch.object(core, 'run_capture', return_value=(1, 'sudo: a password is required')):
            self.assertEqual(probes.probe_sudo(ctx)[0], probes.NEEDS_AUTH)
        with patch.object(core, 'run_capture', return_value=(None, 'timed out')):
            self.assertEqual(probes.probe_sudo(ctx)[0], probes.UNAVAILABLE)

    def test_a_failed_probe_is_unavailable_never_not_installed(self):
        def boom(ctx):
            raise RuntimeError('probe bug')
        ctx = probes.Context(self.env, self.tmp, '1.0.0')
        seen = []
        with patch.dict(probes.PROBES, {key: boom for key in probes.PROBES}):
            results, checked = probes.run_all(ctx, on_result=seen.append)
        self.assertEqual(set(results), {key for key, _ in probes.COMPONENTS + probes.EXTRA})
        self.assertEqual(len(seen), len(results))
        for key, result in results.items():
            with self.subTest(key=key):
                self.assertEqual(result.state, probes.UNAVAILABLE)
                self.assertNotEqual(result.state, probes.NOT_INSTALLED)
                self.assertEqual(result.detail, 'RuntimeError')
        self.assertIsInstance(checked, float)

    def test_run_all_keys_subset_and_structured_value(self):
        ctx = probes.Context(self.env, self.tmp, '1.0.0')
        with patch.dict(probes.PROBES, {'manager': lambda c: (probes.READY, 'ok', '', '1.0.0'),
                                        'git': lambda c: (probes.ATTENTION, 'meh', 'detail')}):
            results, _ = probes.run_all(ctx, keys=['manager', 'git'])
        self.assertEqual(sorted(results), ['git', 'manager'])
        self.assertEqual((results['manager'].state, results['manager'].value), (probes.READY, '1.0.0'))
        self.assertEqual((results['git'].state, results['git'].value, results['git'].detail),
                         (probes.ATTENTION, None, 'detail'))

    def test_placeholder_lists_every_component_as_not_checked(self):
        placeholders = probes.placeholder()
        self.assertEqual(set(placeholders), {key for key, _ in probes.COMPONENTS + probes.EXTRA})
        self.assertTrue(all(result.state == probes.NOT_CHECKED for result in placeholders.values()))


# ---------------------------------------------------------------------------------------------
# 8. engine.Run with a fake install module and a fake bridge
# ---------------------------------------------------------------------------------------------
class FakeBridge:
    alive = True

    def __init__(self, recover=(), handoff=()):
        self.recover_choices = list(recover)
        self.handoff_codes = list(handoff)
        self.states = []       # (key, state) in order
        self.lines = {}        # key -> [line]
        self.recovers = []     # (key, kind, choices, holder, message)
        self.handoffs = []     # title
        self.activities = []
        self.finished_with = []
        self.calls = 0

    def phase_changed(self, phase):
        self.calls += 1
        self.states.append((phase.key, phase.state))

    def output(self, key, lines):
        self.calls += 1
        self.lines.setdefault(key, []).extend(lines)

    def activity(self, text):
        self.calls += 1
        self.activities.append(text)

    def handoff(self, title, notice, work):
        self.calls += 1
        self.handoffs.append(title)
        return self.handoff_codes.pop(0) if self.handoff_codes else 0

    def recover(self, phase, failure):
        self.calls += 1
        self.recovers.append((phase.key, failure.kind, failure.choices, failure.holder, failure.message))
        return self.recover_choices.pop(0) if self.recover_choices else engine.RETURN

    def finished(self, run):
        self.calls += 1
        self.finished_with.append(run.outcome)

    def states_of(self, key):
        return [state for k, state in self.states if k == key]


class FakeInstall:
    """Just what engine.Run reads from install-manager, with real Step/Options/LOCK_SIGNATURE."""
    Step = install.Step
    Options = install.Options
    LOCK_SIGNATURE = install.LOCK_SIGNATURE
    ENGINEER_RECONNECT = 'RECONNECT-NOTICE'
    RESTART_HINT = 'restart hint'

    def __init__(self, source, steps, free=(True,), holder='Package lock held by pid 2230', wait_script=None):
        self.SOURCE = source
        self.steps = steps
        self.free_values = list(free)
        self.holder = holder
        self.wait_script = wait_script
        self.lazydocker_result = ('installed', 'lazydocker 1.0 installed')
        self.check_error = None
        self.check_args = None
        self.actions = []
        self.lock_checks = 0

    def action_steps(self, action, env, version, options):
        self.actions.append((action, version, options))
        return list(self.steps)

    def check_manager(self, env, version, say=print, sudo=('sudo',)):
        self.check_args = (version, tuple(sudo))
        if self.check_error:
            raise ValueError(self.check_error)
        say('Manager running')
        return 'http://127.0.0.1:8081/'

    def setup_lazydocker(self, env, say=print):
        say('lazydocker output')
        return self.lazydocker_result

    def git_setup(self, env):
        return 0

    def run(self, argv, env):
        return subprocess.CompletedProcess(argv, 0)

    def lock_free(self, env):
        self.lock_checks += 1
        return self.free_values.pop(0) if len(self.free_values) > 1 else self.free_values[0]

    def lock_holder_text(self, env):
        return self.holder

    def lock_wait_command(self):
        return ['sh', self.wait_script]


class EngineCase(IsolatedCase):
    def setUp(self):
        super().setUp()
        self.source = self.tmp / 'source'
        self.source.mkdir()
        for target, value in (('credentials_cached', True),):
            patcher = patch.object(engine, target, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)
        # The engine asks core.run_capture only for the clab-discovery password state.
        patcher = patch.object(core, 'run_capture', return_value=(0, 'clab-discovery P 2024-01-01 0 99999 7 -1'))
        patcher.start()
        self.addCleanup(patcher.stop)

    # -- scripts -----------------------------------------------------------------------------
    def counter(self, name):
        return self.tmp / f'count-{name}'

    def count(self, name):
        path = self.counter(name)
        return len(path.read_text().splitlines()) if path.exists() else 0

    def ok_script(self, name, line=None):
        return self.script(name, f'echo x >> {shlex.quote(str(self.counter(name)))}\n'
                                 f'echo {shlex.quote(line or "output of " + name)}')

    def fail_then_ok(self, name, first_output='', code=3):
        counter = shlex.quote(str(self.counter(name)))
        echo = f'echo {shlex.quote(first_output)}' if first_output else ':'
        return self.script(name, f'echo x >> {counter}\nn=$(wc -l < {counter})\n'
                                 f'if [ "$n" -lt 2 ]; then {echo}; exit {code}; fi\necho "{name} ok"')

    def always_fail(self, name, output='', code=3):
        echo = f'echo {shlex.quote(output)}' if output else ':'
        return self.script(name, f'echo x >> {shlex.quote(str(self.counter(name)))}\n{echo}\nexit {code}')

    def gated(self, name):
        """Runs until the test creates <name>.go; creates <name>.started when it begins."""
        started, go = self.tmp / f'{name}.started', self.tmp / f'{name}.go'
        return self.script(name, f'echo x >> {shlex.quote(str(self.counter(name)))}\n'
                                 f': > {shlex.quote(str(started))}\n'
                                 f'i=0\nwhile [ ! -f {shlex.quote(str(go))} ] && [ "$i" -lt 600 ]; do i=$((i+1)); sleep 0.05; done')

    def step(self, key, script, **kwargs):
        return install.Step(key, 'Title ' + key, None, argv=['sh', script], **kwargs)

    # -- running -----------------------------------------------------------------------------
    def build(self, steps, bridge=None, lock=None, **fake):
        self.fake = FakeInstall(self.source, steps, **fake)
        self.bridge = bridge if bridge is not None else FakeBridge()
        self.run_ = engine.Run(self.fake, 'install', self.env, '1.2.3', install.Options(), self.bridge, lock)
        return self.run_

    def go(self, steps, bridge=None, lock=None, **fake):
        run = self.build(steps, bridge, lock, **fake)
        run.start()
        self.join(run)
        return run

    def join(self, run):
        run.thread.join(30)
        self.assertFalse(run.thread.is_alive(), 'the run thread must end')

    def states(self, run):
        return {p.key: p.state for p in run.phases}


class EngineRunTests(EngineCase):
    def test_all_phases_complete_in_plan_order(self):
        steps = [install.Step('admin', 'Admin', None, argv=['sudo', '-v'], interactive='auth'),
                 self.step('prereqs', self.ok_script('prereqs'), tee=True),
                 self.step('launch', self.ok_script('launch')),
                 self.step('capture', self.ok_script('capture')),
                 self.step('engineer', self.ok_script('engineer'))]
        run = self.go(steps)
        self.assertEqual(run.outcome, 'completed')
        self.assertEqual([p.key for p in run.phases], ['admin', 'prereqs', 'launch', 'capture', 'engineer'])
        self.assertTrue(all(p.state == engine.COMPLETED for p in run.phases), self.states(run))
        self.assertEqual(self.bridge.finished_with, ['completed'])
        for name in ('prereqs', 'launch', 'capture', 'engineer'):
            self.assertEqual(self.count(name), 1)
            self.assertEqual(self.bridge.lines[name], ['output of ' + name])
        self.assertEqual(run.phase('engineer').note, 'RECONNECT-NOTICE')
        started = [key for key, state in self.bridge.states if state == engine.RUNNING]
        self.assertEqual(started, ['admin', 'prereqs', 'launch', 'capture', 'engineer'])
        finished = [key for key, state in self.bridge.states if state == engine.COMPLETED]
        self.assertEqual(finished, started)
        self.assertEqual(self.bridge.states_of('launch'), [engine.RUNNING, engine.COMPLETED])
        self.assertEqual(self.fake.actions, [('install', '1.2.3', run.options)])
        self.assertEqual(self.bridge.recovers, [])

    def test_invisible_steps_are_not_run_or_listed(self):
        steps = [self.step('prereqs', self.ok_script('prereqs')),
                 self.step('capture', self.ok_script('capture'), visible=False)]
        run = self.go(steps)
        self.assertEqual([p.key for p in run.phases], ['prereqs'])
        self.assertEqual(self.count('capture'), 0)

    def test_a_run_without_a_bridge_uses_the_null_bridge(self):
        run = engine.Run(FakeInstall(self.source, [self.step('prereqs', self.ok_script('prereqs'))]),
                         'install', self.env, '1.2.3', None)
        run.start()
        self.join(run)
        self.assertEqual(run.outcome, 'completed')

    def test_non_sudo_argv_runs_as_given_and_sudo_gets_n(self):
        recorded = []

        class Recording:
            def __init__(self, argv, env, cwd, **kwargs):
                recorded.append((list(argv), cwd, kwargs))
                self.process = None

            def run(self):
                return 0
        steps = [install.Step('prereqs', 'T', None, argv=['sudo', 'bash', 'x.sh', '--flag'], tee=True),
                 install.Step('capture', 'T', None, argv=['bash', 'y.sh'])]
        lock = core.InstallerLock(self.tmp / 'run.lock').acquire()
        held_fd = lock.fd
        with patch.object(engine.core, 'StepProcess', Recording):
            run = self.go(steps, lock=lock)
        self.assertEqual(run.outcome, 'completed')
        self.assertEqual(recorded[0][0], ['sudo', '-n', 'bash', 'x.sh', '--flag'])
        self.assertEqual(recorded[1][0], ['bash', 'y.sh'])
        self.assertEqual(recorded[0][1], str(self.source))
        self.assertIs(recorded[0][2]['lock_signature'], install.LOCK_SIGNATURE, 'only a tee step looks for the lock text')
        self.assertIsNone(recorded[1][2]['lock_signature'])
        self.assertEqual(recorded[0][2]['pass_fds'], (held_fd,))

    def test_the_installer_lock_descriptor_is_inherited_by_step_processes(self):
        lock = core.InstallerLock(self.tmp / 'run.lock').acquire()
        fd = lock.fd
        script = self.script('fdcheck', f'if [ -e /proc/$$/fd/{fd} ]; then echo FD-HELD; else echo FD-MISSING; fi')
        run = self.go([self.step('prereqs', script)], lock=lock)
        self.assertEqual(self.bridge.lines['prereqs'], ['FD-HELD'])
        self.assertFalse(lock.held, 'released when the run ends')
        core.InstallerLock(self.tmp / 'run.lock').acquire().release()
        self.assertEqual(run.outcome, 'completed')

    def test_failing_phase_retry_repeats_only_that_phase(self):
        steps = [self.step('prereqs', self.ok_script('prereqs')),
                 self.step('launch', self.fail_then_ok('launch', 'boom output', code=3)),
                 self.step('capture', self.ok_script('capture'))]
        run = self.go(steps, FakeBridge(recover=[engine.RETRY]))
        self.assertEqual(run.outcome, 'completed')
        self.assertEqual((self.count('prereqs'), self.count('launch'), self.count('capture')), (1, 2, 1))
        self.assertEqual(run.phase('launch').attempts, 2)
        self.assertEqual(run.phase('prereqs').attempts, 1)
        self.assertEqual(len(self.bridge.recovers), 1)
        key, kind, choices, holder, message = self.bridge.recovers[0]
        self.assertEqual((key, kind, choices), ('launch', 'command', (engine.RETRY, engine.RETURN)))
        self.assertIn('exit status 3', message)
        self.assertEqual(self.bridge.states_of('launch'),
                         [engine.RUNNING, engine.FAILED, engine.RUNNING, engine.COMPLETED])
        self.assertIsNone(run.phase('launch').failure, 'a successful retry clears the failure')
        self.assertEqual(run.phase('launch').code, 0)

    def test_return_keeps_completed_work_and_starts_nothing_later(self):
        steps = [self.step('prereqs', self.ok_script('prereqs')),
                 self.step('launch', self.always_fail('launch', 'bad', code=5)),
                 self.step('capture', self.ok_script('capture')),
                 self.step('engineer', self.ok_script('engineer'))]
        run = self.go(steps, FakeBridge(recover=[engine.RETURN]))
        self.assertEqual(run.outcome, 'returned')
        self.assertEqual(self.states(run), {'prereqs': engine.COMPLETED, 'launch': engine.FAILED,
                                            'capture': engine.NOT_STARTED, 'engineer': engine.NOT_STARTED})
        self.assertEqual((self.count('capture'), self.count('engineer')), (0, 0))
        self.assertEqual(run.phase('launch').code, 5)
        self.assertEqual(run.phase('launch').failure.kind, 'command')
        self.assertEqual(self.bridge.finished_with, ['returned'])

    def test_request_stop_lets_the_active_phase_finish_and_starts_nothing_later(self):
        steps = [self.step('prereqs', self.ok_script('prereqs')),
                 self.step('launch', self.gated('launch')),
                 self.step('capture', self.ok_script('capture')),
                 self.step('engineer', self.ok_script('engineer'))]
        run = self.build(steps)
        run.start()
        self.assertTrue(wait_for(lambda: (self.tmp / 'launch.started').exists()))
        run.request_stop()
        self.assertTrue(run.thread.is_alive(), 'the active phase is still running')
        (self.tmp / 'launch.go').write_text('')
        self.join(run)
        self.assertEqual(run.outcome, 'stopped')
        self.assertEqual(self.states(run), {'prereqs': engine.COMPLETED, 'launch': engine.COMPLETED,
                                            'capture': engine.STOPPED, 'engineer': engine.STOPPED})
        self.assertEqual((self.count('capture'), self.count('engineer')), (0, 0))
        self.assertEqual(run.stop.reason, 'stop after current step')
        self.assertEqual(run.record()['interrupted'], '', 'a deliberate stop is not a lost terminal')
        self.assertEqual(run.record()['outcome'], 'stopped')
        self.assertEqual(self.bridge.finished_with, ['stopped'])

    def test_disconnect_finishes_the_active_phase_and_nothing_else_reaches_the_bridge(self):
        steps = [self.step('prereqs', self.ok_script('prereqs')),
                 self.step('launch', self.gated('launch')),
                 self.step('capture', self.ok_script('capture')),
                 self.step('engineer', self.ok_script('engineer'))]
        run = self.build(steps)
        run.start()
        self.assertTrue(wait_for(lambda: (self.tmp / 'launch.started').exists()))
        run.disconnect()
        calls_at_disconnect = self.bridge.calls
        states_at_disconnect = list(self.bridge.states)
        self.assertIsInstance(run.bridge, engine.NullBridge)
        (self.tmp / 'launch.go').write_text('')
        self.join(run)
        self.assertEqual(run.outcome, 'interrupted')
        self.assertEqual(self.states(run), {'prereqs': engine.COMPLETED, 'launch': engine.COMPLETED,
                                            'capture': engine.STOPPED, 'engineer': engine.STOPPED})
        self.assertEqual((self.count('capture'), self.count('engineer')), (0, 0))
        self.assertEqual(self.bridge.calls, calls_at_disconnect, 'no bridge call after disconnect')
        self.assertEqual(self.bridge.states, states_at_disconnect)
        self.assertEqual(self.bridge.finished_with, [])
        record = run.record()
        self.assertEqual(record['interrupted'], 'terminal disconnected')
        self.assertEqual(record['outcome'], 'interrupted')

    def test_a_failure_after_disconnect_asks_nothing_and_starts_nothing_later(self):
        steps = [self.step('launch', self.gated('launch')), self.step('capture', self.ok_script('capture'))]
        steps[0].argv = ['sh', self.script('failing', f': > {shlex.quote(str(self.tmp / "failing.started"))}\n'
                                                      f'while [ ! -f {shlex.quote(str(self.tmp / "failing.go"))} ]; do sleep 0.05; done\nexit 4')]
        run = self.build(steps, FakeBridge(recover=[engine.RETRY]))
        run.start()
        self.assertTrue(wait_for(lambda: (self.tmp / 'failing.started').exists()))
        run.disconnect()
        (self.tmp / 'failing.go').write_text('')
        self.join(run)
        self.assertEqual(run.outcome, 'interrupted')
        self.assertEqual(self.bridge.recovers, [])
        self.assertEqual(self.states(run)['launch'], engine.FAILED)
        self.assertEqual(self.states(run)['capture'], engine.NOT_STARTED)
        self.assertEqual(self.count('capture'), 0)

    def test_lock_signature_failure_on_a_tee_step_offers_the_lock_choices(self):
        steps = [self.step('prereqs', self.always_fail('prereqs', LOCK_TEXT, code=100), tee=True),
                 self.step('launch', self.ok_script('launch'))]
        run = self.go(steps, FakeBridge(recover=[engine.RETURN]), free=(False,), holder='held by pid 2230 (unattended-upgr)')
        key, kind, choices, holder, message = self.bridge.recovers[0]
        self.assertEqual(kind, 'lock')
        self.assertEqual(choices, (engine.LOCK_WAIT, engine.RETRY, engine.LOCK_CHECK, engine.RETURN))
        self.assertEqual(holder, 'held by pid 2230 (unattended-upgr)')
        self.assertEqual(run.phase('prereqs').failure.kind, 'lock')
        self.assertEqual(run.outcome, 'returned')
        self.assertIn(LOCK_TEXT, self.bridge.lines['prereqs'])

    def test_lock_holder_is_dropped_when_the_lock_is_already_free(self):
        steps = [self.step('prereqs', self.always_fail('prereqs', LOCK_TEXT, code=100), tee=True)]
        self.go(steps, FakeBridge(recover=[engine.RETURN]), free=(True,))
        self.assertEqual(self.bridge.recovers[0][1], 'lock')
        self.assertEqual(self.bridge.recovers[0][3], '')

    def test_the_same_text_from_a_non_tee_step_is_an_ordinary_command_failure(self):
        steps = [self.step('launch', self.always_fail('launch', LOCK_TEXT, code=100))]
        self.go(steps, FakeBridge(recover=[engine.RETURN]))
        key, kind, choices, holder, message = self.bridge.recovers[0]
        self.assertEqual(kind, 'command')
        self.assertEqual(choices, (engine.RETRY, engine.RETURN))
        self.assertNotIn(engine.LOCK_WAIT, choices)

    def test_lock_check_retries_when_the_lock_is_free(self):
        steps = [self.step('prereqs', self.fail_then_ok('prereqs', LOCK_TEXT, code=100), tee=True)]
        run = self.go(steps, FakeBridge(recover=[engine.LOCK_CHECK]), free=(False, True))
        self.assertEqual(run.outcome, 'completed')
        self.assertEqual(self.count('prereqs'), 2)
        self.assertEqual(len(self.bridge.recovers), 1, 'the check retried by itself; no second prompt')

    def test_lock_check_with_a_held_lock_refreshes_the_holder_and_asks_again(self):
        steps = [self.step('prereqs', self.always_fail('prereqs', LOCK_TEXT, code=100), tee=True)]
        run = self.go(steps, FakeBridge(recover=[engine.LOCK_CHECK, engine.RETURN]), free=(False,),
                      holder='fresh holder report')
        self.assertEqual(len(self.bridge.recovers), 2)
        self.assertEqual(self.bridge.recovers[1][3], 'fresh holder report')
        self.assertEqual(self.count('prereqs'), 1)
        self.assertEqual(run.outcome, 'returned')

    def test_lock_wait_runs_the_wait_command_then_retries(self):
        wait = self.script('wait', f'echo x >> {shlex.quote(str(self.counter("wait")))}\necho waiting for the lock')
        steps = [self.step('prereqs', self.fail_then_ok('prereqs', LOCK_TEXT, code=100), tee=True)]
        run = self.go(steps, FakeBridge(recover=[engine.LOCK_WAIT]), free=(False,), wait_script=wait)
        self.assertEqual(run.outcome, 'completed')
        self.assertEqual((self.count('wait'), self.count('prereqs')), (1, 2))
        self.assertIn('waiting for the lock', self.bridge.lines['prereqs'])

    def test_lock_wait_that_does_not_release_asks_again(self):
        wait = self.script('wait', 'exit 1')
        steps = [self.step('prereqs', self.always_fail('prereqs', LOCK_TEXT, code=100), tee=True)]
        run = self.go(steps, FakeBridge(recover=[engine.LOCK_WAIT, engine.RETURN]), free=(False,), wait_script=wait)
        self.assertEqual(len(self.bridge.recovers), 2)
        self.assertEqual(run.outcome, 'returned')

    def test_auth_signature_offers_authenticate_then_retry(self):
        steps = [self.step('launch', self.fail_then_ok('launch', 'sudo: a password is required', code=1)),
                 self.step('capture', self.ok_script('capture'))]
        run = self.go(steps, FakeBridge(recover=[engine.AUTH_RETRY], handoff=[0]))
        key, kind, choices, holder, message = self.bridge.recovers[0]
        self.assertEqual((kind, choices), ('auth', (engine.AUTH_RETRY, engine.RETURN)))
        self.assertEqual(self.bridge.handoffs, ['Administrator access'])
        self.assertEqual(self.count('launch'), 2)
        self.assertEqual(run.outcome, 'completed')

    def test_failed_authentication_asks_again_with_an_auth_failure(self):
        steps = [self.step('launch', self.always_fail('launch', 'sudo: a password is required', code=1))]
        run = self.go(steps, FakeBridge(recover=[engine.AUTH_RETRY, engine.RETURN], handoff=[1]))
        self.assertEqual([r[1] for r in self.bridge.recovers], ['auth', 'auth'])
        self.assertIn('not confirmed', self.bridge.recovers[1][4])
        self.assertEqual(self.count('launch'), 1)
        self.assertEqual(run.outcome, 'returned')

    def test_without_cached_credentials_the_terminal_is_handed_over_before_the_command(self):
        steps = [self.step('launch', self.ok_script('launch'))]
        with patch.object(engine, 'credentials_cached', return_value=False):
            run = self.go(steps, FakeBridge(handoff=[0]))
        self.assertEqual(self.bridge.handoffs, ['Administrator access'])
        self.assertEqual(run.outcome, 'completed')
        self.assertIn(engine.WAITING, self.bridge.states_of('launch'))

    def test_the_first_time_password_launcher_has_the_terminal_and_a_set_password_does_not(self):
        steps = [self.step('launch', self.ok_script('launch'), interactive='password')]
        with patch.object(core, 'run_capture', return_value=(1, 'passwd: unknown user clab-discovery')):
            run = self.go(steps, FakeBridge(handoff=[0]))
        self.assertEqual(self.bridge.handoffs, ['Password, helpers, image and manager'])
        self.assertEqual(self.count('launch'), 0, 'the handoff runs the launcher, not the piped child')
        self.assertEqual(run.outcome, 'completed')
        steps = [self.step('launch', self.ok_script('launch'), interactive='password')]
        run = self.go(steps)   # run_capture patched in setUp: the password is already set
        self.assertEqual(self.bridge.handoffs, [])
        self.assertEqual(self.count('launch'), 1)

    def test_a_failed_password_handoff_is_reported(self):
        steps = [self.step('launch', self.ok_script('launch'), interactive='password')]
        with patch.object(core, 'run_capture', return_value=(1, 'passwd: unknown user')):
            self.go(steps, FakeBridge(handoff=[9]))
        self.assertEqual(self.bridge.recovers[0][1], 'command')
        self.assertIn('exit status 9', self.bridge.recovers[0][4])

    def test_git_post_phase_failure_can_be_skipped_leaving_a_partial_outcome(self):
        steps = [self.step('prereqs', self.ok_script('prereqs')),
                 install.Step('git', 'Git setup', None, argv=['bash', 'setup-git.sh'], interactive='always',
                              bare=True, post=True)]
        run = self.go(steps, FakeBridge(recover=[engine.SKIP], handoff=[1]))
        key, kind, choices, holder, message = self.bridge.recovers[0]
        self.assertEqual((key, kind), ('git', 'git'))
        self.assertEqual(choices, (engine.RETRY, engine.SKIP, engine.RETURN))
        self.assertEqual(self.bridge.handoffs, ['Git setup'])
        self.assertEqual(run.phase('git').state, engine.SKIPPED)
        self.assertEqual(run.phase('git').code, 1)
        self.assertEqual(run.outcome, 'partial')

    def test_git_that_is_not_post_cannot_be_skipped(self):
        steps = [install.Step('git', 'Git setup', None, argv=['bash', 'setup-git.sh'], interactive='always', bare=True)]
        self.go(steps, FakeBridge(handoff=[1]))
        self.assertEqual(self.bridge.recovers[0][2], (engine.RETRY, engine.RETURN))

    def test_git_success_and_a_handoff_that_could_not_happen(self):
        steps = [install.Step('git', 'Git setup', None, argv=['bash', 'g.sh'], interactive='always', bare=True, post=True)]
        run = self.go(steps, FakeBridge(handoff=[0]))
        self.assertEqual((run.phase('git').state, run.outcome), (engine.COMPLETED, 'completed'))

        class Refusing(FakeBridge):
            def handoff(self, title, notice, work):
                return None
        steps = [install.Step('git', 'Git setup', None, argv=['bash', 'g.sh'], interactive='always', bare=True, post=True)]
        self.go(steps, Refusing(recover=[engine.RETURN]))
        self.assertEqual(self.bridge.recovers[0][1], 'handoff')

    def test_skipped_lazydocker_does_not_stop_a_completed_run(self):
        steps = [self.step('prereqs', self.ok_script('prereqs')),
                 install.Step('lazydocker', 'lazydocker (optional)', None, bare=True, post=True),
                 install.Step('git', 'Git setup', None, argv=['bash', 'g.sh'], interactive='always', bare=True, post=True)]
        run = self.build(steps, FakeBridge(handoff=[0]))
        self.fake.lazydocker_result = ('skipped', 'unsupported architecture (riscv64)')
        run.start()
        self.join(run)
        self.assertEqual(run.phase('lazydocker').state, engine.SKIPPED)
        self.assertEqual(run.phase('lazydocker').note, 'unsupported architecture (riscv64)')
        self.assertEqual(run.phase('git').state, engine.COMPLETED)
        self.assertEqual(run.outcome, 'completed')
        self.assertEqual(self.bridge.lines['lazydocker'], ['lazydocker output'])

    def test_installed_lazydocker_completes_with_its_note(self):
        steps = [install.Step('lazydocker', 'lazydocker (optional)', None, bare=True, post=True)]
        run = self.go(steps)
        self.assertEqual(run.phase('lazydocker').state, engine.COMPLETED)
        self.assertEqual(run.phase('lazydocker').note, 'lazydocker 1.0 installed')

    def test_verify_phase_reports_the_manager_address_and_failures(self):
        steps = [install.Step('verify', 'Verify', None)]
        run = self.go(steps)
        self.assertEqual(run.phase('verify').outcome, 'http://127.0.0.1:8081/')
        self.assertEqual(self.fake.check_args, ('1.2.3', ('sudo', '-n')))
        self.assertEqual(self.bridge.lines['verify'], ['Manager running'])
        steps = [install.Step('verify', 'Verify', None)]
        run = self.build(steps, FakeBridge(recover=[engine.RETURN]))
        self.fake.check_error = 'The Compose manager is not running.'
        run.start()
        self.join(run)
        self.assertEqual(self.bridge.recovers[0][1], 'verify')
        self.assertEqual(run.outcome, 'returned')

    def test_settings_phase_copies_without_showing_contents_and_reports_errors(self):
        copied = []
        steps = [install.Step('settings', 'Copy', lambda: copied.append('done'), bare=True)]
        run = self.go(steps)
        self.assertEqual(copied, ['done'])
        self.assertIn('contents not shown', run.phase('settings').note)

        def failing():
            raise FileExistsError('exists')
        steps = [install.Step('settings', 'Copy', failing, bare=True)]
        self.go(steps, FakeBridge(recover=[engine.RETURN]))
        self.assertEqual(self.bridge.recovers[0][1], 'settings')

    def test_an_internal_error_is_a_recoverable_failure_not_a_dead_run(self):
        steps = [install.Step('weird', 'No argv and no special key', None)]
        run = self.go(steps, FakeBridge(recover=[engine.RETURN]))
        self.assertEqual(self.bridge.recovers[0][1], 'internal')
        self.assertEqual(run.outcome, 'returned')
        self.assertFalse(run.active)

    def test_the_run_lock_is_released_when_the_run_ends_even_on_failure(self):
        path = self.tmp / 'run.lock'
        lock = core.InstallerLock(path).acquire()
        run = self.go([self.step('launch', self.always_fail('launch'))], FakeBridge(recover=[engine.RETURN]), lock=lock)
        self.assertEqual(run.outcome, 'returned')
        self.assertFalse(lock.held)
        core.InstallerLock(path).acquire().release()
        lock = core.InstallerLock(path).acquire()
        self.go([self.step('launch', self.ok_script('launch'))], lock=lock)
        self.assertFalse(lock.held)

    def test_the_run_lock_is_released_after_a_stop_too(self):
        lock = core.InstallerLock(self.tmp / 'run.lock').acquire()
        run = self.build([self.step('launch', self.gated('launch')), self.step('capture', self.ok_script('capture'))],
                         lock=lock)
        run.start()
        self.assertTrue(wait_for(lambda: (self.tmp / 'launch.started').exists()))
        self.assertTrue(lock.held)
        run.request_stop()
        (self.tmp / 'launch.go').write_text('')
        self.join(run)
        self.assertFalse(lock.held)

    def test_record_holds_only_metadata(self):
        sentinel = 'SENTINEL-OUTPUT-LINE-9f2c'
        steps = [self.step('prereqs', self.ok_script('prereqs', sentinel)),
                 self.step('launch', self.fail_then_ok('launch', sentinel + ' failing', code=3))]
        run = self.go(steps, FakeBridge(recover=[engine.RETRY]))
        record = run.record()
        self.assertEqual(set(record), {'schema', 'action', 'version', 'started', 'finished', 'outcome',
                                       'interrupted', 'phases'})
        self.assertEqual((record['schema'], record['action'], record['version'], record['outcome'], record['interrupted']),
                         ('clab-node-manager-installer-run-v1', 'install', '1.2.3', 'completed', ''))
        self.assertEqual(len(record['phases']), 2)
        for phase in record['phases']:
            self.assertEqual(set(phase), {'key', 'state', 'exit_status', 'attempts', 'seconds'})
        self.assertEqual([(p['key'], p['state'], p['exit_status'], p['attempts']) for p in record['phases']],
                         [('prereqs', 'Completed', 0, 1), ('launch', 'Completed', 0, 2)])
        self.assertRegex(record['started'], r'^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d')
        self.assertNotIn(sentinel, json.dumps(record))
        stored = core.read_run_record(self.env)
        self.assertEqual(stored, record)
        text = (core.state_dir(self.env) / 'installer-last-run.json').read_text()
        self.assertNotIn(sentinel, text)
        self.assertNotIn(str(self.tmp), text, 'no paths are persisted')

    def test_record_of_phases_that_never_started_has_no_times(self):
        run = self.go([self.step('launch', self.always_fail('launch')), self.step('capture', self.ok_script('capture'))],
                      FakeBridge(recover=[engine.RETURN]))
        phases = {p['key']: p for p in run.record()['phases']}
        self.assertEqual(phases['capture'], {'key': 'capture', 'state': 'Not started', 'exit_status': None,
                                             'attempts': 0, 'seconds': None})
        self.assertIsInstance(phases['launch']['seconds'], float)


class CancelLockWaitTests(EngineCase):
    CHILD = ('import signal, sys, time, pathlib\n'
             'd = pathlib.Path(sys.argv[1])\n'
             'def handler(*args):\n'
             '    (d / "got-sigint").write_text("1"); sys.exit(0)\n'
             'signal.signal(signal.SIGINT, handler)\n'
             '(d / "ready").write_text("1")\n'
             'time.sleep(30)\n')

    def test_cancel_lock_wait_sends_sigint_to_the_waiters_process_group(self):
        run = self.build([])
        waiter = core.StepProcess([sys.executable, '-c', self.CHILD, str(self.tmp)], self.env, str(self.tmp))
        waiter.start()
        try:
            run._lock_waiter = waiter
            self.assertTrue(wait_for(lambda: (self.tmp / 'ready').exists()))
            run.cancel_lock_wait()
            result = {}
            thread = threading.Thread(target=lambda: result.update(code=waiter.wait()), daemon=True)
            thread.start()
            thread.join(15)
            self.assertFalse(thread.is_alive())
        finally:
            if waiter.process.poll() is None:
                waiter.process.kill()
        self.assertEqual(result['code'], 0)
        self.assertTrue((self.tmp / 'got-sigint').exists(), 'the waiter saw SIGINT, so it can restore the APT timers')

    def test_cancel_lock_wait_without_a_waiter_or_after_it_exited_is_harmless(self):
        run = self.build([])
        run.cancel_lock_wait()
        waiter = core.StepProcess(['sh', self.script('quick', 'exit 0')], self.env, str(self.tmp))
        waiter.run()
        run._lock_waiter = waiter
        run.cancel_lock_wait()


# ---------------------------------------------------------------------------------------------
# 9. plan parity with the plain install-manager menu (real module, no mocks of action_steps)
# ---------------------------------------------------------------------------------------------
class PlanParityTests(unittest.TestCase):
    ENV = {'USER': 'owner', 'HOME': '/home/owner'}
    VERSION = '1.30.35'

    def plain_sequence(self, options, advanced):
        """What install() really runs, as [('run', argv, tee) | ('settings', path) | ('verify',) | ('lazydocker',)]."""
        sequence = []

        def fake_run(args, env, capture=False, tee=False):
            sequence.append(('run', list(args), tee))
            return subprocess.CompletedProcess(args, 0, stdout='')
        with patch.object(install, 'ask_install_options', return_value=options), \
                patch.object(install, 'confirm', return_value=True), \
                patch.object(install, 'menu', return_value='1' if options.git_now else '2'), \
                patch.object(install, 'copy_env', side_effect=lambda path: path is not None and sequence.append(('settings', path))), \
                patch.object(install, 'verify_manager', side_effect=lambda env, version: sequence.append(('verify',))), \
                patch.object(install, 'setup_lazydocker', side_effect=lambda env, say=print: sequence.append(('lazydocker',))), \
                patch.object(install, 'run', side_effect=fake_run), patch('sys.stdout', new=io.StringIO()):
            install.install(self.ENV, self.VERSION, advanced=advanced)
        return sequence

    def planned_sequence(self, steps, options):
        sequence = []
        for step in steps:
            if not step.visible:
                continue
            if step.argv:
                sequence.append(('run', list(step.argv), step.tee))
            elif step.key == 'settings':   # (plain install() also calls copy_env(None), a no-op, when invisible)
                sequence.append(('settings', options.env_source))
            elif step.key in ('verify', 'lazydocker'):
                sequence.append((step.key,))
            else:
                self.fail(f'unexpected step {step.key}')
        return sequence

    def assert_plan_matches_plain(self, options, advanced):
        steps = install.action_steps('install', self.ENV, self.VERSION, options)
        plain = self.plain_sequence(options, advanced)
        planned = self.planned_sequence(steps, options)
        self.assertEqual(len(planned), len(plain), (planned, plain))
        for expected, actual in zip(plain, planned):
            self.assertEqual(actual, expected)
        # Every argv element-by-element, and the full-screen noninteractive form differs by -n only.
        for step in steps:
            if not step.argv:
                continue
            piped = core.noninteractive(step.argv)
            if step.argv[0] == 'sudo':
                self.assertEqual(piped[:2], ['sudo', '-n'])
                self.assertEqual(piped[2:], step.argv[1:])
                self.assertEqual(len(piped), len(step.argv) + 1)
            else:
                self.assertEqual(piped, step.argv)
        return steps

    def test_standard_options_match_the_plain_standard_path(self):
        steps = self.assert_plan_matches_plain(install.Options(), advanced=False)
        self.assertEqual([s.key for s in steps if s.visible],
                         ['admin', 'prereqs', 'launch', 'capture', 'verify', 'engineer', 'lazydocker', 'git'])

    def test_every_advanced_combination_matches_the_plain_advanced_path(self):
        count = 0
        for operations, engineer, repair, git_now, env_source in itertools.product(
                ('1', '2'), ('1', '2'), (True, False), (True, False), (None, Path('/home/owner/old/clab-backup-ui/.env'))):
            options = install.Options(env_source, operations, engineer, repair, git_now)
            with self.subTest(operations=operations, engineer=engineer, repair=repair, git_now=git_now,
                              env_source=str(env_source)):
                steps = self.assert_plan_matches_plain(options, advanced=True)
                keys = [s.key for s in steps if s.visible]
                self.assertEqual('git' in keys, git_now)
                self.assertEqual('settings' in keys, env_source is not None)
                self.assertEqual('engineer' in keys, options.engineer == '1')
                launch = next(s for s in steps if s.key == 'launch')
                self.assertEqual('--enable-operations' in launch.argv, operations == '1')
                prereqs = next(s for s in steps if s.key == 'prereqs')
                self.assertEqual('--repair-install-media' in prereqs.argv, repair)
                count += 1
        self.assertEqual(count, 32)

    def test_step_actions_run_the_same_commands_as_the_steps_declare(self):
        options = install.Options(env_source=None, operations='1', engineer='1', repair=True, git_now=True)
        for step in install.action_steps('install', self.ENV, self.VERSION, options):
            if not step.argv:
                continue
            with self.subTest(step=step.key):
                seen = []
                with patch.object(install, 'run', side_effect=lambda args, env, capture=False, tee=False:
                                  (seen.append((list(args), tee)), subprocess.CompletedProcess(args, 0, stdout=''))[1]), \
                        patch('sys.stdout', new=io.StringIO()):
                    step.action()
                self.assertEqual(seen, [(list(step.argv), step.tee)])

    def test_single_actions_match_what_main_runs(self):
        def captured(call):
            seen = []
            with patch.object(install, 'run', side_effect=lambda args, env, capture=False, tee=False:
                              (seen.append(list(args)), subprocess.CompletedProcess(args, 0, stdout=''))[1]), \
                    patch('sys.stdout', new=io.StringIO()):
                call()
            return seen
        env = self.ENV
        engineer = install.action_steps('engineer', env, self.VERSION)
        self.assertEqual(len(engineer), 1)
        self.assertEqual(engineer[0].argv, install.engineer_command(env))
        self.assertEqual(captured(lambda: install.engineer_access(env)), [engineer[0].argv])
        capture = install.action_steps('capture', env, self.VERSION)
        self.assertEqual(len(capture), 1)
        self.assertEqual(capture[0].argv, install.stack_command('setup-capture.sh'))
        self.assertEqual(captured(lambda: install.stacks(env)), [capture[0].argv])
        git = install.action_steps('git', env, self.VERSION)
        self.assertEqual(len(git), 1)
        self.assertEqual(git[0].argv, install.git_command())
        self.assertEqual(captured(lambda: install.git_setup(env)), [git[0].argv])

    def test_unknown_action_is_refused(self):
        with self.assertRaises(ValueError):
            install.action_steps('reboot', self.ENV, self.VERSION)

    def test_the_lock_signature_used_by_the_engine_is_the_one_the_plain_menu_uses(self):
        self.assertTrue(install.LOCK_SIGNATURE.search(LOCK_TEXT))
        self.assertFalse(install.LOCK_SIGNATURE.search('network unreachable'))


# ---------------------------------------------------------------------------------------------
# Source scan
# ---------------------------------------------------------------------------------------------
class SourceScanTests(unittest.TestCase):
    FILES = sorted((DEPLOY / 'installer_tui').glob('*.py'))

    def test_the_package_files_are_found(self):
        names = {path.name for path in self.FILES}
        self.assertTrue({'sanitize.py', 'core.py', 'bootstrap.py', 'probes.py', 'engine.py'} <= names, names)

    def test_nothing_in_the_package_can_reboot_power_off_or_clear_apt_locks_or_use_sudo_pip(self):
        for path in self.FILES:
            text = path.read_text().lower()
            for forbidden in ('reboot', 'shutdown', 'poweroff', 'rm -f /var/lib/dpkg', 'sudo pip', 'sudo -h pip',
                              'pip install --user', '--break-system-packages'):
                with self.subTest(file=path.name, forbidden=forbidden):
                    self.assertNotIn(forbidden, text)

    def test_the_lock_wait_is_cancelled_with_sigint_only(self):
        source = inspect.getsource(engine.Run.cancel_lock_wait)
        code = '\n'.join(line for line in source.splitlines() if not line.strip().startswith('#'))
        body = code.split('"""')[2] if code.count('"""') >= 2 else code
        self.assertIn('signal.SIGINT', body)
        self.assertNotIn('SIGTERM', body)
        self.assertNotIn('SIGKILL', body)
        self.assertNotIn('.terminate(', body)
        self.assertNotIn('.kill(', body)

    def test_no_file_sends_sigterm_or_sigkill_or_kills_a_process_directly(self):
        for path in self.FILES:
            text = path.read_text()
            with self.subTest(file=path.name):
                self.assertIsNone(re.search(r'(?:os\.)?kill(?:pg)?\s*\([^)]*SIG(?:TERM|KILL)', text))
                self.assertIsNone(re.search(r'\.(?:terminate|kill)\s*\(', text))
                self.assertIsNone(re.search(r'\bsend_signal\s*\(', text))

    def test_no_file_runs_a_shell_with_a_string_command(self):
        for path in self.FILES:
            with self.subTest(file=path.name):
                self.assertIsNone(re.search(r'shell\s*=\s*True|os\.system\s*\(|os\.popen\s*\(', path.read_text()))

    def test_standard_library_modules_do_not_import_textual_or_rich(self):
        for name in ('sanitize', 'core', 'bootstrap', 'probes', 'engine'):
            text = (DEPLOY / 'installer_tui' / f'{name}.py').read_text()
            with self.subTest(module=name):
                self.assertIsNone(re.search(r'^\s*(?:import|from)\s+(?:textual|rich)\b', text, re.M))


if __name__ == '__main__':
    unittest.main()
