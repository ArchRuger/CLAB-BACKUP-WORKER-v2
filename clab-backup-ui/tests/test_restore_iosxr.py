"""Unit tests for the Cisco IOS XR restore CLI driver against a scripted fake channel.

The fake models just enough of an XRv9k CLI session (exec/config prompts, 'configure exclusive'
and its foreign lock/trial refusal, hierarchical push/leaf lines with plain 'exit' popping exactly
one level, the prefix-set/route-policy/if-block CLOSER tokens including a nested if-block whose
prompt does not change, the non-CLI 'commit replace confirmed' warning prompt, the raw
"Uncommitted changes...exit?" prompt, the raw "exiting after a commit confirm...rollback
immediately" prompt release() answers, a device flag that makes 'end' answer with the raw
"Uncommitted changes...exiting(yes/no/cancel)?" prompt instead (release() must recognise it too and
never answer it), the same-session-only confirming 'commit', a
`no_trial_on_commit` mode for a true no-op replace (armed and evidenced like any change, but no
second session row -- evidence section 13), and 'show configuration sessions detail' /
'show configuration commit list') to exercise the driver's dialog, including the HOLDS_SESSION
design (two fake channels can share one fake device, so a held session and a fresh reconnect are
modelled independently, the way apply_candidate()/confirm()/release() really see them), without a
real device. The canned text mirrors sanitized snippets of the real transcripts recorded while
proving docs/multi-platform-restore/evidence/xr-live-facts.md.
"""
import socket
import time
import unittest

from app import restore_iosxr
from app.restore_iosxr import (apply_candidate, apply_shell, blocked, capture_shell, compare,
                                confirm, pending, release, session_conflict,
                                strip_generated_header, supports_restore, validate_candidate,
                                IosXrShell, RestoreError, SessionLost)


CLOSER_TOKENS = {'end-set', 'end-policy', 'endif'}
DEFAULT_DIFF = ('!! Building configuration...\n!! IOS XR Configuration 24.3.1\n'
                 '#  interface Loopback0\n#   description test loopback\n#   description NEW\n'
                 '#  !\nend\n')
# The shape proven live (evidence Part 4): once a commit is accepted the target buffer resets, so
# comparing it (now empty) against the just-applied running configuration always shows everything
# as removable. This is the "positive evidence the trial is armed" apply_shell looks for.
DEFAULT_ARMED_DIFF = ('!! Building configuration...\n!! IOS XR Configuration 24.3.1\n'
                       '-  hostname xrv9k\n-  interface Loopback0\n-   description NEW\nend\n')
NO_OP_ARMED_DIFF = DEFAULT_ARMED_DIFF  # a no-op replace still resets the (already empty) target


class FakeDevice:
    """Shared state behind one or more FakeChannel sessions, modelling one XRv9k node."""

    def __init__(self, exclusive_locked=False, plain_session=False, trial_armed=False,
                 bad_line=None, leaves=(), commit_rejected=False, diff_text=None,
                 armed_diff_text=None, running_config=None, commit_list=None, hostname='xrv9k',
                 trigger_uncommitted_exit=False, no_trial_on_commit=False,
                 uncommitted_exit_on_end=False):
        self.exclusive_locked = exclusive_locked
        self.plain_session = plain_session
        self.trial_armed = trial_armed
        self.confirming_owner = None
        self.bad_line = bad_line
        self.leaves = set(leaves)
        self.commit_rejected = commit_rejected
        self.diff_text = diff_text if diff_text is not None else DEFAULT_DIFF
        self.armed_diff_text = armed_diff_text if armed_diff_text is not None else DEFAULT_ARMED_DIFF
        self.running_config = (running_config if running_config is not None else
                                '!! IOS XR Configuration 24.3.1\nhostname xrv9k\n!\nend\n')
        self.commit_list = commit_list or ('SNo. Label/ID  Client  Time\n'
                                            '1    1000005   CLI     Sun Sep 20 23:28:42 2026\n')
        self.hostname = hostname
        self.trigger_uncommitted_exit = trigger_uncommitted_exit
        # Makes the NEXT 'end' answer with the raw "Uncommitted changes...exiting(yes/no/cancel)?"
        # prompt instead of the usual clean/rollback-warning response (release()'s F1 follow-up:
        # _leave_held_configuration must recognise this prompt too and never answer it 'yes'/'no').
        self.uncommitted_exit_on_end = uncommitted_exit_on_end
        # A true no-op replace still resets the target buffer (the "positive evidence" apply_shell
        # checks -- armed_diff_text is still returned) but never creates the second
        # 'Client: commit-confirm' session row a real change does (proven live, evidence section
        # 13): apply_shell() still returns no_op=True with the session held, but there is never a
        # trial for confirm()/pending() to find.
        self.no_trial_on_commit = no_trial_on_commit
        self.commit_accepted = False   # a replace commit was answered 'yes' at least once (no-op or not)
        # The channel presently sitting in configuration mode since 'configure exclusive' (whether
        # still exclusively locked, mid-trial, or just committed a no-op): sessions_detail() shows
        # it as a plain 'Client: CLI' row once the exclusive lock itself drops, which happens the
        # moment a replace is accepted regardless of no_trial_on_commit (proven live, evidence
        # section 10) -- this is what lets a live release()/'end' actually have something to prove
        # it cleared, instead of the row already reading empty before release() ever runs.
        self.session_channel = None
        self.commands = []
        self.bad_exits = []  # 'exit' sent while genuinely at bare (config)#: must stay empty

    def sessions_detail(self):
        if self.trial_armed:
            return ('\n  1) Session: 00001000-00000001-00000000  Sun Sep 20 23:28:42 2026 \n'
                     '     Line: vty0                           Lock: None\n'
                     '     User: clab                           Client: CLI\n'
                     '     Process: config                      PID: 1001\n'
                     '     Node:                                Elapsed Time: 5 sec.\n\n'
                     '  2) Session: 00001000-00000002-00000000  Sun Sep 20 23:28:43 2026 \n'
                     '     Line: vty0                           Lock: None\n'
                     '     User: clab                           Client: commit-confirm\n'
                     '     Process: cfgmgr_trial_co              PID: 1002\n'
                     '     Node:                                Elapsed Time: 4 sec.\n')
        if self.exclusive_locked:
            return ('\n  1) Session: 00001000-00000001-00000000  Sun Sep 20 23:28:42 2026 \n'
                     '     Line: vty0                           Lock: Reserved\n'
                     '     User: clab                           Client: CLI\n'
                     '     Process: config                      PID: 1001\n')
        if self.session_channel is not None or self.plain_session:
            return ('\n  1) Session: 00001000-00000001-00000000  Sun Sep 20 23:28:42 2026 \n'
                     '     Line: vty0                           Lock: None\n'
                     '     User: clab                           Client: CLI\n'
                     '     Process: config                      PID: 1001\n')
        return ''


class FakeChannel:
    """One CLI session's channel onto a shared FakeDevice."""

    def __init__(self, device, name='ch'):
        self.device = device
        self.name = name
        self.in_config = False
        self.mode_stack = []
        self.awaiting_replace_confirm = False
        self.awaiting_uncommitted_exit = False
        self.awaiting_exit_rollback = False
        self.outbuf = b''
        self.inbuf = bytearray(self._initial())
        self.closed = False
        # Every line sent on this channel, whatever state it was sent in (including while a raw
        # yes/no/cancel-style prompt is outstanding) -- unlike d.commands, which only records lines
        # sent from the ordinary command dialog. Lets a test assert a specific answer (e.g. 'yes')
        # was never sent, not merely that it never reached the ordinary command handling below.
        self.sent = []

    def _initial(self):
        return ('\r\n' + self.prompt()).encode()

    def prompt(self):
        if not self.in_config:
            return 'RP/0/RP0/CPU0:%s#' % self.device.hostname
        if not self.mode_stack:
            return 'RP/0/RP0/CPU0:%s(config)#' % self.device.hostname
        return 'RP/0/RP0/CPU0:%s(config-m%d)#' % (self.device.hostname, len(self.mode_stack))

    def frame(self, echo, output=''):
        body = echo + '\r\n'
        if output:
            body += output.replace('\n', '\r\n') + '\r\n'
        return (body + self.prompt()).encode()

    def on_line(self, line):
        line = line.strip()
        self.sent.append(line)
        d = self.device
        if self.awaiting_replace_confirm:
            self.awaiting_replace_confirm = False
            if line.lower() == 'yes':
                if d.commit_rejected:
                    return (line + '\r\n\n% Failed to commit .. As an error encountered during '
                            'commit operation.\r\n' + self.prompt()).encode()
                self.mode_stack = []
                d.commit_accepted = True
                d.exclusive_locked = False
                if not d.no_trial_on_commit:
                    d.trial_armed = True
                    d.confirming_owner = self
                return (line + '\r\n' + self.prompt()).encode()
            return (line + '\r\n' + self.prompt()).encode()
        if self.awaiting_uncommitted_exit:
            self.awaiting_uncommitted_exit = False
            # Whatever is answered, nothing about the mode changes (this models the raw prompt as
            # a dead end the driver must recognise and refuse from, not blindly answer 'yes' to).
            return (line + '\r\n' + self.prompt()).encode()
        if self.awaiting_exit_rollback:
            self.awaiting_exit_rollback = False
            if line.lower() == 'yes':
                # F1(b), proven live: leaving now rolls the still-outstanding trial back
                # immediately, and the session row goes with it.
                d.trial_armed = False
                d.confirming_owner = None
                self.in_config = False
                self.mode_stack = []
                if d.session_channel is self:
                    d.session_channel = None
                return (line + '\r\n' + self.prompt()).encode()
            # 'no' (or anything else): exactly like an unanswered raw prompt -- the trial stays
            # outstanding, nothing about the mode changes, left to the node's own timer.
            return (line + '\r\n' + self.prompt()).encode()
        d.commands.append(line)
        if line in ('terminal length 0', 'terminal width 512'):
            return self.frame(line)
        if line == 'show configuration sessions detail':
            return self.frame(line, d.sessions_detail())
        if line == 'show configuration commit list':
            return self.frame(line, d.commit_list)
        if line == 'configure exclusive':
            if d.trial_armed:
                return self.frame(line, 'Cannot enter exclusive mode. A trial commit is underway '
                                   'in another configuration session.')
            if d.exclusive_locked:
                return self.frame(line, 'Cannot enter exclusive mode. The Configuration '
                                   'Namespace is locked by another agent.')
            self.in_config = True
            self.mode_stack = []
            d.exclusive_locked = True
            d.session_channel = self
            return self.frame(line)
        if line == 'configure':
            self.in_config = True
            self.mode_stack = []
            d.plain_session = True
            return self.frame(line)
        if line == 'end':
            if d.uncommitted_exit_on_end:
                d.uncommitted_exit_on_end = False
                self.awaiting_uncommitted_exit = True
                return ('end\r\n\nUncommitted changes found, commit them before '
                        'exiting(yes/no/cancel)? [cancel]: ').encode()
            if d.trial_armed and d.confirming_owner is self:
                # F1(b), proven live (~research/.../mixed-foreign-trial.log): leaving now, with the
                # trial this session armed still outstanding, is a raw, non-CLI prompt, not a plain
                # return to the exec prompt.
                self.awaiting_exit_rollback = True
                return ("end\r\n\nYou are exiting after a 'commit confirm' with an active rollback "
                        "session.  If you exit the configuration awaiting confirmation will not be "
                        "confirmed and the router will immediately rollback to the previous "
                        "configuration.\r\nDo you wish to exit? [no]: ").encode()
            self.in_config = False
            self.mode_stack = []
            if d.session_channel is self:
                d.session_channel = None
            return self.frame(line)
        if line == 'abort':
            if d.exclusive_locked:
                d.exclusive_locked = False
            if d.plain_session:
                d.plain_session = False
            if d.session_channel is self:
                d.session_channel = None
            self.in_config = False
            self.mode_stack = []
            return self.frame(line)
        if line == 'exit':
            if d.trigger_uncommitted_exit:
                d.trigger_uncommitted_exit = False
                self.awaiting_uncommitted_exit = True
                return ('exit\r\n\nUncommitted changes found, commit them before '
                        'exiting(yes/no/cancel)? [cancel]: ').encode()
            if not self.mode_stack and self.in_config:
                d.bad_exits.append(line)
            if self.mode_stack:
                self.mode_stack.pop()
            else:
                self.in_config = False
                if d.plain_session:
                    d.plain_session = False
                if d.session_channel is self:
                    d.session_channel = None
            return self.frame(line)
        if line in CLOSER_TOKENS:
            if self.mode_stack:
                self.mode_stack.pop()
            return self.frame(line)
        if line == 'show configuration changes diff':
            # The target buffer resets the moment ANY replace commit is accepted, no-op or not
            # (evidence section 11/13), so this reflects commit_accepted, not trial_armed (a
            # no_trial_on_commit no-op accepts the commit but never sets trial_armed).
            return self.frame(line, d.armed_diff_text if d.commit_accepted else d.diff_text)
        if line.startswith('commit replace confirmed'):
            self.awaiting_replace_confirm = True
            return ('%s\r\n\nThis commit will replace or remove the entire running configuration. '
                     'This\r\noperation can be service affecting.\r\nDo you wish to proceed? '
                     '[no]: ' % line).encode()
        if line == 'commit':
            if d.trial_armed and d.confirming_owner is self:
                d.trial_armed = False
                d.confirming_owner = None
                return self.frame(line, '\n% Confirming commit for trial session.')
            return self.frame(line, 'No configuration changes to commit.')
        if line == 'show running-config':
            return self.frame(line, d.running_config)
        if d.bad_line is not None and line == d.bad_line:
            return self.frame(line, line + "\n              ^\n% Invalid input detected at "
                               "'^' marker.")
        if line in d.leaves:
            return self.frame(line)
        if line.startswith('if ') or line in ('pass', 'else', 'drop'):
            # Inside a route-policy/if-block: the prompt does NOT change (proven live), unlike
            # every other non-leaf line, which is treated as entering a genuinely new submode.
            return self.frame(line)
        # anything else not otherwise recognised is treated as entering a new submode
        self.mode_stack.append(line)
        return self.frame(line)

    def settimeout(self, _):
        pass

    def sendall(self, data):
        self.outbuf += data
        while b'\n' in self.outbuf:
            raw, self.outbuf = self.outbuf.split(b'\n', 1)
            self.inbuf += self.on_line(raw.decode('utf-8', 'replace'))

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
    """A paramiko.SSHClient stand-in: invoke_shell() opens a new FakeChannel onto the same
    FakeDevice (so an "arming" client and a later "fresh" client can be modelled as genuinely
    different connections, the way apply_candidate()/confirm() really receive them), and
    get_transport().getpeername() is the peer address pending() matches held sessions against.
    """

    def __init__(self, device, peer=('172.20.20.104', 22), name='c'):
        self.device = device
        self.peer = peer
        self.name = name
        self.channels = []
        self.closed = False

    def invoke_shell(self, **_kw):
        channel = FakeChannel(self.device, name=self.name)
        self.channels.append(channel)
        return channel

    def get_transport(self):
        return self

    def getpeername(self):
        return self.peer

    def close(self):
        self.closed = True


LEAVES = {'hostname xrv9k', 'description test loopback',
          'ipv4 address 10.0.0.1 255.255.255.255', '10.0.0.0/24 le 32'}

CANDIDATE = ('!! IOS XR Configuration 24.3.1\n'
             '!! Last configuration change at Sun Sep 20 22:27:46 2026 by clab\n'
             '!\n'
             'hostname xrv9k\n'
             'interface Loopback0\n'
             ' description test loopback\n'
             ' ipv4 address 10.0.0.1 255.255.255.255\n'
             '!\n'
             'prefix-set TEST-PFX\n'
             '  10.0.0.0/24 le 32\n'
             'end-set\n'
             'end\n')

BANNER_CANDIDATE = ('!! IOS XR Configuration 24.3.1\n'
                     '!\n'
                     'hostname xrv9k\n'
                     'banner motd ^C Welcome ^C\n'
                     '!\n'
                     'end\n')


def shell_for(device, name='ch'):
    return IosXrShell(FakeChannel(device, name=name))


class RestoreIosXrDriverTests(unittest.TestCase):
    def setUp(self):
        restore_iosxr._HELD.clear()

    def tearDown(self):
        restore_iosxr._HELD.clear()

    def test_supported_platforms(self):
        self.assertTrue(supports_restore('cisco_xrv9k'))
        self.assertFalse(supports_restore('arista_ceos'))
        self.assertFalse(supports_restore(None))

    def test_holds_session_flag(self):
        self.assertTrue(restore_iosxr.HOLDS_SESSION)
        self.assertEqual(restore_iosxr.RESTORE_FORMAT, 'iosxr-running-config')

    # --- validate_candidate --------------------------------------------------------

    def test_validate_candidate_ok(self):
        validate_candidate(CANDIDATE)  # does not raise

    def test_validate_candidate_empty(self):
        with self.assertRaises(RestoreError):
            validate_candidate('   \n  ')

    def test_validate_candidate_missing_header(self):
        with self.assertRaises(RestoreError):
            validate_candidate('hostname xrv9k\n!\nend\n')

    def test_validate_candidate_truncated(self):
        with self.assertRaises(RestoreError):
            validate_candidate('!! IOS XR Configuration 24.3.1\n!\nhostname xrv9k\n!\n')

    def test_validate_candidate_refuses_banner(self):
        with self.assertRaises(RestoreError):
            validate_candidate(BANNER_CANDIDATE)

    # --- apply_shell: happy path and command order ----------------------------------

    def test_apply_happy_path_command_order_and_stays_armed(self):
        device = FakeDevice(leaves=LEAVES)
        result = apply_shell(shell_for(device), CANDIDATE, confirm_minutes=7)
        self.assertFalse(result['no_op'])
        self.assertEqual(result['confirm_minutes'], 7)
        self.assertEqual(result['diff'], device.diff_text)
        self.assertEqual(result['handle'], {'token': None})
        commands = device.commands
        self.assertIn('show configuration sessions detail', commands)
        self.assertLess(commands.index('show configuration sessions detail'), commands.index('configure exclusive'))
        self.assertIn('configure exclusive', commands)
        self.assertLess(commands.index('configure exclusive'), commands.index('hostname xrv9k'))
        self.assertLess(commands.index('interface Loopback0'), commands.index('description test loopback'))
        self.assertLess(commands.index('prefix-set TEST-PFX'), commands.index('10.0.0.0/24 le 32'))
        self.assertLess(commands.index('10.0.0.0/24 le 32'), commands.index('end-set'))
        self.assertLess(commands.index('end-set'), commands.index('show configuration changes diff'))
        self.assertIn('commit replace confirmed minutes 7', commands)
        # exit must be sent to leave the interface before entering the prefix-set
        self.assertIn('exit', commands)
        self.assertLess(commands.index('interface Loopback0'), commands.index('exit'))
        self.assertLess(commands.index('exit'), commands.index('prefix-set TEST-PFX'))
        # apply_shell NEVER confirms: no bare 'commit' is sent, and the device stays armed
        self.assertNotIn('commit', commands)
        self.assertNotIn('abort', commands)
        self.assertTrue(device.trial_armed)
        self.assertEqual(device.bad_exits, [])

    def test_apply_never_sends_root_or_bare_end(self):
        device = FakeDevice(leaves=LEAVES)
        apply_shell(shell_for(device), CANDIDATE)
        self.assertNotIn('root', device.commands)
        self.assertNotIn('end', device.commands)

    # --- the replace warning prompt -------------------------------------------------

    def test_replace_warning_prompt_is_answered_yes(self):
        device = FakeDevice(leaves=LEAVES)
        apply_shell(shell_for(device), CANDIDATE)
        # the device only arms (mode_stack cleared, trial_armed True) after seeing 'yes'
        self.assertTrue(device.trial_armed)

    # --- no-op: still armed like any other change -------------------------------------

    def test_apply_no_op_is_accepted_and_evidenced_but_creates_no_trial(self):
        # F3: replaces the previous version of this test, which claimed a no-op replace is "armed"
        # exactly like a real change. Proven live (evidence section 13): a true no-op still answers
        # the replace warning and still resets the target buffer (the same positive-evidence
        # pattern apply_shell checks for a real change), but the device never creates the second
        # 'Client: commit-confirm' session row a real change does -- there is genuinely no trial to
        # confirm, matching driver.pending() reporting '' for this case.
        device = FakeDevice(leaves=LEAVES, no_trial_on_commit=True,
                             diff_text='!! Building configuration...\n!! IOS XR Configuration 24.3.1\nend\n',
                             armed_diff_text=NO_OP_ARMED_DIFF)
        result = apply_shell(shell_for(device), CANDIDATE)
        self.assertTrue(result['no_op'])
        self.assertFalse(device.trial_armed)                        # no outstanding trial for a true no-op
        self.assertNotIn('Client: commit-confirm', device.sessions_detail())

    def test_no_op_apply_candidate_holds_pending_empty_then_release_clears_the_session(self):
        # F3/F1 end to end, at the apply_candidate()/pending()/release() level a true no-op is
        # actually seen at: the session is held exactly like a real change (release() still has
        # cleanup to do), pending() is '' because there is no trial, and release() actually leaves
        # configuration mode (case (a): nothing outstanding) rather than merely dropping the
        # connection -- proven by the fake's own session table reading empty immediately after,
        # not merely because nothing was ever open in the first place.
        device = FakeDevice(leaves=LEAVES, no_trial_on_commit=True,
                             diff_text='!! Building configuration...\n!! IOS XR Configuration 24.3.1\nend\n',
                             armed_diff_text=NO_OP_ARMED_DIFF)
        armer = FakeClient(device, name='armer')
        result = apply_candidate(armer, CANDIDATE, confirm_minutes=2, token='tok-noop')
        self.assertTrue(result['no_op'])
        self.assertIn('tok-noop', restore_iosxr._HELD)
        self.assertNotEqual(device.sessions_detail(), '')           # our own channel is still "in config"
        fresh = FakeClient(device, name='fresh')
        self.assertEqual(pending(fresh), '')                        # nothing to confirm: no trial exists
        release('tok-noop')
        self.assertNotIn('tok-noop', restore_iosxr._HELD)
        self.assertEqual(device.sessions_detail(), '')               # (F1) the row is gone at once
        self.assertEqual(blocked(FakeClient(device)), '')

    # --- bad line ----------------------------------------------------------------------

    def test_apply_bad_line_aborts_and_raises(self):
        device = FakeDevice(leaves=LEAVES, bad_line='interface Loopback0')
        with self.assertRaises(RestoreError):
            apply_shell(shell_for(device), CANDIDATE)
        self.assertIn('abort', device.commands)
        self.assertFalse(any(c.startswith('commit replace') for c in device.commands))

    def test_apply_warning_line_not_treated_as_rejection(self):
        # '% WARNING: ... Use abort to cancel' (redeclaring an existing prefix-set) must not abort
        device = FakeDevice(leaves=LEAVES)

        class WarningOnPrefixSet(FakeChannel):
            def on_line(self, line):
                if line.strip() == 'prefix-set TEST-PFX':
                    self.device.commands.append(line.strip())
                    self.mode_stack.append(line.strip())
                    return self.frame(line.strip(), '% WARNING: Policy object prefix-set '
                                       'TEST-PFX exists! Reconfiguring it via CLI will '
                                       'replace current definition. Use abort to cancel.')
                return super().on_line(line)

        channel = WarningOnPrefixSet(device)
        result = apply_shell(IosXrShell(channel), CANDIDATE)
        self.assertFalse(result['no_op'])
        self.assertNotIn('abort', device.commands)

    def test_is_rejected_per_line_even_beside_a_warning(self):
        # A genuine rejection on one line must not be masked just because another line in the
        # same output happens to contain the word WARNING.
        text = ('% WARNING: Policy object prefix-set X exists! Use abort to cancel.\n'
                '% Invalid input detected at \'^\' marker.\n')
        self.assertTrue(restore_iosxr._is_rejected(text))

    def test_is_rejected_warning_alone_is_not_a_rejection(self):
        text = '% WARNING: Policy object prefix-set X exists! Use abort to cancel.\n'
        self.assertFalse(restore_iosxr._is_rejected(text))

    # --- commit rejection --------------------------------------------------------------

    def test_apply_commit_rejection_aborts_and_raises(self):
        device = FakeDevice(leaves=LEAVES, commit_rejected=True)
        with self.assertRaises(RestoreError):
            apply_shell(shell_for(device), CANDIDATE)
        self.assertIn('abort', device.commands)

    # --- foreign lock/trial refused untouched -----------------------------------------

    def test_apply_refuses_foreign_trial_untouched(self):
        device = FakeDevice(trial_armed=True, leaves=LEAVES)
        with self.assertRaises(RestoreError):
            apply_shell(shell_for(device), CANDIDATE)
        self.assertNotIn('configure exclusive', device.commands)
        self.assertNotIn('abort', device.commands)

    def test_apply_refuses_foreign_lock_untouched(self):
        device = FakeDevice(exclusive_locked=True, leaves=LEAVES)
        with self.assertRaises(RestoreError):
            apply_shell(shell_for(device), CANDIDATE)
        self.assertNotIn('configure exclusive', device.commands)
        self.assertNotIn('abort', device.commands)

    def test_apply_proceeds_with_a_foreign_plain_session(self):
        # An ordinary open (non-exclusive) foreign session does not block a restore: proven live,
        # 'configure exclusive' is granted even while one exists.
        device = FakeDevice(plain_session=True, leaves=LEAVES)
        result = apply_shell(shell_for(device), CANDIDATE)
        self.assertIn('configure exclusive', device.commands)
        self.assertTrue(device.trial_armed)
        self.assertEqual(result['handle'], {'token': None})

    # --- truncated and wrong-format candidates refused with nothing sent -----------------

    def test_apply_truncated_candidate_refused_untouched(self):
        device = FakeDevice(leaves=LEAVES)
        truncated = '!! IOS XR Configuration 24.3.1\n!\nhostname xrv9k\n!\n'
        with self.assertRaises(RestoreError):
            apply_shell(shell_for(device), truncated)
        self.assertEqual(device.commands, [])

    def test_apply_wrong_format_candidate_refused_untouched(self):
        device = FakeDevice(leaves=LEAVES)
        wrong = 'hostname xrv9k\n!\nend\n'
        with self.assertRaises(RestoreError):
            apply_shell(shell_for(device), wrong)
        self.assertEqual(device.commands, [])

    def test_apply_banner_candidate_refused_untouched(self):
        device = FakeDevice(leaves=LEAVES)
        with self.assertRaises(RestoreError):
            apply_shell(shell_for(device), BANNER_CANDIDATE)
        self.assertEqual(device.commands, [])

    # --- SessionLost when the positive-evidence check fails after arming -----------------

    def test_apply_raises_session_lost_when_no_evidence_the_trial_armed(self):
        device = FakeDevice(leaves=LEAVES, armed_diff_text='!! IOS XR Configuration 24.3.1\nend\n')
        with self.assertRaises(SessionLost):
            apply_shell(shell_for(device), CANDIDATE)

    # --- nested route-policy / if / endif where the prompt does not change ---------------

    def test_paste_nested_route_policy_if_endif_prompt_unchanged(self):
        device = FakeDevice(leaves=LEAVES)
        candidate = ('!! IOS XR Configuration 24.3.1\n'
                     '!\n'
                     'hostname xrv9k\n'
                     'route-policy RP1\n'
                     ' if COND then\n'
                     '  pass\n'
                     ' endif\n'
                     'end-policy\n'
                     'end\n')
        result = apply_shell(shell_for(device), candidate)
        self.assertTrue(device.trial_armed)
        self.assertEqual(result['confirm_minutes'], 5)
        commands = device.commands
        self.assertIn('route-policy RP1', commands)
        self.assertIn('if COND then', commands)
        self.assertIn('pass', commands)
        self.assertIn('endif', commands)
        self.assertIn('end-policy', commands)
        # never a bare 'exit' or 'root' to leave the route-policy/if-block
        self.assertNotIn('exit', commands)
        self.assertNotIn('root', commands)
        self.assertEqual(device.bad_exits, [])

    # --- exit is never sent while genuinely at bare (config)# ----------------------------

    def test_exit_never_sent_at_bare_config_prompt(self):
        device = FakeDevice(leaves=LEAVES | {'router-id'})
        candidate = ('!! IOS XR Configuration 24.3.1\n'
                     '!\n'
                     'hostname xrv9k\n'
                     'route-policy RP1\n'
                     ' if COND then\n'
                     '  pass\n'
                     ' endif\n'
                     'end-policy\n'
                     'router ospf 1\n'
                     ' router-id\n'
                     'end\n')
        apply_shell(shell_for(device), candidate)
        self.assertEqual(device.bad_exits, [])

    # --- the raw "Uncommitted changes...exit?" prompt -------------------------------------

    def test_uncommitted_exit_prompt_is_declined_and_raises(self):
        device = FakeDevice(leaves=LEAVES, trigger_uncommitted_exit=True)
        with self.assertRaises(RestoreError):
            apply_shell(shell_for(device), CANDIDATE)
        # the candidate was aborted (declined the raw prompt with 'cancel', never blind 'yes'),
        # and the replace was never armed
        self.assertIn('abort', device.commands)
        self.assertFalse(device.trial_armed)
        self.assertFalse(any(c.startswith('commit replace') for c in device.commands))

    # --- header stripping ---------------------------------------------------------------

    def test_strip_generated_header_removes_timestamp_and_building(self):
        raw = ('Sun Sep 20 23:10:18.048 UTC\n'
               '!! Building configuration...\n'
               '!! IOS XR Configuration 24.3.1\n'
               '!! Last configuration change at Sun Sep 20 22:27:46 2026 by clab\n'
               'hostname xrv9k\n'
               'end\n')
        cleaned = strip_generated_header(raw)
        self.assertNotIn('UTC', cleaned)
        self.assertNotIn('Building configuration', cleaned)
        self.assertIn('!! IOS XR Configuration 24.3.1', cleaned)
        self.assertIn('!! Last configuration change', cleaned)
        self.assertIn('hostname xrv9k', cleaned)

    def test_strip_generated_header_only_drops_first_timestamp(self):
        raw = 'Sun Sep 20 23:10:18.048 UTC\nhostname xrv9k\nend\n'
        cleaned = strip_generated_header(raw)
        self.assertEqual(cleaned, 'hostname xrv9k\nend')

    # --- capture cleaning ----------------------------------------------------------------

    def test_capture_strips_header_and_keeps_banner(self):
        raw = ('Sun Sep 20 23:10:18.048 UTC\n'
               '!! Building configuration...\n'
               '!! IOS XR Configuration 24.3.1\n'
               'hostname rx\n'
               '!\n'
               'end\n')
        device = FakeDevice(running_config=raw)
        out = capture_shell(shell_for(device))
        self.assertIn('hostname rx', out)
        self.assertIn('!! IOS XR Configuration 24.3.1', out)
        self.assertNotIn('UTC', out)
        self.assertNotIn('Building configuration', out)

    # --- session_conflict / _last_commit_was_rollback -------------------------------------

    def test_session_conflict_none(self):
        self.assertEqual(session_conflict(shell_for(FakeDevice())), '')

    def test_session_conflict_plain(self):
        self.assertEqual(session_conflict(shell_for(FakeDevice(plain_session=True))), 'plain')

    def test_session_conflict_lock(self):
        self.assertEqual(session_conflict(shell_for(FakeDevice(exclusive_locked=True))), 'lock')

    def test_session_conflict_trial(self):
        self.assertEqual(session_conflict(shell_for(FakeDevice(trial_armed=True))), 'trial')

    def test_last_commit_was_rollback_requires_two_leading_numbers(self):
        rollback_list = ('SNo. Label/ID  Client    Time\n'
                          '1    1000012   Rollback  Sun Sep 20 23:39:02 2026\n'
                          '2    1000011   CLI       Sun Sep 20 23:35:59 2026\n')
        device = FakeDevice(commit_list=rollback_list)
        self.assertTrue(restore_iosxr._last_commit_was_rollback(shell_for(device)))

    def test_last_commit_was_rollback_ignores_a_stray_digit_led_line(self):
        # A line that merely starts with a digit but is not a real "SNo Label" row (only one
        # number, not two) must not be mistaken for the newest commit entry.
        odd_list = ('SNo. Label/ID  Client    Time\n'
                    '1st entry is not a real row\n'
                    '1    1000011   CLI       Sun Sep 20 23:35:59 2026\n')
        device = FakeDevice(commit_list=odd_list)
        self.assertFalse(restore_iosxr._last_commit_was_rollback(shell_for(device)))

    # --- compare -----------------------------------------------------------------------------

    def test_compare_removed_line(self):
        desired = 'interface Loopback0\n description A\n!\nend\n'
        actual = 'interface Loopback0\n!\nend\n'
        missing, extra = compare(desired, actual)
        self.assertIn('interface Loopback0 > description A', missing)
        self.assertEqual(extra, [])

    def test_compare_added_line(self):
        desired = 'interface Loopback0\n!\nend\n'
        actual = 'interface Loopback0\n description B\n!\nend\n'
        missing, extra = compare(desired, actual)
        self.assertEqual(missing, [])
        self.assertIn('interface Loopback0 > description B', extra)

    def test_compare_same_line_under_different_parent(self):
        desired = 'interface Loopback0\n description same\n!\nend\n'
        actual = 'interface Loopback1\n description same\n!\nend\n'
        missing, extra = compare(desired, actual)
        self.assertIn('interface Loopback0 > description same', missing)
        self.assertIn('interface Loopback1 > description same', extra)

    def test_compare_reports_order_only_route_policy_difference(self):
        desired = ('route-policy RP1\n if A then\n  pass\n endif\nend-policy\nend\n')
        actual = ('route-policy RP1\n endif\n if A then\n  pass\nend-policy\nend\n')
        missing, extra = compare(desired, actual)
        self.assertTrue(any(item.startswith('(order) route-policy RP1') for item in missing))

    # --- HOLDS_SESSION: apply_candidate keeps the channel/client open on success -----------

    def test_apply_candidate_leaves_the_trial_armed_and_channel_open(self):
        device = FakeDevice(leaves=LEAVES)
        client = FakeClient(device, name='armer')
        result = apply_candidate(client, CANDIDATE, confirm_minutes=2, token='tok-1')
        self.assertEqual(result['handle'], {'token': 'tok-1'})
        self.assertIn('tok-1', restore_iosxr._HELD)
        held = restore_iosxr._HELD['tok-1']
        self.assertIs(held['client'], client)
        self.assertFalse(held['channel'].closed)
        self.assertFalse(client.closed)
        self.assertTrue(device.trial_armed)

    def test_apply_candidate_closes_the_channel_on_failure_and_holds_nothing(self):
        device = FakeDevice(trial_armed=True, leaves=LEAVES)  # foreign trial -> refused untouched
        client = FakeClient(device, name='armer')
        with self.assertRaises(RestoreError):
            apply_candidate(client, CANDIDATE, confirm_minutes=2, token='tok-2')
        self.assertNotIn('tok-2', restore_iosxr._HELD)
        self.assertTrue(client.channels[0].closed)

    # --- HOLDS_SESSION: pending() ----------------------------------------------------------

    def test_pending_empty_when_nothing_outstanding(self):
        device = FakeDevice()
        client = FakeClient(device, peer=('172.20.20.104', 22))
        self.assertEqual(pending(client), '')

    def test_pending_returns_the_held_token_for_the_same_peer(self):
        device = FakeDevice(leaves=LEAVES)
        armer = FakeClient(device, peer=('172.20.20.104', 22), name='armer')
        apply_candidate(armer, CANDIDATE, confirm_minutes=2, token='tok-3')
        fresh = FakeClient(device, peer=('172.20.20.104', 22), name='fresh')
        self.assertEqual(pending(fresh), 'tok-3')

    def test_pending_returns_true_for_a_foreign_trial(self):
        device = FakeDevice(trial_armed=True)  # armed directly on the device, not through us
        client = FakeClient(device, peer=('172.20.20.104', 22))
        self.assertIs(pending(client), True)

    # --- HOLDS_SESSION: blocked() ----------------------------------------------------------

    def test_blocked_for_a_foreign_plain_session(self):
        device = FakeDevice(plain_session=True)
        client = FakeClient(device)
        reason = blocked(client)
        self.assertTrue(reason)
        self.assertIn('configuration session is open', reason)

    def test_blocked_for_a_foreign_lock(self):
        device = FakeDevice(exclusive_locked=True)
        self.assertTrue(blocked(FakeClient(device)))

    def test_blocked_is_empty_when_nothing_open(self):
        self.assertEqual(blocked(FakeClient(FakeDevice())), '')

    def test_blocked_is_empty_for_a_trial_that_is_pending_not_blocked(self):
        # A trial is reported through pending(), never through blocked().
        device = FakeDevice(trial_armed=True)
        self.assertEqual(blocked(FakeClient(device)), '')

    # --- HOLDS_SESSION: confirm() ------------------------------------------------------------

    def test_confirm_requires_the_fresh_connection_to_answer_first(self):
        device = FakeDevice(leaves=LEAVES)
        armer = FakeClient(device, name='armer')
        apply_candidate(armer, CANDIDATE, confirm_minutes=2, token='tok-4')
        armer_commands_before = list(device.commands)

        fresh = FakeClient(device, name='fresh')
        result = confirm(fresh, {'token': 'tok-4'})
        self.assertEqual(result, {'confirmed': True})
        # the fresh connection reached its own CLI (its own 'terminal length 0') strictly before
        # anything was sent on the held channel
        new_commands = device.commands[len(armer_commands_before):]
        self.assertIn('terminal length 0', new_commands)
        self.assertIn('commit', new_commands)
        self.assertLess(new_commands.index('terminal length 0'), new_commands.index('commit'))

    def test_confirm_uses_the_held_session_a_different_channel_cannot(self):
        device = FakeDevice(leaves=LEAVES)
        armer = FakeClient(device, name='armer')
        apply_candidate(armer, CANDIDATE, confirm_minutes=2, token='tok-5')
        # A different, unrelated channel on the SAME device cannot confirm the trial (matches the
        # live evidence: the node itself refuses to apply a bare 'commit' to a change it did not
        # arm on that session).
        impostor = shell_for(device, name='impostor')
        impostor.expect([restore_iosxr.PROMPT], 5)
        result_text = impostor.run('commit', 5)
        self.assertNotIn('Confirming commit for trial session', result_text)
        self.assertTrue(device.trial_armed)  # untouched by the impostor

        fresh = FakeClient(device, name='fresh')
        result = confirm(fresh, {'token': 'tok-5'})
        self.assertEqual(result, {'confirmed': True})
        self.assertFalse(device.trial_armed)
        self.assertNotIn('tok-5', restore_iosxr._HELD)
        self.assertTrue(armer.channels[0].closed)  # released once confirmed

    def test_confirm_with_the_held_session_gone_raises_and_sends_no_commit(self):
        device = FakeDevice(leaves=LEAVES)
        fresh = FakeClient(device)
        with self.assertRaises(RestoreError):
            confirm(fresh, {'token': 'never-armed'})
        self.assertNotIn('commit', device.commands)

    def test_confirm_with_the_held_session_gone_after_a_real_rollback(self):
        device = FakeDevice(leaves=LEAVES,
                             commit_list=('SNo. Label/ID  Client    Time\n'
                                          '1    1000012   Rollback  Sun Sep 20 23:39:02 2026\n'))
        fresh = FakeClient(device)
        with self.assertRaises(RestoreError) as ctx:
            confirm(fresh, {'token': 'gone'})
        self.assertIn('rolled', str(ctx.exception).lower())

    # --- HOLDS_SESSION: release() --------------------------------------------------------

    def test_release_of_an_outstanding_trial_leaves_configuration_and_rolls_back_immediately(self):
        # F1(b): release() must not merely drop the connection -- a dropped connection's plain
        # session row lingers for minutes (evidence section 10) and the trial itself is left to its
        # own timer. Leaving configuration mode first answers the node's own raw "exiting rolls
        # back immediately" prompt with 'yes' on purpose: the previous configuration is active
        # again, and the session row gone, as soon as release() returns.
        device = FakeDevice(leaves=LEAVES)
        armer = FakeClient(device, name='armer')
        apply_candidate(armer, CANDIDATE, confirm_minutes=2, token='tok-6')
        self.assertTrue(device.trial_armed)
        release('tok-6')
        self.assertNotIn('tok-6', restore_iosxr._HELD)
        self.assertTrue(armer.channels[0].closed)
        self.assertTrue(armer.closed)
        self.assertNotIn('commit', device.commands)   # never confirmed
        self.assertFalse(device.trial_armed)           # (F1) rolled back immediately, not left to the timer
        self.assertEqual(device.sessions_detail(), '')  # (F1) nothing lingers

    def test_release_of_a_no_op_session_is_the_clean_end_case_not_the_rollback_prompt(self):
        # F1(a) in isolation: no trial to answer for, so 'end' returns straight to the exec prompt
        # -- the raw rollback-warning prompt (case (b)) is never engaged for a true no-op.
        device = FakeDevice(leaves=LEAVES, no_trial_on_commit=True,
                             diff_text='!! Building configuration...\n!! IOS XR Configuration 24.3.1\nend\n',
                             armed_diff_text=NO_OP_ARMED_DIFF)
        armer = FakeClient(device, name='armer')
        apply_candidate(armer, CANDIDATE, confirm_minutes=2, token='tok-noop-release')
        sent_before_release = len(armer.channels[0].sent)
        release('tok-noop-release')
        self.assertNotIn('tok-noop-release', restore_iosxr._HELD)
        # The clean-end case never engages the rollback-warning prompt, so release() itself never
        # sends 'yes' on this channel (replaces the previous, by-construction-true check of
        # awaiting_exit_rollback, which is never set for a no-op regardless of what release() does).
        # Sliced from the point release() was called: apply_shell()'s own earlier 'yes', answering
        # the unrelated replace-confirmed warning, is expected and not what this pins.
        self.assertNotIn('yes', armer.channels[0].sent[sent_before_release:])
        self.assertEqual(device.sessions_detail(), '')

    def test_release_when_end_raises_the_uncommitted_changes_prompt_never_sends_yes_or_no(self):
        # Follow-up review finding: a held session's 'end' could, in principle, meet the raw
        # "Uncommitted changes found, commit them before exiting(yes/no/cancel)? [cancel]:" prompt
        # (evidence §5) instead of the rollback-warning one -- not proven live from a HELD session
        # specifically (see the evidence file's limitations note), but recognised defensively.
        # Before this fix, _leave_held_configuration only expected [PROMPT, EXIT_ROLLBACK_WARNING],
        # so this shape would neither match nor get an answer and would stall for the full
        # PROMPT_TIMEOUT (30s) before the channel was closed. Answering 'yes' would commit whatever
        # is staged (never proven safe -- and on a HELD session there should be nothing staged
        # beyond the already-armed replace); answering 'no' was also rejected (see the module
        # evidence, §5/§11): the safe move is the node's own '[cancel]' default, i.e. no answer at
        # all, and closing the channel right away instead of waiting the prompt out.
        device = FakeDevice(leaves=LEAVES, uncommitted_exit_on_end=True)
        armer = FakeClient(device, name='armer')
        apply_candidate(armer, CANDIDATE, confirm_minutes=2, token='tok-uncommitted')
        sent_before_release = len(armer.channels[0].sent)
        started = time.monotonic()
        release('tok-uncommitted')
        elapsed = time.monotonic() - started
        self.assertLess(elapsed, 5)  # must not stall for PROMPT_TIMEOUT (30s)
        self.assertNotIn('tok-uncommitted', restore_iosxr._HELD)
        self.assertTrue(armer.channels[0].closed)
        # Sliced from the point release() was called: apply_shell()'s own earlier 'yes', answering
        # the unrelated replace-confirmed warning, is expected and not what this pins.
        released_sent = armer.channels[0].sent[sent_before_release:]
        self.assertEqual(released_sent, ['end'])  # 'end' sent, then nothing -- no answer at all
        self.assertNotIn('yes', released_sent)    # never commits leftovers
        self.assertNotIn('no', released_sent)     # never discards blind either -- see the evidence
        self.assertNotIn('cancel', released_sent)

    def test_release_never_raises_when_the_held_channel_is_already_dead(self):
        # F1(c): a channel that is already gone (closed, or its recv() failing) must never make
        # release() raise.
        device = FakeDevice(leaves=LEAVES)
        armer = FakeClient(device, name='armer')
        apply_candidate(armer, CANDIDATE, confirm_minutes=2, token='tok-dead')
        restore_iosxr._HELD['tok-dead']['channel'].closed = True   # simulate a channel that is gone
        release('tok-dead')  # must not raise
        self.assertNotIn('tok-dead', restore_iosxr._HELD)

    def test_release_of_an_unknown_token_never_raises(self):
        release('does-not-exist')  # must not raise

    def test_release_replacing_a_reused_token_releases_the_previous_held_session_first(self):
        # F6: never expected from the real service (its tokens are per-attempt uuids), but a
        # reused token must not silently leak the first held session's channel and client.
        device = FakeDevice(leaves=LEAVES)
        first_armer = FakeClient(device, name='first-armer')
        apply_candidate(first_armer, CANDIDATE, confirm_minutes=2, token='tok-reused')
        first_channel = restore_iosxr._HELD['tok-reused']['channel']
        self.assertFalse(first_channel.closed)
        # Simulate the first change having already been resolved by something else, so the second
        # apply_candidate() (reusing the same token) is not itself refused by a foreign trial/lock.
        device.trial_armed = False
        device.confirming_owner = None
        device.exclusive_locked = False
        device.session_channel = None
        second_armer = FakeClient(device, name='second-armer')
        apply_candidate(second_armer, CANDIDATE, confirm_minutes=2, token='tok-reused')
        self.assertTrue(first_channel.closed)              # (F6) the stale entry was released, not leaked
        self.assertTrue(first_armer.closed)
        self.assertIs(restore_iosxr._HELD['tok-reused']['client'], second_armer)

    # --- F2: confirm() must not release the held session on a fresh-connection failure -----------

    def test_confirm_keeps_the_held_session_when_the_fresh_connection_never_reaches_its_cli(self):
        device = FakeDevice(leaves=LEAVES)
        armer = FakeClient(device, name='armer')
        apply_candidate(armer, CANDIDATE, confirm_minutes=2, token='tok-7')

        class DeadOnArrivalChannel(FakeChannel):
            def __init__(self, *a, **kw):
                super().__init__(*a, **kw)
                self.closed = True  # every recv() returns b'' at once: reach_cli() fails immediately

        class FlakyClient(FakeClient):
            def invoke_shell(self, **_kw):
                channel = DeadOnArrivalChannel(self.device, name=self.name)
                self.channels.append(channel)
                return channel

        flaky = FlakyClient(device, name='flaky')
        with self.assertRaises(SessionLost):
            confirm(flaky, {'token': 'tok-7'})
        # F2: the fresh connection never proved management survived, so the held session -- the
        # only one that can still confirm this change -- is left exactly as it was.
        self.assertIn('tok-7', restore_iosxr._HELD)
        self.assertFalse(armer.channels[0].closed)
        self.assertTrue(device.trial_armed)
        self.assertNotIn('commit', device.commands)

        good = FakeClient(device, name='good')
        result = confirm(good, {'token': 'tok-7'})
        self.assertEqual(result, {'confirmed': True})
        self.assertNotIn('tok-7', restore_iosxr._HELD)

    def test_confirm_releases_the_held_session_once_the_confirming_commit_was_attempted(self):
        # F2's other half: once the confirming commit has actually been attempted (here, it fails
        # because the held channel itself is dead), the held session no longer protects anything
        # and is released, so a stuck token is not kept forever.
        device = FakeDevice(leaves=LEAVES)
        armer = FakeClient(device, name='armer')
        apply_candidate(armer, CANDIDATE, confirm_minutes=2, token='tok-8')
        restore_iosxr._HELD['tok-8']['channel'].closed = True  # the held channel dies right at confirm time

        fresh = FakeClient(device, name='fresh')
        with self.assertRaises(SessionLost):
            confirm(fresh, {'token': 'tok-8'})
        self.assertNotIn('tok-8', restore_iosxr._HELD)

    # --- parallel restore: the held-session table is shared by every node worker -----------------

    def test_every_access_to_the_held_session_table_happens_under_its_lock(self):
        # Several nodes are restored at the same time, each on its own worker thread; the GIL alone is not
        # a contract for the check-then-set in apply_candidate or the scan in pending().
        from unittest.mock import patch
        lock, test = restore_iosxr._HELD_LOCK, self

        class Guarded(dict):
            def _check(self):
                test.assertTrue(lock.locked(), 'the held-session table was touched without _HELD_LOCK')
            def get(self, *args): self._check(); return super().get(*args)
            def pop(self, *args): self._check(); return super().pop(*args)
            def items(self): self._check(); return super().items()
            def __contains__(self, key): self._check(); return super().__contains__(key)
            def __setitem__(self, key, value): self._check(); super().__setitem__(key, value)
        guarded = Guarded()
        with patch.object(restore_iosxr, '_HELD', guarded):
            device = FakeDevice(leaves=LEAVES)
            apply_candidate(FakeClient(device, peer=('172.20.20.104', 22), name='armer'), CANDIDATE,
                            confirm_minutes=2, token='tok-lock')
            self.assertEqual(pending(FakeClient(device, peer=('172.20.20.104', 22), name='fresh')), 'tok-lock')
            self.assertEqual(confirm(FakeClient(device, name='good'), {'token': 'tok-lock'}), {'confirmed': True})
            apply_candidate(FakeClient(FakeDevice(leaves=LEAVES), name='second'), CANDIDATE, confirm_minutes=2,
                            token='tok-lock-2')
            release('tok-lock-2')
        self.assertEqual(dict(guarded), {})
        self.assertFalse(lock.locked(), 'the lock is never left held')

    def test_nodes_armed_and_released_from_many_threads_leave_no_session_behind(self):
        import threading
        errors = []

        def one(index):
            try:
                device = FakeDevice(leaves=LEAVES)
                peer = ('172.20.20.%d' % (100 + index), 22)
                apply_candidate(FakeClient(device, peer=peer, name='armer'), CANDIDATE, confirm_minutes=2,
                                token='tok-par-%d' % index)
                # Each node's fresh connection finds its own token, never another node's.
                if pending(FakeClient(device, peer=peer, name='fresh')) != 'tok-par-%d' % index:
                    errors.append(index)
                release('tok-par-%d' % index)
            except Exception as exc:   # pragma: no cover - reported below
                errors.append(repr(exc))
        threads = [threading.Thread(target=one, args=(index,)) for index in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(30)
        self.assertEqual(errors, [])
        self.assertEqual(restore_iosxr._HELD, {})

    # --- F7: the arming wait is bounded by the confirm window, not just COMMIT_TIMEOUT ------------

    def test_arm_timeout_formula(self):
        self.assertEqual(restore_iosxr._arm_timeout(2), 90)     # 120s window - 30s margin
        self.assertEqual(restore_iosxr._arm_timeout(3), 150)    # 180s window - 30s margin
        self.assertEqual(restore_iosxr._arm_timeout(60), restore_iosxr.COMMIT_TIMEOUT)  # capped
        self.assertEqual(restore_iosxr._arm_timeout(1), 30)     # 60s window - 30s margin

    def test_apply_shell_bounds_the_arming_wait_by_the_confirm_window(self):
        device = FakeDevice(leaves=LEAVES)
        shell = shell_for(device)
        original_expect = shell.expect
        seen = []

        def spying_expect(patterns, timeout=None):
            seen.append(timeout)
            return original_expect(patterns, timeout)

        shell.expect = spying_expect
        # confirm_minutes=3 -> a 150s bound, distinct from LOAD_TIMEOUT (90), PROMPT_TIMEOUT (30)
        # and COMMIT_TIMEOUT (180), so its presence can only come from the arming wait itself.
        apply_shell(shell, CANDIDATE, confirm_minutes=3)
        self.assertIn(restore_iosxr._arm_timeout(3), seen)
        self.assertNotIn(restore_iosxr.COMMIT_TIMEOUT, seen)


if __name__ == '__main__':
    unittest.main()
