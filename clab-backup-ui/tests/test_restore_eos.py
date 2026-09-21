"""Unit tests for the Arista EOS restore CLI driver against a scripted fake channel.

The fake models just enough of an EOS session (user/privileged prompts, an optional enable
password, configuration sessions with `rollback clean-config`, a `copy terminal:
session-config ... ^D` paste, `show session-config diffs`, `commit timer` with its pending
commit-timer table, and `configure session <name> commit` / `write memory`) to exercise the
driver's dialog without a real device.
"""
import socket
import unittest

from app.restore_eos import (EosShell, apply_shell, confirm_shell, capture_shell, pending_shell,
                              reach_cli, validate_candidate, supports_restore, RestoreError,
                              _minutes_to_hms)


class FakeDevice:
    def __init__(self, mode='unpriv', enable_password=None, pending_session=None,
                 load_error=False, commit_timer_ok=True, commit_confirm_ok=True,
                 write_memory_ok=True,
                 diff_text='--- system:/running-config\n+++ session:/x-session-config\n+hostname NEW\n',
                 running_config='! Command: show running-config\n! device: ceos\n!\nhostname ceos\n!\nend\n',
                 hostname='ceos', orphans=()):
        self.mode = mode
        self.enable_password = enable_password
        self.awaiting_enable_password = False
        self.pending_session = pending_session
        self.orphans = list(orphans)
        self.load_error = load_error
        self.commit_timer_ok = commit_timer_ok
        self.commit_confirm_ok = commit_confirm_ok
        self.write_memory_ok = write_memory_ok
        self.diff_text = diff_text
        self.running_config = running_config
        self.hostname = hostname
        self.session_name = None
        self.terminal = False
        self.loaded = ''
        self.commands = []

    def prompt(self):
        if self.mode == 'unpriv':
            return '%s>' % self.hostname
        if self.mode == 'session':
            return '%s(config-s-%s)#' % (self.hostname, self.session_name)
        return '%s#' % self.hostname

    def initial(self):
        return ('\r\n' + self.prompt()).encode()

    def frame(self, echo, output=''):
        body = echo + '\r\n'
        if output:
            body += output.replace('\n', '\r\n') + '\r\n'
        return (body + self.prompt()).encode()

    def _sessions_detail(self):
        # The layout of cEOS 4.35.0F. A session whose commit timer runs is listed as "committed";
        # "pending" is a session that was opened and neither committed nor aborted.
        head = ('Maximum number of completed sessions: 1\nMaximum number of pending sessions: 5\n'
                'Merge on commit is disabled\nAutosave to startup-config on commit is disabled\n\n')
        if self.pending_session:
            head += ('Session with pending commit timer: %s\n'
                     'Time left until commit timer expiry: in 0:01:59\n\n' % self.pending_session)
        rows = ['  Name             State     User  Terminal Completed Time      Committed By',
                '- ---------------- --------- ----- -------- ------------------- ------------']
        if self.pending_session:
            rows.append('  %-16s committed                2026-09-20 23:35:15 admin' % self.pending_session)
        rows += ['  %-16s pending   admin vty8' % name for name in self.orphans]
        rows.append('* s1               aborted   admin vty9     2026-09-20 22:19:28')
        return head + '\n'.join(rows)

    def _confirm(self, line):
        session = line[len('configure session '):-len(' commit')].strip()
        if self.pending_session != session:
            return self.frame(line, '%% Session %s not found' % session)
        if not self.commit_confirm_ok:
            return self.frame(line, '% Configure session commit failed')
        self.pending_session = None
        return self.frame(line)

    def _commit_timer(self, line):
        if not self.commit_timer_ok:
            return self.frame(line, '% Commit failed')
        self.pending_session = self.session_name
        self.mode = 'priv'
        return self.frame(line)

    def on_line(self, line):
        line = line.strip()
        if self.terminal:
            self.loaded += line + '\n'
            return b''  # still capturing pasted configuration; no prompt yet
        if self.awaiting_enable_password:
            self.awaiting_enable_password = False
            if line == self.enable_password:
                self.mode = 'priv'
                return b'\r\n' + self.prompt().encode()
            return b'\r\n% Bad passwords\r\n' + self.prompt().encode()
        self.commands.append(line)
        if line == 'enable':
            if self.mode == 'unpriv':
                if self.enable_password is not None:
                    self.awaiting_enable_password = True
                    return (line + '\r\nPassword: ').encode()
                self.mode = 'priv'
            return self.frame(line)
        if line in ('terminal length 0', 'terminal width 500'):
            return self.frame(line)
        if line == 'show configuration sessions detail':
            return self.frame(line, self._sessions_detail())
        if line.startswith('configure session ') and line.endswith(' commit'):
            return self._confirm(line)
        if line.startswith('configure session '):
            self.session_name = line[len('configure session '):].strip()
            self.mode = 'session'
            return self.frame(line)
        if line == 'rollback clean-config':
            return self.frame(line)
        if line == 'copy terminal: session-config':
            self.terminal = True
            self.loaded = ''
            return b''
        if line == 'show session-config diffs':
            return self.frame(line, self.diff_text)
        if line.startswith('commit timer '):
            return self._commit_timer(line)
        if line == 'abort':
            if self.session_name in self.orphans:
                self.orphans.remove(self.session_name)
            self.mode = 'priv'
            self.session_name = None
            return self.frame(line)
        if line == 'write memory':
            return self.frame(line, 'Copy completed successfully' if self.write_memory_ok
                               else '% Error: could not save configuration')
        if line == 'show running-config':
            return self.frame(line, self.running_config)
        return self.frame(line)

    def on_terminal_end(self, pasted):
        self.terminal = False
        self.loaded = pasted.decode('utf-8', 'replace')
        if self.load_error:
            return self.frame('', '> ! bad\n% Invalid input at line 4\nCopy completed successfully')
        return self.frame('', 'Copy completed successfully')


class FakeChannel:
    def __init__(self, device):
        self.device = device
        self.outbuf = b''
        self.inbuf = bytearray(device.initial())
        self.closed = False

    def settimeout(self, _):
        pass

    def sendall(self, data):
        self.outbuf += data
        while True:
            if b'\x04' in self.outbuf:
                pre, self.outbuf = self.outbuf.split(b'\x04', 1)
                self.inbuf += self.device.on_terminal_end(pre)
                continue
            if b'\n' in self.outbuf:
                line, self.outbuf = self.outbuf.split(b'\n', 1)
                self.inbuf += self.device.on_line(line.decode('utf-8', 'replace'))
                continue
            break

    def recv(self, n):
        if self.closed:
            return b''
        if not self.inbuf:
            raise socket.timeout()
        chunk = bytes(self.inbuf[:n])
        del self.inbuf[:n]
        return chunk

    def close(self):
        self.closed = True


CANDIDATE = ('! Command: show running-config\n'
             '! device: ceos\n'
             '!\n'
             'hostname NEW\n'
             '!\n'
             'interface Ethernet1\n'
             '   no switchport\n'
             '!\n'
             'end\n')


def shell_for(device):
    return EosShell(FakeChannel(device))


class RestoreEosDriverTests(unittest.TestCase):
    def test_supported_platforms(self):
        self.assertTrue(supports_restore('arista_ceos'))
        self.assertFalse(supports_restore('juniper_cjunosevolved'))
        self.assertFalse(supports_restore(None))

    def test_minutes_to_hms_formatting(self):
        self.assertEqual(_minutes_to_hms(5), '00:05:00')
        self.assertEqual(_minutes_to_hms(60), '01:00:00')

    # --- validate_candidate -----------------------------------------------------

    def test_validate_candidate_ok(self):
        validate_candidate(CANDIDATE)  # does not raise

    def test_validate_candidate_empty(self):
        with self.assertRaises(RestoreError):
            validate_candidate('   \n  ')

    def test_validate_candidate_missing_header(self):
        with self.assertRaises(RestoreError):
            validate_candidate('hostname NEW\n!\nend\n')

    def test_validate_candidate_truncated(self):
        with self.assertRaises(RestoreError):
            validate_candidate('! Command: show running-config\n!\nhostname NEW\n!\n')

    # --- apply_shell --------------------------------------------------------------

    def test_apply_happy_path(self):
        device = FakeDevice()
        result = apply_shell(shell_for(device), CANDIDATE, confirm_minutes=5)
        self.assertTrue(result['handle']['session'].startswith('clabmgr-'))
        self.assertFalse(result['no_op'])
        self.assertEqual(result['diff'], device.diff_text)
        self.assertEqual(result['confirm_minutes'], 5)
        self.assertIn('enable', device.commands)  # started at '>' in FakeDevice(mode='unpriv')
        rollback_index = device.commands.index('rollback clean-config')
        copy_index = device.commands.index('copy terminal: session-config')
        self.assertLess(rollback_index, copy_index)
        self.assertTrue(any(c.startswith('configure session clabmgr-') for c in device.commands))
        self.assertTrue(any(c.startswith('commit timer 00:05:00') for c in device.commands))
        self.assertEqual(device.pending_session, result['handle']['session'])
        self.assertNotIn('abort', device.commands)

    def test_apply_no_op_detected_when_diff_empty(self):
        device = FakeDevice(diff_text='')
        result = apply_shell(shell_for(device), CANDIDATE)
        self.assertTrue(result['no_op'])

    def test_apply_bad_line_aborts_and_raises(self):
        device = FakeDevice(load_error=True)
        with self.assertRaises(RestoreError):
            apply_shell(shell_for(device), CANDIDATE)
        self.assertIn('abort', device.commands)
        self.assertFalse(any(c.startswith('commit timer') for c in device.commands))
        self.assertIsNone(device.pending_session)

    def test_apply_truncated_candidate_refused_untouched(self):
        device = FakeDevice()
        truncated = '! Command: show running-config\n!\nhostname NEW\n!\n'
        with self.assertRaises(RestoreError):
            apply_shell(shell_for(device), truncated)
        self.assertEqual(device.commands, [])

    def test_apply_wrong_format_candidate_refused_untouched(self):
        device = FakeDevice()
        wrong = 'hostname NEW\n!\nend\n'
        with self.assertRaises(RestoreError):
            apply_shell(shell_for(device), wrong)
        self.assertEqual(device.commands, [])

    def test_apply_refuses_foreign_pending_timer(self):
        device = FakeDevice(pending_session='someone-elses-session')
        with self.assertRaises(RestoreError):
            apply_shell(shell_for(device), CANDIDATE)
        self.assertFalse(any(c.startswith('configure session ') for c in device.commands))
        self.assertNotIn('abort', device.commands)
        self.assertEqual(device.pending_session, 'someone-elses-session')

    def test_apply_commit_timer_rejection_aborts_and_raises(self):
        device = FakeDevice(commit_timer_ok=False)
        with self.assertRaises(RestoreError):
            apply_shell(shell_for(device), CANDIDATE)
        self.assertIn('abort', device.commands)
        self.assertIsNone(device.pending_session)

    def test_apply_uses_given_confirm_minutes_in_hms(self):
        device = FakeDevice()
        apply_shell(shell_for(device), CANDIDATE, confirm_minutes=60)
        self.assertTrue(any(c.startswith('commit timer 01:00:00') for c in device.commands))

    # --- confirm_shell --------------------------------------------------------------

    def test_confirm_happy_path_runs_write_memory(self):
        device = FakeDevice(mode='priv', pending_session='clabmgr-aaaa')
        result = confirm_shell(shell_for(device), {'session': 'clabmgr-aaaa'})
        self.assertEqual(result, {'confirmed': True, 'saved': True})
        self.assertIn('write memory', device.commands)
        self.assertIsNone(device.pending_session)

    def test_confirm_reports_unsaved_when_write_memory_fails(self):
        device = FakeDevice(mode='priv', pending_session='clabmgr-aaaa', write_memory_ok=False)
        result = confirm_shell(shell_for(device), {'session': 'clabmgr-aaaa'})
        self.assertTrue(result['confirmed'])
        self.assertFalse(result['saved'])

    def test_confirm_when_timer_already_expired_raises(self):
        device = FakeDevice(mode='priv', pending_session=None)
        with self.assertRaises(RestoreError):
            confirm_shell(shell_for(device), {'session': 'clabmgr-aaaa'})
        self.assertNotIn('write memory', device.commands)

    def test_confirm_when_different_session_pending_raises(self):
        device = FakeDevice(mode='priv', pending_session='other-session')
        with self.assertRaises(RestoreError):
            confirm_shell(shell_for(device), {'session': 'clabmgr-ours'})
        self.assertFalse(any(c.startswith('configure session clabmgr-ours commit')
                              for c in device.commands))
        self.assertNotIn('write memory', device.commands)
        self.assertEqual(device.pending_session, 'other-session')

    def test_confirm_after_a_manager_restart_finds_the_session_by_the_job_token(self):
        # The handle may never have been stored; the session is named after the job's token.
        device = FakeDevice(mode='priv', pending_session='clabmgr-aaaa')
        result = confirm_shell(shell_for(device), {'token': 'clabmgr-aaaa'})
        self.assertTrue(result['confirmed'])
        self.assertIn('configure session clabmgr-aaaa commit', device.commands)

    def test_confirm_without_any_identity_refuses_and_touches_nothing(self):
        device = FakeDevice(mode='priv', pending_session='clabmgr-aaaa')
        with self.assertRaises(RestoreError):
            confirm_shell(shell_for(device), {})
        self.assertFalse(any(' commit' in c for c in device.commands))
        self.assertEqual(device.pending_session, 'clabmgr-aaaa')

    def test_apply_names_the_session_after_the_job_token(self):
        device = FakeDevice()
        result = apply_shell(shell_for(device), CANDIDATE, token='clabmgr-job12345')
        self.assertEqual(result['handle'], {'session': 'clabmgr-job12345'})
        self.assertIn('configure session clabmgr-job12345', device.commands)

    def test_persist_saves_the_startup_configuration(self):
        from app.restore_eos import persist_shell
        self.assertTrue(persist_shell(shell_for(FakeDevice(mode='priv'))))
        self.assertFalse(persist_shell(shell_for(FakeDevice(mode='priv', write_memory_ok=False))))

    # --- abandoned sessions ---------------------------------------------------------

    def test_apply_first_aborts_the_managers_own_abandoned_sessions_and_nobody_elses(self):
        device = FakeDevice(orphans=['clabmgr-0d1359af', 'qa-foreign', 'clabmgr-b9e8bda5'])
        result = apply_shell(shell_for(device), CANDIDATE, token='clabmgr-11112222')
        self.assertEqual(device.orphans, ['qa-foreign'])            # somebody's session is left alone
        self.assertEqual(result['handle'], {'session': 'clabmgr-11112222'})
        first_own = device.commands.index('configure session clabmgr-11112222')
        self.assertLess(device.commands.index('configure session clabmgr-0d1359af'), first_own)
        self.assertEqual(device.pending_session, 'clabmgr-11112222')

    def test_cleanup_never_aborts_the_session_whose_commit_timer_is_running(self):
        from app.restore_eos import cleanup_shell
        device = FakeDevice(mode='priv', pending_session='clabmgr-aaaa1111', orphans=['clabmgr-bbbb2222'])
        self.assertEqual(cleanup_shell(shell_for(device)), ['clabmgr-bbbb2222'])
        self.assertEqual(device.pending_session, 'clabmgr-aaaa1111')
        self.assertNotIn('configure session clabmgr-aaaa1111', device.commands)

    def test_cleanup_on_a_clean_node_sends_nothing_but_the_question(self):
        from app.restore_eos import cleanup_shell
        device = FakeDevice(mode='priv')
        self.assertEqual(cleanup_shell(shell_for(device)), [])
        self.assertEqual(device.commands, ['show configuration sessions detail'])

    # --- pending_shell / reach_cli / capture_shell -----------------------------------

    def test_pending_shell_reports_name(self):
        device = FakeDevice(mode='priv', pending_session='clabmgr-bbbb')
        self.assertEqual(pending_shell(shell_for(device)), 'clabmgr-bbbb')

    def test_pending_shell_empty_when_none_pending(self):
        device = FakeDevice(mode='priv')
        self.assertEqual(pending_shell(shell_for(device)), '')

    def test_enable_sent_only_from_unpriv_prompt(self):
        device = FakeDevice(mode='unpriv')
        reach_cli(shell_for(device))
        self.assertIn('enable', device.commands)

    def test_enable_not_sent_from_priv_prompt(self):
        device = FakeDevice(mode='priv')
        reach_cli(shell_for(device))
        self.assertNotIn('enable', device.commands)

    def test_enable_password_prompt_answered(self):
        device = FakeDevice(mode='unpriv', enable_password='zebra')
        reach_cli(shell_for(device), enable_password='zebra')
        self.assertEqual(device.mode, 'priv')

    def test_capture_returns_running_config(self):
        device = FakeDevice(mode='priv', hostname='rx',
                             running_config='! Command: show running-config\n!\nhostname rx\n!\nend\n')
        out = capture_shell(shell_for(device))
        self.assertIn('hostname rx', out)


if __name__ == '__main__':
    unittest.main()
