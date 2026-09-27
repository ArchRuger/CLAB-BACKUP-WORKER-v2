#!/usr/bin/env python3
"""Pass-2 step 4d: Restart device previews and refusals through the deployed manager's API (read-only: a preview
runs the helper's preview mode only; nothing is confirmed). Records status codes, messages, warnings and the
command the helper would run."""
import json, sys, urllib.request, urllib.error
from datetime import datetime, timezone
base = 'http://127.0.0.1:8081'; out = sys.argv[1]
now = lambda: datetime.now(timezone.utc).isoformat(timespec='seconds')
def call(path, method='GET', body=None, headers=None):
    h = {'Content-Type': 'application/json', 'Origin': base}; h.update(headers or {})
    req = urllib.request.Request(base + path, data=json.dumps(body).encode() if body is not None else None, method=method, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=120) as r: return r.status, json.loads(r.read() or b'null')
    except urllib.error.HTTPError as e:
        raw = e.read()
        try: return e.code, json.loads(raw or b'{}')
        except Exception: return e.code, {'raw': raw[:300].decode(errors='replace')}
st, state = call('/api/state')
lab = next(l for l in state['labs'] if l['name'] == 'restore-square')
other = next(l for l in state['labs'] if l['name'] != 'restore-square')
record = {'started': now(), 'manager': state.get('version'), 'lab_id': lab['id'], 'other_lab': {'name': other['name'], 'id': other['id'], 'node': other['nodes'][0]['name'] if other['nodes'] else None}, 'cases': []}
ops_before = len(call('/api/operations')[1])
checks = []
def check(name, ok, detail=''):
    checks.append({'name': name, 'ok': bool(ok), 'detail': str(detail)[:900]}); print(('  ok   ' if ok else '  FAIL ') + name + ('' if ok else ': ' + str(detail)[:500]), flush=True)
def preview(label, body):
    st, res = call('/api/operations/preview', 'POST', body)
    keep = {k: res.get(k) for k in ('warnings', 'command', 'argv', 'summary', 'affected', 'detail', 'action', 'node', 'node_label') if isinstance(res, dict) and k in res}
    if isinstance(res, dict) and 'token' in res: keep['token_issued'] = True
    record['cases'].append({'case': label, 'request': body, 'status': st, 'response': keep, 'response_keys': sorted(res.keys()) if isinstance(res, dict) else None})
    return st, res
LIMIT = {'clab-restore-square-vjunos-switch': 'cannot be started a second time', 'clab-restore-square-xrv9k': 'factory configuration'}
for node, words in LIMIT.items():
    st, res = preview('preview ' + node, {'action': 'restart-node', 'lab_id': lab['id'], 'node': node})
    warnings = res.get('warnings') or [] if isinstance(res, dict) else []
    check('%s preview answers 200' % node, st == 200, '%s %s' % (st, json.dumps(res)[:300]))
    check('%s preview carries the known-limit warning (%s)' % (node, words), any('Known limit' in w and words in w for w in warnings), warnings)
    text = json.dumps(res)
    cmd = res.get('command') if isinstance(res, dict) else None
    check('%s preview names exactly one --node, the topology node' % node, text.count('--node') == 1 and ('"--node", "%s"' % node.split('restore-square-')[1]) in text.replace('\\"', '"'), (cmd or text)[:600])
# ceos: no known limit (control) and no neighbour note while every neighbour runs.
st, res = preview('preview clab-restore-square-ceos (control)', {'action': 'restart-node', 'lab_id': lab['id'], 'node': 'clab-restore-square-ceos'})
check('control: the cEOS preview carries no known-limit note and no neighbour note while all neighbours run', st == 200 and not any('Known limit' in w or 'is not running' in w for w in (res.get('warnings') or [])), json.dumps(res.get('warnings'))[:400])
# Refusals.
refusals = [
    ('node of another lab', {'action': 'restart-node', 'lab_id': lab['id'], 'node': record['other_lab']['node']}),
    ('made-up node name', {'action': 'restart-node', 'lab_id': lab['id'], 'node': 'clab-restore-square-nosuchdevice'}),
    ('short name instead of the container name', {'action': 'restart-node', 'lab_id': lab['id'], 'node': 'ceos'}),
    ('options with node set', {'action': 'restart-node', 'lab_id': lab['id'], 'node': 'clab-restore-square-ceos', 'options': {'node': 'ceos'}}),
    ('options with node set (no top-level node)', {'action': 'restart-node', 'lab_id': lab['id'], 'options': {'node': 'ceos'}}),
    ('options with container set', {'action': 'restart-node', 'lab_id': lab['id'], 'node': 'clab-restore-square-ceos', 'options': {'container': 'clab-restore-square-xrv9k'}}),
    ('other options', {'action': 'restart-node', 'lab_id': lab['id'], 'node': 'clab-restore-square-ceos', 'options': {'force': True}}),
    ('path set', {'action': 'restart-node', 'lab_id': lab['id'], 'node': 'clab-restore-square-ceos', 'path': '/srv/containerlab-node-manager/projects/restore-square/restore-square.clab.yml'}),
    ('no node', {'action': 'restart-node', 'lab_id': lab['id']}),
    ('node on the lab-wide restart', {'action': 'restart', 'lab_id': lab['id'], 'node': 'clab-restore-square-ceos'}),
    ('comma list as node', {'action': 'restart-node', 'lab_id': lab['id'], 'node': 'clab-restore-square-ceos,clab-restore-square-xrv9k'}),
]
for label, body in refusals:
    st, res = preview('refusal: ' + label, body)
    check('refused: %s (4xx, no token)' % label, 400 <= st < 500 and not (isinstance(res, dict) and res.get('token')), '%s %s' % (st, json.dumps(res)[:300]))
# Without the Origin header (the same-origin guard).
st, res = call('/api/operations/preview', 'POST', {'action': 'restart-node', 'lab_id': lab['id'], 'node': 'clab-restore-square-ceos'}, headers={'Origin': 'http://evil.example'})
record['cases'].append({'case': 'foreign Origin', 'status': st, 'response': res if isinstance(res, dict) else str(res)[:200]})
check('a foreign Origin is refused (403)', st == 403, '%s %s' % (st, res))
ops_after = len(call('/api/operations')[1])
check('no operation job was created by any of these requests', ops_after == ops_before, '%d -> %d' % (ops_before, ops_after))
record['checks'] = checks; record['finished'] = now()
open(out, 'w').write(json.dumps(record, indent=1))
print('%d checks, %d failed' % (len(checks), sum(1 for c in checks if not c['ok'])))
