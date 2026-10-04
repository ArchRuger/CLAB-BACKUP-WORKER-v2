import sys, json
sys.path.insert(0, 'docs/git-redesign/tools/live')
from l1lib import *
mark = sys.argv[1]
print('SCENARIO 10: upload failure and recovery (github.com made unreachable with a temporary /etc/hosts line)')
if len(sys.argv) > 2:
    # resume: the save of the first (interrupted) run is already on the VM, waiting
    ja = git_job(sys.argv[2])
    print('resuming with the waiting save', ja['id'][:8], ja['status'])
else:
    set_description('a-ceos1', 'l1-s10-ceos1')
    s, ja = save(LAB_A, note='l1 s10 upload failure')
show_job(ja, ('status', 'note', 'commit', 'pushed'))
s, c = compare(LAB_A, ja['id'])
print(sh('bash', '-c', f"echo '127.0.0.1 github.com www.github.com api.github.com {mark}' | sudo tee -a /etc/hosts >/dev/null; getent hosts github.com"))
s, up = upload_and_wait(ja['id'], c['head'])
print('upload job after the failure:', trim(up, ('status', 'message', 'pushed', 'commit', 'reviewed')))
print('git_status A:', ready(LAB_A)[2])
s, lab = api('GET', f'/api/labs/{LAB_A}/git', show=False)
print('repository_status:', trim(lab.get('repository_status'), limit=500))
checkout('during failure')
print('--- a save while the upload keeps failing: does a new save work (VM only)?')
set_description('a-ceos2', 'l1-s10-ceos2')
s, j2 = save(LAB_A, note='l1 s10 second while blocked'); show_job(j2, ('status', 'message', 'note', 'commit', 'pushed'))
print('git_status after 2nd save:', ready(LAB_A)[2])
print('--- try upload again while still blocked (retry from the failed state)')
s, c2 = compare(LAB_A, j2['id'])
s, up2 = upload_and_wait(j2['id'], c2['head'])
print('second upload attempt:', trim(up2, ('status', 'message', 'pushed')))
print('first job now:', trim(git_job(ja['id']), ('status', 'message', 'pushed')))
print(sh('bash', '-c', f"sudo sed -i '/{mark}/d' /etc/hosts; getent hosts github.com | head -1"))
print('=== network restored; the retry:')
s, c3 = compare(LAB_A, j2['id'])
s, up3 = upload_and_wait(c3['upload_job'], c3['head'])
print('retry job:', trim(up3, ('status', 'message', 'pushed')))
for jid in (ja['id'], j2['id']):
    print(' ', trim(git_job(jid), ('status', 'message', 'pushed', 'note')))
print('git_status A:', ready(LAB_A)[2])
github('after retry'); checkout('after retry')
