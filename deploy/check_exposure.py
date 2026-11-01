"""TLS, firewall and exposure checks for check-install.py (EXPOSURE.md 6.2). Read-only, standard library only.

The group answers: is the manager served over TLS with the installed certificate, does the plain-HTTP port
only redirect, are the VM's other doors (firewall, listeners, published container ports, SSH) closed, and is
a sign-on setup or recovery code still waiting. It never changes anything, never reads a private key and
never prints the setup code, a key or a hash. Every fact comes through ctx.run (a fixed argv, usually
privileged) or the two HTTP helpers ctx.head (three fixed questions) and ctx.module (the certificate rule).
"""
from datetime import datetime, timezone
import importlib.util
import ipaddress
import json
from pathlib import Path
import re
import time

TLS_DIR = '/srv/containerlab-node-manager/tls'
DATA_DIR = '/srv/containerlab-node-manager/data'
SETUP_CODE = DATA_DIR + '/setup-code'
DOCKER = ['docker', '--host', 'unix:///var/run/docker.sock']
DEFAULT_UI_PORT = 8443
DEFAULT_HTTP_PORT = 8081
HSTS_VALUE = 'max-age=15552000'
RECOVERY_SECONDS = 15 * 60
BROAD_RANGE = 1000  # a tcp range wider than this many ports, open to anywhere, is a blanket allow
CAPTURE_PORTS = (5001, 5801)
DOCKER_FIX = 'Check sudo systemctl status docker; rerun the installer if Docker is missing.'
SECURITY_GROUP = ' A cloud security group is an accepted reason to ignore this warning.'

# Owner, group and mode of EXPOSURE 3.3. The script reports metadata only: it opens no file, so no key material
# and no hash can reach the report.
TLS_PROBE = '''import json,os,stat,sys
out=[]
for name in sys.argv[1:]:
    r={'path':name,'kind':'missing','uid':-1,'gid':-1,'mode':0}
    try:
        m=os.lstat(name)
        kind='link' if stat.S_ISLNK(m.st_mode) else 'dir' if stat.S_ISDIR(m.st_mode) else 'file' if stat.S_ISREG(m.st_mode) else 'other'
        r.update(kind=kind,uid=m.st_uid,gid=m.st_gid,mode=stat.S_IMODE(m.st_mode))
    except OSError: pass
    out.append(r)
print(json.dumps(out))
'''
# Whether the setup-code file exists, answered on stdout so that sudo's own chatter on stderr (an unresolvable host name
# is printed on every call of a renamed cloud VM) and its exit status 1 cannot be taken for "absent". Only lstat is
# called: the file is never opened here. An error other than "no such file" exits non-zero and prints nothing.
SETUP_PROBE = '''import os,sys
try:
    os.lstat(sys.argv[1])
except FileNotFoundError:
    print("absent")
except OSError:
    sys.exit(2)
else:
    print("present")
'''
EXPECTED = {'': ('dir', 0, 0, 0o755), '/cert.pem': ('file', 0, 0, 0o644), '/key.pem': ('file', 0, 10001, 0o640),
            '/mode': ('file', 0, 0, 0o644), '/names': ('file', 0, 0, 0o644)}


def env_values(text):
    """Last assignment wins, like start-manager.sh's env_value; the text is never evaluated."""
    values = {}
    for line in (text or '').splitlines():
        match = re.match(r'^([A-Z][A-Z0-9_]*)=(.*)$', line)
        if match:
            value = match[2].strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in '"\'':
                value = value[1:-1]
            values[match[1]] = value
    return values


def port_value(text, default):
    try:
        port = int(text)
    except (TypeError, ValueError):
        return default
    return port if 0 <= port <= 65535 else default


def command_port(command):
    if isinstance(command, list) and '--port' in command:
        try:
            return int(command[command.index('--port') + 1])
        except (ValueError, IndexError):
            return None
    return None


def settings(ctx):
    """UI_PORT, UI_HTTP_PORT and the listed host names from the two environment files (the running manager's own
    --port wins for UI_PORT). Secrets in those files are parsed past and never kept."""
    first = second = {}
    for index, relative in enumerate(('clab-backup-ui/.env', 'deploy/image.env')):
        result = ctx.run(['cat', str(ctx.source / relative)], privileged=True)
        values = env_values(result.stdout) if result.ok else {}
        if index == 0:
            first = values
        else:
            second = values
    merged = dict(second, **first)
    ui_port = command_port(ctx.manager_command) or port_value(merged.get('UI_PORT'), DEFAULT_UI_PORT)
    http_port = port_value(merged.get('UI_HTTP_PORT'), DEFAULT_HTTP_PORT) if merged.get('UI_HTTP_PORT', '') != '' else DEFAULT_HTTP_PORT
    hosts = ','.join(value for value in (first.get('UI_ALLOWED_HOSTS', ''), second.get('UI_ALLOWED_HOSTS', '')) if value)
    return ui_port, http_port, listed_names(ctx, hosts)


def listed_names(ctx, text):
    entries = [entry.strip() for entry in text.split(',') if entry.strip()]
    try:
        spec = importlib.util.spec_from_file_location('allowed_hosts', ctx.source / 'clab-backup-ui/app/allowed_hosts.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        names = [module.host_name(entry) for entry in entries]  # host_name is silent; configured_hosts prints a notice
    except Exception:
        names = [entry.lower().rsplit(':', 1)[0] if re.search(r':\d+$', entry) and entry.count(':') == 1 else entry.lower() for entry in entries]
    return [name for name in names if name]


def san_key(value):
    """('ip', normalised) for an address, ('dns', lower-case) for a name; None when it is neither."""
    text = str(value).strip().strip('[]').lower()
    if not text:
        return None
    try:
        return 'ip', str(ipaddress.ip_address(text))
    except ValueError:
        return 'dns', text


def docker_skip(ctx, ident, title):
    ctx.add(ident, 'SKIP', title, 'Docker access is required for this check.', DOCKER_FIX)


def local_host(ctx):
    """The host part of the manager's own address (the bind address the container command names), loopback by default."""
    if ctx.base_url:
        netloc = ctx.base_url.split('://', 1)[-1].split('/', 1)[0]
        host = netloc.rsplit(':', 1)[0]
        if host:
            return host
    return '127.0.0.1'


def sshd_facts(ctx):
    result = ctx.run(['/usr/sbin/sshd', '-T', '-C', f"user={ctx.owner or 'root'},host=localhost,addr=127.0.0.1"], privileged=True, timeout=5)
    values, ports = {}, []
    if not result.ok:
        return None, [22]
    for line in result.stdout.splitlines():
        fields = line.split()
        if len(fields) >= 2:
            if fields[0] == 'port' and fields[1].isdigit():
                ports.append(int(fields[1]))
            else:
                values.setdefault(fields[0].lower(), fields[1].lower())
    return values, list(dict.fromkeys(ports)) or [22]


def check_files(ctx):
    """tls.files. Returns the validated mode word ('' when invalid) and the operator's names."""
    title = 'TLS certificate files'
    paths = [TLS_DIR + suffix for suffix in EXPECTED]
    records = None
    from_probe = ctx.run(['/usr/bin/python3', '-I', '-c', TLS_PROBE, *paths], privileged=True)
    try:
        value = json.loads(from_probe.stdout) if from_probe.ok else None
    except ValueError:
        value = None
    if isinstance(value, list):
        records = {row.get('path'): row for row in value if isinstance(row, dict)}
    mode_result = ctx.run(['cat', TLS_DIR + '/mode'])
    mode = mode_result.stdout.strip() if mode_result.ok else ''
    fix = ctx.repair('setup-tls.sh')
    if records is None:
        ctx.add('tls.files', 'FAIL', title, 'The TLS files could not be inspected.', fix)
        return '', []
    problems = []
    for suffix, (kind, uid, gid, wanted) in EXPECTED.items():
        row = records.get(TLS_DIR + suffix, {})
        name = 'the TLS directory' if not suffix else suffix.lstrip('/')
        if row.get('kind') == 'missing' or not row:
            if suffix != '/names':
                problems.append(name + ' is missing')
            continue
        if row.get('kind') != kind:
            problems.append(f"{name} is not a regular {'directory' if kind == 'dir' else 'file'} (a symlink or another type is refused)")
        elif (row.get('uid'), row.get('gid')) != (uid, gid):
            problems.append(f"{name} is owned by {row.get('uid')}:{row.get('gid')}, expected {uid}:{gid}")
        elif row.get('mode') != wanted:
            problems.append(f"{name} has mode {row.get('mode', 0):04o}, expected {wanted:04o}")
    if mode not in ('self-signed', 'provided'):
        problems.append('the mode file does not say self-signed or provided')
        mode = ''
    if problems:
        ctx.add('tls.files', 'FAIL', title, 'Not as expected: ' + '; '.join(problems) + '.', fix)
    else:
        ctx.add('tls.files', 'PASS', title, f'Directory, certificate, key and mode file have the expected owners and modes; mode {mode}.')
    names = []
    if records.get(TLS_DIR + '/names', {}).get('kind') == 'file':
        text = ctx.run(['cat', TLS_DIR + '/names'])
        names = [line.strip() for line in text.stdout.splitlines() if line.strip()] if text.ok else []
    return mode, names


def check_certificate(ctx, mode):
    title = 'TLS certificate'
    result = ctx.run(['openssl', 'x509', '-noout', '-enddate', '-fingerprint', '-sha256', '-in', TLS_DIR + '/cert.pem'])
    lines = result.stdout.splitlines() if result.ok else []
    end = next((line for line in lines if line.startswith('notAfter=')), '')
    fingerprint = next((line for line in lines if 'Fingerprint=' in line), '')
    try:
        expires = datetime.strptime(' '.join(end.split('=', 1)[1].split()), '%b %d %H:%M:%S %Y %Z').replace(tzinfo=timezone.utc)
    except (IndexError, ValueError):
        expires = None
    fix = ctx.repair('setup-tls.sh', '--renew') + ' (self-signed) or ' + ctx.repair('setup-tls.sh', '--cert', 'CERT.pem', '--key', 'KEY.pem') + ' (provided)'
    if expires is None or not fingerprint:
        ctx.add('tls.cert', 'FAIL', title, 'The installed certificate could not be read or parsed by openssl.', fix)
    else:
        days = (expires - datetime.now(timezone.utc)).total_seconds() / 86400
        detail = f"{end}; mode {mode or 'unknown'}; {fingerprint}"
        if days <= 0:
            ctx.add('tls.cert', 'FAIL', title, 'Expired. ' + detail, fix)
        elif days < 30:
            ctx.add('tls.cert', 'WARN', title, f'Expires in {int(days)} day(s). ' + detail, fix)
        else:
            ctx.add('tls.cert', 'PASS', title, detail)
    if mode == 'provided':
        ctx.add('tls.hsts-scope', 'INFO', 'HSTS covers every port of the name',
                'With a trusted certificate, browsers that opened https://<name> apply HSTS to every port of that name for 180 days: '
                'http://<name>:<UI_HTTP_PORT> and plain-HTTP lab services on that name are opened by IP address or before the first HTTPS visit.')


def check_names(ctx, hosts, listed):
    title = 'TLS certificate names'
    fix = ctx.repair('setup-tls.sh') + ' (regenerates a self-signed certificate) or install a new provided certificate'
    sans = ctx.run(['openssl', 'x509', '-noout', '-ext', 'subjectAltName', '-in', TLS_DIR + '/cert.pem'])
    if not sans.ok or 'Subject Alternative Name' not in sans.stdout:
        ctx.add('tls.names', 'SKIP', title, 'The certificate names could not be read, so they were not compared.', fix)
        return
    present = {san_key(value) for _, value in re.findall(r'(DNS|IP Address):([^,\s]+)', sans.stdout)}
    routes = []
    for argv in (['ip', '-j', 'route', 'show', 'default'], ['ip', '-6', '-j', 'route', 'show', 'default']):
        result = ctx.run(argv, limit=1024 * 1024)
        try:
            value = json.loads(result.stdout) if result.ok else []
        except ValueError:
            value = []
        routes += value if isinstance(value, list) else []
    result = ctx.run(['ip', '-j', 'address'], limit=1024 * 1024)
    try:
        addresses = json.loads(result.stdout) if result.ok else []
    except ValueError:
        addresses = []
    addresses = addresses if isinstance(addresses, list) else []
    required = []
    try:
        wanted = ctx.module('setup_tls').certificate_addresses(routes, addresses)
    except Exception:  # the rule lives in a sibling script; a missing or damaged one must not hide the other checks
        ctx.add('tls.names', 'SKIP', title, 'The certificate rule of setup-tls.sh could not be loaded, so the names were not compared.', fix)
        return
    for address in wanted:
        key = san_key(address)
        if key and key[0] == 'ip':
            ip = ipaddress.ip_address(key[1])
            if not (ip.is_loopback or ip.is_link_local):  # the rule never names these; belt and braces for the report
                required.append(key)
    required += [key for key in (san_key(name) for name in [*listed, *hosts]) if key]
    missing = []
    for key in dict.fromkeys(required):
        if key not in present:
            missing.append(key[1])
    if missing:
        ctx.add('tls.names', 'WARN', title, 'Not in the certificate: ' + ', '.join(missing) + '. Browsers show a name warning for them.', fix)
    else:
        ctx.add('tls.names', 'PASS', title, 'Every certificate address, listed host name and operator name is in the certificate.')


def check_bind(ctx):
    title = 'TLS listener configuration'
    if not ctx.container:
        return docker_skip(ctx, 'tls.bind', title)
    command = ctx.manager_command
    if not isinstance(command, list):
        ctx.add('tls.bind', 'SKIP', title, 'The manager start command could not be read.', ctx.repair('start-manager.sh'))
        return
    bind = command[command.index('--host') + 1] if '--host' in command[:-1] else '?'
    port = command[command.index('--port') + 1] if '--port' in command[:-1] else '?'
    fix = ctx.repair('start-manager.sh')
    if '--ssl-certfile' not in command or '--ssl-keyfile' not in command:
        ctx.add('tls.bind', 'FAIL', title, f'The manager serves plain HTTP on {bind}:{port}: its start command has no --ssl-certfile and --ssl-keyfile.', fix)
    elif '--no-proxy-headers' not in command:
        ctx.add('tls.bind', 'WARN', title, f'TLS is configured on {bind}:{port}, but --no-proxy-headers is missing (an older compose file).', fix)
    else:
        ctx.add('tls.bind', 'PASS', title, f'TLS arguments and --no-proxy-headers are set; bind {bind}, port {port}.')


def check_listener(ctx):
    """tls.listener. Returns (status, headers) of the pinned HTTPS answer, or None when it was not asked."""
    title = 'TLS listener'
    if not ctx.container:
        docker_skip(ctx, 'tls.listener', title)
        return None
    if ctx.tls_context is None:
        ctx.add('tls.listener', 'SKIP', title, 'The installed certificate could not be read, so the TLS listener was not probed.', ctx.repair('setup-tls.sh'))
        return None
    if not ctx.base_url:
        ctx.add('tls.listener', 'SKIP', title, 'The manager has no usable HTTPS address, so the TLS listener was not probed.', ctx.repair('start-manager.sh'))
        return None
    status, headers = ctx.head('/api/health')
    if status == 200:
        ctx.add('tls.listener', 'PASS', title, 'The listener answered over TLS with the installed certificate pinned.')
    else:
        reason = 'did not answer or presented another certificate than the installed one' if status is None else f'answered HTTP {status}'
        ctx.add('tls.listener', 'FAIL', title, 'The pinned HTTPS request ' + reason + '.',
                ctx.repair('setup-tls.sh', '--show') + ', then ' + ctx.repair('recreate-manager.sh'))
    return status, headers if isinstance(headers, dict) else {}


def check_redirect(ctx, host, ui_port, http_port):
    title = 'HTTP redirect'
    problems, warnings = [], []
    if http_port:
        expected = 'https://' + host + ('' if ui_port == 443 else f':{ui_port}') + '/'
        status, headers = ctx.head('/', base=f'http://{host}:{http_port}')
        if status == 200:
            problems.append(f'plain HTTP serves a page on the redirect port {http_port}')
        elif status == 301 and (headers or {}).get('location') == expected:
            pass
        elif status is not None and 300 <= status < 400 and (headers or {}).get('location') and not str(headers['location']).lower().startswith('https://'):
            # The gate answers `/` with 302 /login: a redirect that stays on plain HTTP carries the sign-in form in cleartext.
            problems.append(f'plain HTTP on the redirect port {http_port} redirects to an address that is not https://')
        elif status is None:
            running = ctx.run([*DOCKER, 'compose', '-f', str(ctx.source / 'clab-backup-ui/compose.yml'), 'ps', '--status', 'running', '--quiet', 'http-redirect'],
                              privileged=True) if ctx.container else None
            warnings.append(f'the redirect on port {http_port} did not answer' + (' and the http-redirect container is not running' if running is not None and running.ok and not running.stdout.strip() else ''))
        elif status == 301:
            warnings.append(f"the redirect on port {http_port} points to {str((headers or {}).get('location', '(no Location)'))[:120]}, not {expected}")
        else:
            warnings.append(f'the redirect on port {http_port} answered HTTP {status}, expected 301')
    plain, _ = ctx.head('/', base=f'http://{host}:{ui_port}')
    if plain is not None:
        # uvicorn with --ssl-* never answers a plain-HTTP request, so any HTTP answer (a gated manager answers 302 /login,
        # not 200) means the port is served without TLS.
        problems.append(f'plain HTTP is answered on the TLS port {ui_port} (HTTP {plain})')
    fix = ctx.repair('start-manager.sh')
    if problems:
        ctx.add('http.redirect', 'FAIL', title, 'Plain HTTP is exposed: ' + '; '.join(problems + warnings) + '.', fix)
    elif warnings:
        text = '; '.join(warnings)
        ctx.add('http.redirect', 'WARN', title, text[0].upper() + text[1:] + '.', fix)
    elif not http_port:
        ctx.add('http.redirect', 'INFO', title, f'HTTP redirect disabled (UI_HTTP_PORT=0); the TLS port {ui_port} refuses plain HTTP.')
    else:
        ctx.add('http.redirect', 'PASS', title, f'Port {http_port} answers 301 to the HTTPS address; the TLS port {ui_port} refuses plain HTTP.')


def check_hsts(ctx, listener):
    title = 'HSTS header'
    if not ctx.container:
        return docker_skip(ctx, 'http.hsts', title)
    if ctx.tls_context is None:
        ctx.add('http.hsts', 'SKIP', title, 'The installed certificate could not be read, so the TLS listener was not probed.', ctx.repair('setup-tls.sh'))
    elif listener is None or listener[0] != 200:
        ctx.add('http.hsts', 'SKIP', title, 'The TLS listener did not answer, so the header was not read.', ctx.repair('start-manager.sh'))
    elif listener[1].get('strict-transport-security') == HSTS_VALUE:
        ctx.add('http.hsts', 'PASS', title, 'Strict-Transport-Security: ' + HSTS_VALUE + ' is sent.')
    else:
        ctx.add('http.hsts', 'WARN', title, 'The Strict-Transport-Security header is absent or has another value (an older image).', ctx.repair('start-manager.sh'))


def port_allowed(rules, port):
    return any(low <= port <= high for low, high in rules)


UFW_ACTION = re.compile(r'^(.*?)\s+(?:ALLOW|LIMIT)\s+IN(?:\s+(.*))?$')


def ufw_rules(text):
    """(rules, broad): the tcp port ranges that ufw allows in, and the descriptions of the blanket allows among
    them. Only inbound rows count: `ufw status verbose` prints the direction, and an `ALLOW OUT` or `ALLOW FWD` row
    opens nothing here. The To column may carry an interface (`Anywhere on eth0`, `8443/tcp on eth0`), an
    application profile (`22/tcp (OpenSSH)`) and `(v6)`. A blanket allow is a rule from anywhere (the source is not
    limited) to every port or to a tcp range wider than BROAD_RANGE ports, on every interface or on any interface but
    loopback. A rule limited to a source address does not count as blanket."""
    rules, broad = [], []
    for line in text.splitlines():
        match = UFW_ACTION.match(line.rstrip())
        if not match:
            continue
        column = match[1]
        interface = re.search(r'\bon\s+(\S+)', column)
        interface = interface[1] if interface else ''
        column = re.sub(r'\bon\s+\S+', ' ', column)
        while True:  # an application profile and (v6), nested: `22/tcp (OpenSSH (v6))`
            stripped = re.sub(r'\([^()]*\)', ' ', column)
            if stripped == column:
                break
            column = stripped
        spec, _, proto = column.strip().partition('/')
        if proto == 'udp':
            continue
        if interface == 'lo':
            continue  # loopback is not an opening to the network
        where = f' on {interface}' if interface else ''
        everywhere = (match[2] or '').strip().lower().startswith('anywhere')
        if spec.lower() == 'anywhere':
            rules.append((1, 65535))
            if everywhere:
                broad.append('every port' + where)
            continue
        for part in spec.split(','):
            low, _, high = part.partition(':')
            if low.isdigit() and (not high or high.isdigit()):
                rules.append((int(low), int(high or low)))
                if everywhere and high and int(high) - int(low) + 1 > BROAD_RANGE:
                    broad.append(f'tcp {low}-{high}' + where)
    return rules, list(dict.fromkeys(broad))


def check_firewall(ctx, ui_port, http_port, ssh_ports):
    title = 'Host firewall'
    fix = ctx.repair('setup-firewall.sh')
    if not ctx.run(['test', '-x', '/usr/sbin/ufw']).ok:
        ctx.add('firewall', 'FAIL', title, 'ufw is not installed, so the VM has no host firewall.' + SECURITY_GROUP, fix)
        return
    result = ctx.run(['/usr/sbin/ufw', 'status', 'verbose'], privileged=True)
    if not result.ok:
        ctx.add('firewall', 'WARN', title, 'The firewall state could not be read.', fix)
        return
    text = result.stdout
    needed = [(f'SSH ({port})' if port in ssh_ports else str(port), port) for port in [*ssh_ports, ui_port, *([http_port] if http_port else [])]]
    rules, broad = ufw_rules(text)
    if not re.search(r'^Status:\s*active', text, re.MULTILINE):
        ctx.add('firewall', 'WARN', title, 'ufw is inactive.' + SECURITY_GROUP, fix)
        return
    problems = []
    default = re.search(r'Default:\s*(\w+)\s*\(incoming\)', text)
    if not default or default[1].lower() not in ('deny', 'reject'):
        problems.append('incoming traffic is not denied by default')
    blocked = [label for label, port in needed if not port_allowed(rules, port)]
    if blocked:
        problems.append('not allowed: ' + ', '.join(blocked))
    if broad:
        problems.append('a rule allows ' + ' and '.join(broad) + ' from anywhere, which opens more than the ports above')
    if problems:
        ctx.add('firewall', 'WARN', title, 'ufw is active but ' + '; '.join(problems) + '.' + SECURITY_GROUP, fix)
    else:
        ctx.add('firewall', 'PASS', title, 'ufw is active, denies incoming traffic by default and allows ' + ', '.join(label for label, _ in needed) + '.')


def loopback(host):
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return ip.is_loopback or bool(getattr(ip, 'ipv4_mapped', None) and ip.ipv4_mapped.is_loopback)


def check_listeners(ctx, ui_port, http_port, ssh_ports):
    title = 'Listening TCP ports'
    result = ctx.run(['ss', '-Hltnp'], privileged=True, limit=1024 * 1024)
    if not result.ok:
        ctx.add('exposure.listeners', 'SKIP', title, 'The listening sockets could not be listed.')
        return
    allowed = {*ssh_ports, ui_port, *([http_port] if http_port else [])}
    seen, unexpected, capture, fine = {}, [], [], []
    for line in result.stdout.splitlines():
        fields = line.split()
        if len(fields) < 4:
            continue
        host, _, port = fields[3].rpartition(':')
        host = host.strip('[]').split('%')[0]
        if not port.isdigit():
            continue
        port = int(port)
        process = re.search(r'users:\(\("([^"]+)"', line)
        label = f"{port} ({process[1] if process else 'unknown process'})"
        if loopback(host):
            continue
        if (port, label) in seen:
            continue
        seen[(port, label)] = True
        (fine if port in allowed else unexpected).append(label)
    for port in CAPTURE_PORTS:
        public = [label for (number, label) in seen if number == port]
        capture += public
    if capture:
        ctx.add('exposure.listeners', 'FAIL', title, 'The capture stack is not loopback-only: ' + ', '.join(capture) + '.',
                'Close or firewall the listed port; the capture stack must stay on 127.0.0.1 (deploy/compose.capture.yml).')
    elif unexpected:
        ctx.add('exposure.listeners', 'WARN', title, 'Other non-loopback listeners: ' + ', '.join(unexpected) + '.',
                'Close or firewall the listed port; the capture stack must stay on 127.0.0.1 (deploy/compose.capture.yml).')
    else:
        ctx.add('exposure.listeners', 'PASS', title, 'Only SSH, the HTTPS port and the redirect port listen beyond loopback: ' + (', '.join(fine) or 'none') + '.')


def check_ports(ctx):
    title = 'Container published ports'
    if not ctx.container:
        return docker_skip(ctx, 'exposure.ports', title)
    result = ctx.run([*DOCKER, 'ps', '--format', '{{.Names}}\t{{.Ports}}'], privileged=True, limit=1024 * 1024)
    if not result.ok:
        ctx.add('exposure.ports', 'SKIP', title, 'The running containers could not be listed.', DOCKER_FIX)
        return
    exposed = []
    for line in result.stdout.splitlines():
        name, _, ports = line.partition('\t')
        for chunk in ports.split(','):
            match = re.match(r'^\s*(.*):(\d+(?:-\d+)?)->', chunk)
            if match and not loopback(match[1].strip('[]')):
                exposed.append(f'{name.strip()} publishes port {match[2]}')
    if exposed:
        ctx.add('exposure.ports', 'WARN', title, 'Published beyond loopback: ' + '; '.join(dict.fromkeys(exposed)) + '.',
                'Remove ports: from the topology or bind them to 127.0.0.1; Docker-published ports bypass ufw.')
    else:
        ctx.add('exposure.ports', 'PASS', title, 'No running container publishes a port beyond loopback.')


def check_bootstrap(ctx, ui_port):
    title = 'Sign-on setup code'
    exists = ctx.run(['/usr/bin/python3', '-I', '-c', SETUP_PROBE, SETUP_CODE], privileged=True)
    answer = exists.stdout.strip() if exists.ok else ''
    if answer == 'absent':
        ctx.add('signon.bootstrap', 'PASS', title, 'No setup or recovery code is waiting.')
        return
    if answer != 'present':
        # No answer is not "absent": the deadline, sudo, the root timeout or a missing command also end here.
        ctx.add('signon.bootstrap', 'SKIP', title, 'The setup-code file could not be checked, so whether a setup or recovery code is waiting is unknown.',
                'Rerun ' + ctx.repair('check-install.sh', '--owner', ctx.owner or 'YOUR_VM_USER') + ' with administrator access.')
        return
    head = ctx.run(['head', '-c', '16', SETUP_CODE], privileged=True, limit=64)
    mode = head.stdout.splitlines()[0].strip() if head.ok and head.stdout.splitlines() else ''
    head = None  # nothing past the first line is kept; the code is never read, held or printed
    url = f'https://<VM address>:{ui_port}/setup'
    if mode == 'mode=setup':
        ctx.add('signon.bootstrap', 'WARN', title, 'Setup not completed: no administrator exists.',
                f'Open {url} and enter the code from: sudo cat {SETUP_CODE}')
    elif mode == 'mode=recover':
        stamp = ctx.run(['stat', '-c', '%Y', SETUP_CODE], privileged=True)
        try:
            age = time.time() - int(stamp.stdout.strip())
        except ValueError:
            age = None
        if age is not None and age >= RECOVERY_SECONDS:
            ctx.add('signon.bootstrap', 'WARN', title,
                    'A recovery code expired unused; the manager removes it at the next /setup request.',
                    'Run ' + ctx.repair('manager-recover-admin.sh') + ' again and open the URL it prints within 15 minutes.')
        else:
            ctx.add('signon.bootstrap', 'WARN', title, 'A recovery is open (it closes 15 minutes after the recovery command ran).',
                    f'Open {url}?recover=1 with the code the recovery command printed, or run ' + ctx.repair('manager-recover-admin.sh') + ' again.')
    else:
        ctx.add('signon.bootstrap', 'WARN', title, 'A setup-code file exists but its first line is not recognised.',
                f'Open {url} and enter the code from: sudo cat {SETUP_CODE}')


def check_ssh(ctx, facts):
    title = 'SSH hardening'
    if facts is None:
        ctx.add('ssh.hardening', 'SKIP', title, 'The effective SSH configuration could not be read.', ctx.repair('setup-ssh-hardening.sh'))
    else:
        weak = []
        if facts.get('permitrootlogin') != 'no':
            weak.append(f"permitrootlogin is {facts.get('permitrootlogin', 'unset')}")
        for key, limit in (('maxauthtries', 4), ('logingracetime', 30)):
            value = facts.get(key, '')
            if not value.isdigit() or int(value) > limit:
                weak.append(f"{key} is {value or 'unset'} (limit {limit})")
        if weak:
            ctx.add('ssh.hardening', 'WARN', title, 'At the OpenSSH default: ' + '; '.join(weak) + '.', ctx.repair('setup-ssh-hardening.sh'))
        else:
            ctx.add('ssh.hardening', 'PASS', title, 'permitrootlogin no, maxauthtries and logingracetime are within the hardened limits.')
    brute = ctx.run(['systemctl', 'is-active', 'fail2ban'])
    if brute.ok:
        ctx.add('ssh.bruteforce', 'PASS', 'SSH brute-force protection', 'fail2ban is active.')
    else:
        ctx.add('ssh.bruteforce', 'WARN', 'SSH brute-force protection',
                'fail2ban is not active or not installed; recommended on an Internet-facing VM; see INSTALL.md.', 'sudo apt-get install -y fail2ban')


def attempt(ctx, idents, title, function, *args, fallback=None):
    """Run one sub-check on its own. An exception becomes a FAIL row for each id the check had not yet recorded (the
    exception class only: its text may carry command output), so one broken check never erases the others."""
    before = len(ctx.checks)
    try:
        return function(*args)
    except Exception as error:
        recorded = {row['id'] for row in ctx.checks[before:]}
        for ident in idents:
            if ident not in recorded:
                ctx.add(ident, 'FAIL', title, f'The check stopped before it could answer ({type(error).__name__}); the other checks of the group still ran. No successful result is assumed.',
                        'Verify a complete source checkout and rerun the report.')
        return fallback


def check_exposure(ctx):
    ui_port, http_port, listed = attempt(ctx, ('exposure.settings',), 'Manager ports and host names', settings, ctx,
                                         fallback=(DEFAULT_UI_PORT, DEFAULT_HTTP_PORT, []))
    mode, names = attempt(ctx, ('tls.files',), 'TLS certificate files', check_files, ctx, fallback=('', []))
    attempt(ctx, ('tls.cert',), 'TLS certificate', check_certificate, ctx, mode)
    attempt(ctx, ('tls.names',), 'TLS certificate names', check_names, ctx, names, listed)
    attempt(ctx, ('tls.bind',), 'TLS listener configuration', check_bind, ctx)
    listener = attempt(ctx, ('tls.listener',), 'TLS listener', check_listener, ctx)
    attempt(ctx, ('http.redirect',), 'HTTP redirect', lambda: check_redirect(ctx, local_host(ctx), ui_port, http_port))
    attempt(ctx, ('http.hsts',), 'HSTS header', check_hsts, ctx, listener)
    try:
        facts, ssh_ports = sshd_facts(ctx)
    except Exception:  # check_ssh then answers SKIP: the effective configuration could not be read
        facts, ssh_ports = None, [22]
    attempt(ctx, ('firewall',), 'Host firewall', check_firewall, ctx, ui_port, http_port, ssh_ports)
    attempt(ctx, ('exposure.listeners',), 'Listening TCP ports', check_listeners, ctx, ui_port, http_port, ssh_ports)
    attempt(ctx, ('exposure.ports',), 'Container published ports', check_ports, ctx)
    attempt(ctx, ('signon.bootstrap',), 'Sign-on setup code', check_bootstrap, ctx, ui_port)
    attempt(ctx, ('ssh.hardening', 'ssh.bruteforce'), 'SSH hardening', check_ssh, ctx, facts)
