"""Unit tests for the Junos network-design driver (`app.design_junos`) against a scripted fake channel.

Mirrors `tests/test_restore_junos.py`'s FakeDevice/FakeChannel approach (operational/configuration
prompts, `show system commit`, `show | compare`, a `load ... terminal` paste ended by Ctrl-D, `commit
check`, `commit confirmed`) and `tests/test_design_eos.py`'s use of a thin `FakeClient` whose
`invoke_shell()` hands back the fake channel, so the design driver's client-facing entry points
(`snapshot`, `render_desired`, `stage`, `confirm`, `pending`, `cleanup`, `persist`, `options`,
`session_name`) can be driven directly, the way `design_apply` (and, live, a connected paramiko
client) drives them.

The fake device tracks three configuration sub-modes distinctly, because Junos shares the prompt
shape ('#') across all of them but the driver's own bookkeeping (foreign-edit detection, the
inside-the-lock re-read, the private-candidate render) depends on which one is open:

* ``conf``  -- the plain, shared ``configure`` used only to look at the candidate for someone else's
  uncommitted edits (never entered by name; always looked-at-and-left);
* ``excl``  -- ``configure exclusive``, the merge transaction of `stage`;
* ``priv``  -- ``configure private``, the throwaway render of `render_desired`.

Leaving ``conf`` asks "Exit with uncommitted changes?" when the shared candidate holds edits (a
bystander's, modelled by ``foreign=True``); leaving ``excl``/``priv`` never asks, because an
exclusive or private candidate is discarded silently on exit.

Inside the exclusive lock, `stage_shell` also reads the bare ``show`` (the device's own hierarchy,
feeding ``design_ownership.junos_blocks``) between the would-be `show | display set` and the
`show | compare` diff; the fake answers it with ``hierarchy_text`` and the driver's returned dict
carries it back as ``'hierarchy'``.
"""
import socket
import unittest

from app import design_junos
from app.design_junos import NAME, RestoreError
from app.restore_shell import SessionLost

CANDIDATE = ('interfaces {\n    ge-0/0/1 {\n        unit 0 {\n            family inet {\n'
             '                address 10.0.0.1/24;\n            }\n        }\n    }\n}\n')
REMOVALS = ['delete interfaces ge-0/0/2', 'delete protocols lldp interface ge-0/0/3']
BEFORE = 'set system host-name r1\n'
WOULD_BE = 'set system host-name r1\nset interfaces ge-0/0/1 unit 0 family inet address 10.0.0.1/24\n'
COMPARE = '[edit interfaces]\n+   ge-0/0/1 {\n+       unit 0 { family inet { address 10.0.0.1/24; } }\n+   }'
HIERARCHY = 'interfaces {\n    ge-0/0/1 { unit 0 { family inet { address 10.0.0.1/24; } } }\n}\n'


class FakeDevice:
    """A scripted Junos CLI for the design driver, modelled on `test_restore_junos.FakeDevice`.

    ``pending`` is what `show system commit` reports as awaiting confirmation: None, a comment, or
    True (somebody else's, no comment). ``foreign`` puts another session's uncommitted change into
    the shared candidate, seen by a plain (non-exclusive, non-private) `configure` + `show | compare`
    and by the "Exit with uncommitted changes?" question when that plain session is left.
    """

    def __init__(self, mode='oper', hostname='r1', pending=None, foreign=False,
                 before_display_set=BEFORE, inside_display_set=None, would_be_display_set=WOULD_BE,
                 compare_text=COMPARE, foreign_compare='[edit]', private_rendered=WOULD_BE,
                 hierarchy_text=HIERARCHY,
                 private_ok=True, check_ok=True, commit_ok=True, commit_mixed=False,
                 delete_error_at=None, load_error=False, missing_load_complete=False):
        self.mode = mode
        self.hostname = hostname
        self.pending = pending
        self.foreign = foreign
        self.before_display_set = before_display_set
        self.inside_display_set = before_display_set if inside_display_set is None else inside_display_set
        self.would_be_display_set = would_be_display_set
        self.compare_text = compare_text
        self.foreign_compare = foreign_compare
        self.private_rendered = private_rendered
        self.hierarchy_text = hierarchy_text
        self.private_ok = private_ok
        self.check_ok = check_ok
        self.commit_ok = commit_ok
        self.commit_mixed = commit_mixed
        self.delete_error_at = delete_error_at
        self.load_error = load_error
        self.missing_load_complete = missing_load_complete
        self.loaded_in_excl = False
        self.asking = False
        self.terminal = False
        self.loaded = ''
        self._delete_index = 0
        self.commands = []

    def prompt(self):
        if self.mode == 'root':
            return 'root@%s%s ' % (self.hostname, '%')
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
            rows.append('0   2026-09-27 10:00:00 UTC by admin via cli commit confirmed, rollback in 5mins')
            if self.pending is not True:
                rows.append('    ' + self.pending)
            rows.append('    rollback pending')
            rows.append('1   2026-09-27 09:00:00 UTC by admin via cli')
        else:
            rows.append('0   2026-09-27 09:00:00 UTC by admin via cli')
        # An old confirmed commit keeps its text for good and must never read as "pending".
        rows.append('2   2026-09-27 08:00:00 UTC by admin via cli commit confirmed, rollback in 5mins')
        return '\n'.join(rows)

    def on_line(self, raw_line):
        if self.terminal:
            self.loaded += raw_line.strip() + '\n'
            return b''  # still capturing pasted configuration; no prompt yet
        line = raw_line.strip()
        self.commands.append(line)
        if self.asking:
            self.asking = False
            if line == 'yes':
                self.mode = 'oper'
                return self.frame(line, 'Exiting configuration mode')
            return self.frame(line)
        if line == 'cli':
            self.mode = 'oper'
            return self.frame(line)
        if line == 'configure':
            self.mode = 'conf'
            return self.frame(line, 'Entering configuration mode')
        if line == 'configure exclusive':
            self.mode = 'excl'
            return self.frame(line, 'warning: uncommitted changes will be discarded on exit')
        if line == 'configure private':
            if not self.private_ok:
                return self.frame(line, 'error: configuration database locked')  # stays at oper
            self.mode = 'priv'
            return self.frame(line, 'warning: uncommitted changes will be discarded on exit')
        if line in ('load override terminal', 'load merge terminal'):
            self.terminal = True
            self.loaded = ''
            return (line + '\r\n[Type ^D at a new line to end input]\r\n').encode()  # no prompt yet
        if line.startswith('show system commit'):
            return self.frame(line, self.commit_log())
        if line.startswith('show configuration'):
            return self.frame(line, self.before_display_set)
        if line.startswith('delete '):
            self._delete_index += 1
            if self._delete_index == self.delete_error_at:
                return self.frame(line, 'error: statement not found')
            return self.frame(line)
        if line == 'show':
            return self.frame(line, self.hierarchy_text)
        if line == 'show | display set':
            if self.mode == 'priv':
                return self.frame(line, self.private_rendered)
            if self.mode == 'excl':
                text = self.would_be_display_set if self.loaded_in_excl else self.inside_display_set
                return self.frame(line, text)
            return self.frame(line, '')
        if line == 'show | compare':
            if self.mode == 'conf':   # the look-before-lock probe sees only other people's edits
                return self.frame(line, self.foreign_compare)
            if self.mode == 'excl':
                return self.frame(line, self.compare_text)
            return self.frame(line, '')
        if line == 'commit check':
            ok = self.check_ok
            if ok and self.mode == 'conf' and self.pending:
                self.pending = None   # on Junos a successful check confirms a pending confirmed commit
            return self.frame(line, 'configuration check succeeds' if ok else 'error: configuration check-out failed')
        if line.startswith('commit confirmed'):
            if self.commit_ok:
                parts = line.split(' comment ', 1)
                self.pending = parts[1] if len(parts) == 2 else True
                output = ('commit confirmed will be automatically rolled back in 5 minutes unless confirmed\n'
                          'commit complete')
                if self.commit_mixed:
                    output += '\nerror: commit failed on re1'
            else:
                output = 'error: commit failed'
            return self.frame(line, output)
        if line == 'exit':
            if self.mode == 'conf' and self.foreign:
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
        if self.missing_load_complete:
            return self.frame('', 'load partially applied')
        if self.mode == 'excl':
            self.loaded_in_excl = True
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


class FakeClient:
    """Enough of a connected paramiko client for `restore_shell.open_shell`: one `invoke_shell()`."""

    def __init__(self, device):
        self.device = device

    def invoke_shell(self, **_kw):
        return FakeChannel(self.device)


def client_for(device):
    return FakeClient(device)


class DesignJunosDriverTests(unittest.TestCase):
    # --- session_name -----------------------------------------------------------

    def test_session_name_matches_pattern(self):
        for _ in range(20):
            self.assertRegex(design_junos.session_name(), r'^clabdsg-[0-9a-f]{8}$')
            self.assertTrue(NAME.match(design_junos.session_name()))

    # --- snapshot -----------------------------------------------------------------

    def test_snapshot_from_login_sets_screen_options_and_reads_display_set(self):
        device = FakeDevice(mode='oper', before_display_set='set system host-name r1\n')
        result = design_junos.snapshot(client_for(device))
        self.assertEqual(result, 'set system host-name r1\n')
        self.assertIn('set cli screen-length 0', device.commands)
        self.assertIn('set cli screen-width 0', device.commands)
        self.assertIn('show configuration | display set | no-more', device.commands)

    def test_snapshot_from_a_root_shell_issues_cli_first(self):
        device = FakeDevice(mode='root')
        design_junos.snapshot(client_for(device))
        self.assertIn('cli', device.commands)
        self.assertLess(device.commands.index('cli'), device.commands.index('set cli screen-length 0'))

    def test_snapshot_from_a_stale_configuration_prompt_rolls_back_and_leaves(self):
        device = FakeDevice(mode='conf')
        design_junos.snapshot(client_for(device))
        self.assertIn('rollback 0', device.commands)
        idx_rollback = device.commands.index('rollback 0')
        idx_exit = device.commands.index('exit')
        idx_show = device.commands.index('show configuration | display set | no-more')
        self.assertLess(idx_rollback, idx_exit)
        self.assertLess(idx_exit, idx_show)

    # --- render_desired -------------------------------------------------------------

    def test_render_desired_happy_path_enters_private_loads_and_rolls_back(self):
        device = FakeDevice(private_rendered='set interfaces ge-0/0/1 unit 0 family inet address 10.0.0.1/24\n')
        result = design_junos.render_desired(client_for(device), CANDIDATE)
        # `show | display set` runs inside configuration mode, so the device's own "[edit]" banner
        # rides along in the returned text uncut (unlike `show | compare`, which `unchanged()` filters).
        self.assertEqual(result[0], '')
        self.assertIn('set interfaces ge-0/0/1 unit 0 family inet address 10.0.0.1/24', result[1])
        idx_private = device.commands.index('configure private')
        idx_load = device.commands.index('load override terminal')
        idx_display = device.commands.index('show | display set')
        idx_rollback = device.commands.index('rollback 0')
        idx_exit = device.commands.index('exit')
        self.assertLess(idx_private, idx_load)
        self.assertLess(idx_load, idx_display)
        self.assertLess(idx_display, idx_rollback)
        self.assertLess(idx_rollback, idx_exit)

    def test_render_desired_load_failure_raises_and_still_rolls_back_and_leaves(self):
        for device in (FakeDevice(load_error=True), FakeDevice(missing_load_complete=True)):
            with self.assertRaises(RestoreError):
                design_junos.render_desired(client_for(device), CANDIDATE)
            self.assertIn('rollback 0', device.commands)
            self.assertIn('exit', device.commands)

    def test_render_desired_refusal_to_enter_private_mode_raises(self):
        device = FakeDevice(private_ok=False)
        with self.assertRaises(RestoreError):
            design_junos.render_desired(client_for(device), CANDIDATE)
        self.assertNotIn('load override terminal', device.commands)

    # --- stage(arm=False): refusals before the transaction --------------------------------

    def test_stage_refuses_a_pending_confirmed_commit_before_anything_else_is_sent(self):
        for pending in (True, 'clabdsg-99998888'):
            device = FakeDevice(pending=pending)
            with self.assertRaises(RestoreError) as ctx:
                design_junos.stage(client_for(device), CANDIDATE, [], 'clabdsg-11111111', arm=False)
            self.assertIn('already pending confirmation', str(ctx.exception))
            self.assertNotIn('show configuration | display set | no-more', device.commands)
            self.assertNotIn('configure exclusive', device.commands)

    def test_stage_invalid_name_raises_before_touching_the_device(self):
        device = FakeDevice()
        with self.assertRaises(RestoreError):
            design_junos.stage(client_for(device), CANDIDATE, [], 'not-a-design-session', arm=False)
        self.assertEqual(device.commands, [])

    def test_stage_refuses_foreign_edits_in_the_shared_candidate(self):
        device = FakeDevice(foreign=True, foreign_compare='[edit system]\n+   location building FOREIGN;')
        with self.assertRaises(RestoreError) as ctx:
            design_junos.stage(client_for(device), CANDIDATE, [], 'clabdsg-22223333', arm=False)
        self.assertEqual(str(ctx.exception), design_junos.FOREIGN_EDITS)
        self.assertNotIn('configure exclusive', device.commands)
        self.assertIn('configure', device.commands)
        self.assertIn('show | compare', device.commands)

    # --- stage(arm=False): the review transaction itself --------------------------------

    def test_stage_raises_when_the_running_configuration_changed_inside_the_lock(self):
        device = FakeDevice(before_display_set='set system host-name r1\n',
                             inside_display_set='set system host-name r1\nset interfaces em0 unit 0 family inet address 192.0.2.1/30\n')
        with self.assertRaises(RestoreError) as ctx:
            design_junos.stage(client_for(device), CANDIDATE, [], 'clabdsg-44445555', arm=False)
        self.assertIn('changed while', str(ctx.exception))
        self.assertIn('rollback 0', device.commands)
        self.assertNotIn('load merge terminal', device.commands)
        self.assertEqual(device.mode, 'oper')

    def test_stage_removals_a_non_delete_line_raises_before_sending_and_a_rejected_one_rolls_back(self):
        bad = FakeDevice()
        with self.assertRaises(RestoreError) as ctx:
            design_junos.stage(client_for(bad), CANDIDATE, ['interfaces ge-0/0/2 disable', 'delete interfaces ge-0/0/3'],
                                'clabdsg-66667777', arm=False)
        self.assertIn('is not a delete statement', str(ctx.exception))
        self.assertFalse(any(c.startswith('delete ') for c in bad.commands))
        self.assertIn('rollback 0', bad.commands)

        rejected = FakeDevice(delete_error_at=1)
        with self.assertRaises(RestoreError) as ctx:
            design_junos.stage(client_for(rejected), CANDIDATE, ['delete interfaces ge-0/0/2'],
                                'clabdsg-88889999', arm=False)
        self.assertIn('rejected removal 1 of 1', str(ctx.exception))
        self.assertIn('delete interfaces ge-0/0/2', rejected.commands)
        self.assertIn('rollback 0', rejected.commands)

    def test_stage_review_happy_path_returns_before_would_be_diff_and_handle_in_order(self):
        device = FakeDevice()
        name = 'clabdsg-bbbbbbbb'
        result = design_junos.stage(client_for(device), CANDIDATE, REMOVALS, name, confirm_minutes=5, arm=False)
        self.assertEqual(result['before'], BEFORE)
        # `show | display set` runs inside the exclusive lock, so its own "[edit]" banner rides
        # along in `would_be` uncut, unlike the diff (`unchanged()` filters `[edit]` there).
        self.assertIn(WOULD_BE.strip(), result['would_be'])
        self.assertIn(COMPARE, result['diff'])
        self.assertIn(HIERARCHY.strip(), result['hierarchy'])
        self.assertFalse(result['no_op'])
        self.assertFalse(result['armed'])
        self.assertEqual(result['handle'], {'session': name})
        idx_load = device.commands.index('load merge terminal')
        idx_would_be = device.commands.index('show | display set', idx_load)
        idx_hierarchy = device.commands.index('show', idx_would_be)
        idx_diff = device.commands.index('show | compare', idx_hierarchy)
        idx_rollback = device.commands.index('rollback 0', idx_diff)
        idx_exit = device.commands.index('exit', idx_rollback)
        self.assertLess(idx_load, idx_would_be)
        self.assertLess(idx_would_be, idx_hierarchy)
        self.assertLess(idx_hierarchy, idx_diff)
        self.assertLess(idx_diff, idx_rollback)
        self.assertLess(idx_rollback, idx_exit)
        self.assertNotIn('commit check', device.commands)
        self.assertFalse(any(c.startswith('commit confirmed') for c in device.commands))

    def test_stage_review_no_op_when_compare_shows_only_edit_lines(self):
        device = FakeDevice(compare_text='[edit]')
        result = design_junos.stage(client_for(device), CANDIDATE, [], 'clabdsg-ccccdddd', arm=False)
        self.assertTrue(result['no_op'])
        self.assertFalse(result['armed'])
        self.assertIn('rollback 0', device.commands)

    # --- stage(arm=True) -------------------------------------------------------------------

    def test_stage_arm_happy_path_exact_command_order(self):
        device = FakeDevice()
        name = 'clabdsg-aaaaaaaa'
        result = design_junos.stage(client_for(device), CANDIDATE, REMOVALS, name, confirm_minutes=5, arm=True)
        self.assertTrue(result['armed'])
        self.assertEqual(result['confirm_minutes'], 5)
        self.assertEqual(result['handle'], {'session': name})
        self.assertIn(HIERARCHY.strip(), result['hierarchy'])
        self.assertEqual(device.commands, [
            'set cli screen-length 0',
            'set cli screen-width 0',
            'set cli complete-on-space off',
            'show system commit | no-more',
            'show configuration | display set | no-more',
            'configure',
            'show | compare',
            'exit',
            'configure exclusive',
            'show | display set',
            'delete interfaces ge-0/0/2',
            'delete protocols lldp interface ge-0/0/3',
            'load merge terminal',
            'show | display set',
            'show',   # the device's own hierarchy, feeding design_ownership.junos_blocks
            'show | compare',
            'commit check',
            'commit confirmed 5 comment clabdsg-aaaaaaaa',
            'exit',
        ])

    def test_stage_arm_no_op_never_sends_commit_check_or_commit_confirmed(self):
        device = FakeDevice(compare_text='[edit]')
        result = design_junos.stage(client_for(device), CANDIDATE, [], 'clabdsg-eeeeffff', arm=True)
        self.assertTrue(result['no_op'])
        self.assertFalse(result['armed'])
        self.assertNotIn('commit check', device.commands)
        self.assertFalse(any(c.startswith('commit confirmed') for c in device.commands))

    def test_stage_arm_commit_check_failure_raises_after_rollback(self):
        device = FakeDevice(check_ok=False)
        with self.assertRaises(RestoreError) as ctx:
            design_junos.stage(client_for(device), CANDIDATE, [], 'clabdsg-11112222', arm=True)
        self.assertIn('failed the configuration check', str(ctx.exception))
        self.assertIn('rollback 0', device.commands)
        self.assertFalse(any(c.startswith('commit confirmed') for c in device.commands))

    def test_stage_arm_commit_confirmed_rejection_raises_after_rollback(self):
        device = FakeDevice(commit_ok=False)
        with self.assertRaises(RestoreError) as ctx:
            design_junos.stage(client_for(device), CANDIDATE, [], 'clabdsg-33334444', arm=True)
        self.assertIn('did not accept the timed commit', str(ctx.exception))
        self.assertIn('commit check', device.commands)
        self.assertIn('rollback 0', device.commands)

    def test_stage_arm_commit_complete_beside_an_error_line_raises_session_lost_without_rollback(self):
        device = FakeDevice(commit_mixed=True)
        with self.assertRaises(SessionLost):
            design_junos.stage(client_for(device), CANDIDATE, [], 'clabdsg-55556666', arm=True)
        self.assertNotIn('rollback 0', device.commands)

    # --- confirm ------------------------------------------------------------------------

    def test_confirm_happy_path_checks_then_reports_confirmed_and_saved(self):
        device = FakeDevice(pending='clabdsg-aaaaaaaa')
        result = design_junos.confirm(client_for(device), {'session': 'clabdsg-aaaaaaaa'})
        self.assertEqual(result, {'confirmed': True, 'saved': True})
        idx_configure = device.commands.index('configure')
        idx_check = device.commands.index('commit check', idx_configure)
        idx_exit = device.commands.index('exit', idx_check)
        self.assertLess(idx_configure, idx_check)
        self.assertLess(idx_check, idx_exit)
        self.assertIsNone(device.pending)

    def test_confirm_with_nothing_pending_raises(self):
        device = FakeDevice(pending=None)
        with self.assertRaises(RestoreError) as ctx:
            design_junos.confirm(client_for(device), {'session': 'clabdsg-aaaaaaaa'})
        self.assertIn('Nothing is waiting', str(ctx.exception))
        self.assertNotIn('configure', device.commands)

    def test_confirm_leaves_a_different_pending_change_alone(self):
        device = FakeDevice(pending='clabdsg-other001')
        with self.assertRaises(RestoreError):
            design_junos.confirm(client_for(device), {'session': 'clabdsg-aaaaaaaa'})
        self.assertNotIn('configure', device.commands)
        self.assertNotIn('commit check', device.commands)
        self.assertEqual(device.pending, 'clabdsg-other001')

    def test_confirm_without_a_valid_session_name_raises_without_touching_the_device(self):
        device = FakeDevice(pending='clabdsg-aaaaaaaa')
        with self.assertRaises(RestoreError):
            design_junos.confirm(client_for(device), {'session': 'not-a-design-session'})
        self.assertEqual(device.commands, [])
        with self.assertRaises(RestoreError):
            design_junos.confirm(client_for(device), {})
        self.assertEqual(device.commands, [])

    # --- pending / cleanup / persist / options -------------------------------------------

    def test_pending_reports_nothing_a_comment_or_true_as_restore_junos_does(self):
        self.assertEqual(design_junos.pending(client_for(FakeDevice(pending=None))), '')
        self.assertIs(design_junos.pending(client_for(FakeDevice(pending=True))), True)
        self.assertEqual(design_junos.pending(client_for(FakeDevice(pending='clabdsg-0000aaaa'))), 'clabdsg-0000aaaa')

    def test_cleanup_returns_empty_and_touches_nothing(self):
        device = FakeDevice()
        self.assertEqual(design_junos.cleanup(client_for(device)), [])
        self.assertEqual(device.commands, [])

    def test_persist_returns_true_and_touches_nothing(self):
        device = FakeDevice()
        self.assertTrue(design_junos.persist(client_for(device)))
        self.assertEqual(device.commands, [])

    def test_options_is_always_empty(self):
        self.assertEqual(design_junos.options({'enable_password': 'zebra'}), {})
        self.assertEqual(design_junos.options({}), {})
        self.assertEqual(design_junos.options(None), {})


class CheckReasonTests(unittest.TestCase):
    def test_commit_check_errors_become_fixed_phrases_never_device_text(self):
        text = ("warning: requires 'vxlan' license\nwarning: requires 'bgp' license\n[edit vlans red]\n"
                "  Error in parsing bridge domains/vlans: SECRET-NAME oddity\nerror: configuration check-out failed\n")
        words = design_junos._check_reasons(text)
        self.assertIn('VLAN or bridge-domain', words)
        self.assertNotIn('SECRET-NAME', words); self.assertNotIn('check-out failed', words)
        self.assertEqual(design_junos._check_reasons('configuration check succeeds\n'), '')


if __name__ == '__main__':
    unittest.main()
