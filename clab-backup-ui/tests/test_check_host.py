import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch


spec = importlib.util.spec_from_file_location('check_host', Path(__file__).resolve().parents[2] / 'deploy/check_host.py')
host = importlib.util.module_from_spec(spec)
spec.loader.exec_module(host)


def result(stdout='', code=0, reason=''):
    return SimpleNamespace(stdout=stdout, stderr='private diagnostic', code=code, reason=reason, ok=code == 0 and not reason)


class Context:
    owner = 'archtop'
    version = '1.16.1'
    source = Path(__file__).parent
    require_admin_sftp = False
    require_kvm = False
    privileged = True

    def __init__(self):
        self.records = {}
        self.commands = []
        self.answers = {}

    def add(self, check_id, status, title, detail, fix=''):
        self.records[check_id] = (status, title, detail, fix)

    def run(self, args, **kwargs):
        self.commands.append((args, kwargs))
        if tuple(args) in self.answers:
            return self.answers[tuple(args)]
        if args[:2] == ['timedatectl', 'show']:
            return result('NTPSynchronized=yes\nNTP=yes\n')
        if args[:2] == ['getent', 'passwd']:
            return result('clab-discovery:x:1001:1001::/home/clab-discovery:/bin/sh\n')
        if args[:2] == ['passwd', '-S']:
            return result('clab-discovery P 09/11/2026 0 99999 7 -1\n')
        if args[:2] == ['/usr/sbin/sshd', '-T']:
            values = dict(host.POLICY)
            if 'user=archtop' in args[-1]:
                values.update(forcecommand='none', authenticationmethods='any')
            return result('\n'.join(f'{key} {value}' for key, value in values.items()) +
                          '\nsubsystem sftp /usr/lib/openssh/sftp-server\nport 22\nlistenaddress 0.0.0.0:22\n')
        if args[0] == 'sudo':
            return result('Sudoers entry:\n    RunAsUsers: root\n    Options: !authenticate\n    Commands:\n        /usr/lib/openssh/sftp-server\n')
        if args[0] == 'dpkg-query':
            return result('installed')
        return result()


class HostChecksTests(unittest.TestCase):
    def test_socket_activation_does_not_require_active_ssh_service(self):
        ctx = Context()
        with patch.object(host, '_executable', return_value=True), patch.object(host.socket, 'create_connection'):
            host._ssh(ctx)
        self.assertEqual(ctx.records['ssh.listener'][0], 'PASS')
        self.assertEqual(ctx.records['ssh.discovery'][0], 'PASS')
        self.assertEqual(ctx.records['sftp.normal'][0], 'PASS')
        self.assertFalse(any(args[:2] == ['systemctl', 'is-active'] for args, _ in ctx.commands))
        self.assertFalse(any('private diagnostic' in str(record) for record in ctx.records.values()))

    def test_clab_discovery_requires_password_and_force_restrictions(self):
        for replacement in ('clab-discovery L 09/11/2026', 'clab-discovery NP 09/11/2026'):
            with self.subTest(replacement=replacement):
                ctx = Context()
                ctx.answers[('passwd', '-S', 'clab-discovery')] = result(replacement)
                with patch.object(host, '_executable', return_value=True), patch.object(host.socket, 'create_connection'):
                    host._ssh(ctx)
                self.assertEqual(ctx.records['ssh.discovery'][0], 'FAIL')
        ctx = Context()
        ctx.answers[('/usr/sbin/sshd', '-T', '-C', 'user=clab-discovery,host=localhost,addr=192.0.2.1')] = result('forcecommand none\n')
        with patch.object(host, '_executable', return_value=True), patch.object(host.socket, 'create_connection'):
            host._ssh(ctx)
        self.assertEqual(ctx.records['ssh.discovery'][0], 'FAIL')

    def test_missing_ssh_reports_critical_failure_and_skips_dependants(self):
        ctx = Context()
        with patch.object(host, '_executable', return_value=False):
            host._ssh(ctx)
        self.assertEqual(ctx.records['ssh.config'][0], 'FAIL')
        self.assertEqual(ctx.records['ssh.discovery'][0], 'SKIP')
        self.assertEqual(ctx.records['sftp.normal'][0], 'SKIP')

    def test_admin_sftp_checks_matching_nopasswd_rule_without_starting_server(self):
        ctx = Context()
        with patch.object(host, '_executable', return_value=True):
            host._admin_sftp(ctx)
        self.assertEqual(ctx.records['sftp.admin'][0], 'PASS')
        self.assertEqual(ctx.commands[0][0], ['sudo', '-n', '-ll', '-U', 'archtop', '--', host.SFTP_SERVER])
        self.assertTrue(ctx.commands[0][1]['privileged'])
        self.assertEqual(len(ctx.commands), 1)

    def test_passwd_unknown_or_denied_sudo_rule_never_passes(self):
        args = ('sudo', '-n', '-ll', '-U', 'archtop', '--', host.SFTP_SERVER)
        for answer in (result('Options: authenticate\nCommands:\n ALL\n'),
                       result(host.SFTP_SERVER), result(code=1),
                       result('Options: !authenticate, authenticate\n')):
            for required, expected in ((False, 'INFO'), (True, 'FAIL')):
                with self.subTest(answer=answer.stdout, required=required):
                    ctx = Context()
                    ctx.require_admin_sftp = required
                    ctx.answers[args] = answer
                    with patch.object(host, '_executable', return_value=True):
                        host._admin_sftp(ctx)
                    self.assertEqual(ctx.records['sftp.admin'][0], expected)

    def test_clock_timeout_does_not_claim_wrong_time_or_change_clock(self):
        ctx = Context()
        args = ('timedatectl', 'show', '--property=NTPSynchronized', '--property=NTP')
        ctx.answers[args] = result(reason='timed out')
        host._clock(ctx)
        self.assertEqual(ctx.records['host.clock'][0], 'WARN')
        self.assertIn('not confirmed', ctx.records['host.clock'][2])
        self.assertEqual(ctx.commands, [(list(args), {'timeout': 5})])

    def test_unavailable_privileges_do_not_claim_account_policy_passed(self):
        ctx = Context()
        ctx.privileged = False
        with patch.object(host, '_executable', return_value=True), patch.object(host.socket, 'create_connection'):
            host._ssh(ctx)
        self.assertEqual(ctx.records['ssh.config'][0], 'WARN')
        self.assertEqual(ctx.records['sftp.admin'][0], 'WARN')
        self.assertEqual(ctx.commands, [])

    def test_nonloopback_binding_warns_instead_of_false_daemon_failure(self):
        for config, expected in (('port 2222\nlistenaddress 10.0.0.1:2222\n', 'WARN'),
                                 ('port 22\nlistenaddress 0.0.0.0:22\n', 'FAIL')):
            ctx = Context()
            with patch.object(host.socket, 'create_connection', side_effect=OSError('refused')) as connect:
                host._listener(ctx, config)
            self.assertEqual(ctx.records['ssh.listener'][0], expected)
            self.assertTrue(all(call.kwargs['timeout'] == 1 for call in connect.call_args_list))

    def test_internal_sftp_supported_and_missing_subsystem_fails(self):
        key = ('/usr/sbin/sshd', '-T', '-C', 'user=archtop,host=localhost,addr=127.0.0.1')
        for subsystem, expected in (('subsystem sftp internal-sftp\n', 'PASS'), ('', 'FAIL')):
            ctx = Context()
            ctx.answers[key] = result('forcecommand none\npasswordauthentication yes\nauthenticationmethods any\n' + subsystem)
            with patch.object(host, '_executable', return_value=True), patch.object(host.socket, 'create_connection'):
                host._ssh(ctx)
            self.assertEqual(ctx.records['sftp.normal'][0], expected)

    def test_full_host_checks_read_only_and_optional_features_not_required(self):
        ctx = Context()
        ctx.answers[('dpkg-query', '-W', '-f=${db:Status-Status}', 'qemu-guest-agent')] = result(code=1)
        with patch.object(host, '_read', return_value='ID=ubuntu\nVERSION_ID="24.04"\n'), \
                patch.object(host.platform, 'machine', return_value='x86_64'), \
                patch.object(host, '_executable', return_value=True), \
                patch.object(host.socket, 'create_connection'), patch.object(host, '_disk'), \
                patch.object(host.os, 'stat', side_effect=FileNotFoundError):
            host.check_host(ctx)
        self.assertEqual(ctx.records['host.os'][0], 'PASS')
        self.assertEqual(ctx.records['host.guest_agent'][0], 'INFO')
        self.assertEqual(ctx.records['host.kvm'][0], 'INFO')
        forbidden = {'install', 'enable', 'restart', 'reload', 'set-ntp', 'apt-get', 'chmod', 'chown'}
        for args, kwargs in ctx.commands:
            self.assertFalse(forbidden.intersection(args))
            self.assertLessEqual(kwargs.get('timeout', 15), 5)

    def test_disk_thresholds_and_missing_directory_ancestor(self):
        for free, expected in ((.5, 'FAIL'), (2, 'WARN'), (20, 'PASS')):
            ctx = Context()
            usage = SimpleNamespace(total=100 * 1024 ** 3, free=free * 1024 ** 3)
            with patch.object(host.shutil, 'disk_usage', return_value=usage):
                host._disk(ctx, 'disk', 'Free space', Path(__file__).parent / 'missing-directory')
            self.assertEqual(ctx.records['disk'][0], expected)

    def test_required_kvm_missing_is_a_failure(self):
        ctx = Context()
        ctx.require_kvm = True
        with patch.object(host, '_read', return_value=''), patch.object(host, '_clock'), \
                patch.object(host, '_disk'), patch.object(host, '_ssh'), \
                patch.object(host.os, 'stat', side_effect=FileNotFoundError):
            host.check_host(ctx)
        self.assertEqual(ctx.records['host.kvm'][0], 'FAIL')


if __name__ == '__main__':
    unittest.main()
