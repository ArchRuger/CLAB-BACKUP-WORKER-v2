#!/usr/bin/env python3
"""Self-check of the Git save and load fixture: starts it on a free port with a fresh data directory, asks the application's
own API (and the fixture's control) and asserts that every seeded scenario is really there.

    clab-backup-ui/.venv/bin/python docs/git-redesign/tools/fixture/check_fixture.py [--port 8191] [--keep-logs]

One line per scenario: `ok`, `FAIL` (exit status 1) or `SKIP` (a route another slice is still building; the line names it).
Port range for this tool: 8191 to 8199. Nothing here reaches a VM, a device or live data.
"""
import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
FIXTURE = ROOT / 'docs' / 'redesign' / 'tools' / 'fixture_manager.py'
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
results = {'ok': 0, 'fail': 0, 'skip': 0}
BASE = ''


def line(kind, name, detail=''):
    results[kind] += 1
    print(f'{kind.upper() if kind != "ok" else "ok":4} {name}' + (f' :: {detail}' if detail else ''), flush=True)


def check(name, condition, detail=''):
    line('ok' if condition else 'fail', name, '' if condition else detail)
    return bool(condition)


def skip(name, why):
    line('skip', name, why)


def call(method, path, body=None, timeout=60):
    data, headers = None, {'Origin': BASE}
    if method != 'GET':
        data, headers['Content-Type'] = json.dumps({} if body is None else body).encode(), 'application/json'
    request = urllib.request.Request(BASE + path, data=data, method=method, headers=headers)
    try:
        with OPENER.open(request, timeout=timeout) as response:
            return response.status, json.loads(response.read().decode() or 'null')
    except urllib.error.HTTPError as error:
        raw = error.read().decode()
        try:
            return error.code, json.loads(raw)
        except ValueError:
            return error.code, {'raw': raw[:300]}


def action(name, **arguments):
    status, answer = call('POST', '/fixture/action', dict(action=name, **arguments))
    return answer.get('result') if status == 200 else answer


def helper(repository, **request):
    """A raw request to the scripted VM Git helper; the answer, or {'error': sentence}."""
    return action('helper', repository=repository, request=request)


def switch(**values):
    return call('POST', '/fixture/switch', values)[1]


def state():
    return call('GET', '/api/state')[1]


def lab_ids():
    return {lab['name']: lab['id'] for lab in state()['labs']}


def idle(timeout=90):
    until = time.time() + timeout
    while time.time() < until:
        s = state()
        busy = [j for j in s['jobs'] if j['status'] in ('queued', 'running')]
        busy += [j for j in s['git_jobs'] if j.get('status') in ('queued', 'capturing', 'exporting', 'pushing')]
        busy += [j for j in s.get('restore_jobs', []) if j.get('status') in ('queued', 'preflight', 'backing_up', 'applying', 'confirming', 'verifying')]
        if not busy:
            return True
        time.sleep(0.5)
    return False


def save(lab, note='check', push=False, **extra):
    request_id = uuid.uuid4().hex
    status, job = call('POST', f'/api/labs/{lab}/git/save', dict(request_id=request_id, note=note, push=push, **extra))
    if status != 200:
        return {'status': 'refused', 'message': str(job)}
    for _ in range(80):
        time.sleep(0.75)
        job = call('GET', f'/api/git/jobs/{request_id}')[1]
        if job['status'] not in ('queued', 'capturing', 'exporting', 'pushing'):
            break
    return job


def preflight(lab, path, names=None):
    body = {'source': {'type': 'folder', 'path': path}}
    if names:
        body['node_names'] = names
    status, answer = call('POST', f'/api/labs/{lab}/restore/preflight', body)
    return answer if status == 200 else {'error': answer, 'status': status, 'targets': []}


def load(lab, path, names, minutes=2, wait=120):
    request_id = uuid.uuid4().hex
    status, job = call('POST', f'/api/labs/{lab}/restore', {'request_id': request_id, 'source': {'type': 'folder', 'path': path}, 'node_names': names,
                                                              'confirm_minutes': minutes, 'acknowledge': True})
    if status != 200:
        return {'status': 'refused', 'targets': [], 'message': str(job)}
    settled, until = {}, time.time() + wait
    start = time.time()
    while time.time() < until:
        time.sleep(0.4)
        job = call('GET', f'/api/restore/jobs/{job["id"]}')[1]
        for t in job['targets']:
            if t['status'] not in ('pending', 'backing_up', 'applying', 'confirming') and t['name'] not in settled:
                settled[t['name']] = time.time() - start
        if job['status'] not in ('queued', 'preflight', 'backing_up', 'applying', 'confirming', 'verifying'):
            break
    job['settled'] = settled
    return job


def outcomes(job):
    return {t['name'].rsplit('-', 1)[-1] if 'xrv9k' not in t['name'] else 'xrv9k': t['status'] for t in job['targets']}


def short(name):
    for key in ('vjunos-switch', 'cjunosevolved', 'xrv9k', 'ceos'):
        if name.endswith('-' + key):
            return key
    return name


# --- the scenarios ---------------------------------------------------------------------------------------------------

def labs_and_repositories():
    s = state()
    labs = {lab['name']: lab for lab in s['labs']}
    for name in ('BGP_TheoryToPractice', 'ospf-basics', 'vlan-lab', 'switching-basics'):
        check(f'classic lab {name} is there', name in labs)
    square = labs.get('restore-square', {})
    check('restore-square: four devices, running, every login answered (Ready)',
          [short(n['name']) for n in square.get('nodes', [])] == ['ceos', 'cjunosevolved', 'vjunos-switch', 'xrv9k'] and square.get('deployment', {}).get('status') == 'Running'
          and all((square.get('nos_readiness', {}).get(n['name'], {}) or {}).get('status', 'reachable') == 'reachable' for n in square['nodes']), json.dumps(square.get('deployment')))
    check('ospf-basics is the stopped lab', labs['ospf-basics']['deployment']['status'] == 'Not deployed')
    fresh = labs['square-fresh']
    check('square-fresh has never saved: running, no save location, no save', not fresh.get('git_binding') and not [j for j in s['git_jobs'] if j.get('lab_id') == fresh['id']]
          and fresh['deployment']['status'] == 'Running')
    status, answer = call('GET', '/api/git/repositories')
    regs = {r['id']: r for r in answer.get('repositories', [])} if status == 200 else {}
    check('the helper lists the registrations', status == 200 and {'reg-work', 'reg-vlan', 'reg-archtop', 'reg-bgp', 'reg-bgp-edge', 'reg-shared', 'reg-solo', 'reg-big'} <= set(regs), str(list(regs)))
    top = [r for r in regs.values() if r['path'].endswith('/Archtop-Lab')]
    check('Archtop-Lab is registered ONLY at its top level and no lab is connected to it',
          [r['prefix'] for r in top] == [''] and not [l for l in labs.values() if (l.get('git_binding') or {}).get('binding_id') == 'reg-archtop'], str(top))
    bound = {name: (lab.get('git_binding') or {}).get('repository', {}).get('prefix') for name, lab in labs.items() if lab.get('git_binding')}
    check('nested lab folders: restore-square saves to BGP and edge-lab to BGP/edge (one repository)',
          bound.get('restore-square') == 'BGP' and bound.get('edge-lab') == 'BGP/edge'
          and labs['restore-square']['git_binding']['repository']['path'] == labs['edge-lab']['git_binding']['repository']['path'])
    check('a third lab saves at the top level of a second repository (solo-lab, Solo-Lab)', bound.get('solo-lab') == '' and labs['solo-lab']['git_binding']['repository']['path'].endswith('Solo-Lab'))
    check('a folder two labs want: shared-a saves to `shared`, shared-b is not connected',
          bound.get('shared-a') == 'shared' and not labs['shared-b'].get('git_binding'))
    check('a folder registered on the VM that no lab uses (old-lab-folder)', 'reg-unused' in regs and not [l for l in labs.values() if (l.get('git_binding') or {}).get('binding_id') == 'reg-unused'])
    check('the first fixture is intact: BGP_TheoryToPractice saves to labs/BGP/work, vlan-lab to labs/VLAN', bound.get('BGP_TheoryToPractice') == 'labs/BGP/work' and bound.get('vlan-lab') == 'labs/VLAN')
    return labs


def states(labs):
    history = helper('reg-bgp', mode='history')
    versions = {v['path']: v for v in history.get('versions', [])}
    check('history carries head and a summary per state (H3)', history.get('head') and all('summary' in v for v in versions.values()), str(list(history)))
    for path in ('BGP/start/latest', 'BGP/broken/latest', 'BGP/final/latest'):
        check(f'course state {path} is a lab state in `latest` layout, not connected', path in versions and not versions[path]['connected'])
    flat = versions.get('Final')
    check('a state stored directly in a folder (Final/manifest.json, flat layout)', bool(flat) and flat['summary'] and len(flat['summary']['devices']) == 4)
    view = versions.get('BGP/start/latest', {}).get('summary') or {}
    check('a state without restore artifacts (BGP/start/latest: view only)', view.get('devices') and not any(d['restore'] for d in view['devices']))
    subset = versions.get('BGP/junos-only/latest', {}).get('summary') or {}
    check('a state covering a subset (BGP/junos-only/latest: 2 of the lab\'s 4 devices)', sorted(d['short_name'] for d in subset.get('devices', [])) == ['cjunosevolved', 'vjunos-switch'])
    other = versions.get('BGP/other-topology/latest', {}).get('summary') or {}
    lab_nodes = {n['name'] for n in labs['restore-square']['nodes']}
    check('a state from a different topology (BGP/other-topology/latest: 3 of its 4 devices are in the lab)',
          len(other.get('devices', [])) == 4 and len({d['node'] for d in other['devices']} & lab_nodes) == 3)
    topo = {p: helper('reg-bgp', mode='read-version', commit=history['head'], path=p).get('snapshot', {}) for p in ('BGP/other-topology/latest', 'BGP/final/latest')}
    check('its embedded topology file differs from the lab\'s', topo['BGP/other-topology/latest'].get('manifest', {}).get('topology_digest') != topo['BGP/final/latest'].get('manifest', {}).get('topology_digest'))
    design = versions.get('BGP/checkpoints/plan-sept', {}).get('summary') or {}
    check('a design export (kind network-design, no devices)', design.get('kind') == 'network-design' and design.get('devices') == [])
    check('an unreadable state has a null summary and cannot be read', 'BGP/legacy' in versions and versions['BGP/legacy']['summary'] is None
          and 'invalid' in str(helper('reg-bgp', mode='read-version', commit=history['head'], path='BGP/legacy').get('error')))
    own = {p for p, v in versions.items() if v['connected']}
    check('the lab\'s own saves: latest, a starting point and two checkpoints', own == {'BGP/latest', 'BGP/baseline', 'BGP/checkpoints/ospf-up', 'BGP/checkpoints/loopbacks-reachable', 'BGP/checkpoints/plan-sept'}, str(sorted(own)))
    s = state()
    jobs = [j for j in s['git_jobs'] if j.get('lab_id') == labs['restore-square']['id']]
    latest = [j for j in jobs if j['target'] == 'latest']
    check('a latest save that is uploaded, three in history, and a history of several commits',
          len(latest) == 3 and latest[-1]['status'] == 'synced' and latest[-1]['pushed'] and len(history['commits']) >= 6, f'{len(latest)} latest, {len(history["commits"])} commits')
    check('two checkpoints and a starting point', sorted(j['target'] for j in jobs if j['target'] != 'latest') == ['baseline', 'checkpoint', 'checkpoint'])
    big = helper('reg-big', mode='browse')
    big_versions = [v['path'] for v in helper('reg-big', mode='history').get('versions', [])]
    check('a large repository: 5000 files, about 300 folders, the listing stops at 4000 files', len(big.get('files', [])) == 4000 and big.get('truncated') is True
          and 290 <= len(big.get('dirs', [])) <= 330 and not big.get('dirs_truncated'), f"{len(big.get('files', []))} files, {len(big.get('dirs', []))} dirs")
    listed = {f['path'] for f in big.get('files', [])}
    check('...with saved states beyond the cap (found by history, not by the tree)', len(big_versions) == 3 and not any(p + '/manifest.json' in listed for p in big_versions), str(big_versions))
    nested = helper('reg-bgp', mode='browse')
    check('browse carries every directory and dirs_truncated (H5)', 'BGP/start/latest' in nested.get('dirs', []) and nested.get('dirs_truncated') is False)
    empty = call('POST', f'/api/labs/{lab_ids()["shared-b"]}/git/connect', {'url': 'https://github.com/ArchRuger/New-Empty.git', 'prefix': '', 'acknowledge': True})
    check('a brand-new empty repository, reachable only by its address, is refused with the sentence the manager recognises (H4)',
          empty[0] == 409 and 'This repository has no commits yet' in json.dumps(empty[1]), str(empty))
    check('...and one connect with initialize starts it (the README commit, uploaded)', 'id' in (helper('', mode='connect', url='https://github.com/ArchRuger/New-Empty.git', prefix='', initialize=True)))


def devices_and_loads(labs):
    ids = lab_ids()
    square = ids['restore-square']
    bgp = preflight(ids['BGP_TheoryToPractice'], 'labs/BGP/solution/latest')
    r = {t['name'].split('-', 2)[-1]: t for t in bgp['targets']}
    check("the first fixture's restore preflight is unchanged: UP-2 matches, GTW-2 differs by one line, PE2 does not answer",
          r['UP-2']['matches_saved'] is True and r['GTW-2']['matches_saved'] is False and r['GTW-2']['pending_changes'] == 1 and r['PE2']['reachable'] is False, json.dumps(bgp)[:400])
    pre = preflight(square, 'BGP/final/latest')
    rows = {short(t['name']): t for t in pre['targets']}
    check('preflight of Final: ceos and xrv9k differ, the two Junos devices already match', not rows['ceos']['matches_saved'] and rows['ceos']['pending_changes'] > 0
          and rows['cjunosevolved']['matches_saved'] and rows['vjunos-switch']['matches_saved'] and not rows['xrv9k']['matches_saved'], json.dumps(pre)[:300])
    pre = preflight(square, 'BGP/start/latest')
    check('preflight of a view-only state: every device is refused with the reason', pre['eligible_count'] == 0 and all('no restore data' in t['reason'] for t in pre['targets']))
    pre = preflight(square, 'BGP/junos-only/latest')
    check('preflight of the 2-of-4 state lists two devices', sorted(short(t['name']) for t in pre['targets']) == ['cjunosevolved', 'vjunos-switch'])
    pre = preflight(square, 'BGP/other-topology/latest')
    check('preflight of the other-topology state: 3 of its 4 devices match the lab', sum(1 for t in pre['targets'] if t['eligible']) == 3
          and [t['reason'] for t in pre['targets'] if not t['eligible']] == ['No running node in this lab matches this saved node.'])

    def run(preset, path='BGP/final/latest', seconds=None):
        action('reset')
        switch(load_preset=preset, **({'load_seconds': seconds} if seconds else {}))
        names = [t['name'] for t in preflight(square, path)['targets'] if t['eligible']]
        return load(square, path, names)
    job = run('all-ok')
    check('load: all devices loaded and verified', job['status'] == 'succeeded' and set(outcomes(job).values()) == {'verified'} and len(job['targets']) == 4, json.dumps(outcomes(job)))
    job = run('one-failed')
    o = outcomes(job)
    check('load: one device not loaded (failed), three loaded', o.get('xrv9k') == 'failed' and list(o.values()).count('verified') == 3, str(o))
    job = run('one-rolled-back')
    o = outcomes(job)
    check('load: one device rolled back (read back as the previous configuration)', o.get('xrv9k') == 'rolled_back' and list(o.values()).count('verified') == 3, str(o))
    job = run('one-uncertain')
    o = outcomes(job)
    check('load: one device uncertain', o.get('xrv9k') == 'uncertain' and list(o.values()).count('verified') == 3, str(o))
    action('reset')
    switch(load_preset='one-unreachable')
    pre = preflight(square, 'BGP/final/latest')
    row = next(t for t in pre['targets'] if short(t['name']) == 'xrv9k')
    check('preflight: a device unreachable', row['reachable'] is False and not row['eligible'] and 'SSH probe failed' in row['reason'], str(row))
    switch(load_preset='one-blocked')
    row = next(t for t in preflight(square, 'BGP/final/latest')['targets'] if short(t['name']) == 'xrv9k')
    check('preflight: a device with a pending change that blocks it', row['reachable'] is True and not row['eligible'] and 'waiting for confirmation' in row['reason'], str(row))
    switch(load_preset='one-editing')
    row = next(t for t in preflight(square, 'BGP/final/latest')['targets'] if short(t['name']) == 'xrv9k')
    check('preflight: a device with somebody editing (blocked by uncommitted changes)', not row['eligible'] and 'uncommitted' in row['reason'], str(row))
    job = run('slow', seconds=1.5)
    times = sorted(job['settled'].values())
    check('a slow load: devices settle one after another (progress can be watched)', job['status'] == 'succeeded' and len(times) == 4 and times[-1] - times[0] >= 3, str(times))
    action('reset')
    idle()


def saves():
    ids = lab_ids()
    square = ids['restore-square']
    action('reset')
    idle()
    job = save(square, 'nothing changed')
    check('Save with nothing changed is `unchanged` (the last save was uploaded)', job['status'] == 'unchanged', f"{job['status']}: {job['message']}")
    action('edit_device', device='ceos', add=['   ip route 0.0.0.0/0 10.0.0.1'])
    action('edit_device', device='xrv9k', add=[' router static', '  address-family ipv4 unicast'])
    job = save(square, 'two devices changed')
    names = {f.split('/')[-1] for f in job.get('changed_files', [])}
    check('after two edits Save commits a change: exactly ceos and xrv9k (and their restore artifacts) changed', job['status'] in ('committed', 'review_pending') and names == {'ceos.cfg', 'ceos.eoscfg', 'xrv9k.cfg', 'xrv9k.xrcfg', 'manifest.json'}, f"{job['status']} {sorted(names)}")
    repo = helper('reg-bgp', mode='status')
    check('the save waits for upload (a commit the remote lacks)', action('helper', repository='reg-bgp', request={'mode': 'compare', 'operation_id': job['id']}).get('outgoing', [None])[0].get('operation_id') == job['id'])
    # a further folder registers while a save waits (H2), and a retire that would strand it is refused (H7)
    check('H2: registering a further folder works while saves wait', 'id' in helper('reg-bgp', mode='register-prefix', prefix='BGP/extra-folder'))
    check('H7: retiring the registration a waiting save was made through is refused', helper('reg-bgp', mode='register-prefix', prefix='moved', retire=True).get('error') == 'A save made in that folder still waits for upload.')
    check('H1: nesting is never refused (inside, above, beside)', all('id' in helper('reg-bgp', mode='register-prefix', prefix=p) for p in ('BGP/edge/deeper', 'BGP-beside', 'shared/inside')))
    check('H1: only a real collision is refused', 'inside' in str(helper('reg-bgp', mode='register-prefix', prefix='BGP/checkpoints/x/y').get('error')))
    # a push carries every earlier waiting commit (the newest only can be pushed)
    action('edit_device', device='ceos', add=['   ip route 10.9.9.0/24 10.0.0.2'])
    second = save(square, 'a second change')
    outgoing = helper('reg-bgp', mode='compare', operation_id=second['id']).get('outgoing') or []
    check('H6: compare answers every commit not yet uploaded, with operation id, subject and files', len(outgoing) == 2 and {o['operation_id'] for o in outgoing} == {job['id'], second['id']}
          and all(o['subject'] and o['files'] for o in outgoing), json.dumps(outgoing)[:300])
    older = helper('reg-bgp', mode='push', operation_id=job['id'])
    check('only the newest commit can be pushed: the older save is refused', older.get('status') == 'needs_attention' and 'moved since this save' in older.get('message', ''), str(older))
    switch(**{'remote_unreachable': True})
    check('H6: outgoing is null when the remote cannot be asked', helper('reg-bgp', mode='compare', operation_id=second['id']).get('outgoing') is None)
    check('...and a push fails with the remote sentence', 'remote branch is unavailable' in helper('reg-bgp', mode='push', operation_id=second['id']).get('message', ''))
    switch(**{'remote_unreachable': None, 'push_fail_once': True})
    failed = helper('reg-bgp', mode='push', operation_id=second['id'])
    check('Upload failed: the next push fails once ("saved on the VM, but push failed")', failed.get('status') == 'needs_attention' and 'push failed' in failed.get('message', ''), str(failed))
    done = helper('reg-bgp', mode='push', operation_id=second['id'])
    check('the next push carries both saves: synced_operations names them all', done.get('pushed') is True and {job['id'], second['id']} <= set(done.get('synced_operations') or []), str(done))
    again = helper('reg-bgp', mode='publish', operation_id=uuid.uuid4().hex, expected_head=helper('reg-bgp', mode='status')['head'], target='latest',
                   snapshot=helper('reg-bgp', mode='read-version', commit=helper('reg-bgp', mode='status')['head'], path='BGP/latest')['snapshot'])
    check('publish of an unchanged capture answers `unchanged`', again.get('status') == 'unchanged' and again.get('changed_files') == [], str(again)[:200])
    check('H7: with nothing waiting a registration can be retired', 'id' in helper('reg-bgp', mode='register-prefix', prefix='moved', retire=True))
    # every problem a status can answer (Can't save, DESIGN 3.6)
    for key, text in (('staged', 'staged changes'), ('edits', 'unsaved edits'), ('operation', 'existing Git operation'), ('diverged', 'diverged'), ('permission', 'cannot push')):
        switch(status_problem=key)
        answer = helper('reg-solo', mode='status')
        check(f'status can answer: {key}', answer.get('ready') is False and text in answer.get('problem', ''), str(answer))
    switch(status_problem=None, vm_unreachable=True)
    status, body = call('GET', f'/api/labs/{ids["solo-lab"]}/git')
    check('...and the manager sees a refused helper (repository_status not ready)', body.get('repository_status', {}).get('ready') is False)
    action('reset')
    # a diverged remote: a waiting save is refused, nothing waiting fast-forwards
    switch(**{'remote_ahead@Solo-Lab': True})
    check('remote_ahead: update with nothing waiting fast-forwards', helper('reg-solo', mode='update', expected_head=helper('reg-solo', mode='status')['head']).get('status') == 'updated')
    action('reset')


def routes_other_slices_build(labs):
    ids = lab_ids()
    lab = ids['square-fresh']
    probes = [('GET', f'/api/labs/{lab}/git/places', None), ('POST', f'/api/labs/{lab}/git/place', {'folder': 'square-fresh'}),
              ('POST', f'/api/labs/{lab}/git/state', {'folder': 'BGP/mine', 'name': 'mine'}), ('GET', f'/api/labs/{lab}/restore/states', None)]
    for method, path, body in probes:
        status, answer = call(method, path, body)
        if status in (404, 405):
            skip(f'{method} {path.replace(lab, "{lab}")}', 'route not built yet at this base commit')
        else:
            check(f'{method} {path.replace(lab, "{lab}")} answers', status == 200, f'{status} {str(answer)[:120]}')


def start(port, logs):
    global BASE
    BASE = f'http://127.0.0.1:{port}'
    data = tempfile.mkdtemp(prefix='clab-fixture-check-')
    log = open(os.path.join(data, 'fixture.log'), 'w+')
    process = subprocess.Popen([sys.executable, str(FIXTURE), '--port', str(port), '--data', os.path.join(data, 'data')], stdout=log, stderr=subprocess.STDOUT,
                               cwd=str(ROOT), env=dict(os.environ, CAPTURE_PROVIDER='disabled'))
    for _ in range(120):
        if process.poll() is not None:
            break
        try:
            if call('GET', '/api/state')[0] == 200:
                return process, data, log
        except (urllib.error.URLError, ConnectionError, OSError):
            pass
        time.sleep(0.5)
    log.seek(0)
    print(log.read()[-3000:])
    process.terminate()
    raise SystemExit('The fixture did not start.')


def free_port(preferred):
    for port in ([preferred] if preferred else []) + list(range(8191, 8200)):
        with socket.socket() as sock:
            if sock.connect_ex(('127.0.0.1', port)) != 0:
                return port
    raise SystemExit('No free port in 8191 to 8199.')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=0)
    parser.add_argument('--keep-logs', action='store_true')
    args = parser.parse_args()
    process, data, log = start(free_port(args.port), args.keep_logs)
    try:
        started = time.time()
        idle()
        labs = labs_and_repositories()
        states(labs)
        devices_and_loads(labs)
        saves()
        routes_other_slices_build(labs)
        print(f'\n{results["ok"]} ok, {results["fail"]} failed, {results["skip"]} skipped in {time.time() - started:.0f} s (fixture on {BASE})')
    finally:
        process.terminate()
        try:
            process.wait(10)
        except subprocess.TimeoutExpired:
            process.kill()
        if args.keep_logs or results['fail']:
            print('fixture log:', os.path.join(data, 'fixture.log'))
        else:
            shutil.rmtree(data, ignore_errors=True)
    return 1 if results['fail'] else 0


if __name__ == '__main__':
    sys.exit(main())
