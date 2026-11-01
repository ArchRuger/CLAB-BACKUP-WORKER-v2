"""deploy/setup_tls.py and deploy/setup-tls.sh: the manager's TLS certificate (docs/sign-on/EXPOSURE.md 3).

Standard library only: CI runs this file with the system python3 before any virtual environment
exists. `openssl` is real (Ubuntu ships it); `ip`, `docker` and the manager's recreate script are
fakes. The shell suite drives a copy of the actual script with only its root guard neutralised and
`/usr/bin/python3` replaced by a wrapper on PATH that points setup_tls.py at a temporary tls
directory, so the option parsing and the recreate decision under test are the shipped ones.

The `ip -j` fixture below (IP_ADDRESS, IP_ROUTE4, IP_ROUTE6) is shared with test_check_exposure.py
(EXPOSURE.md 6.3 case 3): the default-route interface's global addresses are certificate addresses;
docker0, br-*, veth*, virbr*, cni*, clab*, loopback and link-local addresses never are.
"""
import importlib.util
import ipaddress
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / 'deploy/setup-tls.sh'
ROOT_GUARD = "[[ $EUID -eq 0 ]] || { echo 'Run with sudo.' >&2; exit 1; }"
PYTHON_CALL = '/usr/bin/python3 "$script_dir/setup_tls.py"'

spec = importlib.util.spec_from_file_location('setup_tls', ROOT / 'deploy/setup_tls.py')
setup_tls = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = setup_tls
spec.loader.exec_module(setup_tls)


def addr(family, local, scope='global', prefixlen=24):
    return {'family': family, 'local': local, 'prefixlen': prefixlen, 'scope': scope,
            'valid_life_time': 4294967295, 'preferred_life_time': 4294967295}


def interface(index, name, *addresses):
    return {'ifindex': index, 'ifname': name, 'flags': ['BROADCAST', 'MULTICAST', 'UP', 'LOWER_UP'], 'mtu': 1500,
            'operstate': 'UP', 'group': 'default', 'link_type': 'ether', 'addr_info': list(addresses)}


# One `ip -j address` document with every interface kind the rule must sort (REVIEW R18).
IP_ADDRESS = [
    interface(1, 'lo', addr('inet', '127.0.0.1', 'host', 8), addr('inet6', '::1', 'host', 128)),
    interface(2, 'ens3', addr('inet', '192.0.2.10'), addr('inet', '169.254.169.254', 'global', 16),
              addr('inet6', '2001:db8::10', 'global', 64), addr('inet6', 'fe80::5054:ff:fe12:3456', 'link', 64)),
    interface(3, 'ens4', addr('inet', '198.51.100.7')),
    interface(4, 'docker0', addr('inet', '172.17.0.1', 'global', 16)),
    interface(5, 'br-1a2b3c4d5e6f', addr('inet', '172.18.0.1', 'global', 16)),
    interface(6, 'veth9f2c1a', addr('inet6', 'fe80::1c2d:3eff:fe4f:5a6b', 'link', 64)),
    interface(7, 'virbr0', addr('inet', '192.168.122.1')),
    interface(8, 'cni0', addr('inet', '10.244.0.1')),
    interface(9, 'clab-mgmt', addr('inet', '172.20.20.1')),
]
IP_ROUTE4 = [{'dst': 'default', 'gateway': '192.0.2.1', 'dev': 'ens3', 'protocol': 'dhcp', 'prefsrc': '192.0.2.10',
              'metric': 100, 'flags': []}]
IP_ROUTE6 = [{'dst': 'default', 'gateway': 'fe80::1', 'dev': 'ens3', 'protocol': 'ra', 'metric': 1024, 'flags': [],
              'pref': 'medium'}]


def completed(argv, returncode=0, stdout='', stderr=''):
    return subprocess.CompletedProcess(argv, returncode, stdout=stdout, stderr=stderr)


class Runner:
    """A subprocess.run double: `ip` and `docker` answer from fixtures, `openssl` runs for real."""

    def __init__(self, address=IP_ADDRESS, route4=IP_ROUTE4, route6=IP_ROUTE6, docker=None, openssl_hook=None):
        self.address, self.route4, self.route6 = address, route4, route6
        self.docker = docker or {}
        self.openssl_hook = openssl_hook
        self.calls = []

    def __call__(self, argv, **kwargs):
        self.calls.append(list(argv))
        if argv[0] == 'ip':
            if argv[1:] == ['-j', 'route', 'show', 'default']:
                return completed(argv, stdout=json.dumps(self.route4))
            if argv[1:] == ['-6', '-j', 'route', 'show', 'default']:
                return completed(argv, stdout=json.dumps(self.route6))
            if argv[1:] == ['-j', 'address']:
                return completed(argv, stdout=json.dumps(self.address))
            return completed(argv, 1, stderr='unexpected ip argv')
        if argv[0] == 'docker':
            key = ' '.join(argv[1:])
            for prefix, answer in self.docker.items():
                if key.startswith(prefix):
                    return completed(argv, stdout=answer)
            return completed(argv, 1, stderr='no docker answer')
        if argv[0] == 'openssl':
            if self.openssl_hook:
                hooked = self.openssl_hook(argv)
                if hooked is not None:
                    return hooked
            return subprocess.run(argv, **kwargs)
        raise AssertionError('unexpected command ' + repr(argv))


class Chown:
    def __init__(self):
        self.calls = []

    def __call__(self, path, uid, gid):
        # Files are owned while still under their temporary name (.key.pem-abc123) and moved afterwards.
        name = Path(path).name
        match = re.fullmatch(r'\.([a-z.]+)-[A-Za-z0-9_]+', name)
        self.calls.append((match.group(1) if match else name, uid, gid))


def tls(tmp, runner=None, allowed='', image_env=None, hostname='archtop', **kw):
    repo = Path(tmp) / 'repo'
    (repo / 'clab-backup-ui').mkdir(parents=True, exist_ok=True)
    (repo / 'deploy').mkdir(exist_ok=True)
    (repo / 'clab-backup-ui/VERSION').write_text('9.9.9\n')
    if allowed:
        (repo / 'clab-backup-ui/.env').write_text(f'UI_ALLOWED_HOSTS={allowed}\nCAPTURE_PROVIDER=disabled\n')
    if image_env is not None:
        (repo / 'deploy/image.env').write_text(image_env)
    kw.setdefault('chown', Chown())
    return setup_tls.Tls(tls_dir=Path(tmp) / 'tls', repo=repo, run=runner or Runner(), hostname=lambda: hostname, **kw)


class CertificateAddressesTests(unittest.TestCase):
    def test_default_route_interface_global_addresses_only(self):
        self.assertEqual(setup_tls.certificate_addresses(IP_ROUTE4 + IP_ROUTE6, IP_ADDRESS), ['192.0.2.10', '2001:db8::10'])

    def test_second_default_route_adds_its_interface(self):
        routes = IP_ROUTE4 + [{'dst': 'default', 'gateway': '198.51.100.1', 'dev': 'ens4', 'metric': 200}]
        self.assertEqual(setup_tls.certificate_addresses(routes, IP_ADDRESS), ['192.0.2.10', '2001:db8::10', '198.51.100.7'])

    def test_no_default_route_falls_back_to_every_non_excluded_interface(self):
        self.assertEqual(setup_tls.certificate_addresses([], IP_ADDRESS), ['192.0.2.10', '2001:db8::10', '198.51.100.7'])

    def test_bridges_veths_loopback_and_link_local_are_never_named(self):
        for routes in ([], IP_ROUTE4 + IP_ROUTE6):
            with self.subTest(routes=bool(routes)):
                names = set(setup_tls.certificate_addresses(routes, IP_ADDRESS))
                for banned in ('172.17.0.1', '172.18.0.1', '192.168.122.1', '10.244.0.1', '172.20.20.1', '127.0.0.1', '::1',
                               '169.254.169.254', 'fe80::5054:ff:fe12:3456', 'fe80::1c2d:3eff:fe4f:5a6b'):
                    self.assertNotIn(banned, names)

    def test_a_default_route_over_a_bridge_still_names_no_bridge_address(self):
        routes = [{'dst': 'default', 'gateway': '172.17.0.254', 'dev': 'docker0'}]
        self.assertEqual(setup_tls.certificate_addresses(routes, IP_ADDRESS), [])

    def test_malformed_documents_give_an_empty_list(self):
        self.assertEqual(setup_tls.certificate_addresses(None, None), [])
        self.assertEqual(setup_tls.certificate_addresses([{'dst': 'default'}], [{'ifname': 'ens3'}, 'junk', {'addr_info': 'x'}]), [])


class NamesTests(unittest.TestCase):
    def test_subject_names_in_order_without_duplicates(self):
        sans = setup_tls.subject_names(['192.0.2.10', '2001:db8::10'], 'Archtop', frozenset(['manager.example.edu']),
                                       ['198.51.100.7', 'lab.example.edu', 'manager.example.edu', '192.0.2.10'])
        self.assertEqual(sans, ['IP:192.0.2.10', 'IP:2001:db8::10', 'IP:127.0.0.1', 'IP:::1', 'DNS:localhost', 'DNS:archtop',
                                'DNS:manager.example.edu', 'IP:198.51.100.7', 'DNS:lab.example.edu'])

    def test_host_name_that_is_not_a_name_is_left_out(self):
        self.assertNotIn('DNS:bad name', setup_tls.subject_names([], 'bad name', frozenset(), []))
        self.assertIn('IP:192.0.2.5', setup_tls.subject_names([], '192.0.2.5', frozenset(), []))

    def test_primary_name_order(self):
        self.assertEqual(setup_tls.primary_name(['manager.example.edu'], ['lab.example.edu'], ['192.0.2.10'], 'archtop'), 'manager.example.edu')
        self.assertEqual(setup_tls.primary_name([], ['198.51.100.7', 'lab.example.edu'], ['192.0.2.10'], 'archtop'), 'lab.example.edu')
        self.assertEqual(setup_tls.primary_name([], ['198.51.100.7'], ['2001:db8::10', '192.0.2.10'], 'archtop'), '192.0.2.10')
        self.assertEqual(setup_tls.primary_name([], [], ['2001:db8::10'], 'archtop'), 'archtop')

    def test_name_validation(self):
        self.assertEqual(setup_tls.validate_name(' Lab.Example.EDU '), 'lab.example.edu')
        self.assertEqual(setup_tls.validate_name('2001:DB8::10'), '2001:db8::10')
        self.assertEqual(setup_tls.validate_name('198.51.100.7'), '198.51.100.7')
        for bad in ('http://x', 'a b', 'name:8443', '[::1]', '*.example.edu', 'x/y', ''):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError) as error:
                    setup_tls.validate_name(bad)
                if bad:
                    self.assertIn(repr(bad), str(error.exception))

    def test_openssl_argv_is_exact(self):
        argv = setup_tls.openssl_argv('192.0.2.10', ['IP:192.0.2.10', 'DNS:localhost'], Path('/t/key.pem'), Path('/t/cert.pem'))
        self.assertEqual(argv, ['openssl', 'req', '-x509', '-newkey', 'ec', '-pkeyopt', 'ec_paramgen_curve:P-256', '-nodes', '-sha256',
                                '-days', '730', '-subj', '/CN=192.0.2.10', '-addext', 'subjectAltName=IP:192.0.2.10,DNS:localhost',
                                '-addext', 'basicConstraints=critical,CA:FALSE', '-addext', 'keyUsage=digitalSignature',
                                '-addext', 'extendedKeyUsage=serverAuth', '-keyout', '/t/key.pem', '-out', '/t/cert.pem'])

    def test_san_text_is_normalised(self):
        text = ('X509v3 Subject Alternative Name: \n    IP Address:192.0.2.10, IP Address:2001:DB8:0:0:0:0:0:10, '
                'IP Address:0:0:0:0:0:0:0:1, DNS:LocalHost, DNS:archtop\n')
        self.assertEqual(setup_tls.san_entries(text), {'IP:192.0.2.10', 'IP:2001:db8::10', 'IP:::1', 'DNS:localhost', 'DNS:archtop'})

    def test_env_values_never_evaluate_shell(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / '.env'
            path.write_text('# comment\nUI_PORT = 8443\nUI_ALLOWED_HOSTS="a.example.edu, b.example.edu"\nX=$(rm -rf /)\n')
            values = setup_tls.env_values(path)
            self.assertEqual(values['UI_PORT'], '8443')
            self.assertEqual(values['UI_ALLOWED_HOSTS'], 'a.example.edu, b.example.edu')
            self.assertEqual(values['X'], '$(rm -rf /)')
            self.assertEqual(setup_tls.env_values(Path(tmp) / 'missing'), {})


class SelfSignedTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.tmp = Path(self.temp.name)

    def test_generation_writes_the_files_with_their_modes_owners_and_names(self):
        runner = Runner()
        chown = Chown()
        service = tls(self.tmp, runner, allowed='manager.example.edu', chown=chown)
        lines = []
        service.out = lines.append
        reason = service.ensure()
        self.assertIn('no certificate', reason)
        tls_dir = self.tmp / 'tls'
        self.assertEqual(stat.S_IMODE(tls_dir.stat().st_mode), 0o755)
        self.assertEqual(stat.S_IMODE((tls_dir / 'cert.pem').stat().st_mode), 0o644)
        self.assertEqual(stat.S_IMODE((tls_dir / 'key.pem').stat().st_mode), 0o640)
        self.assertEqual(stat.S_IMODE((tls_dir / 'mode').stat().st_mode), 0o644)
        self.assertEqual((tls_dir / 'mode').read_text(), 'self-signed\n')
        self.assertEqual(sorted(p.name for p in tls_dir.iterdir()), ['cert.pem', 'key.pem', 'mode'], 'no temporary directory is left behind')
        self.assertIn(('key.pem', 0, 10001), chown.calls)
        self.assertIn(('cert.pem', 0, 0), chown.calls)
        self.assertIn(('mode', 0, 0), chown.calls)
        facts = service.certificate_facts()
        self.assertEqual(facts['sans'], {'IP:192.0.2.10', 'IP:2001:db8::10', 'IP:127.0.0.1', 'IP:::1', 'DNS:localhost', 'DNS:archtop',
                                         'DNS:manager.example.edu'})
        self.assertEqual(facts['subject'], 'CN = manager.example.edu')
        self.assertRegex(facts['fingerprint'], r'^([0-9A-F]{2}:){31}[0-9A-F]{2}$')
        self.assertTrue(service.valid_for(30 * 86400))
        generation = next(call for call in runner.calls if call[:2] == ['openssl', 'req'])
        self.assertIn('-addext', generation)
        self.assertTrue(generation[generation.index('-keyout') + 1].startswith(str(tls_dir)), 'the key is written inside the tls directory')
        text = '\n'.join(lines)
        self.assertIn(facts['fingerprint'], text)
        self.assertNotIn('PRIVATE KEY', text)

    def test_ensure_keeps_a_valid_certificate_and_ignores_excluded_addresses(self):
        service = tls(self.tmp)
        service.out = lambda line: None
        service.ensure()
        before = service.certificate_facts()['fingerprint']
        noisy = json.loads(json.dumps(IP_ADDRESS))
        noisy[3]['addr_info'].append(addr('inet', '172.17.0.2'))            # docker0 gained an address
        noisy.append(interface(10, 'br-deadbeef0000', addr('inet', '172.19.0.1', 'global', 16)))   # a new lab bridge
        noisy.append(interface(11, 'veth0a1b2c', addr('inet6', 'fe80::2', 'link', 64)))
        noisy[1]['addr_info'].append(addr('inet6', 'fe80::9', 'link', 64))  # a new link-local on the uplink
        service.run = Runner(address=noisy)
        self.assertIsNone(service.ensure())
        self.assertEqual(service.certificate_facts()['fingerprint'], before)

    def test_ensure_regenerates_for_a_new_uplink_address_a_new_name_or_a_names_entry(self):
        service = tls(self.tmp)
        service.out = lambda line: None
        service.ensure()
        first = service.certificate_facts()['fingerprint']
        changed = json.loads(json.dumps(IP_ADDRESS))
        changed[1]['addr_info'].append(addr('inet', '192.0.2.11'))
        service.run = Runner(address=changed)
        self.assertIn('192.0.2.11', service.ensure())
        second = service.certificate_facts()['fingerprint']
        self.assertNotEqual(first, second)
        self.assertIn('IP:192.0.2.11', service.certificate_facts()['sans'])
        (service.repo / 'clab-backup-ui/.env').write_text('UI_ALLOWED_HOSTS=new.example.edu\n')
        self.assertIn('new.example.edu', service.ensure())
        self.assertIn('DNS:new.example.edu', service.certificate_facts()['sans'])
        service.set_names(['lab.example.edu', '198.51.100.7'])
        self.assertEqual((self.tmp / 'tls/names').read_text(), 'lab.example.edu\n198.51.100.7\n')
        self.assertIn('lab.example.edu', service.ensure())
        self.assertLessEqual({'DNS:lab.example.edu', 'IP:198.51.100.7'}, service.certificate_facts()['sans'])
        self.assertIsNone(service.ensure())
        service.set_names([])
        self.assertFalse((self.tmp / 'tls/names').exists())
        self.assertIsNone(service.ensure(), 'a name that disappears from the list is an extra SAN, never a reason to regenerate')

    def test_ensure_regenerates_an_expiring_or_expired_or_unreadable_certificate(self):
        service = tls(self.tmp)
        service.out = lambda line: None
        service.ensure()
        first = service.certificate_facts()['fingerprint']

        def expiring(argv):
            if '-checkend' in argv and argv[argv.index('-checkend') + 1] != '0':
                return completed(argv, 1, stdout='Certificate will expire\n')
            return None
        service.run = Runner(openssl_hook=expiring)
        self.assertIn('30 days', service.ensure())
        second = service.certificate_facts()['fingerprint']
        self.assertNotEqual(first, second)

        def expired(argv):
            if '-checkend' in argv:
                return completed(argv, 1, stdout='Certificate will expire\n')
            return None
        service.run = Runner(openssl_hook=expired)
        self.assertEqual(service.ensure(), 'the certificate has expired')
        service.run = Runner()
        (self.tmp / 'tls/cert.pem').write_text('not a certificate\n')
        self.assertIn('cannot be read', service.ensure())
        self.assertIsNotNone(service.certificate_facts())

    def test_renew_makes_a_new_key_and_is_refused_for_a_provided_certificate(self):
        service = tls(self.tmp)
        service.out = lambda line: None
        service.ensure()
        first = service.certificate_facts()['fingerprint']
        service.renew()
        self.assertNotEqual(service.certificate_facts()['fingerprint'], first)
        service.write_mode('provided')
        with self.assertRaisesRegex(ValueError, 'provided'):
            service.renew()
        service.self_signed()
        self.assertEqual(service.read_mode(), 'self-signed')

    def test_a_symlinked_tls_directory_is_refused(self):
        real = self.tmp / 'elsewhere'
        real.mkdir()
        (self.tmp / 'tls').symlink_to(real)
        service = tls(self.tmp)
        with self.assertRaisesRegex(ValueError, 'symlink'):
            service.ensure()

    def test_show_and_primary(self):
        service = tls(self.tmp, allowed='manager.example.edu')
        lines = []
        service.out = lines.append
        service.show()
        self.assertIn('certificate: none', lines)
        self.assertIn('primary: manager.example.edu', lines)
        self.assertEqual(service.primary(), 'manager.example.edu')
        lines.clear()
        service.ensure()
        lines.clear()
        service.show()
        text = '\n'.join(lines)
        self.assertIn('mode: self-signed', text)
        self.assertIn('subject: CN = manager.example.edu', text)
        self.assertRegex(text, r'fingerprint: ([0-9A-F]{2}:){31}[0-9A-F]{2}')
        self.assertIn('names: IP:192.0.2.10, IP:2001:db8::10, IP:127.0.0.1, IP:::1, DNS:localhost, DNS:archtop, DNS:manager.example.edu', text)
        self.assertIn('expires: ', text)
        self.assertIn('missing: none', text)
        self.assertIn('primary: manager.example.edu', text)
        self.assertNotIn('PRIVATE', text)


def make_pair(directory, name, days=365, encrypted=False, cn='provided.example.edu'):
    key, cert = directory / f'{name}-key.pem', directory / f'{name}-cert.pem'
    subprocess.run(['openssl', 'req', '-x509', '-newkey', 'ec', '-pkeyopt', 'ec_paramgen_curve:P-256', '-nodes', '-sha256', '-days', str(days),
                    '-subj', f'/CN={cn}', '-addext', f'subjectAltName=DNS:{cn}', '-keyout', str(key), '-out', str(cert)],
                   check=True, capture_output=True, stdin=subprocess.DEVNULL)
    if encrypted:
        locked = directory / f'{name}-locked.pem'
        subprocess.run(['openssl', 'pkey', '-in', str(key), '-aes256', '-passout', 'pass:secret', '-out', str(locked)],
                       check=True, capture_output=True, stdin=subprocess.DEVNULL)
        key = locked
    return cert, key


class ProvidedTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.tmp = Path(self.temp.name)
        self.source = self.tmp / 'source'
        self.source.mkdir()

    def test_a_matching_pair_is_installed_with_the_fixed_modes_and_mode_is_written_last(self):
        cert, key = make_pair(self.source, 'good')
        key.chmod(0o600)
        chown = Chown()
        service = tls(self.tmp, chown=chown)
        lines = []
        service.out = lines.append
        service.install_provided(cert, key)
        tls_dir = self.tmp / 'tls'
        self.assertEqual(stat.S_IMODE((tls_dir / 'cert.pem').stat().st_mode), 0o644)
        self.assertEqual(stat.S_IMODE((tls_dir / 'key.pem').stat().st_mode), 0o640)
        self.assertEqual((tls_dir / 'mode').read_text(), 'provided\n')
        self.assertEqual(stat.S_IMODE(key.stat().st_mode), 0o600, 'the source files are left as they were')
        self.assertIn(('key.pem', 0, 10001), chown.calls)
        self.assertEqual(chown.calls[-1][0], 'mode', 'mode=provided is written last')
        self.assertIn('DNS:provided.example.edu', '\n'.join(lines))
        self.assertIsNone(service.ensure(), 'ensure never touches a provided certificate')
        self.assertEqual(service.certificate_facts()['sans'], {'DNS:provided.example.edu'})
        self.assertEqual(service.read_mode(), 'provided')
        self.assertNotIn('PRIVATE', '\n'.join(lines))

    def test_a_pair_that_does_not_match_is_refused_and_nothing_is_installed(self):
        cert, _key = make_pair(self.source, 'one')
        _cert, other_key = make_pair(self.source, 'two')
        service = tls(self.tmp)
        service.out = lambda line: None
        with self.assertRaisesRegex(ValueError, 'does not match'):
            service.install_provided(cert, other_key)
        self.assertFalse((self.tmp / 'tls/cert.pem').exists())
        self.assertFalse((self.tmp / 'tls/mode').exists())

    def test_an_encrypted_key_a_symlink_a_large_file_and_an_expired_certificate_are_refused(self):
        cert, key = make_pair(self.source, 'locked', encrypted=True)
        service = tls(self.tmp)
        service.out = lambda line: None
        with self.assertRaisesRegex(ValueError, 'decrypt the key first'):
            service.install_provided(cert, key)
        cert, key = make_pair(self.source, 'plain')
        link = self.source / 'link.pem'
        link.symlink_to(key)
        with self.assertRaisesRegex(ValueError, 'symlink'):
            service.install_provided(cert, link)
        big = self.source / 'big.pem'
        big.write_bytes(b'-----BEGIN CERTIFICATE-----\n' + b'A' * 70000)
        with self.assertRaisesRegex(ValueError, '64 KiB'):
            service.install_provided(big, key)

        def expired(argv):
            if '-checkend' in argv:
                return completed(argv, 1, stdout='Certificate will expire\n')
            return None
        service.run = Runner(openssl_hook=expired)
        with self.assertRaisesRegex(ValueError, 'expired'):
            service.install_provided(cert, key)
        self.assertFalse((self.tmp / 'tls').exists() and (self.tmp / 'tls/cert.pem').exists())

    def test_names_are_recorded_but_change_nothing_for_a_provided_certificate(self):
        cert, key = make_pair(self.source, 'good')
        service = tls(self.tmp)
        service.out = lambda line: None
        service.install_provided(cert, key)
        before = service.certificate_facts()['fingerprint']
        service.set_names(['lab.example.edu'])
        self.assertIsNone(service.ensure())
        self.assertEqual(service.certificate_facts()['fingerprint'], before)
        lines = []
        service.out = lines.append
        service.show()
        missing = next(line for line in lines if line.startswith('missing: '))
        self.assertIn('DNS:lab.example.edu', missing)
        self.assertIn('mode: provided', lines)


class PortsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.tmp = Path(self.temp.name)

    def env(self, service):
        return service.repo / 'clab-backup-ui/.env'

    def test_defaults_and_a_distinct_explicit_port_write_nothing(self):
        service = tls(self.tmp)
        service.out = lambda line: None
        self.assertIsNone(service.settle_ports())
        self.assertFalse(self.env(service).exists())
        self.env(service).write_text('UI_PORT=9443\nCAPTURE_PROVIDER=disabled\n')
        self.assertIsNone(service.settle_ports())
        self.assertEqual(self.env(service).read_text(), 'UI_PORT=9443\nCAPTURE_PROVIDER=disabled\n')

    def test_an_explicit_8081_without_a_redirect_port_disables_the_redirect_and_keeps_the_other_lines(self):
        service = tls(self.tmp)
        lines = []
        service.out = lines.append
        self.env(service).write_text('# settings\nCAPTURE_PROVIDER=edgeshark\nUI_PORT=8081\n')
        self.assertEqual(service.settle_ports(), 'UI_HTTP_PORT=0')
        self.assertEqual(self.env(service).read_text(), '# settings\nCAPTURE_PROVIDER=edgeshark\nUI_PORT=8081\nUI_HTTP_PORT=0\n')
        self.assertEqual(stat.S_IMODE(self.env(service).stat().st_mode), 0o600)
        text = '\n'.join(lines)
        self.assertIn('Your settings keep the manager on port 8081, which now serves HTTPS; there is no plain-HTTP redirect.', text)
        self.assertIn('set `UI_PORT=8443` and `UI_HTTP_PORT=8081` in `.env` and rerun', text)
        self.assertIsNone(service.settle_ports(), 'the second run finds no collision')

    def test_two_explicit_equal_ports_are_refused_before_anything_is_generated(self):
        service = tls(self.tmp)
        service.out = lambda line: None
        self.env(service).write_text('UI_PORT=8081\nUI_HTTP_PORT=8081\n')
        with self.assertRaisesRegex(ValueError, 'UI_PORT and UI_HTTP_PORT are both 8081'):
            service.ensure()
        self.assertFalse((self.tmp / 'tls/cert.pem').exists())
        self.env(service).write_text('UI_PORT=8081\nUI_HTTP_PORT=x\n')
        with self.assertRaisesRegex(ValueError, 'UI_HTTP_PORT'):
            service.settle_ports()

    def test_the_prepared_image_route_picks_image_env_the_way_recreate_manager_does(self):
        docker = {'compose -f': 'abc123\n', 'inspect --format {{.Config.Image}} abc123': 'registry.example/clab-backup:9.9.9\n',
                  'images --quiet clab-backup:9.9.9': 'sha256:local\n'}
        service = tls(self.tmp, Runner(docker=docker), image_env='MANAGER_IMAGE=registry.example/clab-backup:9.9.9\nUI_PORT=8081\n')
        service.out = lambda line: None
        self.assertEqual(service.route_env_file().name, 'image.env')
        self.assertEqual(service.settle_ports(), 'UI_HTTP_PORT=0')
        self.assertIn('UI_HTTP_PORT=0', (service.repo / 'deploy/image.env').read_text())
        self.assertFalse((service.repo / 'clab-backup-ui/.env').exists())
        # The running image differs and a local source image exists: the source route.
        docker['inspect --format {{.Config.Image}} abc123'] = 'clab-backup:9.9.9\n'
        service.run = Runner(docker=docker)
        self.assertEqual(service.route_env_file().name, '.env')
        # No local source image: the prepared image route even when the running image differs.
        docker['images --quiet clab-backup:9.9.9'] = ''
        service.run = Runner(docker=docker)
        self.assertEqual(service.route_env_file().name, 'image.env')
        # Without MANAGER_IMAGE the source route, and docker is never asked.
        (service.repo / 'deploy/image.env').write_text('UI_PORT=8081\n')
        runner = Runner(docker={})
        service.run = runner
        self.assertEqual(service.route_env_file().name, '.env')
        self.assertFalse(any(call[0] == 'docker' for call in runner.calls))

    def test_allowed_hosts_are_the_union_of_both_env_files_in_the_order_written(self):
        service = tls(self.tmp, allowed='a.example.edu', image_env='UI_ALLOWED_HOSTS=b.example.edu,A.example.edu\n')
        self.assertEqual(service.allowed_names(), ['a.example.edu', 'b.example.edu'])
        service = tls(self.tmp, allowed='Second.example.edu, first.example.edu, http://ignored', image_env='')
        self.assertEqual(service.allowed_names(), ['second.example.edu', 'first.example.edu'])
        self.assertEqual(service.primary(), 'second.example.edu', 'the first name listed is the primary name (EXPOSURE.md 3.2)')


FAKE_IP = """#!/usr/bin/env bash
case "$*" in
  '-j route show default') printf '%s' "$IP_ROUTE4";;
  '-6 -j route show default') printf '%s' "$IP_ROUTE6";;
  '-j address') printf '%s' "$IP_ADDRESS";;
  *) exit 1;;
esac
"""
FAKE_PYTHON = """#!/usr/bin/env bash
script="$1"; shift
exec "$REAL_PYTHON" "$script" --tls-dir "$TLS_DIR" "$@"
"""
FAKE_RECREATE = """#!/usr/bin/env bash
echo recreate >> "$RECREATE_LOG"
"""


class ShellScriptTests(unittest.TestCase):
    def setUp(self):
        text = SCRIPT.read_text()
        self.assertIn(ROOT_GUARD, text, "setup-tls.sh's root guard text changed; update this test's neutralised copy")
        self.assertIn(PYTHON_CALL, text, 'setup-tls.sh runs setup_tls.py with the system interpreter')
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        for rel in ('deploy/setup_tls.py', 'deploy/setup_capture.py', 'clab-backup-ui/app/allowed_hosts.py', 'clab-backup-ui/VERSION'):
            target = self.base / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / rel, target)
        self.script = self.base / 'deploy/setup-tls.sh'
        self.script.write_text(text.replace(ROOT_GUARD, ': # root check removed for this unit test')
                               .replace(PYTHON_CALL, 'python3 "$script_dir/setup_tls.py"'))
        self.script.chmod(0o755)
        bin_dir = self.base / 'bin'
        bin_dir.mkdir()
        for name, body in (('ip', FAKE_IP), ('python3', FAKE_PYTHON)):
            path = bin_dir / name
            path.write_text(body)
            path.chmod(0o755)
        recreate = self.base / 'deploy/recreate-manager.sh'
        recreate.write_text(FAKE_RECREATE)
        recreate.chmod(0o755)
        self.tls_dir = self.base / 'tls'
        self.recreate_log = self.base / 'recreate.log'
        self.env = {**os.environ, 'PATH': str(bin_dir) + os.pathsep + os.environ.get('PATH', ''),
                    'REAL_PYTHON': sys.executable, 'TLS_DIR': str(self.tls_dir), 'RECREATE_LOG': str(self.recreate_log),
                    'IP_ROUTE4': json.dumps(IP_ROUTE4), 'IP_ROUTE6': json.dumps(IP_ROUTE6), 'IP_ADDRESS': json.dumps(IP_ADDRESS)}

    def run_script(self, *args):
        return subprocess.run(['bash', str(self.script), *args], cwd=str(self.base), env=self.env,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=60)

    def recreations(self):
        return self.recreate_log.read_text().count('recreate') if self.recreate_log.exists() else 0

    def fingerprint(self):
        return subprocess.run(['openssl', 'x509', '-in', str(self.tls_dir / 'cert.pem'), '-noout', '-fingerprint', '-sha256'],
                              capture_output=True, text=True, check=True).stdout.strip().split('=', 1)[1]

    def test_ensure_creates_the_certificate_recreates_once_and_then_leaves_it_alone(self):
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertTrue((self.tls_dir / 'cert.pem').exists())
        self.assertIn(self.fingerprint(), result.stdout)
        self.assertEqual(self.recreations(), 1, result.stdout)
        first = self.fingerprint()
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(self.fingerprint(), first)
        self.assertEqual(self.recreations(), 1, 'an unchanged certificate never recreates the manager')

    def test_no_recreate_leaves_the_manager_alone_and_renew_changes_the_fingerprint(self):
        result = self.run_script('--no-recreate')
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(self.recreations(), 0)
        first = self.fingerprint()
        result = self.run_script('--renew', '--no-recreate')
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertNotEqual(self.fingerprint(), first)
        self.assertEqual(self.recreations(), 0)
        result = self.run_script('--renew')
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(self.recreations(), 1)

    def test_names_show_primary_and_fingerprint(self):
        result = self.run_script('--name', 'Lab.Example.EDU', '--name', '198.51.100.7', '--no-recreate')
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual((self.tls_dir / 'names').read_text(), 'lab.example.edu\n198.51.100.7\n')
        show = self.run_script('--show')
        self.assertEqual(show.returncode, 0, show.stdout)
        self.assertIn('DNS:lab.example.edu', show.stdout)
        self.assertIn('IP:198.51.100.7', show.stdout)
        self.assertIn('mode: self-signed', show.stdout)
        self.assertIn('primary: lab.example.edu', show.stdout)
        primary = self.run_script('--primary')
        self.assertEqual(primary.stdout, 'lab.example.edu\n')
        fingerprint = self.run_script('--fingerprint')
        self.assertEqual(fingerprint.stdout.strip(), self.fingerprint())
        self.assertEqual(self.recreations(), 0, 'read-only modes never recreate')
        result = self.run_script('--name', 'not a name', '--no-recreate')
        self.assertEqual(result.returncode, 1)
        self.assertIn("'not a name'", result.stdout)
        result = self.run_script('--name', '', '--no-recreate')
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertFalse((self.tls_dir / 'names').exists())

    def test_provided_certificate_round_trip(self):
        source = self.base / 'source'
        source.mkdir()
        cert, key = make_pair(source, 'good')
        result = self.run_script('--cert', str(cert), '--key', str(key))
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual((self.tls_dir / 'mode').read_text(), 'provided\n')
        self.assertEqual(self.recreations(), 1)
        result = self.run_script('--renew', '--no-recreate')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('provided', result.stdout)
        result = self.run_script('--renew', '--self-signed', '--no-recreate')
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual((self.tls_dir / 'mode').read_text(), 'self-signed\n')

    def test_option_errors(self):
        for args in (('--bogus',), ('--cert', 'x'), ('--key', 'x'), ('--show', '--renew'), ('--name',)):
            with self.subTest(args=args):
                result = self.run_script(*args)
                self.assertEqual(result.returncode, 64, result.stdout)
        self.assertEqual(self.recreations(), 0)

    def test_read_only_modes_need_no_root_and_writing_modes_do(self):
        text = SCRIPT.read_text()
        self.assertLess(text.index('--primary'), text.index(ROOT_GUARD))
        self.assertIn('needs_root', text)
        result = subprocess.run(['bash', str(SCRIPT), '--bogus'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 64)
        self.assertNotIn('Run with sudo', result.stderr, 'the usage error precedes the root guard')

    def test_syntax(self):
        subprocess.run(['bash', '-n', str(SCRIPT)], check=True)


if __name__ == '__main__':
    unittest.main()
