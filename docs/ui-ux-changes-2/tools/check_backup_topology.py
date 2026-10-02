#!/usr/bin/env python3
"""Item 10: the topology and map travel with every backup. Against the deployed manager on the dev VM, through the
product's own API (the same calls the pages make): a small lab (one Arista cEOS, one Linux host, a link, a map) is
saved to the VM through the reviewed publish, added to My labs, deployed, backed up once its device is ready; the
backup record carries the topology and map as read from the VM at capture time, the files sit beside the
configuration, the ZIP carries them under the lab's names; then the lab is connected to the registered repository
under its own test folder, saved on the VM only (no push), and the saved version carries the files as entries of
their kind the restore never offers; finally the lab is destroyed and removed from the manager. Leftovers on the
VM, named at the end: the lab folder, the backup files, the registration and one local commit in the checkout.

    CLAB_BASE=http://192.168.132.132:8081 CLAB_REPO=https://github.com/pruger-dev/CLAB-MNGR-DEV-LLM.git \\
      clab-backup-ui/.venv/bin/python docs/ui-ux-changes-2/tools/check_backup_topology.py
"""
import io
import json
import os
import sys
import time
import uuid
import zipfile

import httpx

BASE = os.environ.get('CLAB_BASE', 'http://192.168.132.132:8081')
REPO = os.environ.get('CLAB_REPO', 'https://github.com/pruger-dev/CLAB-MNGR-DEV-LLM.git')
ROOT = os.environ.get('CLAB_ROOT', '/srv/containerlab-node-manager/projects')
IMAGE = os.environ.get('CLAB_CEOS', 'n24l/ceos:4.35.0F')
NAME = os.environ.get('CLAB_LAB') or 'uiux2-bk-' + time.strftime('%H%M%S')   # an existing deployed lab of this shape can be reused
failed = []
client = httpx.Client(base_url=BASE, timeout=120)


def check(name, ok, detail=''):
    print(('ok   ' if ok else 'FAIL ') + name + (f' :: {detail}' if not ok else ''), flush=True)
    if not ok:
        failed.append(name)


def post(path, body):
    r = client.post('/api' + path, json=body)
    if r.status_code >= 400: raise RuntimeError(f'{path} -> {r.status_code} {r.text[:300]}')
    return r.json()


def state(): return client.get('/api/state').json()
def lab_of(): return next((l for l in state()['labs'] if l['name'] == NAME), None)


def dismiss_saves():
    """A save kept on the VM only waits for its upload review; 'Keep snapshot only in Git history' (dismiss) lets
    the lab be connected again or removed."""
    for job in state().get('git_jobs', []):
        if job.get('lab_id') == lab_id and job.get('status') in ('review_pending', 'committed', 'failed', 'needs_attention'):
            client.post('/api/git/jobs/' + job['id'] + '/dismiss', json={'acknowledge': True})


def wait_idle(seconds=300):
    """The manager runs one job at a time and the readiness monitor submits its own login tests: wait for the queue."""
    for _ in range(seconds // 3):
        s = state()
        if not any(j['status'] in ('queued', 'running') for j in s['jobs']) and not any(j['status'] in ('queued', 'running') for j in s.get('operations', [])): return
        time.sleep(3)


def operation(action, lab_id='', **extra):
    review = post('/operations/preview', {'action': action, 'lab_id': lab_id, **extra})
    job = post('/operations/confirm', {'token': review['token']})
    for _ in range(240):
        current = client.get('/api/operations/' + job['id']).json()
        if current['status'] not in ('queued', 'running'): return current
        time.sleep(2)
    raise RuntimeError(action + ' did not finish')


topology = f'name: {NAME}\ntopology:\n  nodes:\n    sw1:\n      kind: arista_ceos\n      image: {IMAGE}\n    host1:\n      kind: linux\n      image: ghcr.io/srl-labs/network-multitool:latest\n  links:\n    - endpoints: ["sw1:eth1", "host1:eth1"]\n'
annotations = json.dumps({'nodeAnnotations': [{'id': 'sw1', 'position': {'x': 100, 'y': 100}, 'labelPosition': 'top-right'}, {'id': 'host1', 'position': {'x': 300, 'y': 100}}]}, indent=2)
lab_id = ''
try:
    # 1. The lab on the VM, in My labs, deployed (or an existing deployed lab of this name, reused).
    path = f'{ROOT}/{NAME}/{NAME}.clab.yml'
    existing = lab_of()
    if existing and existing.get('deployment', {}).get('status') == 'Running':
        lab_id = existing['id']; print('reusing the deployed lab', NAME)
    else:
        done = operation('publish', options={'root': ROOT, 'text': topology, 'annotations': annotations})
        check('the lab is saved to the VM through the reviewed publish', done['status'] == 'succeeded', done.get('message'))
        source = post('/operations/read', {'path': path})
        registered = client.post('/api/lab-definitions', files={'definition': (NAME + '.clab.yml', source['text'].encode(), 'text/yaml'), 'annotations': (NAME + '.clab.yml.annotations.json', annotations.encode(), 'application/json')}).json()
        lab_id = registered['id']; client.put(f'/api/labs/{lab_id}/operations-settings', json={'path': path})
        deployed = operation('deploy', lab_id, path=path, name=NAME)
        check('the lab deploys', deployed['status'] == 'succeeded', deployed.get('message'))
    source = post('/operations/read', {'path': path})
    for _ in range(90):
        lab = lab_of(); node = next((n for n in lab['nodes'] if n['name'].endswith('sw1')), None) if lab else None
        if node and node.get('nos_login', {}).get('status') == 'ready': break
        time.sleep(5)
    check('the cEOS device becomes ready', node and node['nos_login']['status'] == 'ready', node and node.get('nos_login'))
    # 2. A backup on demand: the topology and map come from the VM's files at capture time.
    wait_idle()
    job = post(f'/labs/{lab_id}/jobs', {'operation': 'backup', 'node_names': [node['name']]})
    for _ in range(90):
        job = next(j for j in state()['jobs'] if j['id'] == job['id'])
        if job['status'] not in ('queued', 'running'): break
        time.sleep(3)
    check('the backup succeeds', job['status'] == 'succeeded', job.get('message'))
    record = job.get('topology') or {}
    check('the backup record carries the topology and map read from the VM', record.get('source') == 'vm' and record.get('path') == path and record.get('annotations_file') and record.get('read_at'), record)
    check('the public record names the download files', record.get('download_name') == NAME + '.clab.yml' and record.get('annotations_download_name') == NAME + '.clab.yml.annotations.json', record)
    archive = client.get(f'/api/jobs/{job["id"]}/download')
    with zipfile.ZipFile(io.BytesIO(archive.content)) as z:
        names = z.namelist()
        check('the ZIP holds the configuration, the manifest, the topology and the map under the lab\'s names', NAME + '.clab.yml' in names and NAME + '.clab.yml.annotations.json' in names and 'manifest.json' in names and len(names) == 4, names)
        check('the embedded topology is the file on the VM, byte for byte', z.read(NAME + '.clab.yml').decode() == source['text'])
        check('the embedded map is the file beside it', json.loads(z.read(NAME + '.clab.yml.annotations.json'))['nodeAnnotations'][0]['labelPosition'] == 'top-right')
        check('the manifest records the provenance', json.loads(z.read('manifest.json'))['topology']['source'] == 'vm')
    # 3. A Git save (on the VM only, no push) carries them as entries of their kind.
    wait_idle(); dismiss_saves()
    connected = post(f'/labs/{lab_id}/git/connect', {'url': REPO, 'prefix': 'uiux2-tests/' + NAME, 'node_names': [node['name']], 'acknowledge': True})
    check('the lab is connected to its own test folder of the registered repository', connected.get('saved') and connected['binding']['repository']['prefix'] == 'uiux2-tests/' + NAME, connected)
    save = post(f'/labs/{lab_id}/git/save', {'request_id': uuid.uuid4().hex, 'target': 'latest', 'push': False, 'note': 'UI/UX changes 2 item 10 check'})
    for _ in range(120):
        save = client.get('/api/git/jobs/' + save['id']).json()
        if save['status'] not in ('queued', 'capturing', 'exporting', 'pushing'): break
        time.sleep(3)
    check('the save on this VM only completes without an upload', save['status'] in ('committed', 'review_pending', 'synced') and not save.get('pushed'), (save.get('status'), save.get('message')))
    history = client.get(f'/api/labs/{lab_id}/git/history').json()
    version = post(f'/labs/{lab_id}/git/version', {'commit': save['commit'], 'path': 'latest'})
    files = [f['name'] for f in version['files']]
    check('the saved version lists the topology and map beside the device file', NAME + '.clab.yml' in files and NAME + '.clab.yml.annotations.json' in files and any(f.endswith('.cfg') for f in files), files)
    kinds = {f['path']: f.get('kind') for f in version['manifest']['files']}
    check('the manifest marks them by kind, not as devices, with the VM provenance', kinds.get(NAME + '.clab.yml') == 'topology' and kinds.get(NAME + '.clab.yml.annotations.json') == 'annotations' and version['manifest']['topology_provenance'] == 'embedded' and all('node' not in f for f in version['manifest']['files'] if f.get('kind')), kinds)
    check('the restore never offers them', version['restore_nodes'] == [node['name']] or NAME + '.clab.yml' not in version['restore_nodes'], version['restore_nodes'])
    check('the embedded topology in the save is the VM file', next(f['text'] for f in version['files'] if f['name'] == NAME + '.clab.yml') == source['text'])
    checkout = connected['binding']['repository']['path']
    print('leftovers on the VM: lab folder %s, backup files of lab %s under the manager data, registration %s in %s with one local commit %s' % (ROOT + '/' + NAME, lab_id, 'uiux2-tests/' + NAME, checkout, save.get('commit')))
finally:
    if lab_id:
        try: client.post(f'/api/labs/{lab_id}/git/unlink', json={})
        except Exception as exc: print('unlink failed:', exc)
        try:
            wait_idle()
            ended = operation('destroy', lab_id, options={'cleanup': True})
            check('the lab is destroyed afterwards', ended['status'] == 'succeeded', ended.get('message'))
        except Exception as exc: print('destroy failed:', exc)
        try:
            wait_idle(); dismiss_saves()
            removed = client.request('DELETE', f'/api/labs/{lab_id}', json={'name': NAME, 'prevent_reimport': False})
            check('the lab is removed from the manager afterwards', removed.status_code == 200, removed.text[:200])
        except Exception as exc: print('remove failed:', exc)
print('FAILED: ' + ', '.join(failed) if failed else 'ALL CHECKS PASSED')
sys.exit(1 if failed else 0)
