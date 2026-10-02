#!/usr/bin/env python3
"""Pass 8 adversarial Restart device transitions on the deployed manager (restarts only host1; a ceos restart
would be allowed but is expected to be refused). Container identities via plain `docker inspect` (read-only).
L1 a Restart review opened for host1 of restore-square, then browser Back to Quick-Test (which also has a host1):
   does the review stay open over the other lab, and does it name its lab? Confirmed: exactly restore-square's
   host1 restarts (job lab id and node), nothing else.
L2 cross-device staleness: an API review of ceos, then a host1 restart of the same lab through the API; the ceos
   review must be refused as stale (409, "ran after this review") and ceos must not restart.
L3 token reuse: the host1 token of L2 confirmed a second time: refused, no second job.
L4 a review closed with its tab: no job.
Usage: live_transitions.py <out dir>"""
import json, subprocess, sys, time, urllib.request, urllib.error
from datetime import datetime, timezone
from pathlib import Path
from playwright.sync_api import sync_playwright
sys.path.insert(0, '/home/clabllm/projects/clab-manager-1.30.42/docs/netlab-ui-qa/tools')
from check_restart_device import open_map_menu, review_open, review_text  # noqa: E402
BASE = 'http://127.0.0.1:8081'; OUT = Path(sys.argv[1])
checks, console, errors, rec = [], [], [], {}
def now(): return datetime.now(timezone.utc).isoformat(timespec='seconds')
def check(name, ok, detail=''): checks.append({'name': name, 'ok': bool(ok), 'detail': str(detail)[:500], 'at': now()}); print(('  ok   ' if ok else '  FAIL ') + name + ('' if ok else ': ' + str(detail)[:400]), flush=True)
def call(method, path, body=None):
    r = urllib.request.Request(BASE + path, data=json.dumps(body).encode() if body is not None else None, method=method, headers={'Content-Type': 'application/json', 'Origin': BASE})
    try:
        with urllib.request.urlopen(r, timeout=120) as resp: return resp.status, json.loads(resp.read() or b'null')
    except urllib.error.HTTPError as e: return e.code, json.loads(e.read() or b'null')
def inspect(names):
    out = json.loads(subprocess.run(['docker', 'inspect'] + names, capture_output=True, text=True, check=True).stdout)
    return {c['Name'].lstrip('/'): {'id': c['Id'][:12], 'started': c['State']['StartedAt'], 'status': c['State']['Status']} for c in out}
def jobs(): return call('GET', '/api/operations')[1] or []
def ids(): return {j['id'] for j in jobs()}
def follow(job_id, t=120):
    end = time.time() + t
    while time.time() < end:
        j = next((j for j in jobs() if j['id'] == job_id), None)
        if j and j['status'] not in ('queued', 'running'): return j
        time.sleep(1)
    return None
def idle(t=90):
    end = time.time() + t
    while time.time() < end:
        s = call('GET', '/api/state')[1]
        if not any(j.get('status') in ('queued', 'running') for j in s.get('operations', [])): return True
        time.sleep(1)
    return False
st = call('GET', '/api/state')[1]; labs = {l['name']: l for l in st['labs']}
rs, qt = labs['restore-square'], labs['Quick-Test']
ALL = [n['name'] for n in rs['nodes']]; H = 'clab-restore-square-host1'; C = 'clab-restore-square-ceos'
rec['started'] = now()
with sync_playwright() as pw:
    br = pw.chromium.launch(); ctx = br.new_context(viewport={'width': 1366, 'height': 800})
    p = ctx.new_page(); p.on('console', lambda m: console.append(m.text) if m.type == 'error' else None); p.on('pageerror', lambda e: errors.append(str(e)))
    # L1
    p.goto(BASE + '/#lab=' + qt['id'] + '&view=topology'); p.wait_for_timeout(2500)
    p.evaluate("(h) => { location.hash = h }", '#lab=' + rs['id'] + '&view=topology')
    p.wait_for_selector('#topology-map [data-map-node="%s"]' % H, timeout=30000); p.wait_for_timeout(1000)
    p.wait_for_function("() => typeof busy === 'function' && !busy()", timeout=90000)
    before = inspect(ALL); n0 = ids()
    open_map_menu(p, H).click(); review_open(p)
    t0 = review_text(p); rec['l1_review'] = t0[:700]
    p.screenshot(path=str(OUT / 'live-L1-1-review.png'))
    p.go_back(); p.wait_for_timeout(2500)
    active = p.evaluate("() => typeof activeId==='string'?activeId:''"); still = p.evaluate("() => !!document.getElementById('operation-review')?.open")
    t1 = review_text(p) if still else ''
    rec['l1_after_back'] = {'active': active, 'is_quick_test': active == qt['id'], 'review_open': still, 'text': t1[:400]}
    p.screenshot(path=str(OUT / 'live-L1-2-after-back.png'))
    check('L1 Back reached Quick-Test', active == qt['id'], rec['l1_after_back'])
    if still:
        check('L1 the review left open over another lab names its own lab (restore-square) and device', 'restore-square' in t1 and 'host1' in t1, t1[:300])
        p.click('#op-confirm'); p.wait_for_timeout(2000)
        new = [j for j in jobs() if j['id'] not in n0]
        j = follow(new[0]['id']) if new else None
        after = inspect(ALL)
        rec['l1_job'] = j and {k: j.get(k) for k in ('id', 'lab_id', 'node', 'status', 'message', 'created', 'finished')}
        check('L1 confirming it restarts exactly restore-square host1 (one job, that lab and node, succeeded)', len(new) == 1 and j and j['lab_id'] == rs['id'] and j['node'] == H and j['status'] == 'succeeded', rec['l1_job'])
        check('L1 only host1 got a new start time', after[H]['started'] > before[H]['started'] and all(after[k] == before[k] for k in ALL if k != H), json.dumps({k: (before[k]['started'], after[k]['started']) for k in ALL}))
    else:
        check('L1 the review closed with the navigation, no job', ids() == n0, ids() - n0)
    # L4: a review closed with its tab
    idle(); q = ctx.new_page(); q.goto(BASE + '/#lab=' + rs['id'] + '&view=topology'); q.wait_for_selector('#topology-map [data-map-node="%s"]' % H, timeout=30000); q.wait_for_timeout(1000)
    q.wait_for_function("() => typeof busy === 'function' && !busy()", timeout=90000)
    n1 = ids(); open_map_menu(q, H).click(); review_open(q); q.close(); time.sleep(2)
    check('L4 a review closed with its tab starts nothing', ids() == n1, ids() - n1)
    br.close()
# L2 and L3 through the API
idle()
code_c, prev_c = call('POST', '/api/operations/preview', {'action': 'restart-node', 'lab_id': rs['id'], 'node': C})
code_h, prev_h = call('POST', '/api/operations/preview', {'action': 'restart-node', 'lab_id': rs['id'], 'node': H})
before = inspect(ALL); n2 = ids()
code, job = call('POST', '/api/operations/confirm', {'token': prev_h['token']})
jh = follow(job['id']) if code == 200 else None
rec['l2_host1_job'] = jh and {k: jh.get(k) for k in ('id', 'status', 'message', 'created', 'finished')}
check('L2 setup: the host1 restart through the API succeeded', code == 200 and jh and jh['status'] == 'succeeded', (code, rec['l2_host1_job']))
idle(); time.sleep(1)
code2, js2 = call('POST', '/api/operations/confirm', {'token': prev_c['token']})
time.sleep(2); after = inspect(ALL)
rec['l2_ceos_confirm'] = {'status': code2, 'detail': (js2 or {}).get('detail'), 'ceos_started_before': before[C]['started'], 'ceos_started_after': after[C]['started']}
check('L2 the older ceos review is refused as stale after a host1 restart of the same lab', code2 == 409 and 'ran after this review' in str((js2 or {}).get('detail')), rec['l2_ceos_confirm'])
check('L2 ceos did not restart', after[C]['started'] == before[C]['started'], rec['l2_ceos_confirm'])
code3, js3 = call('POST', '/api/operations/confirm', {'token': prev_h['token']})
rec['l3_reuse'] = {'status': code3, 'detail': (js3 or {}).get('detail'), 'jobs_new': len(ids() - n2)}
check('L3 a used token confirmed again is refused (4xx) and no second job exists', 400 <= code3 < 500 and len(ids() - n2) == 1, rec['l3_reuse'])
HANDLED = 'Failed to load resource: the server responded with a status of '
check('no unexpected console errors', not [c for c in console if not c.startswith(HANDLED)], console[:5]); check('no page errors', not errors, errors[:3])
rec.update(finished=now(), checks=checks, console=console)
(OUT / 'live-transitions.json').write_text(json.dumps(rec, indent=1) + '\n')
print('%d checks, %d failed' % (len(checks), sum(1 for c in checks if not c['ok'])))
