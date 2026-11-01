"""The plain-HTTP redirect listener (docs/sign-on/EXPOSURE.md 4.1), run as `python -m app.redirect` in its own container.

`app/redirect.py` is the one listener outside the gate and the guard: it holds no data and answers 301 to the
manager's own HTTPS origin after `host_allowed`, 400 for a refused Host or a request target that is not a path, 405
for any method but GET and HEAD, closes a socket 1008, and nothing else.

`Location` is built from the browser's own Host name (without its port, exactly as `HostCheck` accepts it), the fixed
HTTPS port and `raw_path` and `query_string` as the client sent them, never from the decoded path: `%0d%0a` and `%3F`
stay encoded. A target that does not start with `/` (absolute form, `*`, `@evil.example/`) would put another
authority into `Location`, and a byte outside 0x21-0x7e cannot travel in a header, so both answer 400. Every answer
has an empty body, `Content-Length: 0` and the headers of `app.headers.security_headers(scope, status=…,
refusal=True)`; nothing is logged per request. It never imports `app.main`, `app.store` or any service.
"""
import os
import signal
import sys
import threading

from .allowed_hosts import configured_hosts, host_allowed, host_name

METHODS = ('GET', 'HEAD')
DEFAULT_PORT = 8443
DEFAULT_HTTP_PORT = 8081


def printable(value):
    """Only visible ASCII (0x21-0x7e): what h11 accepts in a request target and what a header value can carry."""
    return all(0x21 <= byte <= 0x7e for byte in value)


class Redirect:
    """Pure ASGI: Host, then the target's form, then the method; a websocket is closed 1008 before accept."""
    def __init__(self, port, allowed=frozenset()):
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
        from .headers import security_headers   # S1b's module; imported on first use
        values = security_headers(scope, status=status, refusal=True)
        headers = [(key.lower().encode('latin-1'), value.encode('latin-1')) for key, value in values.items()]
        headers += [*extra, (b'content-length', b'0')]
        await send({'type': 'http.response.start', 'status': status, 'headers': headers})
        await send({'type': 'http.response.body', 'body': b''})


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
    return app, dict(host=(environ.get('UI_BIND') or '').strip() or '0.0.0.0', port=http_port, http='h11',
                     server_header=False, proxy_headers=False, workers=1, access_log=False, log_level='error')


def main(environ=None):
    app, options = settings(os.environ if environ is None else environ)
    if options['port'] == 0:
        # Disabled: keep the container running and bound to nothing, so `restart: unless-stopped` has nothing to
        # restart; as PID 1 the process needs its own SIGTERM handler to stop on `docker stop`.
        print('HTTP redirect disabled', flush=True)
        stop = threading.Event()
        for number in (signal.SIGTERM, signal.SIGINT):
            signal.signal(number, lambda *_: stop.set())
        while not stop.wait(3600):
            pass
        return
    import uvicorn
    uvicorn.run(app, **options)


if __name__ == '__main__':
    main()
