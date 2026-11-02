"""The Host check in front of every request: the defence against DNS rebinding.

Sign-in is required for everything but the exempt rows of `app/sessions.py` (`EXEMPT`); behind the session gate
`/api/` keeps the same-origin guard in main.py and the two WebSockets their own Origin checks, and all of them
build "own origin" from the request's Host header. A page on a name the attacker's DNS controls can re-resolve
that name to the manager's address: its requests then carry a matching Host and Origin (and Sec-Fetch-Site
same-origin), so only the Host name itself tells them apart.

Accepted without configuration are names no internet DNS server answers as written: IP literals, `localhost`,
single-label names and `.local` names (answered on the browser's own network; see the residual below). Any other
name must be listed in UI_ALLOWED_HOSTS. X-Forwarded-Host is never read. One pure ASGI layer, added outermost,
covers HTTP and WebSocket handshakes alike, so no route or socket needs its own copy of the check.

Residual, kept on purpose: single-label and `.local` names are answered by LLMNR, NBNS and mDNS, so a host on
the *browser's* own link (which need not be the manager's network: café Wi-Fi with a VPN or SSH tunnel to the
VM) can answer such a name first with its own page and then with the manager's address. A single-label name is
also expanded by the OS resolver with the DNS search suffixes it was given (DHCP, VPN) and asked of the configured
DNS server as name.<suffix>, so whoever controls a name under that suffix, or the DNS of a hostile network the
browser is on, can answer it too. This check does not stop that (advice: list a real name in UI_ALLOWED_HOSTS or
use an authenticated proxy); docs/INSTALL.md "Opening the manager by a name" says so. Narrowing the default to the VM's own name
would also refuse the `testserver` Host that every Starlette TestClient sends, so it needs the test suites changed
with it (audit 2026-10-03 core/repair, M-13).
"""
import ipaddress
import re

HOST = re.compile(r'(\[[0-9a-f:.]+\]|[a-z0-9_-]+(?:\.[a-z0-9_-]+)*)(?::[0-9]{1,5})?')
REFUSAL = (b'This manager does not answer to the name in the address bar. Open it by the lab VM\'s IP address, for example '
           b'https://192.0.2.10:8443/. To open it by a name such as manager.example.edu, add that name to '
           b'UI_ALLOWED_HOSTS in clab-backup-ui/.env (deploy/image.env for a prepared release image) and recreate '
           b'the manager.\n')


def refusal_headers(scope):
    """The fixed security headers of a refusal (app/headers.py, shared with the gate and the guard) plus the body's type and length."""
    # Imported here, not at the top: deploy/setup_tls.py and deploy/check_exposure.py load this file on its own, outside
    # the app package, for host_name() and configured_hosts(), where a relative import cannot resolve.
    from .headers import encoded, security_headers
    headers = security_headers(scope, status=403, refusal=True)
    headers.update({'Content-Type': 'text/plain; charset=utf-8', 'Content-Length': str(len(REFUSAL))})
    return encoded(headers)


def host_name(value):
    """The lower-case name of a Host value without its port (an IPv6 literal keeps its brackets), or None when
    the value is not a plain host[:port]: userinfo, a path, an unbracketed IPv6 address, an empty label, a bad port."""
    match = HOST.fullmatch(value.strip().lower())
    if not match:
        return None
    name = match.group(1)
    if name.startswith('['):
        try: ipaddress.IPv6Address(name[1:-1])
        except ValueError: return None
    return name


def outside_dns_free(name):
    """True for a name no internet DNS server can answer as written (a host on the browser's own link, or a DNS
    server behind a search suffix, still can; see the module docstring)."""
    if name.startswith('['):
        return True
    try:
        ipaddress.IPv4Address(name)
        return True
    except ValueError:
        pass
    return name == 'localhost' or '.' not in name or name.endswith('.local')


def host_allowed(value, allowed=frozenset()):
    name = host_name(value)
    return name is not None and (name in allowed or outside_dns_free(name))


def configured_hosts(text):
    """UI_ALLOWED_HOSTS: comma-separated names, case-insensitive, any port ignored; an entry that is not a host
    name (a URL, a wildcard) is ignored, and the count of those is printed for the operator."""
    entries = [entry.strip() for entry in (text or '').split(',') if entry.strip()]
    names = {host_name(entry) for entry in entries}
    ignored = sum(1 for entry in entries if host_name(entry) is None)
    if ignored:
        print(f'UI_ALLOWED_HOSTS: ignored {ignored} of {len(entries)} entries that are not host names; write names only, '
              'for example manager.example.edu.', flush=True)
    return frozenset(names - {None})


class HostCheck:
    """Outermost ASGI layer: refuses an HTTP request or a WebSocket handshake whose single Host header is missing,
    repeated, malformed or a name outside DNS could control, before any route, guard or socket handler runs."""
    def __init__(self, app, allowed=frozenset()):
        self.app = app
        self.allowed = frozenset(allowed)

    async def __call__(self, scope, receive, send):
        if scope['type'] in ('http', 'websocket'):
            hosts = [value for key, value in scope.get('headers', ()) if key.lower() == b'host']
            try: accepted = len(hosts) == 1 and host_allowed(hosts[0].decode('ascii'), self.allowed)
            except UnicodeDecodeError: accepted = False
            if not accepted:
                if scope['type'] == 'websocket':
                    # Before accept, a close makes the server answer the handshake with 403.
                    await send({'type': 'websocket.close', 'code': 1008})
                    return
                await send({'type': 'http.response.start', 'status': 403, 'headers': refusal_headers(scope)})
                await send({'type': 'http.response.body', 'body': REFUSAL})
                return
        await self.app(scope, receive, send)
