"""The plain-HTTP redirect listener (docs/sign-on/EXPOSURE.md 4.1), run as `python -m app.redirect` in its own container.

`app/redirect.py` is the one listener outside the gate and the guard: it holds no data and answers 301 to the
manager's own HTTPS origin after `host_allowed`, 400 for a refused Host or a request target that is not a path, 405
for any method but GET and HEAD, closes a socket 1008, and nothing else.

On an exposed port it must also stay up and quiet against a client that holds sockets open: every connection is
closed CONNECTION_DEADLINE seconds after it was accepted, whatever it sent (uvicorn has no request-header timeout),
the soft descriptor limit is set to NOFILE_CEILING at start (raised from 1024, lowered from a container's higher
value, so held sockets cost bounded memory), and asyncio's own errors (an accept that ran out of
descriptors is logged once per backlog slot, every second) reach the log at most once a minute, without a traceback.
`security_headers` is looked up when the listener is built, so a missing `app.headers` stops the start instead of
answering every request 500 with a logged traceback.

`Location` is built from the browser's own Host name (without its port, exactly as `HostCheck` accepts it), the fixed
HTTPS port and `raw_path` and `query_string` as the client sent them, never from the decoded path: `%0d%0a` and `%3F`
stay encoded. A target that does not start with `/` (absolute form, `*`, `@evil.example/`) would put another
authority into `Location`, and a byte outside 0x21-0x7e cannot travel in a header, so both answer 400. Every answer
has an empty body, `Content-Length: 0` and the headers of `app.headers.security_headers(scope, status=…,
refusal=True)`; nothing is logged per request. It never imports `app.main`, `app.store` or any service.
"""
import logging
import os
import resource
import signal
import sys
import threading
import time

from .allowed_hosts import configured_hosts, host_allowed, host_name

METHODS = ('GET', 'HEAD')
DEFAULT_PORT = 8443
DEFAULT_HTTP_PORT = 8081
CONNECTION_DEADLINE = 10       # seconds from accept to close; a redirect is answered in milliseconds
NOFILE_CEILING = 4096          # the listener's soft descriptor limit: about 14 kB of memory per held socket


def printable(value):
    """Only visible ASCII (0x21-0x7e): what h11 accepts in a request target and what a header value can carry."""
    return all(0x21 <= byte <= 0x7e for byte in value)


class Redirect:
    """Pure ASGI: Host, then the target's form, then the method; a websocket is closed 1008 before accept."""
    def __init__(self, port, allowed=frozenset()):
        from .headers import security_headers   # S1b's module: resolved once, when the listener is built
        self.security_headers = security_headers
        self.port = port
        self.allowed = frozenset(allowed)
        self.authority_port = b'' if port == 443 else b':' + str(port).encode()

    async def __call__(self, scope, receive, send):
        kind = scope.get('type')
        if kind == 'lifespan':
            while True:
                message = await receive()
                if message['type'] == 'lifespan.startup':
                    await send({'type': 'lifespan.startup.complete'})
                elif message['type'] == 'lifespan.shutdown':
                    await send({'type': 'lifespan.shutdown.complete'})
                    return
        if kind == 'websocket':
            await send({'type': 'websocket.close', 'code': 1008})
            return
        if kind != 'http':
            return
        name = self.name(scope)
        raw_path, query = scope.get('raw_path'), scope.get('query_string') or b''
        if name is None or not isinstance(raw_path, bytes) or not raw_path.startswith(b'/') \
                or not printable(raw_path) or not isinstance(query, bytes) or not printable(query):
            await self.answer(scope, send, 400)
        elif scope.get('method') not in METHODS:
            await self.answer(scope, send, 405, [(b'allow', b'GET, HEAD')])
        else:
            location = b'https://' + name.encode('ascii') + self.authority_port + raw_path + (b'?' + query if query else b'')
            await self.answer(scope, send, 301, [(b'location', location)])

    def name(self, scope):
        hosts = [value for key, value in scope.get('headers', ()) if key.lower() == b'host']
        if len(hosts) != 1:
            return None
        try:
            value = hosts[0].decode('ascii')
        except UnicodeDecodeError:
            return None
        return host_name(value) if host_allowed(value, self.allowed) else None

    async def answer(self, scope, send, status, extra=()):
        values = self.security_headers(scope, status=status, refusal=True)
        headers = [(key.lower().encode('latin-1'), value.encode('latin-1')) for key, value in values.items()]
        headers += [*extra, (b'content-length', b'0')]
        await send({'type': 'http.response.start', 'status': status, 'headers': headers})
        await send({'type': 'http.response.body', 'body': b''})


_protocol = None


def deadline_protocol():
    """uvicorn's h11 protocol, closing each connection CONNECTION_DEADLINE seconds after accept: a socket that sends
    nothing, or trickles a header, would otherwise hold a descriptor for as long as its client likes."""
    global _protocol
    if _protocol is None:
        from uvicorn.protocols.http.h11_impl import H11Protocol

        class DeadlineH11Protocol(H11Protocol):
            deadline = CONNECTION_DEADLINE

            def connection_made(self, transport):
                super().connection_made(transport)
                # abort, not close: close() waits for a write buffer that a client which never reads keeps full.
                self.deadline_handle = self.loop.call_later(type(self).deadline, transport.abort)

            def connection_lost(self, exc):
                handle = getattr(self, 'deadline_handle', None)
                if handle is not None:
                    handle.cancel()
                super().connection_lost(exc)

        _protocol = DeadlineH11Protocol
    _protocol.deadline = CONNECTION_DEADLINE
    return _protocol


class Throttle(logging.Filter):
    """At most one record per `every` seconds, its traceback reduced to the exception's own sentence."""
    def __init__(self, every=60):
        super().__init__()
        self.every = every
        self.last = None

    def filter(self, record):
        now = time.monotonic()
        if self.last is not None and now - self.last < self.every:
            return False
        self.last = now
        exc = record.exc_info[1] if record.exc_info else None
        first = record.getMessage().splitlines()[0] if record.getMessage() else ''
        record.msg, record.args = (f'{first} ({exc})' if exc is not None else first), ()
        record.exc_info = record.exc_text = record.stack_info = None
        return True


def quiet_asyncio():
    logger = logging.getLogger('asyncio')
    if not any(isinstance(item, Throttle) for item in logger.filters):
        logger.addFilter(Throttle())


def raise_open_files():
    """Soft RLIMIT_NOFILE set to NOFILE_CEILING, or to the hard limit when that is lower (no capability needed).

    Raised from a default of 1024, so idle sockets need four times the descriptors; never above the ceiling, and
    lowered to it when a container starts with a higher soft limit, because every held connection costs the listener
    memory and a container's hard limit (524288 or more) would let one client hold VM memory without bound."""
    try:
        soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        target = NOFILE_CEILING if hard == resource.RLIM_INFINITY else min(hard, NOFILE_CEILING)
        if soft != target:
            resource.setrlimit(resource.RLIMIT_NOFILE, (target, hard))
    except (ValueError, OSError):
        pass   # the limit stays as it was; the deadline still bounds how long a descriptor is held


def port_setting(environ, key, default, lowest):
    text = (environ.get(key) or '').strip() or str(default)
    if not text.isdigit() or not lowest <= int(text) <= 65535:
        print(f'{key} must be a port number from {lowest} to 65535.', file=sys.stderr, flush=True)
        raise SystemExit(2)
    return int(text)


def settings(environ):
    """(the ASGI app, the keyword arguments of uvicorn.run) from UI_BIND, UI_PORT, UI_HTTP_PORT and UI_ALLOWED_HOSTS."""
    port = port_setting(environ, 'UI_PORT', DEFAULT_PORT, 1)
    http_port = port_setting(environ, 'UI_HTTP_PORT', DEFAULT_HTTP_PORT, 0)
    app = Redirect(port, configured_hosts(environ.get('UI_ALLOWED_HOSTS', '')))
    # log_level 'error' keeps uvicorn's per-request "Invalid HTTP request received." warnings out of the log too.
    return app, dict(host=(environ.get('UI_BIND') or '').strip() or '0.0.0.0', port=http_port, http=deadline_protocol(),
                     server_header=False, proxy_headers=False, workers=1, access_log=False, log_level='error')


def main(environ=None):
    environ = os.environ if environ is None else environ
    port_setting(environ, 'UI_PORT', DEFAULT_PORT, 1)
    if port_setting(environ, 'UI_HTTP_PORT', DEFAULT_HTTP_PORT, 0) == 0:
        # Disabled: keep the container running and bound to nothing, so `restart: unless-stopped` has nothing to
        # restart; as PID 1 the process needs its own SIGTERM handler to stop on `docker stop`.
        print('HTTP redirect disabled', flush=True)
        stop = threading.Event()
        for number in (signal.SIGTERM, signal.SIGINT):
            signal.signal(number, lambda *_: stop.set())
        while not stop.wait(3600):
            pass
        return
    app, options = settings(environ)
    raise_open_files()
    quiet_asyncio()
    import uvicorn
    uvicorn.run(app, **options)


if __name__ == '__main__':
    main()
