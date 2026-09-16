"""Unit tests for the Junos restore CLI driver against a scripted fake channel.

The fake models just enough of a Junos session (operational/config prompts, a
`load override terminal ... ^D` paste, root-authentication presence, commit check and
commit confirmed) to exercise the driver's dialog without a real device.
"""
import socket
import unittest

from app.restore_junos import (JunosShell, apply_shell, confirm_shell, capture_shell,
                               RestoreError, supports_restore)


class FakeDevice:
    def __init__(self, has_rootauth=True, compare='[edit system]\n-  host-name OLD;\n+  host-name NEW;',
                 load_error=False, check_ok=True, commit_ok=True, hostname='r1'):
        self.mode = 'oper'
        self.has_rootauth = has_rootauth
        self.compare = compare
        self.load_error = load_error
        self.check_ok = check_ok
        self.commit_ok = commit_ok
        self.hostname = hostname
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
        return (body + self.prompt()).encode()

    def on_line(self, line):
        line = line.strip()
        if self.terminal:
            self.loaded += line + '\n'
            return b''  # still capturing pasted configuration; no prompt yet
        self.commands.append(line)
        if line in ('configure', 'configure exclusive'):
            self.mode = 'conf'
            return self.frame(line)
        if line == 'load override terminal':
            self.terminal = True
            self.loaded = ''
            return (line + '\r\n[Type ^D at a new line to end input]\r\n').encode()  # no prompt yet
        if line.startswith('show configuration system root-authentication'):
            out = 'set system root-authentication encrypted-password "$6$x"' if self.has_rootauth else ''
            return self.frame(line, out)
        if line.startswith('set system root-authentication'):
            self.has_rootauth = True
            return self.frame(line)
        if line == 'show | compare':
            return self.frame(line, self.compare)
        if line == 'commit check':
            return self.frame(line, 'configuration check succeeds' if self.check_ok
                              else 'error: configuration check-out failed')
        if line.startswith('commit confirmed'):
            return self.frame(line, 'commit complete' if self.commit_ok else 'error: commit failed')
        if line == 'commit':
            return self.frame(line, 'commit complete' if self.commit_ok else 'error: commit failed')
        if line.startswith('show configuration | compare rollback'):
            return self.frame(line, self.compare + '\n# commit confirmed will be rolled back in 5 minutes')
        if line.startswith('show configuration'):
            return self.frame(line, 'set system host-name %s' % self.hostname)
        if line == 'exit':
            self.mode = 'oper'
            return self.frame(line)
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

    def test_load_error_discards_and_raises(self):
        device = FakeDevice(load_error=True)
        with self.assertRaises(RestoreError):
            apply_shell(shell_for(device), CANDIDATE)
        self.assertEqual(device.commands.count('rollback 0'), 2)  # enter + abort
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

    def test_no_op_detected_when_compare_empty(self):
        device = FakeDevice(compare='[edit]')
        result = apply_shell(shell_for(device), CANDIDATE)
        self.assertTrue(result['no_op'])

    def test_empty_candidate_refused(self):
        with self.assertRaises(RestoreError):
            apply_shell(shell_for(FakeDevice()), '   \n  ')

    def test_confirm_commits_and_reports_pending(self):
        device = FakeDevice()
        result = confirm_shell(shell_for(device))
        self.assertTrue(result['confirmed'])
        self.assertTrue(result['had_pending_rollback'])
        self.assertIn('commit', device.commands)

    def test_capture_returns_config(self):
        device = FakeDevice(hostname='rx')
        out = capture_shell(shell_for(device), display_set=True)
        self.assertIn('host-name rx', out)


if __name__ == '__main__':
    unittest.main()
