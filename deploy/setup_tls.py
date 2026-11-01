"""Make, install and inspect the manager's TLS certificate (docs/sign-on/EXPOSURE.md section 3).

Run by ``deploy/setup-tls.sh`` with the system python3 on the VM; standard library only, ``openssl``
and ``ip`` are the tools. The tls directory ``/srv/containerlab-node-manager/tls`` is root's; the
container mounts it read-only at ``/tls`` and uvicorn reads ``cert.pem`` and ``key.pem`` from there.

    ensure            the default: a self-signed certificate exists, is not expiring, has its key and
                      names every certificate address, UI_ALLOWED_HOSTS name and tls/names entry;
                      otherwise a new one is made. A provided certificate is never touched, and a
                      certificate without a tls/mode file (not made by this tool) is never touched
                      either; when either cannot serve, ensure fails so the launcher stops before it
                      recreates a manager that cannot start. Also settles the ports (UI_PORT,
                      UI_HTTP_PORT) of the upgrade table (EXPOSURE.md 7.4) in the route's env file.
    prepare           recreate-manager.sh's step: settle the ports and require a usable pair; it never
                      generates (a missing name is ensure's business at the next start-manager.sh).
    renew             a new self-signed certificate now; refused while mode is provided or absent
    self-signed       switch back from provided (or adopt an unregistered pair) and generate
    provided CERT KEY validate and install an operator's certificate
    names [NAME...]   write tls/names (no names: remove it), then ensure
    show | primary | fingerprint   read-only, no root needed

``--route source|image`` (default source) names the env file the caller's compose command reads:
``clab-backup-ui/.env`` for ``clab-backup-ui/compose.yml`` (start-manager.sh, always) or
``deploy/image.env`` for the prepared-image route recreate-manager.sh may choose. The route is the
caller's decision, so this tool never asks Docker anything.

The certificate addresses are the stable global-scope addresses of the default-route interface(s):
never docker0, br-*, veth*, virbr*, cni*, clab*, loopback, link-local, nor a temporary (RFC 4941),
deprecated, tentative or failed address (REVIEW R18), so neither a lab deploy nor a privacy-address
rotation changes the certificate. The pure rule is ``certificate_addresses(routes, addresses)``; the
health check loads it from here so both sides apply the same one.

A replacement is one set, cert.pem, key.pem and mode (the mode moved last): the old files stay until
every new one is in place and are put back on any failure, and a file that did not exist before is
removed again, so the directory never holds a certificate without its key, a pair without its mode, or
a mode that describes another pair. A cert.pem that carries a PRIVATE KEY block is never widened to
0644 and never kept. Nothing here prints a key: errors quote file names, never contents. Notes that
are not the result (an ignored tls/names line, an env file this account cannot read) go to stderr, so
``primary`` and ``fingerprint`` stay one clean line on stdout.
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
MAX_COMMON_NAME = 64
EXCLUDED_INTERFACES = ('lo', 'docker', 'br-', 'veth', 'virbr', 'cni', 'clab')
UNSTABLE_FLAGS = ('temporary', 'deprecated', 'tentative', 'dadfailed')
# name -> (mode, group): the files of EXPOSURE.md 3.3; every owner is root.
FILES = {'cert.pem': (0o644, 0), 'key.pem': (0o640, WORKER_GID), 'mode': (0o644, 0), 'names': (0o644, 0)}
ROUTES = {'source': 'clab-backup-ui/.env', 'image': 'deploy/image.env'}
PORT_NOTE = ('Your settings keep the manager on port {port}, which now serves HTTPS; there is no plain-HTTP redirect. '
             'Old links to that port over plain HTTP show a browser error until retyped as `https://`. '
             'To get the redirect, set `UI_PORT=8443` and `UI_HTTP_PORT=8081` in `.env` and rerun.')
REGISTER_HINT = ('Register the pair with setup-tls.sh --cert PATH --key PATH (copies of the files), '
                 'or replace it with a new self-signed certificate: setup-tls.sh --self-signed.')


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


def _unstable(info):
    """A temporary (privacy), deprecated, tentative or failed address, or one whose preferred lifetime is over."""
    if any(info.get(flag) is True for flag in UNSTABLE_FLAGS):
        return True
    preferred = info.get('preferred_life_time')
    return isinstance(preferred, int) and not isinstance(preferred, bool) and preferred == 0


def _global_addresses(entry):
    infos = entry.get('addr_info')
    for info in infos if isinstance(infos, list) else ():
        if not isinstance(info, dict) or info.get('scope') != 'global' or info.get('family') not in ('inet', 'inet6'):
            continue
        if _unstable(info):
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
    (IPv4 and IPv6 entries concatenated) and ``ip -j address``: the stable global-scope addresses of
    the default-route interface(s), or of every non-excluded interface when there is no default
    route; never an address on an excluded interface, never loopback, link-local or a temporary,
    deprecated, tentative or failed address, in document order."""
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


def _plain(name):
    """A host value as the certificate names it: an IP literal without brackets, compressed; a name as is."""
    text = (name or '').strip()
    bare = text[1:-1] if text.startswith('[') and text.endswith(']') else text
    try:
        return ipaddress.ip_address(bare).compressed
    except ValueError:
        return text


def validate_name(value):
    """A tls/names entry: an IP address (returned compressed) or a host name without port or brackets
    (returned lower-case, at most 63 characters per label and 253 in all); anything else is refused
    with the value quoted."""
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
    if len(name) > 253 or any(len(label) > 63 for label in name.split('.')):
        raise ValueError(f'{text!r} is longer than a DNS name allows (63 characters per label, 253 in all).')
    return name


def san(value):
    return ('IP:' if _is_ip(value) else 'DNS:') + value


def _valid_host(host):
    return bool(host) and (_is_ip(host) or (allowed_hosts.host_name(host) == host and not host.startswith('[')))


def subject_names(addresses, hostname, allowed, names):
    """The SAN list, in order: the certificate addresses, the loopback names, the host name, every
    UI_ALLOWED_HOSTS name (an IP literal among them as an IP: entry), every tls/names entry; no duplicates."""
    entries = [san(a) for a in addresses] + ['IP:127.0.0.1', 'IP:::1', 'DNS:localhost']
    host = (hostname or '').strip().lower()
    if _valid_host(host):
        entries.append(san(host))
    entries += [san(_plain(name)) for name in allowed]
    entries += [san(name) for name in names]
    result = []
    for entry in entries:
        if entry not in result:
            result.append(entry)
    return result


def primary_name(allowed, names, addresses, hostname):
    """The primary name: the first UI_ALLOWED_HOSTS name, else the first tls/names entry that is a name,
    else the first IPv4 certificate address, else the host name."""
    for name in allowed:
        return _plain(name)
    for name in names:
        if not _is_ip(name):
            return name
    for address in addresses:
        if ipaddress.ip_address(address).version == 4:
            return address
    return (hostname or '').strip().lower() or 'localhost'


def common_name(plan):
    """The CN: the primary name when it fits X.509's 64-character limit, else the first candidate of the
    primary-name order that does (the SAN list carries the long name; the CN is cosmetic)."""
    host = (plan.get('hostname') or '').strip().lower()
    candidates = ([plan.get('primary') or ''] + [_plain(name) for name in plan.get('allowed', [])]
                  + [name for name in plan.get('names', []) if not _is_ip(name)]
                  + [address for address in plan.get('addresses', []) if ipaddress.ip_address(address).version == 4]
                  + ([host] if _valid_host(host) else []) + ['localhost'])
    return next(name for name in candidates if 0 < len(name) <= MAX_COMMON_NAME)


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


ENV_LINE = re.compile(r'^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$')


def _env_value(raw):
    """The value as docker compose reads it: quotes removed, an unquoted value ends at a `#` that follows
    whitespace, nothing evaluated."""
    raw = raw.strip()
    if raw[:1] in ('"', "'"):
        end = raw.find(raw[0], 1)
        return raw[1:end] if end > 0 else raw[1:]
    return re.split(r'\s+#', raw, maxsplit=1)[0].rstrip()


def env_values(path):
    """KEY=value pairs of a dotenv file (an `export` prefix allowed), last wins."""
    path = Path(path)
    if not path.is_file():
        return {}
    values = {}
    for line in path.read_text(encoding='utf-8', errors='replace').splitlines():
        match = ENV_LINE.match(line)
        if match:
            values[match[1]] = _env_value(match[2])
    return values


def _port(values, key, default):
    raw = values.get(key)
    if raw is None or raw == '':
        return default, False
    if not re.fullmatch(r'\d{1,5}', raw) or int(raw) > 65535 or (int(raw) == 0 and key != 'UI_HTTP_PORT'):
        raise ValueError(f'{key}={raw!r} is not a port number (1-65535' + (', or 0 to disable the redirect' if key == 'UI_HTTP_PORT' else '') + ').')
    return int(raw), True


# ---- the tool -------------------------------------------------------------------------------

def note(text):
    print(text, file=sys.stderr)


class Tls:
    def __init__(self, tls_dir=TLS_DIR, repo=REPO, run=subprocess.run, chown=os.chown, hostname=socket.gethostname, out=print,
                 replace=os.replace, err=note):
        self.tls_dir = Path(tls_dir)
        self.repo = Path(repo)
        self.run = run
        self.chown = chown
        self.hostname = hostname
        self.out = out
        self.err = err
        self.replace = replace

    # -- processes
    def command(self, argv, check=False):
        result = self.run(argv, capture_output=True, text=True, stdin=subprocess.DEVNULL)
        if check and result.returncode != 0:
            tail = (result.stderr or result.stdout or '').strip().splitlines()
            raise ValueError(f'{argv[0]} {argv[1]} failed' + (': ' + tail[-1] if tail else '') + '.')
        return result

    def _ip_json(self, argv):
        """Parsed JSON of one `ip -j` command; an absent or failing `ip` counts as an empty document."""
        try:
            result = self.command(['ip', *argv])
            return json.loads(result.stdout) if result.returncode == 0 else []
        except (OSError, ValueError):
            return []

    # -- the files
    def path(self, name):
        return self.tls_dir / name

    def file_owner(self, path):
        return os.stat(path).st_uid

    def link_owner(self, path):
        """The owner of a symlink itself (not of its target)."""
        return os.lstat(path).st_uid

    def directory_state(self, path):
        """(owner, permission bits) of a directory."""
        found = os.stat(path)
        return found.st_uid, stat.S_IMODE(found.st_mode)

    def check_directory(self):
        if self.tls_dir.is_symlink():
            raise ValueError(f'Refusing a symlink at {self.tls_dir}.')

    def prepare_directory(self):
        self.check_directory()
        if not self.tls_dir.is_dir():
            self.tls_dir.mkdir(mode=0o755)
            self.chown(self.tls_dir, 0, 0)
        os.chmod(self.tls_dir, 0o755)

    def set_owner(self, path, mode, gid):
        os.chmod(path, mode)
        self.chown(path, 0, gid)

    def stage(self, directory, name, data, mode, gid):
        """Write a file into a staging directory with its final mode and owner (fsync'd), not yet in place."""
        path = Path(directory) / name
        with open(path, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        self.set_owner(path, mode, gid)
        return path

    def install_bytes(self, name, data, mode, gid=0):
        """Write one file through a temporary name inside the tls directory, with its final mode and
        owner, then move it into place (the write_env discipline)."""
        fd, temporary = tempfile.mkstemp(prefix='.' + name + '-', dir=self.tls_dir)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            self.set_owner(temporary, mode, gid)
            os.replace(temporary, self.path(name))
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def install_files(self, staged, staging):
        """Move staged files (name -> staged path, in the order given; the mode last) into place as one
        replacement. Every existing target stays reachable through a hard link in the staging directory
        until every move succeeded; on any failure (a full disk, an interrupt) the old files are put back
        and a target that did not exist before is removed, so the directory never holds a certificate
        without its key, a pair without its mode, or a mode that describes another pair."""
        backups, created = [], []
        for name in staged:
            target = self.path(name)
            try:
                existing = os.lstat(target)
            except FileNotFoundError:
                created.append(target)
                continue
            if stat.S_ISREG(existing.st_mode):
                backup = Path(staging) / (name + '.old')
                os.link(target, backup)
                backups.append((target, backup))
        try:
            for name, source in staged.items():
                self.replace(source, self.path(name))
        except BaseException:
            for target, backup in backups:
                try:
                    os.replace(backup, target)
                except OSError:
                    pass
            for target in created:
                try:
                    os.unlink(target)
                except OSError:
                    pass
            raise

    def certificate_holds_a_key(self):
        """True when cert.pem carries a PRIVATE KEY block (a combined file copied in by hand): such a file
        is never widened to 0644, because every VM account can read cert.pem."""
        try:
            with open(self.path('cert.pem'), 'rb') as stream:
                head = stream.read(MAX_FILE + 1)
        except OSError:
            return False
        return re.search(rb'-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----', head) is not None

    def repair_modes(self):
        """Give every file of the directory its owner and mode of EXPOSURE.md 3.3 again; returns the
        names that needed it. Content is never touched: a wrong mode is no reason for a new fingerprint.
        A cert.pem that holds a private key is left as it is (pair_problem refuses it)."""
        repaired = []
        for name, (mode, gid) in FILES.items():
            path = self.path(name)
            try:
                existing = os.lstat(path)
            except OSError:
                continue
            if not stat.S_ISREG(existing.st_mode):
                continue
            if name == 'cert.pem' and self.certificate_holds_a_key():
                continue
            if stat.S_IMODE(existing.st_mode) != mode or existing.st_uid != 0 or existing.st_gid != gid:
                self.set_owner(path, mode, gid)
                repaired.append(name)
        if repaired:
            self.out('File modes repaired: ' + ', '.join(repaired) + '.')
        return repaired

    def read_mode(self):
        """'self-signed', 'provided', or None when tls/mode is absent or unreadable (a certificate this
        tool did not make, or an install that stopped before its mode write)."""
        try:
            value = self.path('mode').read_text(encoding='utf-8').strip()
        except OSError:
            return None
        return value if value in ('self-signed', 'provided') else None

    def write_mode(self, value):
        self.prepare_directory()
        self.install_bytes('mode', (value + '\n').encode(), 0o644)

    def names(self):
        """The entries of tls/names, each passed through validate_name (the file is documented as one entry
        per line and gets edited by hand): a line the certificate cannot carry as written is ignored with a
        note that quotes it, never fed to openssl and never a reason to regenerate on every start."""
        try:
            lines = self.path('names').read_text(encoding='utf-8').splitlines()
        except OSError:
            return []
        names = []
        for number, line in enumerate(lines, 1):
            if not line.strip():
                continue
            try:
                name = validate_name(line)
            except ValueError as error:
                self.err(f'tls/names line {number} ignored: {error} Rewrite the file with setup-tls.sh --name NAME (repeatable).')
                continue
            if name not in names:
                names.append(name)
        return names

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
    def env_file(self, route='source'):
        """The env file of a route: what the caller's compose command reads (ROUTES)."""
        if route not in ROUTES:
            raise ValueError(f'Unknown route {route!r}; expected source (clab-backup-ui/.env) or image (deploy/image.env).')
        return self.repo / ROUTES[route]

    def env_files(self):
        return [self.env_file(route) for route in ROUTES]

    def env_of(self, path):
        """The values of an env file; one this account cannot read (write_env makes .env 0600, and the
        read-only modes run as any account) counts as absent, with a note on stderr."""
        try:
            return env_values(path)
        except OSError as error:
            self.err(f'Note: {path} cannot be read by this account ({error.strerror or error}); '
                     'its UI_ALLOWED_HOSTS and port settings are not considered.')
            return {}

    def allowed_names(self):
        """Every UI_ALLOWED_HOSTS name of both env files, in the order written (the first is the primary
        name); an IP literal is returned bare and compressed."""
        names = []
        for path in self.env_files():
            text = self.env_of(path).get('UI_ALLOWED_HOSTS', '')
            accepted = allowed_hosts.configured_hosts(text)
            for entry in text.split(','):
                name = allowed_hosts.host_name(entry.strip()) if entry.strip() else None
                if name in accepted and _plain(name) not in names:
                    names.append(_plain(name))
        return names

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

    def public_keys_match(self, cert, key):
        """(matches, problem): whether the key's public key is the certificate's; the problem names the
        file that could not be read, never its contents."""
        key_public = self.command(['openssl', 'pkey', '-in', str(key), '-pubout', '-passin', 'pass:'])
        if key_public.returncode != 0:
            return False, f'{Path(key).name} cannot be read as a private key'
        cert_public = self.command(['openssl', 'x509', '-in', str(cert), '-noout', '-pubkey'])
        if cert_public.returncode != 0:
            return False, f'{Path(cert).name} cannot be read'
        if key_public.stdout.strip() != cert_public.stdout.strip():
            return False, f'{Path(key).name} does not match {Path(cert).name}'
        return True, None

    def pair_problem(self):
        """None, or why cert.pem and key.pem cannot serve (what uvicorn would hit at start)."""
        if not self.path('cert.pem').exists():
            return 'no certificate: cert.pem is missing'
        if self.certificate_holds_a_key():
            return 'cert.pem contains a private key (every VM account can read cert.pem; it must hold the certificate chain alone)'
        if self.certificate_facts() is None:
            return 'cert.pem cannot be read'
        key = self.path('key.pem')
        if key.is_symlink():
            return 'key.pem is a symlink'
        if not key.is_file():
            return 'key.pem is missing'
        return self.public_keys_match(self.path('cert.pem'), key)[1]

    def regeneration_reason(self, plan):
        problem = self.pair_problem()
        if problem:
            return problem
        if not self.valid_for(0):
            return 'the certificate has expired'
        if not self.valid_for(RENEW_WITHIN):
            return 'the certificate expires within 30 days'
        present = self.certificate_facts()['sans']
        missing = [entry for entry in plan['sans'] if entry not in present]
        if missing:
            return 'missing names: ' + ', '.join(missing)
        return None

    # -- the modes
    def generate(self, plan):
        self.prepare_directory()
        staging = Path(tempfile.mkdtemp(prefix='.tls-', dir=self.tls_dir))
        try:
            key, cert = staging / 'key.pem', staging / 'cert.pem'
            self.command(openssl_argv(common_name(plan), plan['sans'], key, cert), check=True)
            self.set_owner(key, *FILES['key.pem'])
            self.set_owner(cert, *FILES['cert.pem'])
            mode = self.stage(staging, 'mode', b'self-signed\n', *FILES['mode'])
            self.install_files({'cert.pem': cert, 'key.pem': key, 'mode': mode}, staging)
        finally:
            shutil.rmtree(staging, ignore_errors=True)

    def report(self, prefix='Certificate fingerprint (SHA-256): '):
        facts = self.certificate_facts()
        if facts:
            self.out(prefix + facts['fingerprint'])
        return facts

    def report_kept(self, label, renewal):
        """The one line of a certificate ensure keeps (provided or unregistered) with its expiry."""
        facts = self.certificate_facts()
        if not self.valid_for(0):
            self.out(f'{label} certificate kept; it EXPIRED on {facts["not_after"]}. {renewal}')
        elif not self.valid_for(RENEW_WITHIN):
            self.out(f'{label} certificate kept; it expires on {facts["not_after"]} (within 30 days). {renewal}')
        else:
            self.out(f'{label} certificate kept; expires {facts["not_after"]}.')

    def ensure(self, route='source'):
        """Returns the reason a certificate was made, or None when the existing one was kept. Raises when
        a certificate this tool must not replace cannot serve."""
        self.check_directory()
        self.settle_ports(route)
        plan = self.plan()
        mode = self.read_mode()
        self.repair_modes()
        if mode == 'provided':
            problem = self.pair_problem()
            if problem:
                raise ValueError(f'Provided certificate: {problem} in {self.tls_dir}; the manager cannot start with it. '
                                 'Install it again with setup-tls.sh --cert PATH --key PATH, or switch to a self-signed one with setup-tls.sh --self-signed.')
            self.report_kept('Provided', 'Install a new one with setup-tls.sh --cert PATH --key PATH.')
            self.report()
            return None
        if mode is None and self.path('cert.pem').exists():
            problem = self.pair_problem()
            if problem:
                raise ValueError(f'Unregistered certificate: {problem} in {self.tls_dir} (tls/mode is absent, so setup-tls.sh did not make these files); '
                                 'the manager cannot start with it. ' + REGISTER_HINT)
            self.out('cert.pem exists but tls/mode is absent: setup-tls.sh did not make this certificate and leaves it alone. ' + REGISTER_HINT)
            self.report_kept('Unregistered', REGISTER_HINT)
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

    def prepare(self, route='source'):
        """recreate-manager.sh's step before `up`: the ports of the route settled, the files usable and
        with their modes; never a new certificate (a changed name is ensure's business at the upgrade)."""
        self.check_directory()
        self.settle_ports(route)
        self.repair_modes()
        problem = self.pair_problem()
        if problem:
            raise ValueError(f'The manager cannot start: {problem} in {self.tls_dir} (uvicorn reads cert.pem and key.pem there). '
                             'Run sudo bash deploy/start-manager.sh to make or repair the certificate, '
                             'or setup-tls.sh --cert PATH --key PATH to install one.')
        self.out(f'TLS files ready ({self.read_mode() or "unregistered"} certificate).')
        self.report()

    def renew(self, force=False):
        self.check_directory()
        mode = self.read_mode()
        if not force and mode != 'self-signed' and self.path('cert.pem').exists():
            if mode == 'provided':
                raise ValueError('The certificate is a provided one; --renew applies to a self-signed certificate. '
                                 'Install a new provided certificate with --cert PATH --key PATH, or add --self-signed to switch back.')
            raise ValueError(f'The certificate in {self.tls_dir} was not made by setup-tls.sh (tls/mode is absent); --renew replaces only '
                             'a self-signed one. Add --self-signed to replace it with a new self-signed certificate.')
        plan = self.plan()
        self.generate(plan)
        self.out('New self-signed certificate for ' + ', '.join(plan['sans']) + f'; valid {DAYS} days. Browsers show their warning again.')
        self.report()

    def self_signed(self):
        self.renew(force=True)

    def _regular_file(self, path, what):
        """(path, bytes) of a given certificate or key file. A symlink is followed only when the link itself
        and its directory are root's, the directory is writable by root alone, and the target is a regular
        file owned by root (certbot's live/NAME links into archive/). A link anyone else could have planted
        (in /tmp, in a home directory) would otherwise carry any root-owned key on the host, such as an
        SSH host key, into tls/key.pem where the container reads it."""
        path = Path(path)
        if path.is_symlink():
            target = Path(os.path.realpath(path))
            try:
                resolved = os.stat(target)
            except OSError:
                raise ValueError(f'The {what} {path} is a symlink to {target}, which does not exist; give the file itself.') from None
            directory_owner, directory_mode = self.directory_state(path.absolute().parent)
            trusted = (self.link_owner(path) == 0 and directory_owner == 0 and not directory_mode & 0o022
                       and stat.S_ISREG(resolved.st_mode) and self.file_owner(target) == 0)
            if not trusted:
                raise ValueError(f'The {what} {path} is a symlink; a link is followed only when the link, its directory and its target '
                                 'are owned by root and the directory is writable by root alone (certbot\'s /etc/letsencrypt/live). '
                                 'Give the file itself.')
            path = target
        if not path.is_file():
            raise ValueError(f'The {what} {path} is not a regular file.')
        if path.stat().st_size > MAX_FILE:
            raise ValueError(f'The {what} {path} is larger than 64 KiB.')
        return path, path.read_bytes()

    def install_provided(self, cert_path, key_path):
        self.check_directory()
        cert_path, cert_bytes = self._regular_file(cert_path, 'certificate')
        key_path, key_bytes = self._regular_file(key_path, 'key')
        blocks = re.findall(rb'-----BEGIN ([A-Z0-9 ]+)-----', cert_bytes)
        if any(b'PRIVATE KEY' in block for block in blocks):
            raise ValueError(f'The certificate {cert_path} contains a PRIVATE KEY block; cert.pem is readable by every account on the VM, '
                             'so give the certificate chain alone as --cert and the key as --key.')
        if not blocks or any(block != b'CERTIFICATE' for block in blocks):
            found = ', '.join(sorted({block.decode() for block in blocks})) or 'none'
            raise ValueError(f'The certificate {cert_path} must hold only CERTIFICATE blocks (the chain, leaf first); found: {found}.')
        if b'ENCRYPTED' in key_bytes[:4096]:
            raise ValueError(f'The key {key_path} is encrypted; decrypt the key first (uvicorn cannot ask for a password at start).')
        if not self.valid_for(0, cert_path):
            raise ValueError(f'The certificate {cert_path} has expired or cannot be read.')
        sans = self.command(['openssl', 'x509', '-in', str(cert_path), '-noout', '-ext', 'subjectAltName'], check=True)
        names = san_entries(sans.stdout)
        if not names:
            raise ValueError(f'The certificate {cert_path} lists no subjectAltName; browsers need at least one name.')
        matches, problem = self.public_keys_match(cert_path, key_path)
        if not matches:
            if 'does not match' in problem:
                raise ValueError(f'The key {key_path} does not match the certificate {cert_path}.')
            raise ValueError(f'The key {key_path} cannot be read by openssl; decrypt the key first or check the file.')
        self.prepare_directory()
        staging = Path(tempfile.mkdtemp(prefix='.tls-', dir=self.tls_dir))
        try:
            cert = self.stage(staging, 'cert.pem', cert_bytes, *FILES['cert.pem'])
            key = self.stage(staging, 'key.pem', key_bytes, *FILES['key.pem'])
            mode = self.stage(staging, 'mode', b'provided\n', *FILES['mode'])
            self.install_files({'cert.pem': cert, 'key.pem': key, 'mode': mode}, staging)
        finally:
            shutil.rmtree(staging, ignore_errors=True)
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
        self.out('mode: ' + (self.read_mode() or 'none'))
        self.out('required: ' + ', '.join(plan['sans']))
        self.out('primary: ' + plan['primary'])

    # -- the ports of the upgrade table (EXPOSURE.md 7.4)
    def settle_ports(self, route='source'):
        """In the route's env file: refuses UI_PORT == UI_HTTP_PORT when both are explicit; writes
        UI_HTTP_PORT=0 when an explicit UI_PORT collides with the default redirect port (the standard
        upgrade path). Returns the line written, or None."""
        path = self.env_file(route)
        values = self.env_of(path)
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


USAGE = ('Usage: setup_tls.py [--tls-dir DIR] [--repo DIR] [--route source|image] '
         'ensure|prepare|renew|self-signed|provided CERT KEY|names [NAME...]|show|primary|fingerprint')


def main(argv):
    options = {'tls_dir': TLS_DIR, 'repo': REPO, 'route': 'source'}
    rest = list(argv)
    while rest and rest[0] in ('--tls-dir', '--repo', '--route'):
        if len(rest) < 2:
            sys.exit(USAGE)
        key = rest[0][2:].replace('-', '_')
        options[key] = rest[1] if key == 'route' else Path(rest[1])
        rest = rest[2:]
    if not rest or options['route'] not in ROUTES:
        sys.exit(USAGE)
    mode, args = rest[0], rest[1:]
    tls = Tls(tls_dir=options['tls_dir'], repo=options['repo'])
    try:
        if mode == 'ensure' and not args:
            tls.ensure(options['route'])
        elif mode == 'prepare' and not args:
            tls.prepare(options['route'])
        elif mode == 'renew' and not args:
            tls.renew()
        elif mode == 'self-signed' and not args:
            tls.self_signed()
        elif mode == 'provided' and len(args) == 2:
            tls.install_provided(args[0], args[1])
        elif mode == 'names':
            tls.set_names(args)
            tls.ensure(options['route'])
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
