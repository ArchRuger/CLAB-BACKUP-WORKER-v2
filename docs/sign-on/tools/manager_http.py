#!/usr/bin/env python3
"""Standard-library client of the live tools for a manager that requires sign-in (sign-on REVIEW R15, BUILD.md S11).

    manager_http.py [--base https://127.0.0.1:8443] [--cafile CA.pem | --pin cert.pem] METHOD PATH [JSON]

The manager answers HTTPS only and every `/api/` route needs a session, so a tool that used a bare `urllib` call
against `http://127.0.0.1:8081` uses this instead:

    from manager_http import Manager
    manager = Manager('https://127.0.0.1:8443')          # trust: the installed certificate, see below
    status, answer = manager.get('/api/state')            # signs in on the first request, keeps the cookie
    status, answer = manager.post('/api/discovery/refresh')   # a missing body is sent as {}

What it does, and what it never does:

* The base URL is `https://`; plain `http://` is refused (the fixture needs no helper: it signs requests in itself).
* Trust. `--pin cert.pem` trusts exactly that certificate and does not compare the name, as the health check does
  (the manager's certificate names the VM's addresses, and a tool often reaches it as 127.0.0.1). `--cafile CA.pem`
  verifies the chain and the name. With neither, the installed `/srv/containerlab-node-manager/tls/cert.pem` is pinned
  when it is readable, otherwise the system store decides (and a self-signed certificate fails). `CLAB_PIN` and
  `CLAB_CAFILE` name the files for a tool that has no option.
* Credentials come from `CLAB_USER` and `CLAB_PASSWORD`, else from a prompt on the terminal (`getpass`, nothing
  echoed). There is no option that takes a password or a user name; a value on the command line would sit in the
  process list and the shell history. Nothing prints a password, a cookie value or a session id.
* A cookie jar keeps the session. A request answered `401 signed_out` signs in once more and is retried once; a
  second 401 is returned as it is. No proxy from the environment is used.
* Every request carries the `Origin` the same-origin guard compares with the base URL's, and every mutating request a
  non-empty JSON body (`{}` when the caller gave none).

`MANAGER` (environment) names the base URL when `--base` is not given; the default is `https://127.0.0.1:8443`.
Prints `HTTP <status>` and then the JSON answer.
"""
import argparse
import getpass
import http.client
import http.cookiejar
import json
import os
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

DEFAULT_BASE = 'https://127.0.0.1:8443'
INSTALLED_CERTIFICATE = Path('/srv/containerlab-node-manager/tls/cert.pem')
SESSION_COOKIE = 'clab_session'


class ManagerError(Exception):
    """The manager could not be reached, its certificate was not accepted, or a sign-in was refused. The text never
    contains a password."""


class Manager:
    def __init__(self, base, cafile=None, pin=None, user=None, password=None, timeout=300):
        parts = urllib.parse.urlsplit(base or '')
        if parts.scheme != 'https' or not parts.hostname:
            raise ValueError('The manager base URL must be https://host[:port], not %r. The manager answers HTTPS only.' % (base,))
        self.base = '%s://%s' % (parts.scheme, parts.netloc)
        self.timeout = timeout
        self._user, self._password = user, password
        self._signed_in = False
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler(context=self._context(cafile, pin)),
                                                  urllib.request.HTTPCookieProcessor(self.jar))

    def __repr__(self):
        return 'Manager(%r)' % self.base

    @staticmethod
    def _context(cafile, pin):
        cafile = cafile or os.environ.get('CLAB_CAFILE') or None
        pin = pin or os.environ.get('CLAB_PIN') or None
        if cafile and pin:
            raise ValueError('Give --cafile or --pin, not both.')
        if pin is None and cafile is None and INSTALLED_CERTIFICATE.is_file() and os.access(INSTALLED_CERTIFICATE, os.R_OK):
            pin = str(INSTALLED_CERTIFICATE)
        if pin:
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            context.load_verify_locations(cafile=pin)
            context.check_hostname = False
            context.verify_mode = ssl.CERT_REQUIRED
            return context
        return ssl.create_default_context(cafile=cafile)

    @classmethod
    def from_args(cls, args, **kwargs):
        return cls(getattr(args, 'base', None) or os.environ.get('MANAGER') or DEFAULT_BASE, cafile=getattr(args, 'cafile', None),
                   pin=getattr(args, 'pin', None), timeout=getattr(args, 'timeout', None) or 300, **kwargs)

    # ---- credentials and the session ----
    def _credentials(self):
        user = self._user or os.environ.get('CLAB_USER') or ''
        password = self._password or os.environ.get('CLAB_PASSWORD') or ''
        if (not user or not password) and sys.stdin.isatty():
            if not user: user = input('Manager user name: ').strip()
            if not password: password = getpass.getpass('Manager password for %s: ' % user)
        if not user or not password:
            raise ManagerError('No sign-in credentials. Set CLAB_USER and CLAB_PASSWORD in the environment, or run this on a terminal '
                               'to be asked. A password is never taken from the command line.')
        return user, password

    def sign_in(self):
        user, password = self._credentials()
        status, answer = self._send('POST', '/api/session', {'username': user, 'password': password})
        if status == 200:
            if (answer.get('user') or {}).get('must_change_password'):
                raise ManagerError('The account %s must change its password before a tool can use it. Sign in on the sign-in page once.' % user)
            self._signed_in = True
            return answer
        detail = answer.get('detail') if isinstance(answer, dict) else None
        message = detail.get('message') if isinstance(detail, dict) else detail
        suffix = ' Try again in %s s.' % detail['retry_after'] if status == 429 and isinstance(detail, dict) and 'retry_after' in detail else ''
        raise ManagerError('Sign-in as %s was refused (HTTP %s): %s%s' % (user, status, message or 'no reason given.', suffix))

    def session_cookie(self):
        """(name, value) of the session cookie once signed in, for a browser context that should share the session."""
        for cookie in self.jar:
            if cookie.name == SESSION_COOKIE: return cookie.name, cookie.value
        return None

    def playwright_cookie(self):
        """The session as a Playwright `context.add_cookies([...])` entry (signs in first when needed)."""
        if not self._signed_in: self.sign_in()
        found = self.session_cookie()
        return {'name': found[0], 'value': found[1], 'url': self.base, 'httpOnly': True, 'secure': True, 'sameSite': 'Strict'}

    # ---- requests ----
    def _send(self, method, path, body, timeout=None, headers=None):
        data, sent = None, {'Origin': self.base, 'Accept': 'application/json'}
        if method != 'GET':
            data = json.dumps({} if body is None else body).encode()
            sent['Content-Type'] = 'application/json'
        sent.update(headers or {})
        request = urllib.request.Request(self.base + path, data=data, method=method, headers=sent)
        try:
            with self.opener.open(request, timeout=timeout or self.timeout) as response:
                status, raw = response.status, response.read().decode()
        except urllib.error.HTTPError as error:
            status, raw = error.code, error.read().decode()
        except (OSError, http.client.HTTPException) as error:
            reason = getattr(error, 'reason', error)
            if isinstance(reason, ssl.SSLError) or isinstance(error, ssl.SSLError):
                raise ManagerError('The manager at %s did not present an accepted certificate (%s). Pin the installed certificate with '
                                   '--pin /srv/containerlab-node-manager/tls/cert.pem, or name its CA with --cafile.' % (self.base, getattr(reason, 'reason', None) or reason))
            raise ManagerError('Cannot reach the manager at %s (%s). Is it running?' % (self.base, reason or type(error).__name__))
        try:
            return status, json.loads(raw or 'null')
        except ValueError:
            return status, {'raw': raw[:500]}

    def request(self, method, path, body=None, timeout=None, headers=None):
        """(status, parsed JSON | {'raw': text}). Signs in before the first request and once more after a `signed_out` 401."""
        if not self._signed_in and path != '/api/session': self.sign_in()
        status, answer = self._send(method, path, body, timeout, headers)
        if status == 401 and path != '/api/session' and isinstance(answer, dict) and (answer.get('detail') or {}).get('code') == 'signed_out':
            self.sign_in()
            status, answer = self._send(method, path, body, timeout, headers)
        return status, answer

    def call(self, method, path, body=None, timeout=300):
        """The signature of the old `mgr.call`."""
        return self.request(method.upper(), path, body, timeout)

    def get(self, path, **kwargs): return self.request('GET', path, **kwargs)
    def post(self, path, body=None, **kwargs): return self.request('POST', path, body, **kwargs)
    def put(self, path, body=None, **kwargs): return self.request('PUT', path, body, **kwargs)
    def patch(self, path, body=None, **kwargs): return self.request('PATCH', path, body, **kwargs)
    def delete(self, path, body=None, **kwargs): return self.request('DELETE', path, body, **kwargs)


def add_arguments(parser):
    """The connection options, for a tool that builds its own parser and then calls `Manager.from_args(args)`."""
    parser.add_argument('--base', default=None, help='manager base URL, https only (default: $MANAGER, else %s)' % DEFAULT_BASE)
    parser.add_argument('--cafile', default=None, help='CA file; the chain and the name are verified (default: $CLAB_CAFILE)')
    parser.add_argument('--pin', default=None, metavar='CERT.PEM', help='trust exactly this certificate, no name check (default: $CLAB_PIN, else the installed cert.pem)')
    parser.add_argument('--timeout', type=float, default=300, help='seconds per request (default %(default)s)')
    return parser


def argument_parser():
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0], epilog='Credentials: CLAB_USER and CLAB_PASSWORD, else a prompt. There is no option for them.')
    add_arguments(parser)
    parser.add_argument('method')
    parser.add_argument('path')
    parser.add_argument('body', nargs='?', default=None, help='JSON body; a mutating request without one sends {}')
    return parser


def main(argv=None):
    args = argument_parser().parse_args(argv)
    try:
        manager = Manager.from_args(args)
        status, answer = manager.call(args.method, args.path, json.loads(args.body) if args.body else None, timeout=args.timeout)
    except (ManagerError, ValueError) as error:
        print('manager_http: %s' % error, file=sys.stderr)
        return 2
    print('HTTP', status)
    print(json.dumps(answer, indent=2, sort_keys=True))
    return 0


if __name__ == '__main__':
    sys.exit(main())
