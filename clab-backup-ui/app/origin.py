"""The one scheme rule (sign-on DESIGN.md 5.6): "own origin" is read from the ASGI scope only.

Nothing in the manager reads `X-Forwarded-*`; uvicorn terminates TLS itself and runs with
`--no-proxy-headers`, so `scope['scheme']` is the truth. The guard, both WebSocket handlers, the capture
cookie, the session cookie and HSTS all ask this function; none keeps a copy of the rule.
"""


def scheme(scope):
    """'https' when the scope's scheme is `https` or `wss`, otherwise 'http'. Reads the scope only: no
    environment variable, no header."""
    return 'https' if scope.get('scheme') in ('https', 'wss') else 'http'
