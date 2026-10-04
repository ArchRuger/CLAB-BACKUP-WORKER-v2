#!/usr/bin/env python3
"""Tiny client for the dev2 manager API (stdlib only).

The manager's same-origin guard needs an Origin header equal to the base URL and a non-empty JSON body on
every mutating request, so this sends both.

    mgr.py GET /api/state
    mgr.py PUT /api/host '{"address":"127.0.0.1","port":22,"username":"clab-discovery","auth":"password","password":""}'
    mgr.py POST /api/discovery/refresh            # a missing body is sent as {}
Environment: MANAGER (default http://127.0.0.1:8081). Prints "HTTP <status>" then the JSON answer.
"""
import json
import os
import sys
import urllib.error
import urllib.request

BASE = os.environ.get('MANAGER', 'http://127.0.0.1:8081').rstrip('/')
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def call(method, path, body=None, timeout=300):
    data = None
    headers = {'Origin': BASE}
    if method != 'GET':
        data = json.dumps({} if body is None else body).encode()
        headers['Content-Type'] = 'application/json'
    request = urllib.request.Request(BASE + path, data=data, method=method, headers=headers)
    try:
        with OPENER.open(request, timeout=timeout) as response:
            return response.status, json.loads(response.read().decode() or 'null')
    except urllib.error.HTTPError as error:
        raw = error.read().decode()
        try:
            return error.code, json.loads(raw or 'null')
        except ValueError:
            return error.code, {'raw': raw[:500]}


if __name__ == '__main__':
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    status, answer = call(sys.argv[1].upper(), sys.argv[2], json.loads(sys.argv[3]) if len(sys.argv) > 3 else None)
    print('HTTP', status)
    print(json.dumps(answer, indent=2, sort_keys=True))
