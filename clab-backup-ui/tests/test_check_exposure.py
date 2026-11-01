"""The TLS, firewall and exposure group of the health check (EXPOSURE.md 6.2, 6.3).

Standard library only. Every command, HTTP question and the setup_tls module loader is mocked on the
context, the way test_check_install.py mocks ctx.http: nothing here touches a real VM, a real certificate
or the manager's data.
"""
from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import time
import unittest
import unittest.mock
from unittest.mock import Mock


DEPLOY = Path(__file__).resolve().parents[2] / 'deploy'


def load(name):
    spec = importlib.util.spec_from_file_location(name, DEPLOY / (name + '.py'))
    value = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = value
    spec.loader.exec_module(value)
    return value


check = load('check_install')
exposure = load('check_exposure')

VERSION = '1.32.0'
PRIVATE = 'PRIVATE-PASSWORD-TOKEN-DO-NOT-PRINT'
TLS = '/srv/containerlab-node-manager/tls'
DATA = '/srv/containerlab-node-manager/data'
SETUP_CODE = DATA + '/setup-code'
FINGERPRINT = 'sha256 Fingerprint=3A:7F:00:11:22:33:44:55:66:77:88:99:AA:BB:CC:DD:EE:FF:01:02:03:04:05:06:07:08:09:0A:0B:0C:0D:0E'
DOCKER0 = '172.17.0.1'
UPLINK = '192.0.2.10'
COMMAND = ['uvicorn', 'app.main:create_app', '--factory', '--host', '0.0.0.0', '--port', '8443', '--workers', '1',
           '--ssl-certfile', '/tls/cert.pem', '--ssl-keyfile', '/tls/key.pem', '--no-proxy-headers', '--no-server-header']
HTTPS = 'https://127.0.0.1:8443'
REDIRECT = 'http://127.0.0.1:8081'
PLAIN_ON_TLS_PORT = 'http://127.0.0.1:8443'
HSTS = {'strict-transport-security': 'max-age=15552000'}

ROUTES_V4 = [{'dst': 'default', 'gateway': '192.0.2.1', 'dev': 'eth0', 'prefsrc': UPLINK}]
ADDRESSES = [
    {'ifname': 'lo', 'addr_info': [{'family': 'inet', 'local': '127.0.0.1', 'scope': 'host'},
                                   {'family': 'inet6', 'local': '::1', 'scope': 'host'}]},
    {'ifname': 'eth0', 'addr_info': [{'family': 'inet', 'local': UPLINK, 'scope': 'global'},
                                     {'family': 'inet6', 'local': 'fe80::1', 'scope': 'link'}]},
    {'ifname': 'docker0', 'addr_info': [{'family': 'inet', 'local': DOCKER0, 'scope': 'global'}]},
    {'ifname': 'br-0123456789ab', 'addr_info': [{'family': 'inet', 'local': '172.20.0.1', 'scope': 'global'}]},
    {'ifname': 'veth1a2b3c', 'addr_info': [{'family': 'inet6', 'local': 'fe80::2', 'scope': 'link'}]},
    {'ifname': 'virbr0', 'addr_info': [{'family': 'inet', 'local': '192.168.122.1', 'scope': 'global'}]},
    {'ifname': 'cni0', 'addr_info': [{'family': 'inet', 'local': '10.88.0.1', 'scope': 'global'}]},
]
EXCLUDED = ('docker0', 'br-', 'veth', 'virbr', 'cni', 'clab')


def certificate_addresses(routes, addresses):
    """A stand-in with the rule of EXPOSURE 3.2, so the check is driven by the same fixture the real one is."""
    uplinks = {route.get('dev') for route in routes if isinstance(route, dict) and route.get('dst') == 'default'}
    found = []
    for nic in addresses:
        name = nic.get('ifname', '')
        if name not in uplinks or name.startswith(EXCLUDED):
            continue
        found += [item['local'] for item in nic.get('addr_info', []) if item.get('scope') == 'global']
    return found


SETUP_TLS = SimpleNamespace(certificate_addresses=Mock(side_effect=certificate_addresses))


def not_after(days):
    when = datetime.now(timezone.utc) + timedelta(days=days)
    return when.strftime('%b %e %H:%M:%S %Y GMT')


def cert_output(days=300, fingerprint=FINGERPRINT):
    return f'notAfter={not_after(days)}\n{fingerprint}\n'


def san_output(*entries):
    return 'X509v3 Subject Alternative Name: \n    ' + ', '.join(entries) + '\n'


BASE_SANS = ('DNS:localhost', 'DNS:archtop', 'IP Address:' + UPLINK, 'IP Address:127.0.0.1', 'IP Address:0:0:0:0:0:0:0:1')
GOOD_SANS = BASE_SANS + ('DNS:manager.example.edu',)


def files(key_mode=0o640, names=False, cert_mode=0o644, key_gid=10001, kinds=None):
    records = {TLS: dict(kind='dir', uid=0, gid=0, mode=0o755),
               TLS + '/cert.pem': dict(kind='file', uid=0, gid=0, mode=cert_mode),
               TLS + '/key.pem': dict(kind='file', uid=0, gid=key_gid, mode=key_mode),
               TLS + '/mode': dict(kind='file', uid=0, gid=0, mode=0o644)}
    if names:
        records[TLS + '/names'] = dict(kind='file', uid=0, gid=0, mode=0o644)
    for path, kind in (kinds or {}).items():
        records[path] = dict(records[path], kind=kind)
    return records


UFW_ACTIVE = '''Status: active
Logging: on (low)
Default: deny (incoming), allow (outgoing), disabled (routed)
New profiles: skip

To                         Action      From
--                         ------      ----
22/tcp                     ALLOW IN    Anywhere
8443/tcp                   ALLOW IN    Anywhere
8081/tcp                   ALLOW IN    Anywhere
22/tcp (v6)                ALLOW IN    Anywhere (v6)
8443/tcp (v6)              ALLOW IN    Anywhere (v6)
8081/tcp (v6)              ALLOW IN    Anywhere (v6)
'''

SS_HEALTHY = '''LISTEN 0 128 0.0.0.0:22 0.0.0.0:* users:(("sshd",pid=900,fd=3))
LISTEN 0 128 [::]:22 [::]:* users:(("sshd",pid=900,fd=4))
LISTEN 0 2048 0.0.0.0:8443 0.0.0.0:* users:(("uvicorn",pid=1200,fd=8))
LISTEN 0 2048 0.0.0.0:8081 0.0.0.0:* users:(("python",pid=1300,fd=7))
LISTEN 0 4096 127.0.0.1:5001 0.0.0.0:* users:(("docker-proxy",pid=1400,fd=4))
LISTEN 0 4096 127.0.0.1:5801 0.0.0.0:* users:(("docker-proxy",pid=1500,fd=4))
LISTEN 0 4096 127.0.0.53%lo:53 0.0.0.0:* users:(("systemd-resolve",pid=600,fd=14))
LISTEN 0 4096 [::1]:631 [::]:* users:(("cupsd",pid=700,fd=7))
'''

SSHD_GOOD = 'port 22\npermitrootlogin no\nmaxauthtries 4\nlogingracetime 30\nforcecommand none\n'
SSHD_DEFAULTS = 'port 22\npermitrootlogin without-password\nmaxauthtries 6\nlogingracetime 120\nforcecommand none\n'

DOCKER_PS_HEALTHY = 'clab-backup-ui-http-redirect-1\t\nclab-sessions\t127.0.0.1:5801->5801/tcp\nclab-edgeshark\t127.0.0.1:5001->5001/tcp\n'


class Fixture:
    """What the fake VM answers; every field can be overridden per test."""

    def __init__(self, **overrides):
        self.files = files()
        self.mode = 'self-signed\n'
        self.names = ''
        self.cert = cert_output()
        self.sans = san_output(*GOOD_SANS)
        self.env = {'clab-backup-ui/.env': 'UI_ALLOWED_HOSTS=Manager.Example.EDU\nUI_PORT=8443\nCAPTURE_SESSION_TOKEN=' + PRIVATE + '\n'}
        self.routes4 = ROUTES_V4
        self.routes6 = []
        self.addresses = ADDRESSES
        self.ufw = UFW_ACTIVE
        self.ufw_installed = True
        self.ss = SS_HEALTHY
        self.sshd = SSHD_GOOD
        self.fail2ban = True
        self.docker_ps = DOCKER_PS_HEALTHY
        self.redirect_running = True
        self.setup_code = None            # None: absent; else (first line, age in seconds)
        self.setup_body = 'code=' + PRIVATE
        self.setup_test = None            # a Result that replaces the answer of the existence question (one that did not run)
        self.__dict__.update(overrides)

    def source_text(self, path):
        for suffix, text in self.env.items():
            if path.endswith(suffix):
                return check.Result(0, text)
        return check.Result(1)

    def __call__(self, args, **kwargs):
        head = args[0]
        if head == '/usr/bin/python3' and args[1:3] == ['-I', '-c'] and args[3] == exposure.SETUP_PROBE:
            if self.setup_test is not None:
                return self.setup_test
            return check.Result(0, 'present\n' if self.setup_code else 'absent\n')
        if head == '/usr/bin/python3':
            return check.Result(0, json.dumps([dict(path=path, **self.files[path]) if path in self.files
                                               else dict(path=path, kind='missing') for path in args[4:]]))
        if head == 'openssl':
            if '-enddate' in args:
                return check.Result(0, self.cert) if self.cert is not None else check.Result(1)
            if '-ext' in args:
                return check.Result(0, self.sans) if self.sans is not None else check.Result(1)
        if head == 'cat':
            path = args[1]
            if path == TLS + '/mode':
                return check.Result(0, self.mode)
            if path == TLS + '/names':
                return check.Result(0, self.names)
            return self.source_text(path)
        if head == 'ip':
            if args[1:] == ['-j', 'route', 'show', 'default']:
                return check.Result(0, json.dumps(self.routes4))
            if args[1:] == ['-6', '-j', 'route', 'show', 'default']:
                return check.Result(0, json.dumps(self.routes6))
            if args[1:] == ['-j', 'address']:
                return check.Result(0, json.dumps(self.addresses))
        if head == 'test':
            if args[1:] == ['-x', '/usr/sbin/ufw']:
                return check.Result(0 if self.ufw_installed else 1)
        if head == '/usr/sbin/ufw' or head == 'ufw':
            return check.Result(0, self.ufw)
        if head == 'ss':
            return check.Result(0, self.ss)
        if head == '/usr/sbin/sshd':
            return check.Result(0, self.sshd) if self.sshd is not None else check.Result(1)
        if head == 'systemctl':
            return check.Result(0 if self.fail2ban else 3, 'active\n' if self.fail2ban else 'inactive\n')
        if head == 'head' and args[-1] == SETUP_CODE:
            whole = self.setup_code[0] + '\n' + self.setup_body
            # Only the exact bounded read is honoured: any other argv gets the whole file back, so a wider read is
            # visible to the tests that assert the argv and to the ones that look for the code in the report.
            return check.Result(0, whole[:16] if args == ['head', '-c', '16', SETUP_CODE] else whole)
        if head == 'stat' and args[-1] == SETUP_CODE:
            return check.Result(0, str(int(time.time()) - self.setup_code[1]) + '\n')
        if head == 'docker':
            if 'ps' in args and '--format' in args:
                return check.Result(0, self.docker_ps)
            if 'compose' in args and 'ps' in args:
                return check.Result(0, 'b' * 64 + '\n' if self.redirect_running else '')
        return check.Result(reason='unexpected command: ' + ' '.join(args)[:80])


def head_router(redirect=(301, {'location': HTTPS + '/'}), listener=(200, HSTS), plain=(None, {})):
    def head(path, base=None):
        if base is None:
            return listener
        if base == REDIRECT:
            return redirect
        if base == PLAIN_ON_TLS_PORT:
            return plain
        return (None, {})
    return head


def context(fixture=None, head=None, **overrides):
    args = check.arguments([])
    ctx = check.Context(args, owner='archtop', privileged=True)
    ctx.version = VERSION
    ctx.container = 'a' * 64
    ctx.base_url = HTTPS
    ctx.tls_context = object()
    ctx.manager_command = list(COMMAND)
    fixture = fixture or Fixture()
    ctx.fixture = fixture
    ctx.run = Mock(side_effect=fixture)
    ctx.head = Mock(side_effect=head or head_router())
    ctx.http = Mock(side_effect=AssertionError('the exposure group asks the manager no HTTP question of its own'))
    ctx.probe = Mock(side_effect=AssertionError('the exposure group runs no manager probe'))
    ctx.module = Mock(side_effect=lambda name: {'setup_tls': SETUP_TLS}[name])
    for key, value in overrides.items():
        setattr(ctx, key, value)
    return ctx


def run_group(**kwargs):
    ctx = context(**kwargs)
    exposure.check_exposure(ctx)
    return ctx


def by_id(ctx, ident):
    return next(record for record in ctx.checks if record['id'] == ident)


def ids(ctx):
    return [record['id'] for record in ctx.checks]


def report(ctx):
    return check.render(check.summarize(ctx))


def head_pairs(ctx):
    pairs = []
    for call in ctx.head.call_args_list:
        base = call.kwargs.get('base') if 'base' in call.kwargs else (call.args[1] if len(call.args) > 1 else None)
        pairs.append((call.args[0], base))
    return pairs


ALL = ['tls.files', 'tls.cert', 'tls.names', 'tls.bind', 'tls.listener', 'http.redirect', 'http.hsts', 'firewall',
       'exposure.listeners', 'exposure.ports', 'signon.bootstrap', 'ssh.hardening', 'ssh.bruteforce']


class HealthyVmTests(unittest.TestCase):
    def test_a_healthy_vm_passes_every_check_and_asks_only_the_three_head_questions(self):
        ctx = run_group()
        self.assertEqual(ids(ctx), ALL)
        for ident in ALL:
            with self.subTest(ident=ident):
                self.assertEqual(by_id(ctx, ident)['status'], 'PASS', by_id(ctx, ident))
        self.assertEqual(head_pairs(ctx), [('/api/health', None), ('/', REDIRECT), ('/', PLAIN_ON_TLS_PORT)])
        ctx.http.assert_not_called()
        ctx.probe.assert_not_called()
        self.assertFalse(any(row['status'] in ('FAIL', 'WARN', 'SKIP') for row in ctx.checks))

    def test_no_check_changes_anything_or_reads_a_key(self):
        # A recovery is open, so the setup-code reads run too: every command of the group is in this list.
        for fixture in (Fixture(), Fixture(setup_code=('mode=recover', 5), mode='provided\n')):
            ctx = run_group(fixture=fixture)
            for call in ctx.run.call_args_list:
                argv = call.args[0]
                if argv[0] == '/usr/bin/python3':
                    self.assertEqual(argv[1:3], ['-I', '-c'], 'the one inspection script is the only command given the key path')
                    continue
                self.assertFalse([item for item in argv if 'key.pem' in item], 'no command but the inspection script names the key: ' + ' '.join(argv)[:80])
                self.assertNotIn(argv[0], ('rm', 'mv', 'cp', 'chmod', 'chown', 'tee', 'sed'))
                if argv[0] == 'ufw' or argv[0].endswith('/ufw'):
                    self.assertEqual(argv[1:], ['status', 'verbose'])
                if argv[0] == 'openssl':
                    self.assertEqual(argv[argv.index('-in') + 1], TLS + '/cert.pem', 'openssl is only ever given the certificate')

    def test_the_report_carries_no_private_value_of_the_environment_file(self):
        self.assertNotIn(PRIVATE, report(run_group()))


class CertificateTests(unittest.TestCase):
    def test_an_expired_certificate_fails_and_a_near_one_warns(self):
        expired = run_group(fixture=Fixture(cert=cert_output(-3)))
        self.assertEqual(by_id(expired, 'tls.cert')['status'], 'FAIL')
        self.assertIn('setup-tls.sh', by_id(expired, 'tls.cert')['fix'])
        soon = run_group(fixture=Fixture(cert=cert_output(20)))
        self.assertEqual(by_id(soon, 'tls.cert')['status'], 'WARN')
        self.assertIn('--renew', by_id(soon, 'tls.cert')['fix'])
        for days in (31, 200):
            self.assertEqual(by_id(run_group(fixture=Fixture(cert=cert_output(days))), 'tls.cert')['status'], 'PASS')

    def test_the_fingerprint_and_mode_appear_exactly_as_printed(self):
        ctx = run_group()
        detail = by_id(ctx, 'tls.cert')['detail']
        self.assertIn(FINGERPRINT, detail)
        self.assertIn('self-signed', detail)
        self.assertIn('notAfter=', detail)

    def test_an_unparsable_certificate_fails(self):
        for cert in (None, 'garbage\n', 'notAfter=not a date\n'):
            with self.subTest(cert=cert):
                ctx = run_group(fixture=Fixture(cert=cert))
                self.assertEqual(by_id(ctx, 'tls.cert')['status'], 'FAIL')

    def test_the_certificate_is_read_unprivileged_with_openssl_only(self):
        ctx = run_group()
        calls = [call for call in ctx.run.call_args_list if call.args[0][0] == 'openssl']
        self.assertEqual(len(calls), 2)
        for call in calls:
            self.assertFalse(call.kwargs.get('privileged', False))
            self.assertIn('x509', call.args[0])
            self.assertIn(TLS + '/cert.pem', call.args[0])

    def test_hsts_scope_is_an_info_only_in_provided_mode_right_after_the_certificate(self):
        provided = run_group(fixture=Fixture(mode='provided\n'))
        self.assertEqual(by_id(provided, 'tls.hsts-scope')['status'], 'INFO')
        self.assertEqual(ids(provided)[:3], ['tls.files', 'tls.cert', 'tls.hsts-scope'])
        self.assertIn('180 days', by_id(provided, 'tls.hsts-scope')['detail'])
        self.assertIn('IP address', by_id(provided, 'tls.hsts-scope')['detail'])
        self.assertNotIn('tls.hsts-scope', ids(run_group(fixture=Fixture(mode='self-signed\n'))))


class FileTests(unittest.TestCase):
    def test_a_world_readable_key_fails_and_no_key_material_reaches_the_report(self):
        fixture = Fixture(files=files(key_mode=0o644))
        for path, record in fixture.files.items():
            record['sha256'] = PRIVATE
        ctx = run_group(fixture=fixture)
        row = by_id(ctx, 'tls.files')
        self.assertEqual(row['status'], 'FAIL')
        self.assertIn('key.pem', row['detail'])
        self.assertIn('setup-tls.sh', row['fix'])
        self.assertNotIn(PRIVATE, report(ctx))
        self.assertNotIn(PRIVATE, json.dumps(check.summarize(ctx)))

    def test_every_deviation_of_section_3_3_fails(self):
        cases = {'a wider certificate mode': Fixture(files=files(cert_mode=0o666)),
                 'the key owned by the wrong group': Fixture(files=files(key_gid=0)),
                 'a symlinked certificate': Fixture(files=files(kinds={TLS + '/cert.pem': 'link'})),
                 'a symlinked directory': Fixture(files=files(kinds={TLS: 'link'})),
                 'a missing key': Fixture(files={k: v for k, v in files().items() if not k.endswith('key.pem')}),
                 'an unknown mode value': Fixture(mode='letsencrypt\n')}
        for name, fixture in cases.items():
            with self.subTest(name):
                self.assertEqual(by_id(run_group(fixture=fixture), 'tls.files')['status'], 'FAIL')

    def test_the_names_file_is_checked_when_it_exists(self):
        self.assertEqual(by_id(run_group(fixture=Fixture(files=files(names=True), names='manager.example.edu\n')), 'tls.files')['status'], 'PASS')
        bad = files(names=True)
        bad[TLS + '/names']['mode'] = 0o666
        self.assertEqual(by_id(run_group(fixture=Fixture(files=bad)), 'tls.files')['status'], 'FAIL')

    def test_the_inspection_script_never_reads_file_contents(self):
        ctx = run_group()
        script = next(call.args[0] for call in ctx.run.call_args_list if call.args[0][0] == '/usr/bin/python3')
        self.assertEqual(script[1:3], ['-I', '-c'])
        self.assertNotIn('read_bytes', script[3])
        self.assertNotIn('hashlib', script[3])
        self.assertNotIn('open(', script[3])


class NamesTests(unittest.TestCase):
    def test_a_new_address_of_the_uplink_missing_from_the_sans_warns_and_names_it(self):
        addresses = [dict(nic) for nic in ADDRESSES]
        addresses[1] = dict(addresses[1], addr_info=addresses[1]['addr_info'] + [{'family': 'inet', 'local': '198.51.100.7', 'scope': 'global'}])
        ctx = run_group(fixture=Fixture(addresses=addresses))
        row = by_id(ctx, 'tls.names')
        self.assertEqual(row['status'], 'WARN')
        self.assertIn('198.51.100.7', row['detail'])
        self.assertNotIn(UPLINK, row['detail'])
        self.assertIn('setup-tls.sh', row['fix'])

    def test_bridge_and_link_local_addresses_are_never_required_or_named(self):
        ctx = run_group()
        self.assertEqual(by_id(ctx, 'tls.names')['status'], 'PASS')
        text = report(ctx) + json.dumps(check.summarize(ctx))
        for private in (DOCKER0, '172.20.0.1', '192.168.122.1', '10.88.0.1', 'fe80::1', 'fe80::2'):
            self.assertNotIn(private, text)

    def test_the_rule_is_setup_tls_certificate_addresses_fed_the_three_ip_documents(self):
        SETUP_TLS.certificate_addresses.reset_mock()
        v6 = [{'dst': 'default', 'gateway': 'fe80::1', 'dev': 'eth0'}]
        run_group(fixture=Fixture(routes6=v6))
        routes, addresses = SETUP_TLS.certificate_addresses.call_args.args
        self.assertEqual(routes, ROUTES_V4 + v6)
        self.assertEqual(addresses, ADDRESSES)

    def test_allowed_host_names_and_the_names_file_must_be_sans_too(self):
        fixture = Fixture(env={'clab-backup-ui/.env': 'UI_ALLOWED_HOSTS=Manager.Example.EDU,lab.example.edu\n'},
                          files=files(names=True), names='198.51.100.9\nother.example.edu\n',
                          sans=san_output(*BASE_SANS))
        row = by_id(run_group(fixture=fixture), 'tls.names')
        self.assertEqual(row['status'], 'WARN')
        for name in ('manager.example.edu', 'lab.example.edu', '198.51.100.9', 'other.example.edu'):
            self.assertIn(name, row['detail'])
        sans = BASE_SANS + ('DNS:manager.example.edu', 'DNS:lab.example.edu', 'IP Address:198.51.100.9', 'DNS:OTHER.example.edu')
        fixture.sans = san_output(*sans)
        self.assertEqual(by_id(run_group(fixture=fixture), 'tls.names')['status'], 'PASS')

    def test_ipv6_sans_compare_by_address_not_by_spelling(self):
        fixture = Fixture(addresses=[dict(ADDRESSES[1], addr_info=[{'family': 'inet', 'local': UPLINK, 'scope': 'global'},
                                                                     {'family': 'inet6', 'local': '2001:db8::10', 'scope': 'global'}])] + ADDRESSES[2:],
                          sans=san_output(*GOOD_SANS, 'IP Address:2001:DB8:0:0:0:0:0:10'))
        self.assertEqual(by_id(run_group(fixture=fixture), 'tls.names')['status'], 'PASS')

    def test_an_unreadable_certificate_skips_instead_of_passing(self):
        self.assertEqual(by_id(run_group(fixture=Fixture(sans=None)), 'tls.names')['status'], 'SKIP')


class BindListenerAndRedirectTests(unittest.TestCase):
    def test_a_manager_without_tls_arguments_fails_and_an_old_compose_file_warns(self):
        plain = [item for item in COMMAND if item not in ('--ssl-certfile', '/tls/cert.pem', '--ssl-keyfile', '/tls/key.pem')]
        ctx = run_group(manager_command=plain)
        row = by_id(ctx, 'tls.bind')
        self.assertEqual(row['status'], 'FAIL')
        self.assertIn('plain HTTP', row['detail'])
        self.assertIn('start-manager.sh', row['fix'])
        old = [item for item in COMMAND if item != '--no-proxy-headers']
        self.assertEqual(by_id(run_group(manager_command=old), 'tls.bind')['status'], 'WARN')
        self.assertIn('8443', by_id(run_group(), 'tls.bind')['detail'])

    def test_a_listener_that_does_not_answer_the_pinned_certificate_fails(self):
        for answer in ((None, {}), (503, {})):
            with self.subTest(answer=answer):
                ctx = run_group(head=head_router(listener=answer))
                row = by_id(ctx, 'tls.listener')
                self.assertEqual(row['status'], 'FAIL')
                self.assertIn('setup-tls.sh --show', row['fix'])
                self.assertEqual(by_id(ctx, 'http.hsts')['status'], 'SKIP')

    def test_the_redirect_port_serving_a_page_fails(self):
        ctx = run_group(head=head_router(redirect=(200, {})))
        self.assertEqual(by_id(ctx, 'http.redirect')['status'], 'FAIL')
        self.assertIn('plain HTTP', by_id(ctx, 'http.redirect')['detail'])

    def test_plain_http_served_by_the_tls_port_fails(self):
        ctx = run_group(head=head_router(plain=(200, {})))
        self.assertEqual(by_id(ctx, 'http.redirect')['status'], 'FAIL')
        self.assertIn(str(8443), by_id(ctx, 'http.redirect')['detail'])

    def test_a_gated_manager_on_plain_http_fails_whatever_status_it_answers(self):
        # The sign-on gate answers `/` with 302 /login, so a 200 never comes back from a manager that has it; the sign-in form
        # and the passwords typed into it would still travel in cleartext.
        for status in (302, 303, 307, 401, 403, 404, 500):
            with self.subTest(status=status, port='TLS'):
                row = by_id(run_group(head=head_router(plain=(status, {'location': '/login'}))), 'http.redirect')
                self.assertEqual(row['status'], 'FAIL', row)
                self.assertIn('plain HTTP', row['detail'])
                self.assertIn('8443', row['detail'])
                self.assertIn('start-manager.sh', row['fix'])
        for answer in ((302, {'location': '/login'}), (302, {'location': '/login?next=/'}), (301, {'location': 'http://127.0.0.1:8081/'}),
                       (307, {'location': 'http://manager.example/'})):
            with self.subTest(answer=answer, port='redirect'):
                row = by_id(run_group(head=head_router(redirect=answer)), 'http.redirect')
                self.assertEqual(row['status'], 'FAIL', row)
                self.assertIn('plain HTTP', row['detail'])
                self.assertIn('8081', row['detail'])
                self.assertNotIn('/login', row['detail'], 'the Location value is not echoed')

    def test_a_missing_redirect_container_or_a_wrong_answer_warns(self):
        stopped = Fixture(redirect_running=False)
        ctx = run_group(fixture=stopped, head=head_router(redirect=(None, {})))
        self.assertEqual(by_id(ctx, 'http.redirect')['status'], 'WARN')
        self.assertIn('not running', by_id(ctx, 'http.redirect')['detail'])
        self.assertIn('start-manager.sh', by_id(ctx, 'http.redirect')['fix'])
        for answer in ((302, {'location': HTTPS + '/'}), (301, {'location': 'https://evil.example/'}), (301, {}), (404, {})):
            with self.subTest(answer=answer):
                self.assertEqual(by_id(run_group(head=head_router(redirect=answer)), 'http.redirect')['status'], 'WARN')

    def test_a_disabled_redirect_is_an_info_and_asks_only_two_questions(self):
        ctx = run_group(fixture=Fixture(env={'clab-backup-ui/.env': 'UI_HTTP_PORT=0\n'}))
        self.assertEqual(by_id(ctx, 'http.redirect')['status'], 'INFO')
        self.assertIn('disabled', by_id(ctx, 'http.redirect')['detail'])
        self.assertEqual(head_pairs(ctx), [('/api/health', None), ('/', PLAIN_ON_TLS_PORT)])

    def test_the_redirect_location_omits_port_443(self):
        command = [item if item != '8443' else '443' for item in COMMAND]
        ctx = run_group(manager_command=command, base_url='https://127.0.0.1:443',
                        head=lambda path, base=None: (301, {'location': 'https://127.0.0.1/'}) if base == REDIRECT else (200, HSTS) if base is None else (None, {}))
        self.assertEqual(by_id(ctx, 'http.redirect')['status'], 'PASS')

    def test_hsts_header_must_carry_the_documented_value(self):
        for headers in ({}, {'strict-transport-security': 'max-age=60'}):
            with self.subTest(headers=headers):
                ctx = run_group(head=head_router(listener=(200, headers)))
                self.assertEqual(by_id(ctx, 'http.hsts')['status'], 'WARN')
                self.assertIn('start-manager.sh', by_id(ctx, 'http.hsts')['fix'])
                self.assertEqual(by_id(ctx, 'tls.listener')['status'], 'PASS')


class FirewallAndListenerTests(unittest.TestCase):
    def test_active_default_deny_with_every_needed_port_passes(self):
        row = by_id(run_group(), 'firewall')
        self.assertEqual(row['status'], 'PASS')
        self.assertIn('8443', row['detail'])

    def test_inactive_missing_port_and_open_default_warn_naming_the_cause(self):
        inactive = run_group(fixture=Fixture(ufw='Status: inactive\n'))
        self.assertEqual(by_id(inactive, 'firewall')['status'], 'WARN')
        self.assertIn('setup-firewall.sh', by_id(inactive, 'firewall')['fix'])
        self.assertIn('security group', by_id(inactive, 'firewall')['detail'])
        missing = run_group(fixture=Fixture(ufw=UFW_ACTIVE.replace('8081/tcp                   ALLOW IN    Anywhere\n', '').replace('8081/tcp (v6)              ALLOW IN    Anywhere (v6)\n', '')))
        self.assertEqual(by_id(missing, 'firewall')['status'], 'WARN')
        self.assertIn('8081', by_id(missing, 'firewall')['detail'])
        permissive = run_group(fixture=Fixture(ufw=UFW_ACTIVE.replace('deny (incoming)', 'allow (incoming)')))
        self.assertEqual(by_id(permissive, 'firewall')['status'], 'WARN')

    def test_a_disabled_redirect_port_is_not_required_and_ranges_and_lists_count(self):
        ufw = UFW_ACTIVE.replace('8081/tcp', '8000:8100/tcp').replace('8443/tcp ', '80,8443/tcp ')
        self.assertEqual(by_id(run_group(fixture=Fixture(ufw=ufw)), 'firewall')['status'], 'PASS')
        no_redirect = Fixture(env={'clab-backup-ui/.env': 'UI_HTTP_PORT=0\n'}, ufw=UFW_ACTIVE.replace('8081/tcp                   ALLOW IN    Anywhere\n', ''))
        self.assertEqual(by_id(run_group(fixture=no_redirect), 'firewall')['status'], 'PASS')

    def test_a_blanket_allow_is_not_a_closed_door(self):
        blanket = {'every port from anywhere': 'Anywhere                   ALLOW IN    Anywhere\n',
                   'every port from anywhere, IPv6': 'Anywhere (v6)              ALLOW IN    Anywhere (v6)\n',
                   'every port, tcp only': 'Anywhere/tcp               ALLOW IN    Anywhere\n',
                   'the whole tcp range': '1:65535/tcp                ALLOW IN    Anywhere\n',
                   'a very wide tcp range': '2000:9000/tcp              ALLOW IN    Anywhere\n',
                   'every port on the uplink (ufw allow in on eth0)': 'Anywhere on eth0           ALLOW IN    Anywhere\n',
                   'every port on the uplink, IPv6': 'Anywhere (v6) on eth0      ALLOW IN    Anywhere (v6)\n',
                   'every port on the uplink, LIMIT': 'Anywhere on eth0           LIMIT IN    Anywhere\n',
                   'the whole tcp range on the uplink': '1:65535/tcp on eth0        ALLOW IN    Anywhere\n',
                   'a very wide tcp range on the uplink': '2000:9000/tcp on eth0      ALLOW IN    Anywhere\n'}
        for name, rule in blanket.items():
            with self.subTest(name):
                row = by_id(run_group(fixture=Fixture(ufw=UFW_ACTIVE + rule)), 'firewall')
                self.assertEqual(row['status'], 'WARN', row)
                self.assertIn('from anywhere', row['detail'])
                self.assertIn('setup-firewall.sh', row['fix'])
                self.assertIn('security group', row['detail'])
        only_blanket = UFW_ACTIVE.split('To ')[0] + 'To                         Action      From\n--                         ------      ----\nAnywhere                   ALLOW IN    Anywhere\n'
        row = by_id(run_group(fixture=Fixture(ufw=only_blanket)), 'firewall')
        self.assertEqual(row['status'], 'WARN')
        self.assertNotIn('not allowed', row['detail'], 'a blanket rule does cover the needed ports; the finding is the blanket')

    def test_a_blanket_allow_on_the_uplink_names_the_interface(self):
        row = by_id(run_group(fixture=Fixture(ufw=UFW_ACTIVE + 'Anywhere on eth0           ALLOW IN    Anywhere\n')), 'firewall')
        self.assertIn('every port on eth0', row['detail'])

    def test_a_blanket_allow_on_loopback_is_not_an_opening(self):
        self.assertEqual(by_id(run_group(fixture=Fixture(ufw=UFW_ACTIVE + 'Anywhere on lo             ALLOW IN    Anywhere\n')), 'firewall')['status'], 'PASS')

    def test_a_needed_port_allowed_on_an_interface_or_through_an_app_profile_is_allowed(self):
        bound = (UFW_ACTIVE.split('22/tcp ')[0] +
                 '22/tcp (OpenSSH)           ALLOW IN    Anywhere\n'
                 '22/tcp (OpenSSH (v6))      ALLOW IN    Anywhere (v6)\n'
                 '8443/tcp on eth0           ALLOW IN    Anywhere\n'
                 '8081/tcp (v6) on eth0      ALLOW IN    Anywhere (v6)\n')
        row = by_id(run_group(fixture=Fixture(ufw=bound)), 'firewall')
        self.assertEqual(row['status'], 'PASS', row)
        self.assertNotIn('not allowed', row['detail'])

    def test_an_outbound_or_routed_rule_is_not_an_inbound_allow(self):
        header = UFW_ACTIVE.split('22/tcp ')[0]
        for direction in ('OUT', 'FWD'):
            with self.subTest(direction):
                only_out = header + (f'22/tcp                     ALLOW IN    Anywhere\n8443/tcp                   ALLOW IN    Anywhere\n'
                                     f'8081/tcp                   ALLOW {direction.ljust(4)}  Anywhere\n')
                row = by_id(run_group(fixture=Fixture(ufw=only_out)), 'firewall')
                self.assertEqual(row['status'], 'WARN', row)
                self.assertIn('not allowed: 8081', row['detail'])
                wide = by_id(run_group(fixture=Fixture(ufw=UFW_ACTIVE + f'Anywhere                   ALLOW {direction.ljust(4)}  Anywhere\n')), 'firewall')
                self.assertEqual(wide['status'], 'PASS', wide)

    def test_rules_limited_to_a_source_or_to_other_single_ports_do_not_warn(self):
        quiet = ('5432/tcp                   ALLOW IN    Anywhere\n'
                 'Anywhere                   ALLOW IN    10.0.0.0/8\n'
                 '1:65535/tcp                ALLOW IN    203.0.113.0/24\n'
                 '1:65535/udp                ALLOW IN    Anywhere\n')
        self.assertEqual(by_id(run_group(fixture=Fixture(ufw=UFW_ACTIVE + quiet)), 'firewall')['status'], 'PASS')

    def test_ufw_not_installed_fails(self):
        row = by_id(run_group(fixture=Fixture(ufw_installed=False)), 'firewall')
        self.assertEqual(row['status'], 'FAIL')
        self.assertIn('setup-firewall.sh', row['fix'])

    def test_an_unexpected_public_listener_warns_with_port_and_process(self):
        ss = SS_HEALTHY + 'LISTEN 0 128 0.0.0.0:6379 0.0.0.0:* users:(("redis-server",pid=1700,fd=6))\n'
        row = by_id(run_group(fixture=Fixture(ss=ss)), 'exposure.listeners')
        self.assertEqual(row['status'], 'WARN')
        self.assertIn('6379', row['detail'])
        self.assertIn('redis-server', row['detail'])
        self.assertIn('Close or firewall', row['fix'])

    def test_the_capture_stack_on_a_public_address_fails(self):
        for port in (5001, 5801):
            with self.subTest(port=port):
                ss = SS_HEALTHY.replace(f'127.0.0.1:{port} ', f'0.0.0.0:{port} ')
                row = by_id(run_group(fixture=Fixture(ss=ss)), 'exposure.listeners')
                self.assertEqual(row['status'], 'FAIL')
                self.assertIn(str(port), row['detail'])
                self.assertIn('127.0.0.1', row['fix'])

    def test_a_published_container_port_warns_and_loopback_bindings_pass(self):
        ps = DOCKER_PS_HEALTHY + 'clab-lab-srv1\t0.0.0.0:8080->80/tcp, [::]:8080->80/tcp\n'
        row = by_id(run_group(fixture=Fixture(docker_ps=ps)), 'exposure.ports')
        self.assertEqual(row['status'], 'WARN')
        self.assertIn('clab-lab-srv1', row['detail'])
        self.assertIn('8080', row['detail'])
        self.assertIn('bypass ufw', row['fix'])
        self.assertNotIn('clab-sessions', row['detail'])

    def test_a_non_default_ssh_port_is_an_allowed_listener(self):
        ss = SS_HEALTHY.replace(':22 ', ':2222 ')
        ufw = UFW_ACTIVE.replace('22/tcp', '2222/tcp')
        ctx = run_group(fixture=Fixture(ss=ss, ufw=ufw, sshd=SSHD_GOOD.replace('port 22', 'port 2222')))
        self.assertEqual(by_id(ctx, 'exposure.listeners')['status'], 'PASS')
        self.assertEqual(by_id(ctx, 'firewall')['status'], 'PASS')


class BootstrapTests(unittest.TestCase):
    def test_no_setup_code_file_passes(self):
        self.assertEqual(by_id(run_group(), 'signon.bootstrap')['status'], 'PASS')

    def test_setup_mode_warns_and_the_code_never_reaches_the_report(self):
        ctx = run_group(fixture=Fixture(setup_code=('mode=setup', 5)))
        row = by_id(ctx, 'signon.bootstrap')
        self.assertEqual(row['status'], 'WARN')
        self.assertIn('Setup not completed: no administrator exists', row['detail'])
        self.assertIn('sudo cat /srv/containerlab-node-manager/data/setup-code', row['fix'])
        self.assertIn('/setup', row['fix'])
        self.assertNotIn(PRIVATE, report(ctx))
        self.assertNotIn(PRIVATE, json.dumps(check.summarize(ctx)))

    def test_a_recent_recovery_is_open_and_names_the_query_and_the_script(self):
        ctx = run_group(fixture=Fixture(setup_code=('mode=recover', 300)))
        row = by_id(ctx, 'signon.bootstrap')
        self.assertEqual(row['status'], 'WARN')
        self.assertIn('A recovery is open', row['detail'])
        self.assertIn('?recover=1', row['fix'])
        self.assertIn('manager-recover-admin.sh', row['fix'])
        self.assertNotIn(PRIVATE, report(ctx))

    def test_an_expired_recovery_names_the_script_and_not_the_page(self):
        ctx = run_group(fixture=Fixture(setup_code=('mode=recover', 16 * 60)))
        row = by_id(ctx, 'signon.bootstrap')
        self.assertEqual(row['status'], 'WARN')
        self.assertIn('A recovery code expired unused', row['detail'])
        self.assertIn('manager-recover-admin.sh', row['fix'])
        self.assertNotIn('?recover=1', row['fix'])
        self.assertNotIn(PRIVATE, report(ctx))

    def test_the_boundary_is_fifteen_minutes(self):
        self.assertIn('is open', by_id(run_group(fixture=Fixture(setup_code=('mode=recover', 899))), 'signon.bootstrap')['detail'])
        self.assertIn('expired', by_id(run_group(fixture=Fixture(setup_code=('mode=recover', 900))), 'signon.bootstrap')['detail'])

    def test_an_unrecognised_first_line_warns_without_echoing_it(self):
        ctx = run_group(fixture=Fixture(setup_code=('mode=' + PRIVATE, 5)))
        self.assertEqual(by_id(ctx, 'signon.bootstrap')['status'], 'WARN')
        self.assertNotIn(PRIVATE, report(ctx))

    def test_only_the_first_sixteen_bytes_and_the_mtime_are_read(self):
        ctx = run_group(fixture=Fixture(setup_code=('mode=recover', 5)))
        reads = [call.args[0] for call in ctx.run.call_args_list if SETUP_CODE in call.args[0]]
        self.assertEqual(reads, [['/usr/bin/python3', '-I', '-c', exposure.SETUP_PROBE, SETUP_CODE], ['head', '-c', '16', SETUP_CODE], ['stat', '-c', '%Y', SETUP_CODE]],
                         'the existence probe (lstat only), exactly sixteen bytes and the modification time: nothing else touches the file')
        self.assertTrue(all(call.kwargs.get('privileged') for call in ctx.run.call_args_list if SETUP_CODE in call.args[0]))

    def test_a_wider_read_would_put_the_code_in_the_report_which_the_fixture_makes_visible(self):
        # The guard of the test above: the fixture hands the whole file to any head argv but the exact one.
        fixture = Fixture(setup_code=('mode=recover', 5))
        whole = fixture(['head', '-n', '2', SETUP_CODE]).stdout
        self.assertIn(PRIVATE, whole)
        self.assertNotIn(PRIVATE, fixture(['head', '-c', '16', SETUP_CODE]).stdout)

    def test_a_question_that_did_not_run_is_a_skip_never_a_pass(self):
        cases = {'the report deadline expired in the group': check.Result(reason='report time limit reached'),
                 'sudo refused or timed out': check.Result(1, '', stderr='sudo: a password is required'),
                 'the root timeout killed it': check.Result(124),
                 'administrator access was unavailable': check.Result(reason='administrator access unavailable'),
                 'the command could not run': check.Result(reason='command unavailable or could not run')}
        for name, answer in cases.items():
            with self.subTest(name):
                ctx = run_group(fixture=Fixture(setup_code=('mode=setup', 5), setup_test=answer))
                row = by_id(ctx, 'signon.bootstrap')
                self.assertEqual(row['status'], 'SKIP', row)
                self.assertNotIn('No setup or recovery code is waiting', row['detail'])
                self.assertIn('could not be checked', row['detail'])
                self.assertIn('check-install.sh', row['fix'])
                self.assertNotIn(PRIVATE, report(ctx))

    def test_the_answer_is_on_stdout_so_a_sudo_warning_on_stderr_does_not_hide_it(self):
        # `sudo: unable to resolve host NAME` is printed on every call of a renamed cloud VM; `test -e` could not tell it from a refusal.
        noisy = 'sudo: unable to resolve host vm1: Name or service not known\n'
        ctx = run_group(fixture=Fixture(setup_test=check.Result(0, 'absent\n', stderr=noisy)))
        self.assertEqual(by_id(ctx, 'signon.bootstrap')['status'], 'PASS')
        question = next(call for call in ctx.run.call_args_list if SETUP_CODE in call.args[0])
        self.assertEqual(question.args[0][:3], ['/usr/bin/python3', '-I', '-c'], 'no `test -e`: its exit status is shared with a sudo refusal')
        self.assertTrue(question.kwargs.get('privileged'))
        waiting = run_group(fixture=Fixture(setup_code=('mode=setup', 5), setup_test=check.Result(0, 'present\n', stderr=noisy)))
        self.assertEqual(by_id(waiting, 'signon.bootstrap')['status'], 'WARN')

    def test_only_the_exact_word_absent_from_a_successful_probe_means_absent(self):
        for name, answer in {'empty output': check.Result(0, ''), 'another word': check.Result(0, 'maybe\n'),
                             'absent with a failing exit': check.Result(1, 'absent\n'), 'a sudo refusal': check.Result(1, '', stderr='sudo: a password is required\n'),
                             'absent plus noise': check.Result(0, 'absent\nextra\n')}.items():
            with self.subTest(name):
                row = by_id(run_group(fixture=Fixture(setup_code=('mode=setup', 5), setup_test=answer)), 'signon.bootstrap')
                self.assertEqual(row['status'], 'SKIP', row)

    def test_the_probe_reports_absent_only_for_a_missing_file(self):
        import tempfile
        import subprocess
        with tempfile.TemporaryDirectory() as directory:
            target = str(Path(directory) / 'setup-code')
            def ask(path):
                return subprocess.run([sys.executable, '-I', '-c', exposure.SETUP_PROBE, path], capture_output=True, text=True)
            self.assertEqual((ask(target).returncode, ask(target).stdout), (0, 'absent\n'))
            Path(target).write_text('mode=setup\n')
            self.assertEqual((ask(target).returncode, ask(target).stdout), (0, 'present\n'))
            blocker = str(Path(directory) / 'setup-code' / 'below')  # a parent that is a file: not "missing", so no "absent"
            self.assertNotEqual(ask(blocker).stdout, 'absent\n')


class SshTests(unittest.TestCase):
    def test_defaults_warn_and_name_which_directive(self):
        row = by_id(run_group(fixture=Fixture(sshd=SSHD_DEFAULTS)), 'ssh.hardening')
        self.assertEqual(row['status'], 'WARN')
        for word in ('permitrootlogin', 'maxauthtries', 'logingracetime'):
            self.assertIn(word, row['detail'])
        self.assertIn('setup-ssh-hardening.sh', row['fix'])
        partly = by_id(run_group(fixture=Fixture(sshd=SSHD_GOOD.replace('maxauthtries 4', 'maxauthtries 6'))), 'ssh.hardening')
        self.assertEqual(partly['status'], 'WARN')
        self.assertIn('maxauthtries', partly['detail'])
        self.assertNotIn('permitrootlogin', partly['detail'])

    def test_sshd_that_cannot_be_read_skips(self):
        self.assertEqual(by_id(run_group(fixture=Fixture(sshd=None)), 'ssh.hardening')['status'], 'SKIP')

    def test_fail2ban_absent_warns_with_the_documented_install_line(self):
        row = by_id(run_group(fixture=Fixture(fail2ban=False)), 'ssh.bruteforce')
        self.assertEqual(row['status'], 'WARN')
        self.assertIn('Internet-facing', row['detail'])
        self.assertIn('INSTALL.md', row['detail'])
        self.assertEqual(row['fix'], 'sudo apt-get install -y fail2ban')


class DockerAndCertificateSkipTests(unittest.TestCase):
    def test_without_docker_the_container_checks_skip_with_the_docker_fix_and_never_pass(self):
        ctx = run_group(container='', base_url='', manager_command=None, tls_context=None)
        for ident in ('tls.bind', 'tls.listener', 'http.hsts', 'exposure.ports'):
            with self.subTest(ident=ident):
                row = by_id(ctx, ident)
                self.assertEqual(row['status'], 'SKIP')
                self.assertIn('Docker', row['detail'] + row['fix'])
        self.assertNotIn(('/api/health', None), head_pairs(ctx))
        self.assertTrue(any(row['status'] == 'PASS' for row in ctx.checks), 'host-only checks still run')
        self.assertEqual([row['id'] for row in ctx.checks if row['status'] == 'PASS'].count('tls.bind'), 0)

    def test_an_unreadable_certificate_skips_the_pinned_requests_with_the_tls_files_fix(self):
        ctx = run_group(tls_context=None, base_url='')
        for ident in ('tls.listener', 'http.hsts'):
            row = by_id(ctx, ident)
            self.assertEqual(row['status'], 'SKIP')
            self.assertIn('The installed certificate could not be read, so the TLS listener was not probed.', row['detail'])
            self.assertIn('setup-tls.sh', row['fix'])
        self.assertNotIn(('/api/health', None), head_pairs(ctx))

    def test_a_stopped_manager_without_an_address_skips_the_listener_checks(self):
        # As production leaves the context: the certificate is pinned (inspect_manager does it first), the container
        # exists but does not run, and no address was built. The cause named is the missing address, not the certificate.
        ctx = run_group(base_url='', manager_running=False)
        self.assertIsNotNone(ctx.tls_context)
        for ident in ('tls.listener', 'http.hsts'):
            row = by_id(ctx, ident)
            self.assertEqual(row['status'], 'SKIP')
            self.assertNotIn('certificate could not be read', row['detail'])
            self.assertIn('start-manager.sh', row['fix'])
        self.assertIn('no usable HTTPS address', by_id(ctx, 'tls.listener')['detail'])
        self.assertNotIn(('/api/health', None), head_pairs(ctx))


class FormatTests(unittest.TestCase):
    def test_a_run_group_is_report_safe_and_json_serialisable(self):
        ctx = run_group(fixture=Fixture(setup_code=('mode=setup', 1)))
        json.dumps(check.summarize(ctx))
        for row in ctx.checks:
            self.assertTrue(row['title'])
            self.assertIn(row['status'], check.STATUSES)

    def test_a_check_that_raises_is_not_hidden_it_becomes_that_checks_own_fail(self):
        # Rewritten from "the exception escapes to main": the claim that a crash is never hidden stays, but it
        # now costs only the crashing check, and the exception text (which may carry a command's output) is not shown.
        ctx = context()
        ctx.run = Mock(side_effect=RuntimeError(PRIVATE))
        exposure.check_exposure(ctx)
        self.assertEqual(ids(ctx), ['exposure.settings'] + ALL)
        for ident in ('exposure.settings', 'tls.files', 'tls.cert', 'firewall', 'exposure.listeners', 'signon.bootstrap', 'ssh.bruteforce'):
            with self.subTest(ident=ident):
                self.assertEqual(by_id(ctx, ident)['status'], 'FAIL')
                self.assertIn('RuntimeError', by_id(ctx, ident)['detail'])
        self.assertEqual(by_id(ctx, 'ssh.hardening')['status'], 'SKIP', 'sshd -T raising is the same as sshd -T not answering')
        self.assertNotIn(PRIVATE, report(ctx))
        self.assertNotIn(PRIVATE, json.dumps(check.summarize(ctx)))

    def test_one_failing_sub_check_leaves_every_other_check_in_the_report(self):
        for crashing in ('check_files', 'check_certificate', 'check_bind', 'check_listener', 'check_redirect', 'check_hsts',
                         'check_firewall', 'check_listeners', 'check_ports', 'check_bootstrap', 'check_ssh'):
            with self.subTest(crashing=crashing), unittest.mock.patch.object(exposure, crashing, Mock(side_effect=RuntimeError(PRIVATE))):
                ctx = run_group()
                self.assertEqual(sorted(ids(ctx)), sorted(ALL), 'every check of the group is in the report')
                failed = [row for row in ctx.checks if row['status'] == 'FAIL']
                self.assertEqual(len(failed), 1 if crashing != 'check_ssh' else 2, failed)
                self.assertTrue(all('RuntimeError' in row['detail'] for row in failed))
                self.assertNotIn(PRIVATE, report(ctx))

    def test_unreadable_settings_fall_back_to_the_defaults_and_say_so(self):
        with unittest.mock.patch.object(exposure, 'settings', Mock(side_effect=RuntimeError(PRIVATE))):
            ctx = run_group()
        self.assertEqual(by_id(ctx, 'exposure.settings')['status'], 'FAIL')
        self.assertEqual(sorted(i for i in ids(ctx) if i != 'exposure.settings'), sorted(ALL))
        self.assertNotIn(PRIVATE, report(ctx))

    def test_an_sshd_query_that_raises_is_a_skip_of_the_hardening_check(self):
        with unittest.mock.patch.object(exposure, 'sshd_facts', Mock(side_effect=RuntimeError(PRIVATE))):
            ctx = run_group()
        self.assertEqual(sorted(ids(ctx)), sorted(ALL))
        self.assertEqual(by_id(ctx, 'ssh.hardening')['status'], 'SKIP')
        self.assertEqual(by_id(ctx, 'firewall')['status'], 'PASS', 'port 22 is assumed, as when sshd -T cannot run')

    def test_the_real_module_loader_failing_costs_only_the_names_check(self):
        # deploy/setup_tls.py does not exist before S4 is integrated; its import can also fail on a damaged checkout.
        for failure in (FileNotFoundError('setup_tls.py'), ImportError('allowed_hosts'), SyntaxError('bad')):
            with self.subTest(failure=type(failure).__name__):
                ctx = context(module=Mock(side_effect=failure))
                exposure.check_exposure(ctx)
                self.assertEqual(ids(ctx), ALL)
                row = by_id(ctx, 'tls.names')
                self.assertEqual(row['status'], 'SKIP')
                self.assertIn('could not be loaded', row['detail'])
                self.assertIn('setup-tls.sh', row['fix'])
                for ident in ALL:
                    if ident != 'tls.names':
                        self.assertEqual(by_id(ctx, ident)['status'], 'PASS', ident)

    def test_the_real_checkout_loader_is_isolated_too(self):
        ctx = context(module=check.module)  # the production loader: it fails here until S4 adds deploy/setup_tls.py
        exposure.check_exposure(ctx)
        self.assertEqual(ids(ctx), ALL)
        self.assertIn(by_id(ctx, 'tls.names')['status'], ('PASS', 'WARN', 'SKIP'))
        self.assertEqual(by_id(ctx, 'tls.listener')['status'], 'PASS')
        self.assertEqual(by_id(ctx, 'ssh.bruteforce')['status'], 'PASS')


if __name__ == '__main__':
    unittest.main()
