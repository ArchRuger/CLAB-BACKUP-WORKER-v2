#!/usr/bin/env python3
"""Tiny client for the dev2 manager API, on the sign-on helper (docs/sign-on/tools/manager_http.py).

The manager answers HTTPS only and needs a session. This signs in on the first request with CLAB_USER and
CLAB_PASSWORD (or a prompt on a terminal; never a command-line value), keeps the cookie, and sends the same-origin
headers and a non-empty JSON body on every mutating request.

    mgr.py GET /api/state
    mgr.py PUT /api/host '{"address":"127.0.0.1","port":22,"username":"clab-discovery","auth":"password","password":""}'
    mgr.py POST /api/discovery/refresh            # a missing body is sent as {}
Environment: MANAGER (default https://127.0.0.1:8443), CLAB_USER, CLAB_PASSWORD, CLAB_PIN or CLAB_CAFILE (default: the installed
cert.pem is pinned). Prints "HTTP <status>" then the JSON answer.
"""
import json
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / 'sign-on' / 'tools'))
import manager_http  # noqa: E402

BASE = os.environ.get('MANAGER', manager_http.DEFAULT_BASE).rstrip('/')
_MANAGER = None


def client():
    global _MANAGER
    if _MANAGER is None:
        _MANAGER = manager_http.Manager(BASE)
    return _MANAGER


def call(method, path, body=None, timeout=300):
    """(status, parsed answer); the signature the L1/L2 scripts have always used."""
    return client().call(method, path, body, timeout)


if __name__ == '__main__':
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    try:
        status, answer = call(sys.argv[1].upper(), sys.argv[2], json.loads(sys.argv[3]) if len(sys.argv) > 3 else None)
    except manager_http.ManagerError as error:
        sys.exit('mgr: %s' % error)
    print('HTTP', status)
    print(json.dumps(answer, indent=2, sort_keys=True))
