import sys, json
sys.path.insert(0, 'docs/git-redesign/tools/live')
from l1lib import *
B2 = ['clab-git-redesign-b-ceos1', 'clab-git-redesign-b-ceos2']
def op(action, **kw):
    s, p = api('POST', '/api/operations/preview', dict(action=action, lab_id=LAB_B, **kw), limit=900)
    if s != 200: return s, p
    tok = p.get('token') or p.get('confirm_token')
    s, c = api('POST', '/api/operations/confirm', dict(token=tok), limit=500)
    jid = c.get('id') or c.get('job_id')
    while True:
        j = mgr.call('GET', f'/api/operations/{jid}')[1]
        if j.get('status') not in ('queued', 'running'):
            print(f'[{now()}]   operation {action} ->', trim(j, ('status', 'message', 'action'), 500)); return s, j
        time.sleep(3)
print('SCENARIO 15: a stopped lab (git-redesign-b destroyed with the manager\'s own lab operation)')
print('--- first a save of B so nothing waits, and an upload')
set_description('b-ceos1', 'l1-s15-b1'); s, j = save(LAB_B, note='l1 s15 before destroy'); s, c = compare(LAB_B, j['id']); s, up = upload_and_wait(j['id'], c['head'])
print('upload:', trim(up, ('status', 'pushed', 'destination')))
print('B git_status', ready(LAB_B)[2]); show_descriptions('before destroy', ['b-ceos1', 'b-ceos2'])
s, p = api('POST', '/api/operations/preview', dict(action='destroy', lab_id=LAB_B), show=False); print('destroy preview keys:', sorted(p.keys()) if isinstance(p, dict) else p, 'HTTP', s)
tok = p.get('token')
s, c = api('POST', '/api/operations/confirm', dict(token=tok), limit=400)
jid = c.get('id') or c.get('job_id')
for _ in range(60):
    jj = mgr.call('GET', f'/api/operations/{jid}')[1]
    if jj.get('status') not in ('queued', 'running'): break
    time.sleep(3)
print('destroy job:', trim(jj, ('status', 'message', 'action'), 600))
time.sleep(8)
print('lab B readiness now:', ready(LAB_B))
print('containers:', containers_up())
print('--- a load of lab B\'s own save onto the stopped lab')
src = dict(type='folder', path='git-redesign/b/latest')
s, p = preflight(LAB_B, src)
s, a = api('POST', f'/api/labs/{LAB_B}/restore', dict(request_id=rid(), source=src, node_names=B2, confirm_minutes=5, acknowledge=True), limit=700)
print('--- states list for a stopped lab:')
s, a = api('GET', f'/api/labs/{LAB_B}/restore/states', show=False); print('HTTP', s, [(x['name'], x['loadable_devices']) for x in a.get('states', [])][:4])
print('--- a save of the stopped lab:')
s, j = save(LAB_B, note='l1 s15 stopped lab'); show_job(j, ('status', 'message'))
