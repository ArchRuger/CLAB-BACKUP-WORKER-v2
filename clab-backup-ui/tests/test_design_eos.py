"""Unit tests for the Arista EOS network-design driver (`app.design_eos`) against a scripted fake
channel.

Mirrors `tests/test_restore_eos.py`'s FakeDevice/FakeChannel approach, adapted for the design
driver's own shape: sessions named `clabdsg-<8 hex>`, the `show session-config` /
`show session-config diffs` review pair (rather than the restore driver's single diff command),
and the client-facing entry points (`snapshot`, `render_desired`, `stage`, `confirm`, `pending`,
`cleanup`, `persist`, `options`) instead of the restore driver's shell-level functions. A thin
`FakeClient` whose `invoke_shell()` hands back a `FakeChannel` lets those entry points be driven
directly, the way `design_apply` (and, live, a connected paramiko client) drives them.
"""
import socket
import unittest

from app import design_eos
from app.design_eos import NAME, RestoreError
from app.restore_shell import SessionLost

CANDIDATE = 'interface Ethernet1\n   no switchport\n!\n'
REMOVALS = ['interface Ethernet2', '   no shutdown']
DEFAULT_RUNNING_CONFIG = '! Command: show running-config\n! device: ceos\n!\nhostname ceos\n!\nend\n'
DEFAULT_SESSION_CONFIG = '! Command: show session-configuration named x\n!\nhostname ceos\n!\nend\n'
DEFAULT_DIFF = ('--- system:/running-config\n+++ session:/x-session-config\n'
                 'interface Ethernet1\n+   no switchport\n')


class FakeDevice:
    def __init__(self, mode='unpriv', enable_password=None, pending_session=None, orphans=(),
                 load_error=False, commit_timer_ok=True, write_memory_ok=True,
                 diff_text=DEFAULT_DIFF, running_configs=None, session_configs=None,
                 hostname='ceos', disconnect_on_paste=False, clean_config_error=''):
        self.mode = mode
        self.enable_password = enable_password
        self.awaiting_enable_password = False
        self.pending_session = pending_session
        self.orphans = list(orphans)
        self.load_error = load_error
        self.commit_timer_ok = commit_timer_ok
        self.write_memory_ok = write_memory_ok
        self.diff_text = diff_text
        self.running_configs = list(running_configs) if running_configs else [DEFAULT_RUNNING_CONFIG]
        self.session_configs = list(session_configs) if session_configs else [DEFAULT_SESSION_CONFIG]
        self.hostname = hostname
        self.disconnect_on_paste = disconnect_on_paste
        self.clean_config_error = clean_config_error
        self.session_name = None
        self.terminal = False
        self.loaded = ''
        self.pastes = []
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

    def _pop_running_config(self):
        if len(self.running_configs) > 1:
            return self.running_configs.pop(0)
        return self.running_configs[0]

    def _pop_session_config(self):
        if len(self.session_configs) > 1:
            return self.session_configs.pop(0)
        return self.session_configs[0]

    def _sessions_detail(self):
        head = ('Maximum number of completed sessions: 1\nMaximum number of pending sessions: 5\n'
                'Merge on commit is disabled\nAutosave to startup-config on commit is disabled\n\n')
        if self.pending_session:
            head += ('Session with pending commit timer: %s\n'
                     'Time left until commit timer expiry: in 0:04:59\n\n' % self.pending_session)
        rows = ['  Name             State     User  Terminal Completed Time      Committed By',
                '- ---------------- --------- ----- -------- ------------------- ------------']
        if self.pending_session:
            rows.append('  %-16s committed                2026-09-27 10:00:00 admin' % self.pending_session)
        rows += ['  %-16s pending   admin vty8' % name for name in self.orphans]
        return head + '\n'.join(rows)

    def _confirm(self, line):
        session = line[len('configure session '):-len(' commit')].strip()
        if self.pending_session != session:
            return self.frame(line, '%% Session %s not found' % session)
        self.pending_session = None
        return self.frame(line)

    def _commit_timer(self, line):
        if not self.commit_timer_ok:
            return self.frame(line, '% Commit failed')
        self.pending_session = self.session_name
        self.mode = 'priv'
        return self.frame(line)

    def on_line(self, raw_line):
        if self.terminal:
            self.loaded += raw_line + '\n'
            return b''
        line = raw_line.strip()
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
            return self.frame(line, self.clean_config_error)
        if line == 'copy terminal: session-config':
            self.terminal = True
            self.loaded = ''
            return b''
        if line == 'show session-config diffs':
            return self.frame(line, self.diff_text)
        if line == 'show session-config':
            return self.frame(line, self._pop_session_config())
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
            return self.frame(line, self._pop_running_config())
        return self.frame(line)

    def on_terminal_end(self, _pre):
        self.terminal = False
        self.pastes.append(self.loaded)
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
        if self.closed:
            return
        self.outbuf += data
        while True:
            if b'\x04' in self.outbuf:
                if self.device.disconnect_on_paste:
                    self.closed = True
                    self.outbuf = b''
                    return
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


class FakeClient:
    """Enough of a connected paramiko client for `restore_shell.open_shell`: one `invoke_shell()`."""

    def __init__(self, device):
        self.device = device

    def invoke_shell(self, **_kw):
        return FakeChannel(self.device)


def client_for(device):
    return FakeClient(device)


class DesignEosDriverTests(unittest.TestCase):
    # --- session_name -----------------------------------------------------------

    def test_session_name_matches_pattern(self):
        for _ in range(20):
            self.assertRegex(design_eos.session_name(), r'^clabdsg-[0-9a-f]{8}$')
            self.assertTrue(NAME.match(design_eos.session_name()))

    # --- snapshot -----------------------------------------------------------------

    def test_snapshot_reaches_priv_disables_paging_and_reads_running_config(self):
        device = FakeDevice(mode='unpriv', running_configs=['RUNNING_TEXT'])
        result = design_eos.snapshot(client_for(device))
        self.assertEqual(result, 'RUNNING_TEXT')
        self.assertIn('enable', device.commands)
        self.assertIn('terminal length 0', device.commands)
        self.assertIn('terminal width 500', device.commands)
        self.assertIn('show running-config', device.commands)

    def test_snapshot_skips_enable_from_the_privileged_prompt(self):
        device = FakeDevice(mode='priv', running_configs=['RUNNING_TEXT'])
        design_eos.snapshot(client_for(device))
        self.assertNotIn('enable', device.commands)

    # --- render_desired -------------------------------------------------------------

    def test_render_desired_happy_path_reads_clean_base_then_rendered(self):
        device = FakeDevice(session_configs=['CLEAN_BASE_TEXT', 'RENDERED_TEXT'])
        clean, rendered = design_eos.render_desired(client_for(device), CANDIDATE)
        self.assertEqual(clean, 'CLEAN_BASE_TEXT')
        self.assertEqual(rendered, 'RENDERED_TEXT')
        self.assertEqual(device.pastes, [CANDIDATE])
        open_idx = next(i for i, c in enumerate(device.commands) if c.startswith('configure session clabdsg-'))
        rollback_idx = device.commands.index('rollback clean-config')
        show_indices = [i for i, c in enumerate(device.commands) if c == 'show session-config']
        paste_idx = device.commands.index('copy terminal: session-config')
        self.assertEqual(len(show_indices), 2)
        self.assertLess(open_idx, rollback_idx)
        self.assertLess(rollback_idx, show_indices[0])
        self.assertLess(show_indices[0], paste_idx)
        self.assertLess(paste_idx, show_indices[1])
        self.assertEqual(device.commands[-1], 'abort')

    def test_render_desired_rejected_line_raises_and_still_aborts(self):
        device = FakeDevice(load_error=True)
        with self.assertRaises(RestoreError):
            design_eos.render_desired(client_for(device), CANDIDATE)
        self.assertIn('abort', device.commands)

    def test_render_desired_refused_session_reset_raises_before_anything_is_read_or_loaded(self):
        # Without the reset the throwaway session is still a copy of the running configuration: the "desired"
        # set would be the candidate merged onto the running one (the sibling of audit L-11 in restore_eos).
        for error in ('% Invalid input', '% Error: could not roll back the session'):
            with self.subTest(error=error):
                device = FakeDevice(clean_config_error=error, session_configs=['RUNNING_COPY', 'MERGED'])
                with self.assertRaises(RestoreError) as refused:
                    design_eos.render_desired(client_for(device), CANDIDATE)
                self.assertNotIn(error, str(refused.exception))
                self.assertIn('did not empty', str(refused.exception))
                self.assertNotIn('show session-config', device.commands)
                self.assertNotIn('copy terminal: session-config', device.commands)
                self.assertEqual(device.pastes, [])
                self.assertEqual(device.commands[-1], 'abort')
                self.assertIsNone(device.session_name)

    # --- stage(arm=False): refusals and orphan cleanup -----------------------------------

    def test_stage_review_refuses_a_foreign_pending_timer_before_opening_a_session(self):
        device = FakeDevice(pending_session='someone-elses-session')
        with self.assertRaises(RestoreError):
            design_eos.stage(client_for(device), CANDIDATE, [], 'clabdsg-11111111', arm=False)
        self.assertFalse(any(c.startswith('configure session') for c in device.commands))
        self.assertEqual(device.pending_session, 'someone-elses-session')

    def test_stage_review_aborts_only_its_own_orphaned_sessions(self):
        device = FakeDevice(orphans=['clabdsg-11112222', 'clabmgr-33334444', 'qa-foreign'],
                             session_configs=['WOULD_BE'], diff_text='+something\n')
        design_eos.stage(client_for(device), CANDIDATE, [], 'clabdsg-99998888', arm=False)
        self.assertEqual(device.orphans, ['clabmgr-33334444', 'qa-foreign'])
        orphan_open = device.commands.index('configure session clabdsg-11112222')
        self.assertEqual(device.commands[orphan_open + 1], 'abort')
        self.assertNotIn('configure session clabmgr-33334444', device.commands)
        self.assertNotIn('configure session qa-foreign', device.commands)

    def test_stage_invalid_name_raises_before_touching_the_device(self):
        device = FakeDevice()
        with self.assertRaises(RestoreError):
            design_eos.stage(client_for(device), CANDIDATE, [], 'not-a-design-session', arm=False)
        self.assertEqual(device.commands, [])

    # --- stage(arm=False): the review transaction itself --------------------------------

    def test_stage_review_with_removals_pastes_removals_then_candidate(self):
        device = FakeDevice(session_configs=['WOULD_BE_TEXT'], diff_text='+something\n',
                             running_configs=['BEFORE_TEXT'])
        name = 'clabdsg-aaaaaaaa'
        result = design_eos.stage(client_for(device), CANDIDATE, REMOVALS, name, confirm_minutes=5, arm=False)
        self.assertFalse(result['armed'])
        self.assertFalse(result['no_op'])
        self.assertEqual(result['before'], 'BEFORE_TEXT')
        self.assertEqual(result['would_be'], 'WOULD_BE_TEXT')
        self.assertEqual(result['diff'], device.diff_text)
        self.assertEqual(result['handle'], {'session': name})
        self.assertEqual(device.pastes, ['\n'.join(REMOVALS) + '\n', CANDIDATE])
        idx_before = device.commands.index('show running-config')
        idx_open = device.commands.index('configure session %s' % name)
        idx_would_be = device.commands.index('show session-config')
        idx_diff = device.commands.index('show session-config diffs')
        self.assertLess(idx_before, idx_open)
        self.assertLess(idx_open, idx_would_be)
        self.assertLess(idx_would_be, idx_diff)
        self.assertEqual(device.commands[-1], 'abort')

    def test_stage_review_without_removals_pastes_only_the_candidate(self):
        device = FakeDevice(session_configs=['WOULD_BE'], diff_text='+something\n')
        design_eos.stage(client_for(device), CANDIDATE, [], 'clabdsg-bbbbbbbb', arm=False)
        self.assertEqual(device.pastes, [CANDIDATE])

    # --- stage(arm=True) -------------------------------------------------------------------

    def test_stage_arm_arms_the_commit_timer_when_running_config_is_unchanged(self):
        device = FakeDevice(session_configs=['WOULD_BE'], diff_text='+something\n',
                             running_configs=['SAME_BEFORE'])
        result = design_eos.stage(client_for(device), CANDIDATE, [], 'clabdsg-cccccccc',
                                   confirm_minutes=5, arm=True)
        self.assertTrue(result['armed'])
        self.assertEqual(result['confirm_minutes'], 5)
        self.assertTrue(any(c.startswith('commit timer 00:05:00') for c in device.commands))
        self.assertEqual(device.pending_session, 'clabdsg-cccccccc')
        self.assertNotIn('abort', device.commands)

    def test_stage_arm_raises_when_running_config_changed_while_staging(self):
        device = FakeDevice(session_configs=['WOULD_BE'], diff_text='+something\n',
                             running_configs=['hostname ceos\n', 'hostname NEW\n'])
        with self.assertRaises(RestoreError) as ctx:
            design_eos.stage(client_for(device), CANDIDATE, [], 'clabdsg-dddddddd',
                              confirm_minutes=5, arm=True)
        self.assertIn('changed while', str(ctx.exception))
        self.assertIn('abort', device.commands)
        self.assertFalse(any(c.startswith('commit timer') for c in device.commands))
        self.assertIsNone(device.pending_session)

    def test_stage_arm_asks_accept_with_the_would_be_before_the_commit_timer(self):
        # The service compares the would-be configuration with the review's before anything is armed (audit L-14):
        # a refusal aborts the session, so nothing unreviewed runs on the device for the confirmation window.
        device = FakeDevice(session_configs=['WOULD_BE'], diff_text='+something\n', running_configs=['SAME_BEFORE'])
        seen = []
        def refuse(text):
            seen.append((text, list(device.commands))); return False
        with self.assertRaises(RestoreError) as ctx:
            design_eos.stage(client_for(device), CANDIDATE, [], 'clabdsg-abcdabcd', confirm_minutes=5, arm=True, accept=refuse)
        self.assertIn('differs from the reviewed one', str(ctx.exception))
        self.assertEqual([text for text, _ in seen], ['WOULD_BE'])
        self.assertIn('show session-config', seen[0][1], 'asked after the would-be configuration was read')
        self.assertIn('abort', device.commands)
        self.assertFalse(any(c.startswith('commit timer') for c in device.commands))
        self.assertIsNone(device.pending_session)
        # Accepted: armed as before; a review (arm=False) and a no-op never ask.
        device = FakeDevice(session_configs=['WOULD_BE'], diff_text='+something\n', running_configs=['SAME_BEFORE'])
        seen = []
        result = design_eos.stage(client_for(device), CANDIDATE, [], 'clabdsg-abcdabce', confirm_minutes=5, arm=True, accept=lambda t: seen.append(t) or True)
        self.assertTrue(result['armed'])
        self.assertEqual(seen, ['WOULD_BE'])
        for arm, diff in ((False, '+something\n'), (True, '')):
            device = FakeDevice(session_configs=['WOULD_BE'], diff_text=diff); seen = []
            design_eos.stage(client_for(device), CANDIDATE, [], 'clabdsg-abcdabcf', arm=arm, accept=lambda t: seen.append(t) or False)
            self.assertEqual(seen, [])

    def test_stage_arm_no_op_does_not_arm_and_aborts(self):
        device = FakeDevice(session_configs=['WOULD_BE'], diff_text='')
        result = design_eos.stage(client_for(device), CANDIDATE, [], 'clabdsg-eeeeeeee', arm=True)
        self.assertTrue(result['no_op'])
        self.assertFalse(result['armed'])
        self.assertIn('abort', device.commands)
        self.assertFalse(any(c.startswith('commit timer') for c in device.commands))

    def test_stage_arm_commit_timer_rejection_raises_after_abort(self):
        device = FakeDevice(session_configs=['WOULD_BE'], diff_text='+something\n', commit_timer_ok=False)
        with self.assertRaises(RestoreError):
            design_eos.stage(client_for(device), CANDIDATE, [], 'clabdsg-ffffffff', arm=True)
        self.assertIn('abort', device.commands)
        self.assertIsNone(device.pending_session)

    # --- stage: a session that dies mid-paste --------------------------------------------

    def test_stage_arm_session_lost_mid_paste_sends_no_commit_timer(self):
        device = FakeDevice(disconnect_on_paste=True)
        with self.assertRaises(SessionLost):
            design_eos.stage(client_for(device), CANDIDATE, [], 'clabdsg-11119999', confirm_minutes=5, arm=True)
        self.assertIn('copy terminal: session-config', device.commands)
        self.assertFalse(any(c.startswith('commit timer') for c in device.commands))

    # --- confirm ------------------------------------------------------------------------

    def test_confirm_happy_path_commits_then_saves(self):
        device = FakeDevice(mode='priv', pending_session='clabdsg-aaaaaaaa')
        result = design_eos.confirm(client_for(device), {'session': 'clabdsg-aaaaaaaa'})
        self.assertEqual(result, {'confirmed': True, 'saved': True})
        self.assertIn('configure session clabdsg-aaaaaaaa commit', device.commands)
        self.assertIn('write memory', device.commands)
        self.assertIsNone(device.pending_session)

    def test_confirm_reports_unsaved_when_write_memory_fails(self):
        device = FakeDevice(mode='priv', pending_session='clabdsg-aaaaaaaa', write_memory_ok=False)
        result = design_eos.confirm(client_for(device), {'session': 'clabdsg-aaaaaaaa'})
        self.assertTrue(result['confirmed'])
        self.assertFalse(result['saved'])

    def test_confirm_with_nothing_pending_raises(self):
        device = FakeDevice(mode='priv', pending_session=None)
        with self.assertRaises(RestoreError) as ctx:
            design_eos.confirm(client_for(device), {'session': 'clabdsg-aaaaaaaa'})
        self.assertIn('nothing to confirm', str(ctx.exception))
        self.assertNotIn('write memory', device.commands)

    def test_confirm_with_a_different_pending_change_raises_and_sends_no_commit(self):
        device = FakeDevice(mode='priv', pending_session='clabdsg-other001')
        with self.assertRaises(RestoreError) as ctx:
            design_eos.confirm(client_for(device), {'session': 'clabdsg-a1a1a1a1'})
        self.assertIn('different pending change', str(ctx.exception))
        self.assertNotIn('configure session clabdsg-a1a1a1a1 commit', device.commands)
        self.assertNotIn('write memory', device.commands)
        self.assertEqual(device.pending_session, 'clabdsg-other001')

    def test_confirm_without_a_valid_session_in_the_handle_raises(self):
        device = FakeDevice(mode='priv', pending_session='clabdsg-aaaaaaaa')
        with self.assertRaises(RestoreError):
            design_eos.confirm(client_for(device), {})
        self.assertNotIn('show configuration sessions detail', device.commands)
        self.assertEqual(device.pending_session, 'clabdsg-aaaaaaaa')

    # --- pending / cleanup / persist / options -------------------------------------------

    def test_pending_reports_the_session_name(self):
        device = FakeDevice(mode='priv', pending_session='clabdsg-bbbbcccc')
        self.assertEqual(design_eos.pending(client_for(device)), 'clabdsg-bbbbcccc')

    def test_pending_is_empty_when_nothing_is_pending(self):
        device = FakeDevice(mode='priv')
        self.assertEqual(design_eos.pending(client_for(device)), '')

    def test_cleanup_removes_only_its_own_orphaned_sessions(self):
        device = FakeDevice(mode='priv', orphans=['clabdsg-aaaa1111', 'clabmgr-bbbb2222', 'other-name'])
        removed = design_eos.cleanup(client_for(device))
        self.assertEqual(removed, ['clabdsg-aaaa1111'])
        self.assertEqual(device.orphans, ['clabmgr-bbbb2222', 'other-name'])
        self.assertNotIn('configure session clabmgr-bbbb2222', device.commands)
        self.assertNotIn('configure session other-name', device.commands)

    def test_cleanup_never_touches_the_session_whose_commit_timer_is_running(self):
        device = FakeDevice(mode='priv', pending_session='clabdsg-abcd1234', orphans=['clabdsg-abcd1234'])
        self.assertEqual(design_eos.cleanup(client_for(device)), [])
        self.assertEqual(device.pending_session, 'clabdsg-abcd1234')
        self.assertNotIn('configure session clabdsg-abcd1234', device.commands)

    def test_persist_reports_write_memory_success_and_failure(self):
        self.assertTrue(design_eos.persist(client_for(FakeDevice(mode='priv'))))
        self.assertFalse(design_eos.persist(client_for(FakeDevice(mode='priv', write_memory_ok=False))))

    def test_options_carries_the_enable_password(self):
        self.assertEqual(design_eos.options({'enable_password': 'zebra'}), {'enable_password': 'zebra'})
        self.assertEqual(design_eos.options({}), {'enable_password': ''})
        self.assertEqual(design_eos.options(None), {'enable_password': ''})


if __name__ == '__main__':
    unittest.main()
