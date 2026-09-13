"""The SSH shell driver against scripted NOS sessions: enable, scoped commits, repeat safety, aborts."""
import socket
import unittest

from app.telemetry_adapters import ADAPTERS
from app.telemetry_provision import LIMIT, ProvisionError, provision


class FakeChannel:
    """A scripted interactive session: each sent line is answered from a table."""
    def __init__(self, banner, answers, prompt):
        self.pending = banner.encode()
        self.answers = answers   # command -> (output, new prompt or None)
        self.prompt = prompt
        self.sent = []
        self.closed = False

    def settimeout(self, value): pass

    def recv(self, size):
        if not self.pending:
            raise socket.timeout()
        chunk, self.pending = self.pending[:size], self.pending[size:]
        return chunk

    def sendall(self, data):
        line = data.decode().rstrip('\n')
        self.sent.append(line)
        output, prompt = self.answers.get(line, ('', None))
        if callable(output): output = output(line)
        if prompt: self.prompt = prompt
        self.pending += (line + '\r\n' + output + self.prompt).encode()

    def close(self): self.closed = True


class FakeClient:
    def __init__(self, channel): self.channel = channel
    def invoke_shell(self, **kwargs): return self.channel


EOS_SHOW = ADAPTERS['arista_ceos'].show_commands()
XR_SHOW = ADAPTERS['cisco_xrv9k'].show_commands()
JUNOS_SHOW = ADAPTERS['juniper_cjunosevolved'].show_commands()


class EosProvisionTests(unittest.TestCase):
    def session(self, gnmi_after=None, enable_password=True, privilege='Current privilege level is 15'):
        state = {'gnmi': ''}
        def show(_): return state['gnmi']
        def commit(_):
            state['gnmi'] = 'management api gnmi\n   transport grpc default\n'
            return ''
        answers = {'enable': ('Password: ', 'Password: ') if enable_password else ('', 'ceos1#'),
                   'secret': ('', 'ceos1#'), 'terminal length 0': ('', None), 'show privilege': (privilege + '\n', None),
                   EOS_SHOW[0]: (show, None), EOS_SHOW[1]: ('interface Management0\n   ip address 172.20.20.2/24\n', None),
                   'configure terminal': ('', 'ceos1(config)#'), 'management api gnmi': ('', 'ceos1(config-mgmt-api-gnmi)#'),
                   'transport grpc default': (commit, 'ceos1(config-mgmt-api-gnmi-default)#'), 'end': ('', 'ceos1#')}
        if gnmi_after is not None: state['gnmi'] = gnmi_after
        channel = FakeChannel('\r\nceos1>', answers, 'ceos1>')
        return channel, FakeClient(channel)

    def test_enable_with_password_then_add_only_the_missing_transport(self):
        channel, client = self.session()
        result = provision(client, ADAPTERS['arista_ceos'], {'enable_password': 'secret'})
        self.assertEqual(result['applied'], ['management api gnmi', '   transport grpc default'])
        self.assertEqual((result['port'], result['transport']), (6030, 'plaintext'))
        self.assertEqual(channel.sent[:3], ['enable', 'secret', 'terminal length 0'])
        self.assertIn('configure terminal', channel.sent); self.assertNotIn('write', channel.sent); self.assertNotIn('write memory', channel.sent)
        self.assertTrue(channel.closed)

    def test_already_configured_nodes_are_left_alone(self):
        channel, client = self.session(gnmi_after='management api gnmi\n   transport grpc default\n', enable_password=False)
        result = provision(client, ADAPTERS['arista_ceos'], {})
        self.assertEqual(result['applied'], []); self.assertIn('nothing changed', result['message'])
        self.assertNotIn('configure terminal', channel.sent, 'repeat runs never rewrite configuration')
        check = provision(FakeClient(self.session(gnmi_after='management api gnmi\n   transport grpc default\n', enable_password=False)[0]), ADAPTERS['arista_ceos'], {}, mode='check')
        self.assertEqual(check['missing'], [])

    def test_missing_enable_password_and_low_privilege_are_reported_not_guessed(self):
        _, client = self.session()
        with self.assertRaisesRegex(ProvisionError, 'enable password'):
            provision(client, ADAPTERS['arista_ceos'], {'enable_password': ''})
        _, client = self.session(enable_password=False, privilege='Current privilege level is 1')
        with self.assertRaisesRegex(ProvisionError, 'privilege level 15'):
            provision(client, ADAPTERS['arista_ceos'], {})

    def test_rejected_lines_abort_and_never_report_success(self):
        channel, client = self.session(enable_password=False)
        channel.answers['transport grpc default'] = ('% Invalid input\n', None)
        with self.assertRaisesRegex(ProvisionError, 'rejected'):
            provision(client, ADAPTERS['arista_ceos'], {})
        self.assertEqual(channel.sent[-1], 'end')

    def test_output_flood_and_silence_are_bounded(self):
        channel, client = self.session(enable_password=False)
        channel.answers[EOS_SHOW[0]] = ('x' * (LIMIT + 10), None)
        with self.assertRaisesRegex(ProvisionError, 'more output'):
            provision(client, ADAPTERS['arista_ceos'], {})
        channel = FakeChannel('', {}, 'ceos1#')
        from app import telemetry_provision
        with unittest.mock.patch.object(telemetry_provision, 'PROMPT_TIMEOUT', 0.05):
            with self.assertRaisesRegex(ProvisionError, 'did not return'):
                provision(FakeClient(channel), ADAPTERS['arista_ceos'], {})


class IosxrProvisionTests(unittest.TestCase):
    def session(self, existing='', commit_output=''):
        state = {'grpc': existing}
        def show(_): return state['grpc'] or '% No such configuration item(s)\n'
        def commit(_):
            if not commit_output: state['grpc'] = 'grpc\n port 57400\n!\n'
            return commit_output
        answers = {'terminal length 0': ('', None), 'terminal width 512': ('', None), XR_SHOW[0]: (show, None),
                   XR_SHOW[1]: ('interface MgmtEth0/RP0/CPU0/0\n ipv4 address dhcp\n!\n', None),
                   'configure terminal': ('', 'RP/0/RP0/CPU0:ios(config)#'), 'grpc': ('', 'RP/0/RP0/CPU0:ios(config-grpc)#'),
                   'port 57400': ('', None), 'commit': (commit, None), 'end': ('', 'RP/0/RP0/CPU0:ios#'), 'abort': ('', 'RP/0/RP0/CPU0:ios#')}
        channel = FakeChannel('\r\n\r\nRP/0/RP0/CPU0:ios#', answers, 'RP/0/RP0/CPU0:ios#')
        return channel, FakeClient(channel)

    def test_grpc_is_added_with_a_scoped_commit(self):
        channel, client = self.session()
        result = provision(client, ADAPTERS['cisco_xrv9k'], {})
        self.assertEqual(result['applied'], ['grpc', ' port 57400']); self.assertEqual(result['transport'], 'tls')
        self.assertLess(channel.sent.index('commit'), channel.sent.index('end'))
        self.assertEqual(channel.sent[-2:], XR_SHOW, 'the running configuration is read again to verify')
        self.assertNotIn('copy running-config startup-config', channel.sent)

    def test_failed_commit_is_aborted(self):
        channel, client = self.session(commit_output='% Failed to commit one or more configuration items during a pseudo-atomic operation.\n')
        with self.assertRaisesRegex(ProvisionError, 'rejected'):
            provision(client, ADAPTERS['cisco_xrv9k'], {})
        self.assertEqual(channel.sent[-1], 'abort')

    def test_preconfigured_no_tls_grpc_is_reused(self):
        channel, client = self.session(existing='grpc\n port 57400\n no-tls\n!\n')
        result = provision(client, ADAPTERS['cisco_xrv9k'], {})
        self.assertEqual((result['applied'], result['transport'], result['port']), ([], 'plaintext', 57400))
        self.assertNotIn('configure terminal', channel.sent)


class JunosProvisionTests(unittest.TestCase):
    def session(self, existing='', private_output='', commit_output='commit complete\n'):
        state = {'svc': existing}
        def show(_): return state['svc']
        def commit(_):
            if 'complete' in commit_output: state['svc'] = 'set system services extension-service request-response grpc clear-text port 32767\n'
            return commit_output
        answers = {'set cli screen-length 0': ('Screen length set to 0\n', None), 'set cli screen-width 0': ('Screen width set to 0\n', None),
                   JUNOS_SHOW[0]: (show, None), JUNOS_SHOW[1]: ('', None),
                   'configure private': (private_output, 'admin@r1#' if not private_output else None),
                   'set system services extension-service request-response grpc clear-text port 32767': ('', None),
                   'commit and-quit': (commit, 'admin@r1>' if 'complete' in commit_output else None),
                   'rollback 0': ('load complete\n', None), 'exit configuration-mode': ('', 'admin@r1>'), 'cli': ('', 'admin@r1>')}
        channel = FakeChannel('--- JUNOS 26.2R1.7-EVO Linux (none) ...\r\nadmin@r1>', answers, 'admin@r1>')
        return channel, FakeClient(channel)

    def test_private_configuration_commit_adds_the_service(self):
        channel, client = self.session()
        result = provision(client, ADAPTERS['juniper_cjunosevolved'], {})
        self.assertEqual(result['applied'], ['set system services extension-service request-response grpc clear-text port 32767'])
        self.assertIn('configure private', channel.sent); self.assertIn('commit and-quit', channel.sent)
        self.assertNotIn('configure exclusive', channel.sent); self.assertNotIn('commit confirmed', ' '.join(channel.sent))

    def test_commit_errors_roll_back_the_private_candidate(self):
        channel, client = self.session(commit_output='error: configuration check-out failed\n')
        with self.assertRaisesRegex(ProvisionError, 'rejected'):
            provision(client, ADAPTERS['juniper_cjunosevolved'], {})
        self.assertEqual(channel.sent[-2:], ['rollback 0', 'exit configuration-mode'])

    def test_a_root_shell_enters_the_cli_first(self):
        channel, client = self.session(existing='set system services extension-service request-response grpc clear-text port 32767\n')
        channel.pending = b'root@r1:~ % '; channel.prompt = 'root@r1:~ % '
        result = provision(client, ADAPTERS['juniper_cjunosevolved'], {})
        self.assertEqual(channel.sent[0], 'cli'); self.assertEqual(result['applied'], [])

    def test_removal_deletes_only_recorded_lines(self):
        channel, client = self.session(existing='set system services extension-service request-response grpc clear-text port 32767\n')
        channel.answers['delete system services extension-service request-response grpc clear-text'] = ('', None)
        result = provision(client, ADAPTERS['juniper_cjunosevolved'], {}, mode='remove',
                           owned=['set system services extension-service request-response grpc clear-text port 32767'])
        self.assertEqual(len(result['removed']), 1); self.assertIn('delete system services extension-service request-response grpc clear-text', channel.sent)
        untouched = provision(FakeClient(self.session(existing='set system services extension-service request-response grpc ssl port 32767\n')[0]),
                              ADAPTERS['juniper_cjunosevolved'], {}, mode='remove', owned=[])
        self.assertEqual(untouched['removed'], []); self.assertIn('No manager-owned', untouched['message'])


import unittest.mock  # noqa: E402

if __name__ == '__main__':
    unittest.main()
