#!/usr/bin/env python3
"""Pass-4 adversarial check (own design): crafted / malicious requests to the restart-node
preview and confirm endpoints, run against the fixture manager (never the deployed product).

Targets a defect class the campaign's own tools do not replay directly: whether the reviewed-action
endpoints (`/api/operations/preview`, `/api/operations/confirm`) hold their input contract against a
hand-crafted (non-browser) client, in the spirit of RD-003/RD-004 (defence in depth: a page-supplied
`path`, an out-of-shape container name) but exercised with raw HTTP requests instead of a browser.

Checks:
  1. A `restart-node` preview with a client-supplied `path` is refused (400, "Restart device uses the
     lab's own topology file.") -- RD-004's fix, replayed here as a raw HTTP call.
  2. A preview with an extra, undeclared JSON field is refused (422) -- the Request model's
     `extra='forbid'`.
  3. A preview naming a node with shell/path-traversal-looking characters resolves through structured
     node lookup only (no shell interpretation) and is refused cleanly, never a 500 or a hang.
  4. A confirm with a token that was never issued by a preview is refused (409, "Review expired...").

Usage:
    PATH="$PWD/clab-backup-ui/.venv/bin:$PATH" clab-backup-ui/.venv/bin/python \\
        docs/netlab-ui-qa/acceptance/pass-4/tools/adversarial_restart_preview.py --port 8155
"""
import argparse
import json
import subprocess
import sys
import time
import urllib.request


def post(base, path, body, origin=None):
    headers = {'Content-Type': 'application/json'}
    if origin:
        headers['Origin'] = origin
    req = urllib.request.Request(base + path, data=json.dumps(body).encode(), headers=headers, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode())


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--port', type=int, default=8155)
    ap.add_argument('--data')
    args = ap.parse_args()
    base = 'http://127.0.0.1:%d' % args.port

    checks = []

    def check(name, ok, detail=''):
        checks.append((name, ok, detail))
        print(('  ok   ' if ok else '  FAIL ') + name + ('' if ok else ': ' + str(detail)[:300]))

    with urllib.request.urlopen(base + '/api/state', timeout=10) as resp:
        state = json.loads(resp.read().decode())
    lab = next(l for l in state['labs'] if l['name'] == 'ospf-basics')
    node = lab['nodes'][0]['name']

    status, body = post(base, '/api/operations/preview',
                         {'action': 'restart-node', 'lab_id': lab['id'], 'node': node, 'path': '/etc/passwd'}, base)
    check('client-supplied path on restart-node preview is refused (400, exact message)',
          status == 400 and body.get('detail') == "Restart device uses the lab's own topology file.", (status, body))

    status, body = post(base, '/api/operations/preview',
                         {'action': 'restart-node', 'lab_id': lab['id'], 'node': node, 'evil_field': 'x'}, base)
    check('an undeclared extra field is refused (422)', status == 422, (status, body))

    status, body = post(base, '/api/operations/preview',
                         {'action': 'restart-node', 'lab_id': lab['id'], 'node': '../../etc/passwd; rm -rf /'}, base)
    check('a shell/path-traversal-looking node name is refused cleanly, never 200 or 500',
          status in (400, 404, 409), (status, body))

    status, body = post(base, '/api/operations/confirm', {'token': '0' * 32}, base)
    check('a confirm with a never-issued token is refused (409, review expired)',
          status == 409 and 'expired' in body.get('detail', ''), (status, body))

    failed = [c for c in checks if not c[1]]
    print('%d checks, %d failed' % (len(checks), len(failed)))
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
