"""Make, install and inspect the manager's TLS certificate (docs/sign-on/EXPOSURE.md section 3).

Run by ``deploy/setup-tls.sh`` with the system python3 on the VM; standard library only, ``openssl``
and ``ip`` are the tools. The tls directory ``/srv/containerlab-node-manager/tls`` is root's; the
container mounts it read-only at ``/tls`` and uvicorn reads ``cert.pem`` and ``key.pem`` from there.

    ensure            the default: a self-signed certificate exists, is not expiring and names every
                      certificate address, UI_ALLOWED_HOSTS name and tls/names entry; otherwise a new
                      one is made. A provided certificate is never touched. Also settles the ports
                      (UI_PORT, UI_HTTP_PORT) of the upgrade table (EXPOSURE.md 7.4).
    renew             a new self-signed certificate now; refused while mode is provided
    self-signed       switch back from provided and generate
    provided CERT KEY validate and install an operator's certificate
    names [NAME...]   write tls/names (no names: remove it), then ensure
    show | primary | fingerprint   read-only, no root needed

The certificate addresses are the global-scope addresses of the default-route interface(s): never
docker0, br-*, veth*, virbr*, cni*, clab*, loopback or link-local (REVIEW R18), so a lab deploy
never changes the certificate. The pure rule is ``certificate_addresses(routes, addresses)``; the
health check loads it from here so both sides apply the same one.

Nothing here prints a key: errors quote file names, never contents.
"""
import importlib.util
import ipaddress
import json
import os
from pathlib import Path
import re
import shutil
import socket
import stat
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
TLS_DIR = Path('/srv/containerlab-node-manager/tls')
DAYS = 730
RENEW_WITHIN = 30 * 86400
WORKER_GID = 10001
DEFAULT_TLS_PORT = 8443
DEFAULT_HTTP_PORT = 8081
MAX_FILE = 64 * 1024
EXCLUDED_INTERFACES = ('lo', 'docker', 'br-', 'veth', 'virbr', 'cni', 'clab')
PORT_NOTE = ('Your settings keep the manager on port {port}, which now serves HTTPS; there is no plain-HTTP redirect. '
             'Old links to that port over plain HTTP show a browser error until retyped as `https://`. '
             'To get the redirect, set `UI_PORT=8443` and `UI_HTTP_PORT=8081` in `.env` and rerun.')


def _load(name, path):
    sys.dont_write_bytecode = True
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# The .env discipline (symlink refusal, tempfile + fsync + 0600 + chown + replace) and the Host rules
# are imported from their owners, never copied.
setup_capture = _load('setup_capture', HERE / 'setup_capture.py')
allowed_hosts = _load('allowed_hosts', REPO / 'clab-backup-ui/app/allowed_hosts.py')


# ---- pure rules -------------------------------------------------------------------------------

def excluded_interface(name):
    return not isinstance(name, str) or name == 'lo' or any(name.startswith(prefix) for prefix in EXCLUDED_INTERFACES)


def _global_addresses(entry):
    infos = entry.get('addr_info')
    for info in infos if isinstance(infos, list) else ():
        if not isinstance(info, dict) or info.get('scope') != 'global' or info.get('family') not in ('inet', 'inet6'):
            continue
        try:
            address = ipaddress.ip_address(str(info.get('local', '')))
        except ValueError:
            continue
        if address.is_loopback or address.is_link_local or address.is_unspecified or address.is_multicast:
            continue
        yield address.compressed


def certificate_addresses(routes, addresses):
    """The IP addresses the certificate names, from the parsed JSON of ``ip -j route show default``
    (IPv4 and IPv6 entries concatenated) and ``ip -j address``: the global-scope addresses of the
    default-route interface(s), or of every non-excluded interface when there is no default route;
    never an address on an excluded interface, never loopback or link-local, in document order."""
    routes = routes if isinstance(routes, list) else []
    addresses = addresses if isinstance(addresses, list) else []
    uplinks = [route.get('dev') for route in routes if isinstance(route, dict) and route.get('dst') == 'default' and route.get('dev')]
    found = []
    for entry in addresses:
        if not isinstance(entry, dict):
            continue
        name = entry.get('ifname')
        if excluded_interface(name) or (uplinks and name not in uplinks):
            continue
        for address in _global_addresses(entry):
            if address not in found:
                found.append(address)
    return found


def _is_ip(value):
    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        return False


def validate_name(value):
    """A tls/names entry: an IP address (returned compressed) or a host name without port or brackets
    (returned lower-case); anything else is refused with the value quoted."""
    text = (value or '').strip()
    if not text:
        raise ValueError('An empty name.')
    try:
        return ipaddress.ip_address(text).compressed
    except ValueError:
        pass
    name = allowed_hosts.host_name(text)
    if name is None or name != text.lower() or name.startswith('['):
        raise ValueError(f'{text!r} is not a host name or an IP address (write names without a port or a scheme, '
                         'IPv6 addresses without brackets).')
    return name


def san(value):
    return ('IP:' if _is_ip(value) else 'DNS:') + value


def subject_names(addresses, hostname, allowed, names):
    """The SAN list, in order: the certificate addresses, the loopback names, the host name, every
    UI_ALLOWED_HOSTS name, every tls/names entry; no duplicates."""
    entries = [san(a) for a in addresses] + ['IP:127.0.0.1', 'IP:::1', 'DNS:localhost']
    host = (hostname or '').strip().lower()
    if host and (_is_ip(host) or (allowed_hosts.host_name(host) == host and not host.startswith('['))):
        entries.append(san(host))
    entries += ['DNS:' + name for name in sorted(allowed)]
    entries += [san(name) for name in names]
    result = []
    for entry in entries:
        if entry not in result:
            result.append(entry)
    return result


def primary_name(allowed, names, addresses, hostname):
    """The CN: the first UI_ALLOWED_HOSTS name, else the first tls/names entry that is a name, else the
    first IPv4 certificate address, else the host name."""
    for name in allowed:
        return name
    for name in names:
        if not _is_ip(name):
            return name
    for address in addresses:
        if ipaddress.ip_address(address).version == 4:
            return address
    return (hostname or '').strip().lower() or 'localhost'


def openssl_argv(primary, sans, key_path, cert_path):
    return ['openssl', 'req', '-x509', '-newkey', 'ec', '-pkeyopt', 'ec_paramgen_curve:P-256', '-nodes', '-sha256',
            '-days', str(DAYS), '-subj', '/CN=' + primary, '-addext', 'subjectAltName=' + ','.join(sans),
            '-addext', 'basicConstraints=critical,CA:FALSE', '-addext', 'keyUsage=digitalSignature',
            '-addext', 'extendedKeyUsage=serverAuth', '-keyout', str(key_path), '-out', str(cert_path)]


def san_entries(text):
    """The SANs of ``openssl x509 -ext subjectAltName`` output, normalised to ``IP:<compressed>`` and
    ``DNS:<lower-case>``."""
    found = set()
    for match in re.finditer(r'(IP Address|IP|DNS):([^,\s]+)', text or ''):
        kind, value = match.group(1), match.group(2)
        if kind == 'DNS':
            found.add('DNS:' + value.lower())
        else:
            try:
                found.add('IP:' + ipaddress.ip_address(value).compressed)
            except ValueError:
                found.add('IP:' + value)
    return found


def env_values(path):
    """KEY=value pairs of a dotenv file, last wins, quotes stripped, nothing evaluated."""
    path = Path(path)
    if not path.is_file():
        return {}
    values = {}
    for line in path.read_text(encoding='utf-8', errors='replace').splitlines():
        match = re.match(r'^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$', line)
        if match:
            values[match[1]] = match[2].strip().strip('"\'')
    return values


def _port(values, key, default):
    raw = values.get(key)
    if raw is None or raw == '':
        return default, False
    if not re.fullmatch(r'\d{1,5}', raw) or int(raw) > 65535 or (int(raw) == 0 and key != 'UI_HTTP_PORT'):
        raise ValueError(f'{key}={raw!r} is not a port number (1-65535' + (', or 0 to disable the redirect' if key == 'UI_HTTP_PORT' else '') + ').')
    return int(raw), True


# ---- the tool -------------------------------------------------------------------------------

class Tls:
    def __init__(self, tls_dir=TLS_DIR, repo=REPO, run=subprocess.run, chown=os.chown, hostname=socket.gethostname, out=print):
        self.tls_dir = Path(tls_dir)
        self.repo = Path(repo)
        self.run = run
        self.chown = chown
        self.hostname = hostname
        self.out = out

    # -- processes
    def command(self, argv, check=False):
        result = self.run(argv, capture_output=True, text=True, stdin=subprocess.DEVNULL)
        if check and result.returncode != 0:
            tail = (result.stderr or result.stdout or '').strip().splitlines()
            raise ValueError(f'{argv[0]} {argv[1]} failed' + (': ' + tail[-1] if tail else '') + '.')
        return result

    def _ip_json(self, argv):
        if shutil.which('ip') is None and self.run is subprocess.run:
            return []
        try:
            result = self.command(['ip', *argv])
            return json.loads(result.stdout) if result.returncode == 0 else []
        except (OSError, ValueError):
            return []

    # -- the files
    def path(self, name):
        return self.tls_dir / name

    def check_directory(self):
        if self.tls_dir.is_symlink():
            raise ValueError(f'Refusing a symlink at {self.tls_dir}.')

    def prepare_directory(self):
        self.check_directory()
        if not self.tls_dir.is_dir():
            self.tls_dir.mkdir(mode=0o755)
            self.chown(self.tls_dir, 0, 0)
        os.chmod(self.tls_dir, 0o755)

    def install_bytes(self, name, data, mode, gid=0):
        """Write a file through a temporary name inside the tls directory, with its final mode and
        owner, then move it into place (the write_env discipline)."""
        fd, temporary = tempfile.mkstemp(prefix='.' + name + '-', dir=self.tls_dir)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temporary, mode)
            self.chown(temporary, 0, gid)
            os.replace(temporary, self.path(name))
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def read_mode(self):
        try:
            value = self.path('mode').read_text(encoding='utf-8').strip()
        except OSError:
            return 'self-signed'
        return value if value in ('self-signed', 'provided') else 'self-signed'

    def write_mode(self, value):
        self.prepare_directory()
        self.install_bytes('mode', (value + '\n').encode(), 0o644)

    def names(self):
        try:
            lines = self.path('names').read_text(encoding='utf-8').splitlines()
        except OSError:
            return []
        return [line.strip() for line in lines if line.strip()]

    def set_names(self, values):
        names = [validate_name(value) for value in values if (value or '').strip()]
        if not names:
            if self.path('names').exists() or self.path('names').is_symlink():
                self.path('names').unlink()
            self.out('tls/names removed.')
            return names
        self.prepare_directory()
        self.install_bytes('names', ('\n'.join(names) + '\n').encode(), 0o644)
        self.out('tls/names: ' + ', '.join(names))
        return names

    # -- the facts
    def env_files(self):
        return [self.repo / 'clab-backup-ui/.env', self.repo / 'deploy/image.env']

    def allowed_names(self):
        names = set()
        for path in self.env_files():
            names |= allowed_hosts.configured_hosts(env_values(path).get('UI_ALLOWED_HOSTS', ''))
        return sorted(names)

    def host_addresses(self):
        routes = self._ip_json(['-j', 'route', 'show', 'default']) + self._ip_json(['-6', '-j', 'route', 'show', 'default'])
        return certificate_addresses(routes, self._ip_json(['-j', 'address']))

    def plan(self):
        addresses, allowed, names = self.host_addresses(), self.allowed_names(), self.names()
        try:
            hostname = self.hostname()
        except OSError:
            hostname = ''
        return {'addresses': addresses, 'allowed': allowed, 'names': names, 'hostname': hostname,
                'sans': subject_names(addresses, hostname, allowed, names),
                'primary': primary_name(allowed, names, addresses, hostname)}

    def primary(self):
        return self.plan()['primary']

    def certificate_facts(self):
        """subject, sans, not_after and fingerprint of cert.pem, or None when there is none or openssl cannot read it."""
        cert = self.path('cert.pem')
        if not cert.is_file():
            return None
        result = self.command(['openssl', 'x509', '-in', str(cert), '-noout', '-subject', '-enddate', '-ext', 'subjectAltName',
                               '-fingerprint', '-sha256'])
        if result.returncode != 0:
            return None
        facts = {'subject': '', 'not_after': '', 'fingerprint': '', 'sans': set()}
        for line in result.stdout.splitlines():
            if line.startswith('subject='):
                facts['subject'] = line[len('subject='):].strip()
            elif line.startswith('notAfter='):
                facts['not_after'] = line[len('notAfter='):].strip()
            elif 'Fingerprint=' in line:
                facts['fingerprint'] = line.split('=', 1)[1].strip()
        facts['sans'] = san_entries(result.stdout)
        return facts

    def valid_for(self, seconds, cert=None):
        result = self.command(['openssl', 'x509', '-in', str(cert or self.path('cert.pem')), '-noout', '-checkend', str(int(seconds))])
        return result.returncode == 0

    def fingerprint(self):
        facts = self.certificate_facts()
        return facts['fingerprint'] if facts else ''

    def regeneration_reason(self, plan):
        facts = self.certificate_facts()
        if facts is None:
            return 'no certificate' if not self.path('cert.pem').exists() else 'the certificate cannot be read'
        if not self.valid_for(0):
            return 'the certificate has expired'
        if not self.valid_for(RENEW_WITHIN):
            return 'the certificate expires within 30 days'
        missing = [entry for entry in plan['sans'] if entry not in facts['sans']]
        if missing:
            return 'missing names: ' + ', '.join(missing)
        return None

    # -- the modes
    def generate(self, plan):
        self.prepare_directory()
        temporary = Path(tempfile.mkdtemp(prefix='.tls-', dir=self.tls_dir))
        try:
            key, cert = temporary / 'key.pem', temporary / 'cert.pem'
            self.command(openssl_argv(plan['primary'], plan['sans'], key, cert), check=True)
            os.chmod(key, 0o640)
            self.chown(key, 0, WORKER_GID)
            os.chmod(cert, 0o644)
            self.chown(cert, 0, 0)
            os.replace(cert, self.path('cert.pem'))
            os.replace(key, self.path('key.pem'))
        finally:
            shutil.rmtree(temporary, ignore_errors=True)
        self.write_mode('self-signed')

    def report(self, prefix='Certificate fingerprint (SHA-256): '):
        facts = self.certificate_facts()
        if facts:
            self.out(prefix + facts['fingerprint'])
        return facts

    def ensure(self):
        """Returns the reason a certificate was made, or None when the existing one was kept."""
        self.check_directory()
        self.settle_ports()
        plan = self.plan()
        if self.read_mode() == 'provided':
            facts = self.certificate_facts()
            if facts is None:
                self.out('Provided certificate: cert.pem is missing or unreadable; install it again with setup-tls.sh --cert PATH --key PATH.')
            elif not self.valid_for(0):
                self.out(f'Provided certificate kept; it EXPIRED on {facts["not_after"]}. Install a new one with setup-tls.sh --cert PATH --key PATH.')
            elif not self.valid_for(RENEW_WITHIN):
                self.out(f'Provided certificate kept; it expires on {facts["not_after"]} (within 30 days).')
            else:
                self.out(f'Provided certificate kept; expires {facts["not_after"]}.')
            self.report()
            return None
        reason = self.regeneration_reason(plan)
        if reason is None:
            self.out('Self-signed certificate kept: it names ' + ', '.join(plan['sans']) + '.')
            self.report()
            return None
        self.generate(plan)
        self.out(f'New self-signed certificate ({reason}) for ' + ', '.join(plan['sans']) + f'; valid {DAYS} days. '
                 'Browsers show their warning again for a new certificate.')
        self.report()
        return reason

    def renew(self, force=False):
        self.check_directory()
        if self.read_mode() == 'provided' and not force:
            raise ValueError('The certificate is a provided one; --renew applies to a self-signed certificate. '
                             'Install a new provided certificate with --cert PATH --key PATH, or add --self-signed to switch back.')
        plan = self.plan()
        self.generate(plan)
        self.out('New self-signed certificate for ' + ', '.join(plan['sans']) + f'; valid {DAYS} days. Browsers show their warning again.')
        self.report()

    def self_signed(self):
        self.renew(force=True)

    def _regular_file(self, path, what):
        path = Path(path)
        if path.is_symlink():
            raise ValueError(f'The {what} {path} is a symlink; give the file itself.')
        if not path.is_file():
            raise ValueError(f'The {what} {path} is not a regular file.')
        if path.stat().st_size > MAX_FILE:
            raise ValueError(f'The {what} {path} is larger than 64 KiB.')
        return path.read_bytes()

    def install_provided(self, cert_path, key_path):
        self.check_directory()
        cert_bytes = self._regular_file(cert_path, 'certificate')
        key_bytes = self._regular_file(key_path, 'key')
        if b'ENCRYPTED' in key_bytes[:4096]:
            raise ValueError(f'The key {key_path} is encrypted; decrypt the key first (uvicorn cannot ask for a password at start).')
        cert_path, key_path = str(cert_path), str(key_path)
        if not self.valid_for(0, cert_path):
            raise ValueError(f'The certificate {cert_path} has expired or cannot be read.')
        sans = self.command(['openssl', 'x509', '-in', cert_path, '-noout', '-ext', 'subjectAltName'], check=True)
        names = san_entries(sans.stdout)
        if not names:
            raise ValueError(f'The certificate {cert_path} lists no subjectAltName; browsers need at least one name.')
        key_public = self.command(['openssl', 'pkey', '-in', key_path, '-pubout', '-passin', 'pass:'])
        if key_public.returncode != 0:
            raise ValueError(f'The key {key_path} cannot be read by openssl; decrypt the key first or check the file.')
        cert_public = self.command(['openssl', 'x509', '-in', cert_path, '-noout', '-pubkey'], check=True)
        if key_public.stdout.strip() != cert_public.stdout.strip():
            raise ValueError(f'The key {key_path} does not match the certificate {cert_path}.')
        self.prepare_directory()
        self.install_bytes('cert.pem', cert_bytes, 0o644)
        self.install_bytes('key.pem', key_bytes, 0o640, WORKER_GID)
        self.write_mode('provided')
        self.out('Provided certificate installed; it names ' + ', '.join(sorted(names)) + '.')
        self.report()

    def show(self):
        plan = self.plan()
        facts = self.certificate_facts()
        if facts is None:
            self.out('certificate: none' if not self.path('cert.pem').exists() else 'certificate: unreadable')
        else:
            self.out('subject: ' + facts['subject'])
            self.out('names: ' + ', '.join(sorted(facts['sans'], key=lambda e: (plan['sans'].index(e) if e in plan['sans'] else len(plan['sans']), e))))
            self.out('expires: ' + facts['not_after'] + ('' if self.valid_for(0) else ' (EXPIRED)'))
            missing = [entry for entry in plan['sans'] if entry not in facts['sans']]
            self.out('missing: ' + (', '.join(missing) if missing else 'none'))
            self.out('fingerprint: ' + facts['fingerprint'])
        self.out('mode: ' + (self.read_mode() if facts is not None or self.path('mode').exists() else 'none'))
        self.out('required: ' + ', '.join(plan['sans']))
        self.out('primary: ' + plan['primary'])

    # -- the ports of the upgrade table (EXPOSURE.md 7.4)
    def route_env_file(self):
        """The env file recreate-manager.sh would use: deploy/image.env on a prepared-image
        installation (MANAGER_IMAGE set, and the running container uses that image or no local
        source image exists), else clab-backup-ui/.env."""
        source_env, image_env = self.env_files()
        manager_image = env_values(image_env).get('MANAGER_IMAGE', '')
        if not manager_image:
            return source_env
        compose = ['docker', 'compose', '-f', str(self.repo / 'clab-backup-ui/compose.yml')]
        if source_env.is_file():
            compose += ['--env-file', str(source_env)]
        existing = self._quiet(compose + ['ps', '--all', '--quiet', 'backup-ui'])
        running_image = self._quiet(['docker', 'inspect', '--format', '{{.Config.Image}}', existing]) if existing else ''
        try:
            version = (self.repo / 'clab-backup-ui/VERSION').read_text().strip()
        except OSError:
            version = ''
        local_source = self._quiet(['docker', 'images', '--quiet', 'clab-backup:' + version])
        return image_env if running_image == manager_image or not local_source else source_env

    def _quiet(self, argv):
        try:
            result = self.command(argv)
        except OSError:
            return ''
        return result.stdout.strip().splitlines()[0] if result.returncode == 0 and result.stdout.strip() else ''

    def settle_ports(self):
        """Refuses UI_PORT == UI_HTTP_PORT when both are explicit; writes UI_HTTP_PORT=0 when an
        explicit UI_PORT collides with the default redirect port (the standard upgrade path).
        Returns the line written, or None."""
        path = self.route_env_file()
        values = env_values(path)
        tls_port, tls_explicit = _port(values, 'UI_PORT', DEFAULT_TLS_PORT)
        http_port, http_explicit = _port(values, 'UI_HTTP_PORT', DEFAULT_HTTP_PORT)
        if http_port == 0 or tls_port != http_port:
            return None
        if tls_explicit and not http_explicit:
            env_path, old, metadata = setup_capture.read_env(path)
            lines = setup_capture.without(old.splitlines(), ['UI_HTTP_PORT'])
            lines.append('UI_HTTP_PORT=0')
            setup_capture.write_env(env_path, lines, metadata)
            self.out(PORT_NOTE.format(port=tls_port) + f' (UI_HTTP_PORT=0 was written to {path}.)')
            return 'UI_HTTP_PORT=0'
        raise ValueError(f'UI_PORT and UI_HTTP_PORT are both {tls_port} in {path}: the TLS port and the plain-HTTP redirect port must differ. '
                         'Set UI_PORT=8443 and UI_HTTP_PORT=8081 (or UI_HTTP_PORT=0 for no redirect) and rerun.')


USAGE = 'Usage: setup_tls.py [--tls-dir DIR] [--repo DIR] ensure|renew|self-signed|provided CERT KEY|names [NAME...]|show|primary|fingerprint'


def main(argv):
    options = {'tls_dir': TLS_DIR, 'repo': REPO}
    rest = list(argv)
    while rest and rest[0] in ('--tls-dir', '--repo'):
        if len(rest) < 2:
            sys.exit(USAGE)
        options[rest[0][2:].replace('-', '_')] = Path(rest[1])
        rest = rest[2:]
    if not rest:
        sys.exit(USAGE)
    mode, args = rest[0], rest[1:]
    tls = Tls(tls_dir=options['tls_dir'], repo=options['repo'])
    try:
        if mode == 'ensure' and not args:
            tls.ensure()
        elif mode == 'renew' and not args:
            tls.renew()
        elif mode == 'self-signed' and not args:
            tls.self_signed()
        elif mode == 'provided' and len(args) == 2:
            tls.install_provided(args[0], args[1])
        elif mode == 'names':
            tls.set_names(args)
            tls.ensure()
        elif mode == 'show' and not args:
            tls.show()
        elif mode == 'primary' and not args:
            print(tls.primary())
        elif mode == 'fingerprint' and not args:
            print(tls.fingerprint())
        else:
            sys.exit(USAGE)
    except (OSError, ValueError) as error:
        sys.exit(str(error) or repr(error))


if __name__ == '__main__':
    main(sys.argv[1:])
