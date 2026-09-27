"""Unit tests for the Cisco IOS XR network-design provisioning driver (`app.design_iosxr`) against a
scripted fake channel.

Modeled on `tests/test_restore_iosxr.py`'s FakeDevice/FakeChannel approach (the same XRv9k prompt
shapes -- 'RP/0/RP0/CPU0:xrv9k#' and its parenthetical configuration-mode forms -- and the same
hierarchical push/leaf-line/plain-'exit' tracking `design_iosxr` reuses wholesale from
`restore_iosxr._paste`/`_send`/`_is_rejected`), adapted for the design driver's own shape: sessions
named `clabdsg-<8 hex>`, a plain `configure` session for `render_desired`, `configure exclusive` for
`stage`, the `show configuration merge` / `show configuration` review pair (rather than the restore
driver's single `show configuration changes diff`), `commit confirmed minutes <N>` (rather than
`commit replace confirmed minutes <N>`) and the client-facing entry points (`snapshot`,
`render_desired`, `stage`, `confirm`, `pending`, `cleanup`, `persist`, `options`, `release`,
`session_name`) instead of the restore driver's shell-level functions. A `FakeClient` whose
`invoke_shell()` hands back a fresh `FakeChannel` onto a shared `FakeDevice`, with
`get_transport().getpeername()` for the peer matching `pending()` needs, lets those entry points be
driven directly and lets a held (armed) session and a later fresh reconnect be modelled as genuinely
different connections, the way `stage()`/`confirm()`/`pending()`/`release()` really see them.
"""
import socket
import unittest

from app import design_iosxr
from app.design_iosxr import NAME, RestoreError
from app.restore_iosxr import strip_generated_header
from app.restore_shell import SessionLost

CANDIDATE_MIN = '!! IOS XR Configuration 24.3.1\n!\nhostname xrv9k\nend\n'
LEAVES_MIN = {'hostname xrv9k'}

CANDIDATE = ('!! IOS XR Configuration 24.3.1\n'
             '!! Last configuration change at Sun Sep 20 22:27:46 2026 by clab\n'
             '!\n'
             'hostname xrv9k\n'
             'interface Loopback0\n'
             ' description test loopback\n'
             ' ipv4 address 10.0.0.1 255.255.255.255\n'
             '!\n'
             'end\n')
LEAVES = {'hostname xrv9k', 'description test loopback', 'ipv4 address 10.0.0.1 255.255.255.255'}

# The removals shape documented for stage(): an indented 'no ...' line under its parent, closed only
# by the '!' comment marker _paste() skips -- never an explicit 'exit'.
REMOVALS = ['router bgp 65000', ' no neighbor 10.255.0.4', '!']
REMOVAL_LEAVES = LEAVES_MIN | {'no neighbor 10.255.0.4'}

BEFORE_TEXT = '!! IOS XR Configuration 24.3.1\nhostname xrv9k\n!\nend\n'
MERGE_DIFFERENT_TEXT = ('!! Building configuration...\n!! IOS XR Configuration 24.3.1\n'
                         'hostname xrv9k\nrouter bgp 65000\n!\nend\n')
NO_OP_MERGE_TEXT = '!! Building configuration...\n!! IOS XR Configuration 24.3.1\nhostname xrv9k\n!\nend\n'
DIFF_TEXT = '!! IOS XR Configuration 24.3.1\nhostname xrv9k\n!\nend\n'


class FakeDevice:
    """Shared state behind one or more FakeChannel sessions, modelling one XRv9k node."""

    def __init__(self, hostname='xrv9k', leaves=(), bad_line=None, running_config=None,
                 merge_text=None, target_text=None, commit_list=None,
                 commit_confirmed_outcome='ok', exclusive_locked=False, plain_session=False,
                 trial_armed=False, hide_trial_evidence=False):
        self.hostname = hostname
        self.leaves = set(leaves)
        self.bad_line = bad_line
        self.running_config = running_config if running_config is not None else BEFORE_TEXT
        self.merge_text = merge_text if merge_text is not None else MERGE_DIFFERENT_TEXT
        self.target_text = target_text if target_text is not None else DIFF_TEXT
        self.commit_list = commit_list or ('SNo. Label/ID  Client  Time\n'
                                            '1    1000005   CLI     Sun Sep 20 23:28:42 2026\n')
        self.commit_confirmed_outcome = commit_confirmed_outcome  # 'ok', 'rejected', 'no_changes'
        self.exclusive_locked = exclusive_locked  # a foreign lock, or our own once we hold it
        self.plain_session = plain_session        # a foreign plain session
        self.trial_armed = trial_armed            # a foreign trial, or our own once armed
        self.confirming_channel = None            # whichever channel armed the current trial
        self.session_channel = None                # whichever channel currently owns configuration mode
        self.hide_trial_evidence = hide_trial_evidence
        self.commands = []

    def sessions_detail(self):
        if self.hide_trial_evidence:
            return ''
        if self.trial_armed:
            return ('\n  1) Session: 00001000-00000001-00000000  Sun Sep 20 23:28:42 2026 \n'
                     '     Line: vty0                           Lock: None\n'
                     '     User: clab                           Client: CLI\n\n'
                     '  2) Session: 00001000-00000002-00000000  Sun Sep 20 23:28:43 2026 \n'
                     '     Line: vty0                           Lock: None\n'
                     '     User: clab                           Client: commit-confirm\n')
        if self.exclusive_locked:
            return ('\n  1) Session: 00001000-00000001-00000000  Sun Sep 20 23:28:42 2026 \n'
                     '     Line: vty0                           Lock: Reserved\n'
                     '     User: clab                           Client: CLI\n')
        if self.plain_session or self.session_channel is not None:
            return ('\n  1) Session: 00001000-00000001-00000000  Sun Sep 20 23:28:42 2026 \n'
                     '     Line: vty0                           Lock: None\n'
                     '     User: clab                           Client: CLI\n')
        return ''


class FakeChannel:
    """One CLI session's channel onto a shared FakeDevice."""

    def __init__(self, device, name='ch'):
        self.device = device
        self.name = name
        self.in_config = False
        self.mode_stack = []
        self.awaiting_exit_rollback = False
        self.outbuf = b''
        self.inbuf = bytearray(self._initial())
        self.closed = False
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

    def on_line(self, raw_line):
        line = raw_line.strip()
        self.sent.append(line)
        d = self.device
        if self.awaiting_exit_rollback:
            self.awaiting_exit_rollback = False
            if line.lower() == 'yes':
                d.trial_armed = False
                d.confirming_channel = None
                self.in_config = False
                self.mode_stack = []
                if d.session_channel is self:
                    d.session_channel = None
            return (line + '\r\n' + self.prompt()).encode()
        d.commands.append(line)
        if line in ('terminal length 0', 'terminal width 512'):
            return self.frame(line)
        if line in ('show configuration sessions detail', 'do show configuration sessions detail'):
            return self.frame(line, d.sessions_detail())
        if line == 'show configuration commit list':
            return self.frame(line, d.commit_list)
        if line == 'show configuration merge':
            return self.frame(line, d.merge_text)
        if line == 'show configuration':
            return self.frame(line, d.target_text)
        if line == 'show running-config':
            return self.frame(line, d.running_config)
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
            d.session_channel = self
            return self.frame(line)
        if line.startswith('commit confirmed minutes'):
            if d.commit_confirmed_outcome == 'rejected':
                return self.frame(line, '% Failed to commit .. As an error encountered during '
                                   'commit operation.')
            if d.commit_confirmed_outcome == 'no_changes':
                return self.frame(line, 'No configuration changes to commit.')
            self.mode_stack = []
            d.exclusive_locked = False
            d.trial_armed = True
            d.confirming_channel = self
            return self.frame(line)
        if line == 'commit':
            if d.trial_armed and d.confirming_channel is self:
                d.trial_armed = False
                d.confirming_channel = None
                return self.frame(line, '\n% Confirming commit for trial session.')
            return self.frame(line, 'No configuration changes to commit.')
        if line == 'end':
            if d.trial_armed and d.confirming_channel is self:
                self.awaiting_exit_rollback = True
                return ("end\r\n\nYou are exiting after a 'commit confirm' with an active rollback "
                        "session.  If you exit the configuration awaiting confirmation will not be "
                        "confirmed and the router will immediately rollback to the previous "
                        "configuration.\r\nDo you wish to exit? [no]: ").encode()
            self.in_config = False
            self.mode_stack = []
            if d.session_channel is self:
                d.session_channel = None
                d.exclusive_locked = False
                d.plain_session = False
            return self.frame(line)
        if line == 'abort':
            if d.session_channel is self:
                d.session_channel = None
            d.exclusive_locked = False
            d.plain_session = False
            self.in_config = False
            self.mode_stack = []
            return self.frame(line)
        if line == 'exit':
            if self.mode_stack:
                self.mode_stack.pop()
            else:
                self.in_config = False
                if d.session_channel is self:
                    d.session_channel = None
            return self.frame(line)
        if d.bad_line is not None and line == d.bad_line:
            return self.frame(line, line + "\n              ^\n% Invalid input detected at "
                               "'^' marker.")
        if line in d.leaves:
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
    FakeDevice, and get_transport().getpeername() is the peer address pending() matches held
    sessions against."""

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


class DesignIosXrDriverTests(unittest.TestCase):
    def setUp(self):
        design_iosxr._HELD.clear()

    def tearDown(self):
        design_iosxr._HELD.clear()

    # --- session_name / options / cleanup / persist ---------------------------------------------

    def test_session_name_matches_pattern_and_options_is_empty(self):
        for _ in range(20):
            self.assertRegex(design_iosxr.session_name(), r'^clabdsg-[0-9a-f]{8}$')
            self.assertTrue(NAME.match(design_iosxr.session_name()))
        self.assertEqual(design_iosxr.options({'enable_password': 'x'}), {})
        self.assertEqual(design_iosxr.options({}), {})
        self.assertEqual(design_iosxr.options(None), {})

    def test_cleanup_and_persist_never_touch_the_device(self):
        device = FakeDevice(leaves=LEAVES)
        client = FakeClient(device)
        self.assertEqual(design_iosxr.cleanup(client), [])
        self.assertTrue(design_iosxr.persist(client))
        self.assertEqual(device.commands, [])
        self.assertEqual(client.channels, [])  # neither ever opens a channel

    # --- snapshot ---------------------------------------------------------------------------------

    def test_snapshot_reaches_prompt_disables_paging_and_strips_header(self):
        raw = ('Sun Sep 20 23:10:18.048 UTC\n!! Building configuration...\n'
               '!! IOS XR Configuration 24.3.1\nhostname xrv9k\nend\n')
        device = FakeDevice(leaves=LEAVES, running_config=raw)
        client = FakeClient(device)
        result = design_iosxr.snapshot(client)
        self.assertNotIn('UTC', result)
        self.assertNotIn('Building configuration', result)
        self.assertIn('hostname xrv9k', result)
        self.assertIn('terminal length 0', device.commands)
        self.assertIn('terminal width 512', device.commands)
        self.assertIn('show running-config', device.commands)
        self.assertTrue(client.channels[0].closed)

    # --- render_desired -----------------------------------------------------------------------------

    def test_render_desired_refuses_when_locked_by_another_session(self):
        device = FakeDevice(leaves=LEAVES, exclusive_locked=True)
        client = FakeClient(device)
        with self.assertRaises(RestoreError) as ctx:
            design_iosxr.render_desired(client, CANDIDATE)
        self.assertIn('not reviewed', str(ctx.exception))
        self.assertNotIn('configure', device.commands)
        self.assertTrue(client.channels[0].closed)

    def test_render_desired_happy_path_plain_configure_paste_show_abort(self):
        raw_target = ('Sun Sep 20 23:10:18.048 UTC\n!! Building configuration...\n'
                       '!! IOS XR Configuration 24.3.1\nhostname xrv9k\ninterface Loopback0\n'
                       ' description test loopback\n ipv4 address 10.0.0.1 255.255.255.255\n!\nend\n')
        device = FakeDevice(leaves=LEAVES, target_text=raw_target)
        client = FakeClient(device)
        base, rendered = design_iosxr.render_desired(client, CANDIDATE)
        self.assertEqual(base, '')
        self.assertNotIn('UTC', rendered)
        self.assertNotIn('Building configuration', rendered)
        self.assertIn('hostname xrv9k', rendered)
        commands = device.commands
        self.assertLess(commands.index('configure'), commands.index('hostname xrv9k'))
        self.assertLess(commands.index('hostname xrv9k'), commands.index('interface Loopback0'))
        self.assertLess(commands.index('interface Loopback0'), commands.index('description test loopback'))
        self.assertLess(commands.index('description test loopback'),
                         commands.index('ipv4 address 10.0.0.1 255.255.255.255'))
        self.assertLess(commands.index('ipv4 address 10.0.0.1 255.255.255.255'),
                         commands.index('show configuration'))
        self.assertEqual(commands[-1], 'abort')
        self.assertNotIn('!', commands)
        self.assertNotIn('end', commands)

    def test_render_desired_rejected_line_raises_after_abort(self):
        device = FakeDevice(leaves=LEAVES, bad_line='hostname xrv9k')
        client = FakeClient(device)
        with self.assertRaises(RestoreError):
            design_iosxr.render_desired(client, CANDIDATE)
        self.assertIn('abort', device.commands)
        self.assertNotIn('show configuration', device.commands)

    # --- stage(arm=False): refusals before touching configuration -------------------------------------

    def test_stage_refuses_foreign_trial_before_entering_configuration(self):
        device = FakeDevice(leaves=LEAVES, trial_armed=True)
        client = FakeClient(device)
        with self.assertRaises(RestoreError) as ctx:
            design_iosxr.stage(client, CANDIDATE_MIN, [], design_iosxr.session_name(), arm=False)
        self.assertIn('pending confirmation', str(ctx.exception))
        self.assertNotIn('configure exclusive', device.commands)
        self.assertNotIn('show running-config', device.commands)

    def test_stage_refuses_foreign_lock_before_entering_configuration(self):
        device = FakeDevice(leaves=LEAVES, exclusive_locked=True)
        client = FakeClient(device)
        with self.assertRaises(RestoreError) as ctx:
            design_iosxr.stage(client, CANDIDATE_MIN, [], design_iosxr.session_name(), arm=False)
        self.assertIn('exclusive configuration lock', str(ctx.exception))
        self.assertNotIn('configure exclusive', device.commands)
        self.assertNotIn('show running-config', device.commands)

    def test_stage_refuses_foreign_plain_session_before_entering_configuration(self):
        device = FakeDevice(leaves=LEAVES, plain_session=True)
        client = FakeClient(device)
        with self.assertRaises(RestoreError) as ctx:
            design_iosxr.stage(client, CANDIDATE_MIN, [], design_iosxr.session_name(), arm=False)
        self.assertIn('configuration session is open', str(ctx.exception))
        self.assertNotIn('configure exclusive', device.commands)
        self.assertNotIn('show running-config', device.commands)

    def test_stage_invalid_name_raises_with_nothing_sent(self):
        device = FakeDevice(leaves=LEAVES)
        client = FakeClient(device)
        with self.assertRaises(RestoreError):
            design_iosxr.stage(client, CANDIDATE_MIN, [], 'not-a-design-session', arm=False)
        self.assertEqual(device.commands, [])
        # the channel is still opened (stage() opens it before stage_shell's own checks run) then closed
        self.assertEqual(len(client.channels), 1)
        self.assertTrue(client.channels[0].closed)

    # --- stage(arm=False): the review transaction itself ------------------------------------------------

    def test_stage_review_removals_then_candidate_command_order_and_result(self):
        device = FakeDevice(leaves=REMOVAL_LEAVES, running_config=BEFORE_TEXT,
                             merge_text=MERGE_DIFFERENT_TEXT, target_text=DIFF_TEXT)
        client = FakeClient(device)
        name = design_iosxr.session_name()
        result = design_iosxr.stage(client, CANDIDATE_MIN, REMOVALS, name, confirm_minutes=5, arm=False)
        self.assertFalse(result['armed'])
        self.assertFalse(result['no_op'])
        self.assertEqual(result['before'], strip_generated_header(BEFORE_TEXT))
        self.assertEqual(result['would_be'], strip_generated_header(MERGE_DIFFERENT_TEXT))
        self.assertEqual(result['diff'], strip_generated_header(DIFF_TEXT))
        self.assertEqual(result['handle'], {'session': name})
        commands = device.commands
        self.assertLess(commands.index('show running-config'), commands.index('configure exclusive'))
        self.assertLess(commands.index('configure exclusive'), commands.index('router bgp 65000'))
        self.assertLess(commands.index('router bgp 65000'), commands.index('no neighbor 10.255.0.4'))
        self.assertLess(commands.index('no neighbor 10.255.0.4'), commands.index('hostname xrv9k'))
        self.assertLess(commands.index('hostname xrv9k'), commands.index('show configuration merge'))
        self.assertLess(commands.index('show configuration merge'), commands.index('show configuration'))
        self.assertEqual(commands[-1], 'abort')
        self.assertNotIn('!', commands)
        # The removals and the candidate are one paste: the depth tracking leaves `router bgp 65000` before the
        # candidate's first top-level line (an earlier draft pasted them separately and the second paste started
        # at depth 0, so a top-level line would have been typed inside the submode).
        self.assertIn('exit', commands)
        self.assertLess(commands.index('no neighbor 10.255.0.4'), commands.index('exit'))
        self.assertLess(commands.index('exit'), commands.index('hostname xrv9k'))

    def test_stage_review_no_op_detected_when_merge_matches_before(self):
        device = FakeDevice(leaves=LEAVES_MIN, running_config=BEFORE_TEXT, merge_text=NO_OP_MERGE_TEXT,
                             target_text=DIFF_TEXT)
        client = FakeClient(device)
        name = design_iosxr.session_name()
        result = design_iosxr.stage(client, CANDIDATE_MIN, [], name, confirm_minutes=5, arm=False)
        self.assertTrue(result['no_op'])
        self.assertFalse(result['armed'])
        self.assertEqual(device.commands[-1], 'abort')

    def test_stage_review_rejected_line_raises_after_abort(self):
        device = FakeDevice(leaves=LEAVES_MIN, bad_line='hostname xrv9k')
        client = FakeClient(device)
        with self.assertRaises(RestoreError):
            design_iosxr.stage(client, CANDIDATE_MIN, [], design_iosxr.session_name(), arm=False)
        self.assertIn('abort', device.commands)
        self.assertNotIn('show configuration merge', device.commands)

    # --- stage(arm=True) ------------------------------------------------------------------------------

    def test_stage_arm_happy_path_command_order_and_holds_session(self):
        device = FakeDevice(leaves=LEAVES_MIN, running_config=BEFORE_TEXT,
                             merge_text=MERGE_DIFFERENT_TEXT, target_text=DIFF_TEXT)
        armer = FakeClient(device, peer=('10.0.0.5', 22), name='armer')
        name = design_iosxr.session_name()
        result = design_iosxr.stage(armer, CANDIDATE_MIN, [], name, confirm_minutes=3, arm=True)
        self.assertTrue(result['armed'])
        self.assertTrue(result['held'])
        self.assertFalse(result['no_op'])
        self.assertEqual(result['confirm_minutes'], 3)
        self.assertEqual(result['handle'], {'session': name})
        self.assertIn(name, design_iosxr._HELD)
        held = design_iosxr._HELD[name]
        self.assertIs(held['client'], armer)
        self.assertIs(held['channel'], armer.channels[0])
        self.assertEqual(held['peer'], ('10.0.0.5', 22))
        self.assertFalse(held['channel'].closed)
        self.assertFalse(armer.closed)
        commands = device.commands
        self.assertLess(commands.index('configure exclusive'), commands.index('hostname xrv9k'))
        self.assertLess(commands.index('hostname xrv9k'), commands.index('show configuration merge'))
        self.assertLess(commands.index('show configuration merge'), commands.index('show configuration'))
        self.assertLess(commands.index('show configuration'), commands.index('commit confirmed minutes 3'))
        self.assertLess(commands.index('commit confirmed minutes 3'),
                         commands.index('do show configuration sessions detail'))
        self.assertNotIn('abort', commands)
        self.assertNotIn('commit', commands)  # stage() never confirms inline

    def test_stage_arm_rejected_commit_raises_after_abort(self):
        device = FakeDevice(leaves=LEAVES_MIN, running_config=BEFORE_TEXT,
                             merge_text=MERGE_DIFFERENT_TEXT, target_text=DIFF_TEXT,
                             commit_confirmed_outcome='rejected')
        armer = FakeClient(device, name='armer')
        name = design_iosxr.session_name()
        with self.assertRaises(RestoreError):
            design_iosxr.stage(armer, CANDIDATE_MIN, [], name, confirm_minutes=2, arm=True)
        self.assertIn('abort', device.commands)
        self.assertNotIn(name, design_iosxr._HELD)
        self.assertTrue(armer.channels[0].closed)

    def test_stage_arm_no_configuration_changes_returns_no_op_after_abort(self):
        device = FakeDevice(leaves=LEAVES_MIN, running_config=BEFORE_TEXT,
                             merge_text=MERGE_DIFFERENT_TEXT, target_text=DIFF_TEXT,
                             commit_confirmed_outcome='no_changes')
        armer = FakeClient(device, name='armer')
        name = design_iosxr.session_name()
        result = design_iosxr.stage(armer, CANDIDATE_MIN, [], name, confirm_minutes=2, arm=True)
        self.assertTrue(result['no_op'])
        self.assertFalse(result['armed'])
        self.assertNotIn('held', result)
        self.assertIn('abort', device.commands)
        self.assertNotIn('do show configuration sessions detail', device.commands)
        self.assertNotIn(name, design_iosxr._HELD)
        self.assertTrue(armer.channels[0].closed)

    def test_stage_arm_missing_trial_evidence_raises_session_lost(self):
        device = FakeDevice(leaves=LEAVES_MIN, running_config=BEFORE_TEXT,
                             merge_text=MERGE_DIFFERENT_TEXT, target_text=DIFF_TEXT,
                             hide_trial_evidence=True)
        armer = FakeClient(device, name='armer')
        name = design_iosxr.session_name()
        with self.assertRaises(SessionLost):
            design_iosxr.stage(armer, CANDIDATE_MIN, [], name, confirm_minutes=2, arm=True)
        self.assertNotIn('abort', device.commands)  # this check runs outside the abort-on-failure try/except
        self.assertNotIn(name, design_iosxr._HELD)
        self.assertTrue(armer.channels[0].closed)   # closed by stage()'s own except clause

    def test_stage_arm_no_op_never_sends_commit_confirmed(self):
        device = FakeDevice(leaves=LEAVES_MIN, running_config=BEFORE_TEXT, merge_text=NO_OP_MERGE_TEXT,
                             target_text=DIFF_TEXT)
        armer = FakeClient(device, name='armer')
        name = design_iosxr.session_name()
        result = design_iosxr.stage(armer, CANDIDATE_MIN, [], name, confirm_minutes=2, arm=True)
        self.assertTrue(result['no_op'])
        self.assertFalse(result['armed'])
        self.assertFalse(any(c.startswith('commit confirmed') for c in device.commands))
        self.assertIn('abort', device.commands)

    # --- confirm() -------------------------------------------------------------------------------------

    def _armed(self, peer=('10.0.0.5', 22)):
        device = FakeDevice(leaves=LEAVES_MIN, running_config=BEFORE_TEXT,
                             merge_text=MERGE_DIFFERENT_TEXT, target_text=DIFF_TEXT)
        armer = FakeClient(device, peer=peer, name='armer')
        name = design_iosxr.session_name()
        design_iosxr.stage(armer, CANDIDATE_MIN, [], name, confirm_minutes=2, arm=True)
        return device, armer, name

    def test_confirm_happy_path_command_order_and_result(self):
        device, armer, name = self._armed()
        baseline = len(device.commands)
        fresh = FakeClient(device, name='fresh')
        result = design_iosxr.confirm(fresh, {'session': name})
        self.assertEqual(result, {'confirmed': True, 'saved': True})
        self.assertNotIn(name, design_iosxr._HELD)
        self.assertTrue(armer.channels[0].closed)
        new_commands = device.commands[baseline:]
        # the fresh connection reaches its own CLI strictly before anything is sent on the held channel
        self.assertIn('terminal length 0', new_commands)
        self.assertIn('commit', new_commands)
        self.assertLess(new_commands.index('terminal length 0'), new_commands.index('commit'))
        # the held shell is told to leave configuration mode only after the confirming commit
        self.assertLess(new_commands.index('commit'), new_commands.index('end'))
        # only then does the fresh shell check the session table again
        self.assertLess(new_commands.index('end'), new_commands.index('show configuration sessions detail'))

    def test_confirm_missing_confirmation_text_raises_and_releases_held_session(self):
        device, armer, name = self._armed()
        # Simulate the trial having already lapsed independently of this confirm() call: the held
        # channel's own 'commit' now answers with the ordinary no-op wording, missing the confirming text.
        device.trial_armed = False
        device.confirming_channel = None
        fresh = FakeClient(device, name='fresh')
        with self.assertRaises(RestoreError):
            design_iosxr.confirm(fresh, {'session': name})
        self.assertNotIn(name, design_iosxr._HELD)
        self.assertTrue(armer.channels[0].closed)
        self.assertTrue(armer.closed)

    def test_confirm_with_nothing_held_raises_gone(self):
        device = FakeDevice(leaves=LEAVES_MIN)
        fresh = FakeClient(device)
        with self.assertRaises(RestoreError) as ctx:
            design_iosxr.confirm(fresh, {'session': design_iosxr.session_name()})
        self.assertIn('gone', str(ctx.exception))
        self.assertNotIn('commit', device.commands)

    def test_confirm_with_nothing_held_after_rollback_says_undone(self):
        rollback_list = ('SNo. Label/ID  Client    Time\n'
                          '1    1000012   Rollback  Sun Sep 20 23:39:02 2026\n')
        device = FakeDevice(leaves=LEAVES_MIN, commit_list=rollback_list)
        fresh = FakeClient(device)
        with self.assertRaises(RestoreError) as ctx:
            design_iosxr.confirm(fresh, {'session': design_iosxr.session_name()})
        self.assertIn('undone', str(ctx.exception))

    def test_confirm_invalid_handle_raises_without_touching_device(self):
        device = FakeDevice(leaves=LEAVES_MIN)
        client = FakeClient(device)
        with self.assertRaises(RestoreError):
            design_iosxr.confirm(client, {'session': 'not-a-valid-name'})
        self.assertEqual(device.commands, [])
        self.assertEqual(client.channels, [])

    # --- pending() ---------------------------------------------------------------------------------------

    def test_pending_empty_without_trial(self):
        device = FakeDevice(leaves=LEAVES_MIN)
        client = FakeClient(device, peer=('10.0.0.5', 22))
        self.assertEqual(design_iosxr.pending(client), '')

    def test_pending_returns_held_name_for_same_peer(self):
        device, _armer, name = self._armed(peer=('10.0.0.5', 22))
        fresh = FakeClient(device, peer=('10.0.0.5', 22), name='fresh')
        self.assertEqual(design_iosxr.pending(fresh), name)

    def test_pending_true_when_no_matching_held_peer(self):
        device, _armer, _name = self._armed(peer=('10.0.0.5', 22))
        fresh = FakeClient(device, peer=('10.0.0.99', 22), name='fresh')
        self.assertIs(design_iosxr.pending(fresh), True)

    def test_pending_true_for_a_foreign_trial_with_nothing_held(self):
        device = FakeDevice(leaves=LEAVES_MIN, trial_armed=True)  # armed directly on the device
        client = FakeClient(device, peer=('10.0.0.5', 22))
        self.assertIs(design_iosxr.pending(client), True)

    # --- release() -----------------------------------------------------------------------------------

    def test_release_leaves_configuration_and_answers_rollback_then_closes(self):
        device, armer, name = self._armed()
        self.assertTrue(device.trial_armed)
        design_iosxr.release(name)
        self.assertNotIn(name, design_iosxr._HELD)
        self.assertTrue(armer.channels[0].closed)
        self.assertTrue(armer.closed)
        self.assertFalse(device.trial_armed)  # rolled back immediately
        self.assertIn('yes', armer.channels[0].sent)

    def test_release_of_unknown_name_does_nothing(self):
        design_iosxr.release('does-not-exist')  # must not raise


class ReviewPassFourTests(unittest.TestCase):
    """The fourth risk-review pass: a stale held entry cannot shadow the caller's own session, and a refused commit
    reaches the job in the manager's words only."""

    def setUp(self):
        design_iosxr._HELD.clear()

    def tearDown(self):
        design_iosxr._HELD.clear()

    def test_pending_prefers_the_callers_own_session_over_another_held_entry(self):
        peer = ('10.0.0.5', 22)
        device = FakeDevice(leaves=LEAVES_MIN, trial_armed=True)
        with design_iosxr._HELD_LOCK:
            design_iosxr._HELD['clabdsg-0000aaaa'] = {'client': object(), 'channel': None, 'shell': None, 'peer': peer}
            design_iosxr._HELD['clabdsg-0000bbbb'] = {'client': object(), 'channel': None, 'shell': None, 'peer': peer}
        fresh = FakeClient(device, peer=peer, name='fresh')
        self.assertEqual(design_iosxr.pending(fresh, session='clabdsg-0000bbbb'), 'clabdsg-0000bbbb')
        self.assertEqual(design_iosxr.pending(FakeClient(device, peer=peer, name='fresh2'), session='clabdsg-0000aaaa'), 'clabdsg-0000aaaa')
        self.assertIn(design_iosxr.pending(FakeClient(device, peer=peer, name='fresh3'), session='clabdsg-0000cccc'), ('clabdsg-0000aaaa', 'clabdsg-0000bbbb'))

    def test_failure_reasons_are_fixed_phrases_never_the_devices_text(self):
        class Shell:
            def run(self, command, timeout=None):
                assert command == 'show configuration failed'
                return ('!! SEMANTIC ERRORS: This configuration was rejected by the system due to semantic errors.\n'
                        'router bgp 65100\n!!% BGP is still in process of unconfiguration for instance default\n'
                        ' bgp router-id 10.255.0.4\n!!% Something odd: route-policy SECRET-NAME not defined\n!\nend\n')
        text = design_iosxr._failure_reasons(Shell())
        self.assertIn('two applies', text)
        self.assertIn('does not have yet', text)
        self.assertNotIn('unconfiguration', text); self.assertNotIn('SECRET-NAME', text); self.assertNotIn('router bgp', text)
        class Silent:
            def run(self, command, timeout=None): return 'RP/0/RP0/CPU0:xrv9k#'
        self.assertEqual(design_iosxr._failure_reasons(Silent()), '')


if __name__ == '__main__':
    unittest.main()
