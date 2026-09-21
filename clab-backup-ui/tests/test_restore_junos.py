"""Unit tests for the Junos restore CLI driver against a scripted fake channel.

The fake models just enough of a Junos session (operational/config prompts, a
`load override terminal ... ^D` paste, root-authentication presence, commit check and
commit confirmed) to exercise the driver's dialog without a real device.
"""
import socket
import unittest

from app.restore_junos import (JunosShell, apply_shell, confirm_shell, capture_shell,
                               RestoreError, supports_restore, pending_rollback_shell)


class FakeDevice:
    """A scripted Junos CLI, modelled on the transcripts of the two lab images.

    `pending` is what awaits confirmation: None, a commit comment, or True (a confirmed commit
    without a comment, i.e. somebody else's). `foreign_edits` puts another session's uncommitted
    change into the shared candidate: a plain session sees it in `show | compare`, leaving
    configuration mode asks before abandoning it, and a plain `commit` would activate it.
    """
    def __init__(self, has_rootauth=True, compare='[edit system]\n-  host-name OLD;\n+  host-name NEW;',
                 load_error=False, check_ok=True, commit_ok=True, hostname='r1', pending=None,
                 foreign_edits=False, exclusive_ok=True, check_confirms=True):
        self.mode = 'oper'
        self.has_rootauth = has_rootauth
        self.compare = compare
        self.load_error = load_error
        self.check_ok = check_ok
        self.commit_ok = commit_ok
        self.hostname = hostname
        self.pending = pending
        self.foreign_edits = foreign_edits
        self.foreign_activated = False
        self.exclusive_ok = exclusive_ok
        self.check_confirms = check_confirms
        self.asking = False
        self.terminal = False
        self.loaded = ''
        self.commands = []

    def prompt(self):
        return 'admin@%s%s ' % (self.hostname, '>' if self.mode == 'oper' else '#')

    def initial(self):
        return ('\r\n' + self.prompt()).encode()

    def frame(self, echo, output=''):
        body = echo + '\r\n'
        if output:
            body += output.replace('\n', '\r\n') + '\r\n'
        if self.mode != 'oper':
            body += '\r\n[edit]\r\n'
        return (body + self.prompt()).encode()

    def commit_log(self):
        rows = []
        if self.pending:
            rows.append('0   2026-09-20 23:49:09 UTC by admin via cli commit confirmed, rollback in 5mins')
            if self.pending is not True:
                rows.append('    ' + self.pending)
            rows.append('    rollback pending')
            rows.append('1   2026-09-20 23:11:36 UTC by admin via cli')
        else:
            rows.append('0   2026-09-20 23:11:36 UTC by admin via cli')
        # An old confirmed commit keeps its text for good and must never read as "pending".
        rows.append('2   2026-09-20 22:47:07 UTC by admin via cli commit confirmed, rollback in 5mins')
        return '\n'.join(rows)

    def on_line(self, line):
        line = line.strip()
        if self.terminal:
            self.loaded += line + '\n'
            return b''  # still capturing pasted configuration; no prompt yet
        self.commands.append(line)
        if self.asking:
            self.asking = False
            if line == 'yes':
                self.mode = 'oper'
                return self.frame(line, 'Exiting configuration mode')
            return self.frame(line)
        if line == 'configure':
            self.mode = 'conf'
            return self.frame(line, 'Entering configuration mode' + (
                '\nThe configuration has been changed but not committed' if self.foreign_edits else ''))
        if line == 'configure exclusive':
            if not self.exclusive_ok or self.foreign_edits:
                return self.frame(line, 'error: configuration database modified')  # stays at the operational prompt
            self.mode = 'excl'
            return self.frame(line, 'warning: uncommitted changes will be discarded on exit')
        if line == 'load override terminal':
            self.terminal = True
            self.loaded = ''
            return (line + '\r\n[Type ^D at a new line to end input]\r\n').encode()  # no prompt yet
        if line.startswith('show system commit'):
            return self.frame(line, self.commit_log())
        if line.startswith('set system root-authentication'):
            self.has_rootauth = True
            return self.frame(line)
        if line == 'show | compare':
            if self.mode == 'conf':   # the look-before-lock probe sees only other people's edits
                return self.frame(line, '[edit system]\n+   location building FOREIGN;' if self.foreign_edits else '')
            return self.frame(line, self.compare)
        if line == 'commit check':
            ok = self.check_ok
            if ok and self.mode == 'conf' and self.pending and self.check_confirms:
                self.pending = None   # on Junos a successful check confirms a pending confirmed commit
            return self.frame(line, 'configuration check succeeds' if ok else 'error: configuration check-out failed')
        if line.startswith('commit confirmed'):
            if self.commit_ok:
                parts = line.split(' comment ', 1)
                self.pending = parts[1] if len(parts) == 2 else True
            return self.frame(line, 'commit confirmed will be automatically rolled back in 5 minutes unless confirmed\n'
                              'commit complete' if self.commit_ok else 'error: commit failed')
        if line == 'commit':
            if self.foreign_edits:
                self.foreign_activated = True   # what the old confirmation did to a bystander's edit
            self.pending = None
            return self.frame(line, 'commit complete' if self.commit_ok else 'error: commit failed')
        if line.startswith('show configuration'):
            return self.frame(line, 'set system host-name %s' % self.hostname)
        if line == 'exit':
            if self.mode == 'conf' and self.foreign_edits:
                self.asking = True
                return (line + '\r\nThe configuration has been changed but not committed\r\n'
                        'Exit with uncommitted changes? [yes,no] (yes) ').encode()
            self.mode = 'oper'
            return self.frame(line, 'Exiting configuration mode')
        return self.frame(line)

    def on_terminal_end(self, pasted):
        self.terminal = False
        for raw in pasted.decode('utf-8', 'replace').splitlines():
            if raw.strip():
                self.loaded += raw.strip() + '\n'
        if self.load_error:
            return self.frame('', 'error: could not load configuration')
        return self.frame('', 'load complete')


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


CANDIDATE = ('system {\n    host-name NEW;\n    login {\n        user admin {\n'
             '            authentication {\n                encrypted-password "$6$fromlogin";\n'
             '            }\n        }\n    }\n}\n')
# Same, but already carrying the mandatory system root-authentication.
CANDIDATE_WITH_ROOT = ('system {\n    root-authentication {\n        encrypted-password "$6$root";\n    }\n'
                       '    host-name NEW;\n    login {\n        user admin {\n'
                       '            authentication {\n                encrypted-password "$6$fromlogin";\n'
                       '            }\n        }\n    }\n}\n')


def shell_for(device):
    return JunosShell(FakeChannel(device))


class RestoreJunosDriverTests(unittest.TestCase):
    def test_supported_platforms(self):
        self.assertTrue(supports_restore('juniper_cjunosevolved'))
        self.assertTrue(supports_restore('juniper_vjunosswitch'))
        self.assertFalse(supports_restore('arista_ceos'))
        self.assertFalse(supports_restore(None))

    def test_apply_happy_path_with_present_root_auth(self):
        device = FakeDevice(has_rootauth=True)
        result = apply_shell(shell_for(device), CANDIDATE_WITH_ROOT, confirm_minutes=5)
        self.assertEqual(result['root_authentication'], 'present')
        # The candidate already carries root-authentication, so none is synthesised.
        self.assertFalse(any(c.startswith('set system root-authentication') for c in device.commands))
        self.assertFalse(result['no_op'])
        self.assertIn('host-name NEW', result['diff'])
        self.assertIn('load override terminal', device.commands)
        self.assertIn('commit check', device.commands)
        self.assertTrue(any(c.startswith('commit confirmed 5') for c in device.commands))
        # It never issued a plain confirming commit in the apply phase.
        self.assertNotIn('commit', device.commands)

    def test_apply_synthesizes_root_auth_when_absent(self):
        device = FakeDevice(has_rootauth=False)
        result = apply_shell(shell_for(device), CANDIDATE, confirm_minutes=3)
        self.assertEqual(result['root_authentication'], 'synthesized')
        self.assertTrue(any(c.startswith('set system root-authentication encrypted-password "$6$fromlogin"')
                            for c in device.commands))

    def test_apply_refuses_when_no_root_auth_and_no_login_password(self):
        device = FakeDevice(has_rootauth=False)
        with self.assertRaises(RestoreError):
            apply_shell(shell_for(device), 'system {\n    host-name NEW;\n}\n')
        self.assertIn('rollback 0', device.commands)  # candidate discarded on failure
        self.assertEqual(device.mode, 'oper')

    def test_load_error_discards_and_raises(self):
        device = FakeDevice(load_error=True)
        with self.assertRaises(RestoreError):
            apply_shell(shell_for(device), CANDIDATE)
        # Only our own failed candidate is ever discarded, inside our exclusive session; entering
        # configuration mode discards nothing (there may be somebody's work in the shared candidate).
        self.assertEqual(device.commands.count('rollback 0'), 1)
        self.assertLess(device.commands.index('configure exclusive'), device.commands.index('rollback 0'))
        self.assertNotIn('commit check', device.commands)

    def test_commit_check_failure_raises_before_commit(self):
        device = FakeDevice(check_ok=False)
        with self.assertRaises(RestoreError):
            apply_shell(shell_for(device), CANDIDATE)
        self.assertIn('commit check', device.commands)
        self.assertFalse(any(c.startswith('commit confirmed') for c in device.commands))

    def test_commit_confirmed_failure_raises(self):
        device = FakeDevice(commit_ok=False)
        with self.assertRaises(RestoreError):
            apply_shell(shell_for(device), CANDIDATE)
        self.assertTrue(any(c.startswith('commit confirmed') for c in device.commands))

    def test_a_commit_that_reports_both_success_and_an_error_is_not_called_unchanged(self):
        from app.restore_shell import SessionLost
        device = FakeDevice()
        original = device.on_line

        def mixed(line):
            if line.strip().startswith('commit confirmed'):
                device.commands.append(line.strip())
                return device.frame(line.strip(), 're0:\ncommit complete\nre1:\nerror: commit failed on re1')
            return original(line)
        device.on_line = mixed
        with self.assertRaises(SessionLost):
            apply_shell(shell_for(device), CANDIDATE_WITH_ROOT)
        self.assertNotIn('rollback 0', device.commands)   # no pretending that nothing happened

    def test_no_op_detected_when_compare_empty(self):
        device = FakeDevice(compare='[edit]')
        result = apply_shell(shell_for(device), CANDIDATE)
        self.assertTrue(result['no_op'])

    def test_empty_candidate_refused(self):
        with self.assertRaises(RestoreError):
            apply_shell(shell_for(FakeDevice()), '   \n  ')

    def test_confirm_commits_and_reports_pending(self):
        # The confirmation is `commit check`: on Junos it cancels the pending rollback without
        # committing the shared candidate. Its proof is that "rollback pending" is gone.
        device = FakeDevice(pending='clabmgr-1a2b3c4d')
        result = confirm_shell(shell_for(device), {'token': 'clabmgr-1a2b3c4d'})
        self.assertTrue(result['confirmed'])
        self.assertIn('commit check', device.commands)
        self.assertNotIn('commit', device.commands)   # never a plain commit
        self.assertIsNone(device.pending)

    def test_confirm_never_activates_another_sessions_uncommitted_edit(self):
        device = FakeDevice(pending='clabmgr-1a2b3c4d', foreign_edits=True)
        result = confirm_shell(shell_for(device), {'token': 'clabmgr-1a2b3c4d'})
        self.assertTrue(result['confirmed'])
        self.assertFalse(device.foreign_activated)
        # Leaving configuration mode asked about the bystander's edit; "yes" keeps it where it was.
        self.assertIn('yes', device.commands)
        self.assertEqual(device.mode, 'oper')

    def test_confirm_refuses_when_nothing_is_pending(self):
        device = FakeDevice(pending=None)
        with self.assertRaises(RestoreError):
            confirm_shell(shell_for(device), {'token': 'clabmgr-1a2b3c4d'})
        self.assertNotIn('configure', device.commands)

    def test_confirm_leaves_a_foreign_pending_change_alone(self):
        for foreign in ('someone-elses-comment', True):
            device = FakeDevice(pending=foreign)
            with self.assertRaises(RestoreError):
                confirm_shell(shell_for(device), {'token': 'clabmgr-1a2b3c4d'})
            self.assertNotIn('commit check', device.commands)
            self.assertEqual(device.pending, foreign)

    def test_confirm_reports_failure_when_the_node_still_shows_the_change_pending(self):
        device = FakeDevice(pending='clabmgr-1a2b3c4d', check_confirms=False)
        with self.assertRaises(RestoreError):
            confirm_shell(shell_for(device), {'token': 'clabmgr-1a2b3c4d'})

    def test_apply_arms_the_change_under_the_job_token(self):
        device = FakeDevice()
        result = apply_shell(shell_for(device), CANDIDATE_WITH_ROOT, confirm_minutes=5, token='clabmgr-1a2b3c4d')
        self.assertIn('commit confirmed 5 comment clabmgr-1a2b3c4d', device.commands)
        self.assertEqual(result['handle'], {'token': 'clabmgr-1a2b3c4d'})
        self.assertEqual(pending_rollback_shell(shell_for(device)), 'clabmgr-1a2b3c4d')

    def test_apply_refuses_a_token_that_is_not_a_plain_word(self):
        device = FakeDevice()
        with self.assertRaises(RestoreError):
            apply_shell(shell_for(device), CANDIDATE_WITH_ROOT, token='x; request system reboot')
        self.assertEqual(device.commands, [])

    def test_apply_refuses_while_another_confirmation_is_pending(self):
        device = FakeDevice(pending=True)
        with self.assertRaises(RestoreError):
            apply_shell(shell_for(device), CANDIDATE_WITH_ROOT)
        self.assertNotIn('configure', device.commands)
        self.assertNotIn('load override terminal', device.commands)

    def test_apply_refuses_and_preserves_somebody_elses_uncommitted_edits(self):
        device = FakeDevice(foreign_edits=True)
        with self.assertRaises(RestoreError) as refused:
            apply_shell(shell_for(device), CANDIDATE_WITH_ROOT)
        self.assertIn('uncommitted', str(refused.exception))
        self.assertNotIn('rollback 0', device.commands)            # their candidate is not discarded
        self.assertNotIn('configure exclusive', device.commands)
        self.assertNotIn('load override terminal', device.commands)
        self.assertTrue(device.foreign_edits)
        self.assertEqual(device.mode, 'oper')

    def test_apply_refuses_without_the_exclusive_lock_and_has_no_shared_fallback(self):
        device = FakeDevice(exclusive_ok=False)
        with self.assertRaises(RestoreError):
            apply_shell(shell_for(device), CANDIDATE_WITH_ROOT)
        self.assertNotIn('load override terminal', device.commands)
        self.assertEqual(device.commands.count('configure'), 1)     # the probe only

    def test_pending_reads_only_the_newest_entry(self):
        # Entry 2 of the fake log is an old confirmed commit: its text stays for good and is not "pending".
        self.assertEqual(pending_rollback_shell(shell_for(FakeDevice(pending=None))), '')
        self.assertIs(pending_rollback_shell(shell_for(FakeDevice(pending=True))), True)
        self.assertEqual(pending_rollback_shell(shell_for(FakeDevice(pending='clabmgr-0000aaaa'))), 'clabmgr-0000aaaa')

    def test_capture_returns_config(self):
        device = FakeDevice(hostname='rx')
        out = capture_shell(shell_for(device), display_set=True)
        self.assertIn('host-name rx', out)


if __name__ == '__main__':
    unittest.main()
