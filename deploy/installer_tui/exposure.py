"""What the installers say about the manager's HTTPS door (standard library only).

Both front ends (the plain menu in install-manager.py and the full-screen installer) read the
same facts from here, so they cannot disagree: the ports in the manager's settings file, the
certificate in /srv/containerlab-node-manager/tls, the address people should open, and the
one-time setup code.

Nothing here writes anything or runs as root. The certificate (cert.pem, mode 0644) and its
`mode` file are public facts read with `openssl x509` as the ordinary account; the private key
is never touched. The setup code is the one secret: `read_setup_code` returns it to the caller
and keeps nothing, no caller stores it, and the installer's run record has no field for it
(EXPOSURE.md 7.2, REVIEW U13).
"""
import ipaddress
import json
import os
from pathlib import Path
import re
import ssl
import subprocess
from datetime import date, datetime
from urllib.request import HTTPSHandler, ProxyHandler, build_opener

TLS_DIR = Path('/srv/containerlab-node-manager/tls')
SETUP_CODE_FILE = '/srv/containerlab-node-manager/data/setup-code'
SETUP_CODE_COMMAND = 'sudo cat ' + SETUP_CODE_FILE
DEFAULT_TLS_PORT = 8443
DEFAULT_HTTP_PORT = 8081
MAX_ENV_BYTES = 65536
MAX_ADDRESSES = 3

SETUP_CODE_SHAPE = re.compile(r'[a-z0-9]{6}(?:-[a-z0-9]{6}){3}')
HOST_SHAPE = re.compile(r'[A-Za-z0-9._:\[\]-]{1,253}')
SSH_CONNECTION_SHAPE = re.compile(r'[0-9A-Fa-f:.]+ [0-9]{1,5} [0-9A-Fa-f:.]+ [0-9]{1,5}')


# ---- the settings file -----------------------------------------------------------------------
def env_values(source, keys):
    """Only the named keys of the checkout's clab-backup-ui/.env."""
    return env_file_values(Path(source) / 'clab-backup-ui' / '.env', keys)


def env_file_values(path, keys):
    """Only the named keys of one settings file (it also holds a session token). A symlink or a
    file over 64 KiB answers nothing, as the manager's own readers do."""
    path = Path(path)
    values = {}
    try:
        if path.is_symlink() or path.stat().st_size > MAX_ENV_BYTES:
            return values
        for line in path.read_text(errors='replace').splitlines():
            name, sep, value = line.partition('=')
            if sep and name.strip() in keys:
                values[name.strip()] = value.strip().strip('"\'')
    except OSError:
        pass
    return values


def _port(text, default):
    try:
        number = int(text)
    except (TypeError, ValueError):
        return default
    return number if 0 <= number <= 65535 else default


def ports(source, env_path=None):
    """(TLS port, plain-HTTP redirect port or 0), the defaults of EXPOSURE.md 2.4 when absent."""
    values = _port_values(source, env_path)
    tls = _port(values.get('UI_PORT') or None, DEFAULT_TLS_PORT) or DEFAULT_TLS_PORT
    redirect = _port(values.get('UI_HTTP_PORT') or None, DEFAULT_HTTP_PORT) if 'UI_HTTP_PORT' in values else DEFAULT_HTTP_PORT
    return tls, redirect


def _port_values(source, env_path):
    keys = ('UI_PORT', 'UI_HTTP_PORT')
    return env_file_values(env_path, keys) if env_path else env_values(source, keys)


def ports_collide(source, env_path=None):
    """EXPOSURE.md 7.4: an explicit UI_PORT=8081 with no UI_HTTP_PORT would put TLS on the port the
    redirect uses by default. Only this situation asks the advanced-mode question. `env_path` names
    a previous settings file that is about to be copied into the checkout."""
    values = _port_values(source, env_path)
    return 'UI_HTTP_PORT' not in values and _port(values.get('UI_PORT') or None, None) == DEFAULT_HTTP_PORT


# ---- the certificate -------------------------------------------------------------------------
def pinned_context(cafile):
    """A TLS client context that trusts exactly the manager's own certificate file. The host name
    is not checked (the installer asks 127.0.0.1 or [::1]; the certificate names the VM's
    addresses), which is safe because the only trusted certificate is the pinned one. A provided
    certificate's file is a chain without its root, so a trusted leaf or intermediate must be
    enough (partial chain); strict mode is off because a self-signed leaf is its own anchor."""
    context = ssl.create_default_context(cafile=str(cafile))
    context.check_hostname = False
    context.verify_flags |= ssl.VERIFY_X509_PARTIAL_CHAIN
    context.verify_flags &= ~ssl.VERIFY_X509_STRICT
    return context


def health_ready(url, cafile, timeout=3):
    """True when GET <url>/api/health over the pinned certificate answers 200 {"ready": true}."""
    opener = build_opener(ProxyHandler({}), HTTPSHandler(context=pinned_context(cafile)))
    with opener.open(url.rstrip('/') + '/api/health', timeout=timeout) as response:
        data = response.read(65536)
        if response.status != 200:
            return False
    body = json.loads(data)
    return isinstance(body, dict) and body.get('ready') is True


def _expiry(text):
    """'Nov  1 12:00:00 2028 GMT' as '2028-11-01'; the raw text when it does not parse."""
    try:
        return datetime.strptime(' '.join(text.split()), '%b %d %H:%M:%S %Y GMT').date().isoformat()
    except ValueError:
        return text.strip()


def days_left(expires, today=None):
    try:
        return (date.fromisoformat(expires) - (today or date.today())).days
    except ValueError:
        return None


def facts(tls_dir=None, run=subprocess.run):
    """The installed certificate's public facts, or None when it cannot be read.

    {'mode': 'self-signed'|'provided'|'unknown', 'fingerprint': 'AB:CD:…', 'expires': 'YYYY-MM-DD',
     'addresses': [IP certificate names], 'names': [DNS certificate names]}"""
    tls_dir = Path(tls_dir or TLS_DIR)
    try:
        result = run(['openssl', 'x509', '-in', str(tls_dir / 'cert.pem'), '-noout', '-fingerprint', '-sha256',
                      '-enddate', '-ext', 'subjectAltName'],
                     stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    text = result.stdout or ''
    fingerprint = re.search(r'Fingerprint=([0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){31})', text)
    ends = re.search(r'notAfter=(.+)', text)
    if not fingerprint or not ends:
        return None
    addresses, names = [], []
    for entry in re.findall(r'(IP Address|DNS):([^,\n]+)', text):
        kind, value = entry[0], entry[1].strip()
        if kind == 'DNS':
            names.append(value)
            continue
        try:
            addresses.append(str(ipaddress.ip_address(value)))
        except ValueError:
            continue
    try:
        mode = (tls_dir / 'mode').read_text().strip()
    except OSError:
        mode = ''
    return {'mode': mode if mode in ('self-signed', 'provided') else 'unknown',
            'fingerprint': fingerprint.group(1).upper(), 'expires': _expiry(ends.group(1)),
            'addresses': addresses, 'names': names}


def primary(source, run=subprocess.run):
    """`setup-tls.sh --primary`: the one name the installers print first (EXPOSURE.md 3.1), or None."""
    try:
        result = run(['bash', str(Path(source) / 'deploy/setup-tls.sh'), '--primary'],
                     stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    lines = (result.stdout or '').strip().splitlines()
    return lines[0].strip() if len(lines) == 1 and HOST_SHAPE.fullmatch(lines[0].strip()) else None


def host_url(host, port, path='/'):
    """https://host[:port]/path; the port is left out for 443 and an IPv6 literal gets its brackets."""
    if ':' in host and not host.startswith('['):
        host = f'[{host}]'
    return f'https://{host}' + ('' if port == 443 else f':{port}') + path


def _usable(address):
    try:
        value = ipaddress.ip_address(address)
    except ValueError:
        return False
    return not (value.is_loopback or value.is_link_local or value.is_unspecified)


def access_urls(name, certificate, port):
    """The addresses to open: https://<primary>:<port>/ first, then each IP certificate name that
    differs from it, at most three in all. Never the interface list (REVIEW R18): it holds docker0
    and every containerlab bridge. The certificate names only the addresses a person can reach, so a
    URL here never adds a name-mismatch warning to the self-signed one. Without a primary name the line says <VM address>."""
    urls = []
    if name:
        urls.append(host_url(name, port))
    for address in (certificate or {}).get('addresses', []):
        if len(urls) >= MAX_ADDRESSES:
            break
        if address != name and _usable(address) and host_url(address, port) not in urls:
            urls.append(host_url(address, port))
    return urls or [host_url('<VM address>', port)]


def certificate_sentence(certificate):
    """The one sentence about the certificate the closing output and the summary screen carry."""
    if not certificate:
        return ('The certificate could not be read here; bash deploy/setup-tls.sh --show prints its '
                'fingerprint.')
    if certificate['mode'] == 'provided':
        return (f'The certificate is the one you provided (expires {certificate["expires"]}). After a first HTTPS '
                'visit the browser applies HSTS to every port of its name: open plain-HTTP lab services on that '
                'name by IP address.')
    return ('The certificate is self-signed: the browser warns once; its SHA-256 fingerprint is '
            + certificate['fingerprint'] + '.')


# ---- the session's own SSH port --------------------------------------------------------------
def ssh_connection(environ=None):
    """SSH_CONNECTION of the installing session when it has the sshd shape, else None. The firewall
    script uses its server port to refuse a rule set that would lock this very session out."""
    value = (os.environ if environ is None else environ).get('SSH_CONNECTION', '')
    return value if SSH_CONNECTION_SHAPE.fullmatch(value) else None


def session_ssh_port(environ=None):
    value = ssh_connection(environ)
    return value.split()[3] if value else None


# ---- the setup code --------------------------------------------------------------------------
def parse_setup_code(text):
    """('setup'|'recover', code) from the file's two lines, or None for anything else."""
    values = {}
    for line in (text or '').splitlines()[:4]:
        key, sep, value = line.partition('=')
        if sep:
            values[key.strip()] = value.strip()
    mode, code = values.get('mode'), values.get('code', '')
    if mode in ('setup', 'recover') and SETUP_CODE_SHAPE.fullmatch(code):
        return mode, code
    return None


def read_setup_code(cwd=None, sudo=('sudo',), interactive=True, run=subprocess.run):
    """Read the code file now, as root through sudo: (state, mode, code).

    state is 'open' (mode and code are set), 'absent' (the manager has an administrator) or
    'unreadable' (sudo refused, a timeout, a file that is not the two-line form). `interactive`
    lets the plain menu's sudo ask for a password on the terminal; the full-screen installer
    passes False with `sudo -n`. The code goes back to the caller only: it is never logged, never
    stored here and never part of an exception text."""
    try:
        result = run([*sudo, 'cat', SETUP_CODE_FILE], cwd=cwd, stdin=None if interactive else subprocess.DEVNULL,
                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return 'unreadable', None, None
    if result.returncode == 0:
        parsed = parse_setup_code(result.stdout)
        return ('open', *parsed) if parsed else ('unreadable', None, None)
    if 'no such file' in (result.stderr or '').lower():
        return 'absent', None, None
    return 'unreadable', None, None


def setup_lines(reading, base):
    """The closing lines about signing in. `base` is the first address, 'https://host:8443/'.
    The code is only ever in the returned text, which the caller prints to the operator's terminal."""
    state, mode, code = reading
    base = base.rstrip('/')
    if state == 'open':
        if mode == 'recover':
            return [f'Open {base}/setup?recover=1 within 15 minutes and enter this recovery code: {code}',
                    'It is also readable on the VM with: ' + SETUP_CODE_COMMAND]
        return [f'Open {base}/setup and enter this setup code: {code}',
                'It is also readable on the VM with: ' + SETUP_CODE_COMMAND]
    if state == 'absent':
        return [f'An administrator exists; sign in at {base}/']
    return ['The setup code could not be read here. On the VM, run: ' + SETUP_CODE_COMMAND]
