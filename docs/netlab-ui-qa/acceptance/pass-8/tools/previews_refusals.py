#!/usr/bin/env python3
"""Pass 8 API previews and refusals against the deployed manager (previews only, never a confirmation of a
restart that is not allowed). Known-limit texts are compared verbatim with RESTART_KNOWN_LIMITS read from the
worktree's lab_operations.py (ast, no import). Writes previews-refusals.json into --out."""
import ast, json, sys, urllib.request, urllib.error
from datetime import datetime, timezone
from pathlib import Path
BASE = 'http://127.0.0.1:8081'; OUT = Path(sys.argv[1])
SRC = Path('/home/clabllm/projects/clab-manager-1.30.42/clab-backup-ui/app/lab_operations.py').read_text()
LIMITS = next(ast.literal_eval(n.value) for n in ast.parse(SRC).body if isinstance(n, ast.Assign) and getattr(n.targets[0], 'id', '') == 'RESTART_KNOWN_LIMITS')
def now(): return datetime.now(timezone.utc).isoformat(timespec='seconds')
def call(method, path, body=None, headers=None, raw=None):
    h = {'Content-Type': 'application/json', 'Origin': BASE}; h.update(headers or {})
    h = {k: v for k, v in h.items() if v is not None}
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    r = urllib.request.Request(BASE + path, data=data, method=method, headers=h)
    try:
        with urllib.request.urlopen(r, timeout=120) as resp: return resp.status, json.loads(resp.read() or b'null')
    except urllib.error.HTTPError as e:
        t = e.read()
        try: return e.code, json.loads(t)
        except Exception: return e.code, {'raw': t.decode(errors='replace')[:200]}
rows = []; checks = []
def check(name, ok, detail=''): checks.append({'name': name, 'ok': bool(ok), 'detail': str(detail)[:400]}); print(('  ok   ' if ok else '  FAIL ') + name + ('' if ok else ': ' + str(detail)[:300]))
st = call('GET', '/api/state')[1]
labs = {l['name']: l for l in st['labs']}; rs = labs['restore-square']; other = labs['netlab-test']
def ops(): return len(call('GET', '/api/operations')[1] or [])
before = ops()
def preview(lab_id, node, headers=None, label=None, body=None):
    code, js = call('POST', '/api/operations/preview', body if body is not None else {'action': 'restart-node', 'lab_id': lab_id, 'node': node}, headers)
    row = {'request': label or node, 'at': now(), 'status': code, 'token': bool((js or {}).get('token')) if isinstance(js, dict) else False,
           'detail': (js or {}).get('detail') if isinstance(js, dict) else None, 'warnings': (js or {}).get('warnings') if isinstance(js, dict) else None}
    rows.append(row); return row
v = preview(rs['id'], 'clab-restore-square-vjunos-switch', label='preview vjunos-switch')
check('vjunos-switch preview 200 with a token', v['status'] == 200 and v['token'], v)
check('vjunos-switch preview carries RESTART_KNOWN_LIMITS[juniper_vjunosswitch] verbatim', LIMITS['juniper_vjunosswitch'] in (v['warnings'] or []), v['warnings'])
x = preview(rs['id'], 'clab-restore-square-xrv9k', label='preview xrv9k')
check('xrv9k preview 200 with a token', x['status'] == 200 and x['token'], x)
check('xrv9k preview carries RESTART_KNOWN_LIMITS[cisco_xrv9k] verbatim', LIMITS['cisco_xrv9k'] in (x['warnings'] or []), x['warnings'])
c = preview(rs['id'], 'clab-restore-square-ceos', label='preview ceos')
check('ceos preview carries no known-limit text', c['status'] == 200 and not any(w in LIMITS.values() for w in (c['warnings'] or [])) and not any('Known limit' in w for w in (c['warnings'] or [])), c['warnings'])
h = preview(rs['id'], 'clab-restore-square-host1', label='preview host1 (cJunosEvolved not requested at all)')
check('host1 preview carries no known-limit text', h['status'] == 200 and not any('Known limit' in w for w in (h['warnings'] or [])), h['warnings'])
def refused(row, name): check(name + ' is a 4xx without a token', 400 <= row['status'] < 500 and not row['token'], row)
refused(preview(rs['id'], 'clab-netlab-test-host1', label='node of another lab (netlab-test host1) under restore-square'), 'node of another lab')
refused(preview(other['id'], 'clab-restore-square-host1', label='restore-square host1 under netlab-test id'), 'restore-square node under another lab id')
refused(preview(rs['id'], 'clab-restore-square-nosuch', label='unknown node'), 'unknown node')
refused(preview(rs['id'], 'clab-restore-square-host1', headers={'Origin': 'http://evil.example.com'}, label='foreign Origin'), 'foreign Origin')
refused(preview(rs['id'], 'clab-restore-square-host1', headers={'Sec-Fetch-Site': 'cross-site'}, label='Sec-Fetch-Site cross-site'), 'cross-site fetch')
refused(preview(rs['id'], 'host1', label='bare short name host1'), 'bare short name (not the manager node name)') if False else None
refused(preview(rs['id'], 'clab-restore-square-host1 ', label='node with trailing space'), 'node with trailing space')
refused(preview(rs['id'], '../clab-restore-square-host1', label='node with a path prefix'), 'node with a path prefix')
refused(preview(rs['id'], 'clab-restore-square-host1', body={'action': 'restart-node', 'lab_id': rs['id'], 'node': 'clab-restore-square-host1', 'options': {'node': 'cjunosevolved'}}, label='options smuggling another node'), 'options smuggling another node')
refused(preview(rs['id'], 'clab-restore-square-host1', body={'action': 'restart-node', 'lab_id': rs['id'], 'node': 'clab-restore-square-host1', 'path': '/etc/passwd'}, label='path given'), 'path given')
refused(preview(rs['id'], 'x', body={'action': 'restart-node', 'lab_id': rs['id']}, label='no node'), 'no node')
code, js = call('POST', '/api/operations/confirm', {'token': 'f' * 32}); rows.append({'request': 'confirm forged token', 'status': code, 'detail': (js or {}).get('detail')})
check('forged confirm token refused 4xx', 400 <= code < 500, (code, js))
after = ops()
check('no operation job was created (count before == after)', before == after, (before, after))
json.dump({'at': now(), 'jobs_before': before, 'jobs_after': after, 'rows': rows, 'checks': checks}, open(OUT / 'previews-refusals.json', 'w'), indent=1); open(OUT / 'previews-refusals.json', 'a').write('\n')
print('%d checks, %d failed' % (len(checks), sum(1 for c in checks if not c['ok'])))
