#!/usr/bin/env python3
"""Pass 6: Restart device API previews (never confirmations) and refusals against the deployed manager.

Previews for vjunos-switch, xrv9k (known-limit warning verbatim against RESTART_KNOWN_LIMITS) and ceos (none);
refusals: node of another lab, unknown node, foreign Origin, plus adversarial extras (mismatched Sec-Fetch-Site,
an empty body, a node name with a path/option injection shape, a stale lab id). Counts operation jobs before and
after. Prints JSON; never posts a confirmation."""
import json, sys, urllib.request, urllib.error, datetime
sys.path.insert(0, '/home/clabllm/projects/clab-manager-1.30.42/clab-backup-ui')
from app.lab_operations import RESTART_KNOWN_LIMITS  # noqa: E402
BASE = 'http://127.0.0.1:8081'

def req(path, body=None, origin=BASE, extra=None, raw=None):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    h = {'Content-Type': 'application/json'}
    if origin: h['Origin'] = origin
    h.update(extra or {})
    r = urllib.request.Request(BASE + path, data=data, headers=h, method='POST' if data is not None else 'GET')
    try:
        with urllib.request.urlopen(r, timeout=30) as resp: return resp.status, json.loads(resp.read() or b'null')
    except urllib.error.HTTPError as e:
        t = e.read()
        try: return e.code, json.loads(t)
        except Exception: return e.code, t.decode(errors='replace')[:300]

def now(): return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds')
out = {'started': now(), 'rows': []}
_, state = req('/api/state')
labs = {l['name']: l for l in state['labs']}
rs = labs['restore-square']; other = next(l for n, l in labs.items() if n != 'restore-square')
ops_before = len(req('/api/operations')[1])
def row(name, status, body, expect):
    tok = isinstance(body, dict) and any(k for k in body if 'token' in k.lower())
    ok = expect(status, body)
    out['rows'].append({'name': name, 'status': status, 'has_token': bool(tok), 'ok': bool(ok),
                        'body': body if not isinstance(body, dict) else {k: (v if k in ('detail', 'warnings', 'notes', 'argv', 'summary') else '…') for k, v in body.items()}})
kinds = {n['name']: n.get('kind') for n in rs['nodes']}
def warn_text(b): return json.dumps(b) if isinstance(b, dict) else str(b)
for node in ('clab-restore-square-vjunos-switch', 'clab-restore-square-xrv9k', 'clab-restore-square-ceos'):
    s, b = req('/api/operations/preview', {'action': 'restart-node', 'lab_id': rs['id'], 'node': node})
    lim = RESTART_KNOWN_LIMITS.get(kinds[node])
    if lim: row('preview %s carries its known limit verbatim' % node, s, b, lambda s, b, lim=lim: s == 200 and lim in warn_text(b))
    else: row('preview %s carries no known-limit text' % node, s, b, lambda s, b: s == 200 and not any(v in warn_text(b) for v in RESTART_KNOWN_LIMITS.values()) and 'Known limit' not in warn_text(b))
H = lambda s, b: 400 <= s < 500 and not (isinstance(b, dict) and any('token' in k.lower() for k in b))
row('refusal: node of another lab', *req('/api/operations/preview', {'action': 'restart-node', 'lab_id': rs['id'], 'node': other['nodes'][0]['name'] if other.get('nodes') else 'clab-%s-r1' % other['name']}), H)
row('refusal: node of restore-square under another lab id', *req('/api/operations/preview', {'action': 'restart-node', 'lab_id': other['id'], 'node': 'clab-restore-square-ceos'}), H)
row('refusal: unknown node', *req('/api/operations/preview', {'action': 'restart-node', 'lab_id': rs['id'], 'node': 'clab-restore-square-nosuch'}), H)
row('refusal: foreign Origin', *req('/api/operations/preview', {'action': 'restart-node', 'lab_id': rs['id'], 'node': 'clab-restore-square-ceos'}, origin='http://evil.example.com'), H)
row('refusal: Sec-Fetch-Site cross-site', *req('/api/operations/preview', {'action': 'restart-node', 'lab_id': rs['id'], 'node': 'clab-restore-square-ceos'}, extra={'Sec-Fetch-Site': 'cross-site'}), H)
row('refusal: option-shaped node name', *req('/api/operations/preview', {'action': 'restart-node', 'lab_id': rs['id'], 'node': '--all'}), H)
row('refusal: short name with a comma list', *req('/api/operations/preview', {'action': 'restart-node', 'lab_id': rs['id'], 'node': 'ceos,host1'}), H)
row('refusal: empty body', *req('/api/operations/preview', raw=b''), H)
row('refusal: unknown lab id', *req('/api/operations/preview', {'action': 'restart-node', 'lab_id': '0' * 32, 'node': 'clab-restore-square-ceos'}), H)
row('refusal: confirm with a forged token (never a real one)', *req('/api/operations/confirm', {'token': 'f' * 32}), H)
ops_after = len(req('/api/operations')[1])
out['ops_before'] = ops_before; out['ops_after'] = ops_after
out['rows'].append({'name': 'no operation job created', 'ok': ops_before == ops_after, 'status': None, 'has_token': False, 'body': '%d before, %d after' % (ops_before, ops_after)})
out['finished'] = now()
print(json.dumps(out, indent=1))
print('%d rows, %d failed' % (len(out['rows']), sum(1 for r in out['rows'] if not r['ok'])), file=sys.stderr)
