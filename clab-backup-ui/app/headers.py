"""The fixed security headers of every response (sign-on DESIGN.md 6.1, 16.3; RECONCILIATION Dq5).

One function, used by `allowed_hosts.HostCheck`, the session gate and the guard in `main.py`, so a response
the guard never sees (a refusal by one of the two ASGI layers, or the guard's own early return) carries the
same headers as a routed one. HSTS is added when the request's own scheme is https (`origin.scheme`): 180
days, no `includeSubDomains`, no `preload` (EXPOSURE.md 4.2 states its port-wide scope).
"""
from .origin import scheme

HSTS = 'max-age=15552000'
IMMUTABLE_PREFIX = '/static/lab-builder/assets/'
# xterm's DOM renderer creates font, cell-width and ANSI-color styles, and the lab builder's editor (React Flow,
# MUI) sets element styles at run time. Permit those only in their dedicated documents; scripts remain self-only.
INLINE_STYLE_PAGES = ('/static/terminal.html', '/static/capture-session.html', '/static/lab-builder.html', '/static/map-editor.html')
REFUSAL_CSP = "default-src 'none'; frame-ancestors 'none'"


def security_headers(scope, *, status=200, refusal=False):
    """A dict of header name → value for a response to `scope`. `refusal=True` is the shape of a response that
    carries no page: the two ASGI layers and the guard's early returns use it."""
    path = scope.get('path', '')
    headers = {'X-Content-Type-Options': 'nosniff', 'Referrer-Policy': 'no-referrer', 'X-Frame-Options': 'DENY'}
    # The lab builder's editor bundle is several megabytes of content-hashed files that only change with a release;
    # everything else is never cached.
    cached = status == 200 and not refusal and path.startswith(IMMUTABLE_PREFIX)
    headers['Cache-Control'] = 'public, max-age=31536000, immutable' if cached else 'no-store'
    if refusal:
        headers['Content-Security-Policy'] = REFUSAL_CSP
    else:
        styles = "'self' 'unsafe-inline'" if path in INLINE_STYLE_PAGES else "'self'"
        headers['Content-Security-Policy'] = (f"default-src 'self'; script-src 'self'; style-src {styles}; img-src 'self' data:; "
                                              "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
    if scheme(scope) == 'https':
        headers['Strict-Transport-Security'] = HSTS
    return headers


def encoded(headers):
    """The ASGI header list of a dict (lower-cased names, latin-1 bytes)."""
    return [(name.lower().encode('latin-1'), value.encode('latin-1')) for name, value in headers.items()]
