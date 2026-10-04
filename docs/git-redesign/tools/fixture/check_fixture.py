#!/usr/bin/env python3
"""Self-check of the Git save and load fixture: starts it on a free port with a fresh data directory, asks the application's
own API (and the fixture's control) and asserts that every seeded scenario is really there, that the scripted VM Git helper answers
the shapes and orders of the real one (`app/host_git.py`), and that every route of the Git save and load redesign answers through it.

    clab-backup-ui/.venv/bin/python docs/git-redesign/tools/fixture/check_fixture.py [--port 8191] [--keep-logs] [--only places,saves]

Sections (each on a fresh fixture, because what they do cannot be undone): `seed` (labs, repositories, states, loads), `places` (the
folder chooser: places, places/check, place, New folder, an empty repository, a large one), `saves` (the save model: names, summary,
review, upload, rename, checkpoint, lab states, the states list), `causes` (what stops a save, as the chip's code), `helper` (the helper's
own rules: registrations, retire, connect). One line per check: `ok` or `FAIL` (exit status 1). There is no SKIP: every route exists.
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
sys.path[:0] = [str(ROOT / 'clab-backup-ui'), str(HERE)]
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
results = {'ok': 0, 'fail': 0}
BASE = ''
BUSY = ('queued', 'capturing', 'exporting', 'pushing')
START = 'This repository has no commits yet'


def line(kind, name, detail=''):
    results[kind] += 1
    print(f'{kind.upper() if kind != "ok" else "ok":4} {name}' + (f' :: {detail}' if detail else ''), flush=True)


def check(name, condition, detail=''):
    line('ok' if condition else 'fail', name, '' if condition else detail)
    return bool(condition)


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


def lab_state(name):
    return next(lab for lab in state()['labs'] if lab['name'] == name)


def idle(timeout=90):
    until = time.time() + timeout
    while time.time() < until:
        s = state()
        busy = [j for j in s['jobs'] if j['status'] in ('queued', 'running')]
        busy += [j for j in s['git_jobs'] if j.get('status') in BUSY]
        busy += [j for j in s.get('restore_jobs', []) if j.get('status') in ('queued', 'preflight', 'backing_up', 'applying', 'confirming', 'verifying')]
        if not busy:
            return True
        time.sleep(0.5)
    return False


def settle(job_id, tries=120):
    job = {}
    for _ in range(tries):
        time.sleep(0.5)
        job = call('GET', f'/api/git/jobs/{job_id}')[1]
        if job['status'] not in BUSY:
            break
    return job


def save(lab, note='', push=True, wait=True, **extra):
    """POST the save route (a name is optional) and wait for the job; `push` is the review request, nothing uploads by itself."""
    request_id = uuid.uuid4().hex
    status, job = call('POST', f'/api/labs/{lab}/git/save', dict(request_id=request_id, note=note, push=push, **extra))
    if status != 200:
        return {'status': 'refused', 'message': str(job), 'http': status}
    return settle(request_id) if wait else job


def lab_state_save(lab, folder, name, choice='', repository=''):
    request_id = uuid.uuid4().hex
    status, answer = call('POST', f'/api/labs/{lab}/git/state', dict(request_id=request_id, folder=folder, name=name, choice=choice, repository=repository))
    if status != 200 or 'question' in answer:
        return status, answer
    return status, settle(request_id)


def review(lab, job):
    return call('POST', f'/api/labs/{lab}/git/compare', {'job_id': job['id']})[1]


def upload(job, head, reviewed=True):
    status, answer = call('POST', f'/api/git/jobs/{job["id"]}/retry', dict(push=True, reviewed=reviewed, head=head))
    return status, (settle(answer['id']) if status == 200 else answer)


def check_place(lab, repository, folder, purpose='save', name=''):
    return call('POST', f'/api/labs/{lab}/git/places/check', dict(repository=repository, folder=folder, purpose=purpose, name=name))[1]


def place(lab, **body):
    status, answer = call('POST', f'/api/labs/{lab}/git/place', body)
    return status, answer


def preflight(lab, path=None, source=None, names=None):
    body = {'source': source or {'type': 'folder', 'path': path}}
    if names:
        body['node_names'] = names
    status, answer = call('POST', f'/api/labs/{lab}/restore/preflight', body)
    return answer if status == 200 else {'error': answer, 'status': status, 'targets': []}


def load(lab, path=None, names=(), minutes=2, wait=120, source=None):
    request_id = uuid.uuid4().hex
    status, job = call('POST', f'/api/labs/{lab}/restore', {'request_id': request_id, 'source': source or {'type': 'folder', 'path': path}, 'node_names': list(names),
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


def edit(device, *lines):
    action('edit_device', device=device, add=list(lines))


def answer_view(answer):
    return {k: answer.get(k) for k in ('folder', 'kind', 'exists', 'adjusted', 'mark')}


# --- seed: the labs, the repositories, the saved states, the loads --------------------------------------------------------

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
    check('every lab carries git_status: nothing asked yet (ready null), nothing waiting', all(l['git_status']['ready'] is None and l['git_status']['waiting'] == 0 for l in labs.values()
                                                                                              if l['name'] in ('restore-square', 'square-fresh', 'solo-lab')), str(labs['square-fresh'].get('git_status')))
    # The default place of the never-saved lab is the owner's standard install: the repository registered only at its top level.
    status, places = call('GET', f'/api/labs/{fresh["id"]}/git/places')
    default = (places or {}).get('default') or {}
    check('the default place of the never-saved lab: Archtop-Lab (top level only), in a folder named after the lab, no question',
          status == 200 and default.get('repository') == 'reg-archtop' and default.get('folder') == 'square-fresh' and default.get('ask') is False
          and answer_view(default['answer']) == dict(folder='square-fresh', kind='free', exists=False, adjusted='', mark=''), json.dumps(default)[:300])
    check('...and the repositories it offers are the five checkouts of the VM (Archtop-Lab first by name)',
          [r['name'] for r in places['repositories']] == ['Archtop-Lab', 'Big-Repo', 'Course-Labs', 'Nested-Labs', 'Solo-Lab'] and not any(r['current'] for r in places['repositories']))
    return labs


def states(labs):
    history = helper('reg-bgp', mode='history')
    versions = {v['path']: v for v in history.get('versions', [])}
    check('history carries head, commits, versions and summaries_truncated', {'head', 'commits', 'versions', 'summaries_truncated'} == set(history) and history['summaries_truncated'] is False, str(list(history)))
    shape = {'lab_id', 'lab_name', 'kind', 'state', 'captured_at', 'topology_digest', 'devices'}
    readable = [v['summary'] for v in versions.values() if v['summary'] is not None]
    check('every readable summary has exactly the helper\'s keys, and every device node, short_name, platform and restore (a boolean)',
          readable and all(set(s) == shape and all(set(d) == {'node', 'short_name', 'platform', 'restore'} and isinstance(d['restore'], bool) for d in s['devices']) for s in readable))
    check('a missing field is null, never an empty string: an ordinary capture has kind null, a design export `network-design`',
          versions['BGP/final/latest']['summary']['kind'] is None and versions['BGP/checkpoints/plan-sept']['summary']['kind'] == 'network-design')
    for path, name in (('BGP/start/latest', 'Start'), ('BGP/broken/latest', 'Broken'), ('BGP/final/latest', 'Final')):
        mark = (versions.get(path) or {}).get('summary', {}) or {}
        check(f'course state {path} is a lab state in `latest` layout carrying `state: {name}`, not connected', path in versions and not versions[path]['connected'] and mark.get('state') == name, str(mark.get('state')))
    flat = versions.get('Final')
    check('a state stored directly in a folder (Final/manifest.json, flat layout; no `state` mark: `state` is \'\')', bool(flat) and flat['summary'] and len(flat['summary']['devices']) == 4
          and flat['summary']['state'] == '')
    check('the lab\'s own saves carry state \'\' (a lab state is only what "Save as a lab state" wrote)', versions['BGP/latest']['summary']['state'] == '' and versions['BGP/baseline']['summary']['state'] == '')
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
    check('the lab\'s own saves are listed first, then the rest by path (the helper\'s sort)', [v['connected'] for v in history['versions']] == sorted((v['connected'] for v in history['versions']), reverse=True)
          and [v['path'] for v in history['versions'] if not v['connected']] == sorted(v['path'] for v in history['versions'] if not v['connected']))
    archtop = {v['path']: v for v in helper('reg-archtop', mode='history').get('versions', [])}
    check('Archtop-Lab holds the course states under Course/ with the same marks, Start view only',
          {p: (archtop[p]['summary'] or {}).get('state') for p in archtop} == {'Course/start/latest': 'Start', 'Course/broken/latest': 'Broken', 'Course/final/latest': 'Final'}
          and not any(d['restore'] for d in archtop['Course/start/latest']['summary']['devices']))
    s = state()
    jobs = [j for j in s['git_jobs'] if j.get('lab_id') == labs['restore-square']['id']]
    latest = [j for j in jobs if j['target'] == 'latest']
    check('a latest save that is uploaded, three in history, and a history of several commits',
          len(latest) == 3 and latest[-1]['status'] == 'synced' and latest[-1]['pushed'] and len(history['commits']) >= 6, f'{len(latest)} latest, {len(history["commits"])} commits')
    check('two checkpoints and a starting point', sorted(j['target'] for j in jobs if j['target'] != 'latest') == ['baseline', 'checkpoint', 'checkpoint'])
    big = helper('reg-big', mode='browse')
    big_versions = [v['path'] for v in helper('reg-big', mode='history').get('versions', [])]
    check('a large repository: 5000 files, about 300 folders, the listing stops at 4000 files and every folder is in `dirs`', len(big.get('files', [])) == 4000 and big.get('truncated') is True
          and 290 <= len(big.get('dirs', [])) <= 330 and big.get('dirs_truncated') is False, f"{len(big.get('files', []))} files, {len(big.get('dirs', []))} dirs")
    listed = {f['path'] for f in big.get('files', [])}
    check('...with saved states beyond the cap (found by history, not by the tree)', len(big_versions) == 3 and not any(p + '/manifest.json' in listed for p in big_versions), str(big_versions))
    nested = helper('reg-bgp', mode='browse')
    names = [f['path'] for f in nested['files']]
    check('browse carries every directory and dirs_truncated (H5)', 'BGP/start/latest' in nested.get('dirs', []) and nested.get('dirs_truncated') is False)
    check('files and dirs come in Git\'s tree order, not Python\'s: `notes-old` before `notes` (`-` sorts before the `/` of a directory)',
          nested['dirs'].index('notes-old') < nested['dirs'].index('notes') and names.index('notes-old/week0.md') < names.index('notes/week1.md'), str(nested['dirs'][:12]))
    check('browse answers saved times for latest, baseline and checkpoints and the folders registered in the checkout', set(nested['saved']) == {'latest', 'baseline', 'checkpoints'}
          and {f['prefix'] for f in nested['folders']} == {'BGP', 'BGP/edge', 'shared', 'old-lab-folder'})


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
    check('...and says the topology is the same (source.topology.differs false, 4 of 4 devices match)', pre['source']['topology'] == {'differs': False, 'saved_devices': 4, 'matching_devices': 4}, str(pre['source']['topology']))
    pre = preflight(square, 'BGP/start/latest')
    check('preflight of a view-only state: every device is refused with the reason', pre['eligible_count'] == 0 and all('no restore data' in t['reason'] for t in pre['targets']))
    pre = preflight(square, 'BGP/junos-only/latest')
    check('preflight of the 2-of-4 state lists two devices', sorted(short(t['name']) for t in pre['targets']) == ['cjunosevolved', 'vjunos-switch'])
    pre = preflight(square, 'BGP/other-topology/latest')
    check('preflight of the other-topology state: 3 of its 4 devices match the lab, and source.topology says it differs', sum(1 for t in pre['targets'] if t['eligible']) == 3
          and [t['reason'] for t in pre['targets'] if not t['eligible']] == ['No running node in this lab matches this saved node.']
          and pre['source']['topology'] == {'differs': True, 'saved_devices': 4, 'matching_devices': 3}, str(pre['source'].get('topology')))
    check('a preflight through a registration the lab does not save to: the repository is named in the source and the lab states are read there',
          preflight(ids['square-fresh'], source={'type': 'folder', 'path': 'Course/final/latest', 'repository': 'reg-archtop'})['source']['repository'] == 'reg-archtop')

    rs = {r['path']: r for r in call('GET', f'/api/labs/{square}/restore/states')[1]['states']}
    check('restore/states, before anything is saved: Start is view only (no restore data), Broken and Final load on 4 of 4, the subset 2 of 2, the other topology 3 of 4, the design export is view only',
          rs['BGP/start/latest']['view_only'] is True and rs['BGP/start/latest']['view_only_reason'] == 'no_restore_data' and rs['BGP/start/latest']['saved_devices'] == 4 and rs['BGP/start/latest']['loadable_devices'] == 0
          and (rs['BGP/broken/latest']['saved_devices'], rs['BGP/broken/latest']['loadable_devices']) == (4, 4) and (rs['BGP/junos-only/latest']['saved_devices'], rs['BGP/junos-only/latest']['loadable_devices']) == (2, 2)
          and (rs['BGP/other-topology/latest']['saved_devices'], rs['BGP/other-topology/latest']['loadable_devices']) == (4, 3) and rs['BGP/checkpoints/plan-sept']['view_only_reason'] == 'design', str({p: (r['saved_devices'], r['loadable_devices'], r['view_only']) for p, r in rs.items()}))
    status, answer = call('POST', f'/api/labs/{square}/restore', {'request_id': uuid.uuid4().hex, 'source': {'type': 'folder', 'path': 'BGP/final/latest'}, 'node_names': [t['name'] for t in pre['targets']]})
    check('a load needs the acknowledgement that the running configuration is replaced (400 without it)', status == 400 and 'Acknowledge' in json.dumps(answer), f'{status} {answer}')

    def run(preset, path='BGP/final/latest', seconds=None):
        action('reset')
        switch(load_preset=preset, **({'load_seconds': seconds} if seconds else {}))
        names = [t['name'] for t in preflight(square, path)['targets'] if t['eligible']]
        return load(square, path, names)
    job = run('all-ok')
    check('load all-ok: all devices loaded and verified, through the submit with acknowledge', job['status'] == 'succeeded' and set(outcomes(job).values()) == {'verified'} and len(job['targets']) == 4, json.dumps(outcomes(job)))
    check('...the job names its source: the folder, the repository (own: empty), the topology comparison and the capture id (a state\'s own manifest names none)',
          job['source']['path'] == '/BGP/final/latest' and job['source']['repository'] == '' and job['source']['topology']['differs'] is False and job['source']['capture_id'] == '', json.dumps(job['source']))
    # undo: the safety backup the load took first is a `backup` source
    pre_id = job.get('pre_backup_job_id')
    undo_pre = preflight(square, source={'type': 'backup', 'backup_job_id': pre_id})
    check('undo: the safety backup of the load is a `backup` source and its preflight offers the devices the load changed', bool(pre_id) and undo_pre['eligible_count'] >= 2
          and any(short(t['name']) == 'ceos' and not t['matches_saved'] for t in undo_pre['targets']), json.dumps(undo_pre)[:400])
    undone = load(square, names=[t['name'] for t in undo_pre['targets'] if t['eligible']], source={'type': 'backup', 'backup_job_id': pre_id})
    check('undo: loading the safety backup succeeds and the devices run what they ran before the load',
          undone['status'] == 'succeeded' and set(outcomes(undone).values()) == {'verified'}
          and any(short(t['name']) == 'ceos' and not t['matches_saved'] for t in preflight(square, 'BGP/final/latest')['targets']), json.dumps(outcomes(undone)))
    job = run('one-failed')
    o = outcomes(job)
    check('load one-failed: one device not loaded (failed), three loaded', o.get('xrv9k') == 'failed' and list(o.values()).count('verified') == 3, str(o))
    job = run('one-rolled-back')
    o = outcomes(job)
    check('load one-rolled-back: one device rolled back (read back as the previous configuration)', o.get('xrv9k') == 'rolled_back' and list(o.values()).count('verified') == 3, str(o))
    job = run('one-uncertain')
    o = outcomes(job)
    check('load one-uncertain: one device uncertain', o.get('xrv9k') == 'uncertain' and list(o.values()).count('verified') == 3, str(o))
    for preset, reason, word in (('one-unreachable', 'SSH probe failed', 'unreachable'), ('one-blocked', 'waiting for confirmation', 'blocked'), ('one-editing', 'uncommitted', 'editing'),
                                 ('one-bad-login', 'login', 'bad login')):
        action('reset')
        switch(load_preset=preset)
        row = next(t for t in preflight(square, 'BGP/final/latest')['targets'] if short(t['name']) == 'xrv9k')
        check(f'preflight with {preset}: the device cannot be ticked and says why ({word})', not row['eligible'] and reason in row['reason'], str(row))
    job = run('slow', seconds=1.5)
    times = sorted(job['settled'].values())
    check('load slow: devices settle one after another (progress can be watched)', job['status'] == 'succeeded' and len(times) == 4 and times[-1] - times[0] >= 3, str(times))
    action('reset')
    idle()


# --- places: the folder chooser (PROMPT 6.2, DESIGN 2.5 to 2.8) -------------------------------------------------------------------

def places():
    ids = lab_ids()
    fresh, sq, edge, sa, sb, solo = (ids[n] for n in ('square-fresh', 'restore-square', 'edge-lab', 'shared-a', 'shared-b', 'solo-lab'))
    # --- the first placement into the repository registered only at its top level: no question, no refusal
    status, answer = place(fresh, repository='reg-archtop', folder='square-fresh', acknowledge=True)
    binding = (answer or {}).get('binding') or {}
    check('first placement into Archtop-Lab (registered only at its top level): saved at once, no question, the folder is square-fresh',
          status == 200 and answer.get('saved') is True and 'question' not in answer and binding.get('repository', {}).get('prefix') == 'square-fresh' and answer.get('job') is None, str(answer)[:300])
    regs = action('helper', repository='reg-archtop', request={'mode': 'browse'})['folders']
    check('...the top-level registration stays, the lab\'s folder is registered beside it (nothing retired, nesting never refused)', sorted(f['prefix'] for f in regs) == ['', 'square-fresh'], str(regs))
    check('...git_status stays unasked after a placement (DESIGN 3.8 N1 lists "a place" among the calls that record it; place makes none: reported to the lead), and the settings read records it',
          lab_state('square-fresh')['git_status']['ready'] is None and call('GET', f'/api/labs/{fresh}/git')[0] == 200
          and lab_state('square-fresh')['git_status']['ready'] is True and lab_state('square-fresh')['git_status']['waiting'] == 0)
    check('...asking again with the same folder changes nothing (saved, moved false)', place(fresh, repository='reg-archtop', folder='square-fresh', acknowledge=True)[1].get('moved') is False)

    # --- PROMPT 6.2, row by row, through places/check (the answer) and place (the applying)
    def row(name, lab, repository, folder, kind, folder_out=None, adjusted=None, exists=None, mark=None, **more):
        got = check_place(lab, repository, folder)
        good = got.get('kind') == kind and (folder_out is None or got.get('folder') == folder_out) and (adjusted is None or got.get('adjusted') == adjusted) \
            and (exists is None or got.get('exists') is exists) and (mark is None or got.get('mark') == mark) and all(got.get(k) == v for k, v in more.items())
        check(f'6.2 {name}: places/check answers {kind}' + (f' with folder {folder_out!r}' if folder_out is not None else ''), good, json.dumps(answer_view(got)) + ' ' + json.dumps({k: got.get(k) for k in ('lab', 'beside', 'label', 'collision')}))
        return got
    new = check_place(sb, 'reg-bgp', 'brand-new/deeper')
    check('6.2 a folder that does not exist: free, not "existing" (it is only planned until the first save)', new['kind'] == 'free' and new['folder'] == 'brand-new/deeper' and new['exists'] is False)
    status, answer = place(sb, repository='reg-bgp', folder='brand-new/deeper', acknowledge=True)
    check('...place saves it with no question; the folder is created by the first save', status == 200 and answer['binding']['repository']['prefix'] == 'brand-new/deeper' and 'question' not in answer, str(answer)[:200])
    row('an existing folder with ordinary files (BGP/exercises)', sa, 'reg-bgp', 'BGP/exercises', 'free', 'BGP/exercises', '', True)
    row('an existing ordinary folder of Archtop-Lab (notes)', fresh, 'reg-archtop', 'notes', 'free', 'notes', '', True)
    row('the repository\'s top level', sa, 'reg-bgp', '', 'free', '', '', True)
    row('inside another lab\'s folder (BGP/edge/inner, a lab saves at BGP/edge)', sa, 'reg-bgp', 'BGP/edge/inner', 'free', 'BGP/edge/inner', '', False)
    row('beside another lab\'s folder (BGP-beside)', sa, 'reg-bgp', 'BGP-beside', 'free', 'BGP-beside', '', False)
    row('above every lab folder (the top level of Nested-Labs)', sa, 'reg-bgp', '', 'free', '')
    got = row('the very folder another connected lab saves to (shared-a\'s)', sb, 'reg-bgp', 'shared', 'lab', 'shared', '', True, 'shared-a saves here', beside='shared/shared-b', collision=False)
    check('...the other lab is named, and the suggestion is <folder>/<this lab>', got['lab']['name'] == 'shared-a')
    row('a folder another lab saves to, one lab deeper (BGP/edge)', sb, 'reg-bgp', 'BGP/edge', 'lab', 'BGP/edge', '', True, 'edge-lab saves here', beside='BGP/edge/shared-b')
    row('a folder that holds a saved state (Start, layout latest)', sb, 'reg-bgp', 'BGP/start', 'state', 'BGP/start', '', True, 'Lab state: Start', layout='latest', label='Start', beside='BGP/start/shared-b')
    row('a folder that holds a saved state stored flat (Final)', sb, 'reg-bgp', 'Final', 'state', 'Final', '', True, 'Lab state: Final', layout='flat', beside='Final/shared-b')
    row('a folder that holds a course state in Archtop-Lab (Course/final)', fresh, 'reg-archtop', 'Course/final', 'state', 'Course/final', '', True, 'Lab state: Final')
    row('part of a saved state (BGP/latest of another lab\'s folder): the lab folder above is used and the answer says so', sb, 'reg-bgp', 'BGP/latest', 'lab', 'BGP', 'above-state', True, '')
    row('part of this lab\'s own saved state (BGP/checkpoints/ospf-up): the lab folder above, own', sq, 'reg-bgp', 'BGP/checkpoints/ospf-up', 'own', 'BGP', 'above-state', True)
    row('part of a saved state of a folder nobody saves to (Course/latest): the folder above, free', fresh, 'reg-archtop', 'Course/latest', 'free', 'Course', 'above-state', True)
    row('part of a course state (Course/start/latest): the state\'s folder above, its question stays', fresh, 'reg-archtop', 'Course/start/latest', 'state', 'Course/start', 'above-state')
    row('a name with characters that are not safe in a path (My Lab: A/B): corrected as typed', fresh, 'reg-archtop', 'My Lab: A/B', 'free', 'My-Lab-A/B', 'corrected', False)
    row('this lab\'s own folder', sq, 'reg-bgp', 'BGP', 'own', 'BGP', '', True, 'This lab saves here')
    row('a folder registered on the VM that no lab uses (old-lab-folder): invisible, free', sb, 'reg-bgp', 'old-lab-folder', 'free', 'old-lab-folder', '', False)
    check('...and it never shows as another lab\'s folder in the tree', 'old-lab-folder' not in {f['path'] for f in call('GET', f'/api/labs/{sb}/git/places?repository=reg-bgp')[1]['tree']['folders']})
    status, answer = call('POST', f'/api/labs/{sb}/git/places/check', dict(repository='reg-bgp', folder='/'.join(['x' * 100] * 6)))
    check('the one validation left: a path over 500 characters is a 400 with the length sentence', status == 400 and '500' in json.dumps(answer), f'{status} {answer}')
    row('a very long single name is cut to what the helper takes (181 characters), never refused', sb, 'reg-bgp', 'y' * 400, 'free', 'y' * 181, 'corrected', False)

    # --- the questions, through place (DESIGN 2.6)
    status, answer = place(sa, repository='reg-bgp', folder='BGP', acknowledge=True)
    check('question 1 (place): another lab saves in the folder: a question with the lab and the suggestion, not an error', status == 200 and answer['question']['kind'] == 'lab'
          and answer['question']['lab']['name'] == 'restore-square' and answer['question']['beside'] == 'BGP/shared-a', str(answer)[:300])
    status, answer = place(sa, repository='reg-bgp', folder='BGP', acknowledge=True, choice='beside')
    check('...Save in <folder>/<this lab> (beside): placed in BGP/shared-a, restore-square untouched', status == 200 and answer['binding']['repository']['prefix'] == 'BGP/shared-a'
          and lab_state('restore-square')['git_binding']['repository']['prefix'] == 'BGP', str(answer)[:300])
    status, answer = place(sb, repository='reg-bgp', folder='BGP/shared-a', acknowledge=True)
    check('question 1 with the identical folder: both buttons (Save in <folder>/<this lab>, Use this folder anyway)', status == 200 and answer['question']['kind'] == 'lab' and answer['question']['collision'] is False
          and answer['question']['lab']['name'] == 'shared-a' and answer['question']['beside'] == 'BGP/shared-a/shared-b', str(answer)[:300])
    status, answer = place(sb, repository='reg-bgp', folder='BGP/shared-a', acknowledge=True, choice='take')
    check('...Use this folder anyway (take): shared-b saves there now, shared-a is disconnected from it and has no save location (its saves stay as versions)', status == 200
          and answer['binding']['repository']['prefix'] == 'BGP/shared-a' and not lab_state('shared-a').get('git_binding') and lab_state('shared-b')['git_binding']['repository']['prefix'] == 'BGP/shared-a', str(answer)[:300])
    check('own-before: a folder that holds this lab\'s own earlier save (shared-a\'s shared/latest) is no question: the lab continues there', check_place(sa, 'reg-bgp', 'shared')['kind'] == 'own-before'
          and check_place(sb, 'reg-bgp', 'shared')['kind'] == 'state')
    status, answer = place(sa, repository='reg-bgp', folder='shared', acknowledge=True)
    check('...and place puts it back in shared at once', status == 200 and answer.get('saved') is True and answer['binding']['repository']['prefix'] == 'shared', str(answer)[:300])
    status, answer = place(solo, repository='reg-bgp', folder='BGP/final', acknowledge=True)
    check('question 2 (place): a folder that holds the state "Final": a question with Replace it and the suggestion beside it', status == 200 and answer['question']['kind'] == 'state'
          and answer['question']['label'] == 'Final' and answer['question']['beside'] == 'BGP/final/solo-lab', str(answer)[:300])
    status, answer = place(solo, repository='reg-bgp', folder='BGP/final', acknowledge=True, choice='beside')
    check('...Save beside it: BGP/final/solo-lab', answer['binding']['repository']['prefix'] == 'BGP/final/solo-lab', str(answer)[:300])
    status, answer = place(solo, repository='reg-bgp', folder='BGP/start', acknowledge=True, choice='take')
    check('...Replace it: the lab takes BGP/start (its next save replaces latest there)', answer['binding']['repository']['prefix'] == 'BGP/start', str(answer)[:300])
    status, answer = place(solo, repository='reg-solo', folder='', acknowledge=True)
    check('moving back to Solo-Lab\'s top level: its own registration is reused (nothing new on the VM)', answer['binding']['binding_id'] == 'reg-solo', str(answer)[:200])
    # a folder registered on the VM that no lab uses is reused when chosen
    status, answer = place(sb, repository='reg-bgp', folder='old-lab-folder', acknowledge=True)
    check('a folder registered on the VM that no lab uses is reused when chosen (reg-unused)', answer['binding']['binding_id'] == 'reg-unused', str(answer)[:200])
    status, answer = place(sa, repository='reg-bgp', folder='x' * 60 + '/' + 'My Lab: A/B', acknowledge=True)
    check('unsafe characters through place: corrected, never refused', status == 200 and answer['binding']['repository']['prefix'].endswith('/My-Lab-A/B'), str(answer)[:200])

    # --- a save that waits: Question 3, and Move and keep it on the VM only
    edit('ceos', '   ip route 0.0.0.0/0 10.0.0.1')
    action('prefer_repository', repository='Nested-Labs', lab='restore-square')
    waiting = save(sq, 'before the move')
    check('a save of restore-square waits for upload (review_pending, committed on the VM)', waiting['status'] == 'review_pending' and waiting['commit'], str(waiting)[:200])
    status, answer = place(sq, repository='reg-bgp', folder='BGP-moved', acknowledge=True)
    q = (answer or {}).get('question') or {}
    check('question 3 (place): a folder change while a save waits is one question with the waiting save named, never a refusal', status == 200 and q.get('kind') == 'pending' and q.get('count') == 1
          and q.get('names') == ['before the move'] and q.get('folder') == 'BGP-moved', str(answer)[:300])
    status, answer = place(sq, repository='reg-bgp', folder='BGP-moved', acknowledge=True, pending='keep', move_files=True)
    moved = (answer or {}).get('job') or {}
    check('Move and keep that save on the VM only: the lab changes folder and the saved files are brought along by a move job', status == 200 and answer.get('moved') is True and moved.get('target') == 'move', str(answer)[:300])
    job = settle(moved['id'])
    check('...the move never uploads by itself: it ends committed, not uploaded, and waits for Upload like a save', job['status'] == 'committed' and job['pushed'] is False, f"{job['status']} {job.get('pushed')}")
    old = call('GET', f'/api/git/jobs/{waiting["id"]}')[1]
    check('...and the waiting save is still there, waiting, with its own binding (still reviewable and uploadable)', old['status'] == 'review_pending' and old['pushed'] is False)
    r = review(sq, old)
    check('...the review of the waiting save names the move as part of the same upload (also_sends)', any(row.get('target') == 'move' for row in r['also_sends']), json.dumps(r['also_sends'])[:300])
    code, up = upload(old, r['head'])
    check('...Upload through the waiting save: the save at HEAD (the move) is the one pushed and both end uploaded', code == 200 and up['id'] == moved['id'] and up['status'] == 'synced'
          and call('GET', f'/api/git/jobs/{waiting["id"]}')[1]['pushed'] is True, f'{code} {str(up)[:200]}')

    # --- New folder, always possible, in every state of the repository
    def new_folder(lab, repository, parent, name):
        status, answer = call('POST', f'/api/git/repositories/{repository}/folders/new', dict(lab_id=lab, parent=parent, name=name))
        return status, answer
    status, answer = new_folder(fresh, 'reg-archtop', '', 'Week 2')
    check('New folder at the top level: planned, corrected as typed (Week-2), listed before any save',
          status == 200 and answer['folder'] == 'Week-2' and answer['existed'] is False and answer['adjusted'] == 'corrected' and answer['answer']['kind'] == 'free' and answer['answer']['exists'] is False, str(answer)[:300])
    check('...and the tree lists it as planned (not "in the repository")', 'Week-2' in {f['path'] for f in call('GET', f'/api/labs/{fresh}/git/places?repository=reg-archtop')[1]['tree']['folders']})
    status, answer = new_folder(fresh, 'reg-archtop', 'notes', 'drafts')
    check('New folder inside an ordinary folder (notes/drafts)', answer['folder'] == 'notes/drafts' and answer['existed'] is False and answer['adjusted'] == '')
    status, answer = new_folder(sa, 'reg-bgp', 'BGP/edge', 'inner2')
    check('New folder inside another lab\'s folder (BGP/edge/inner2)', status == 200 and answer['folder'] == 'BGP/edge/inner2' and answer['answer']['kind'] == 'free', str(answer)[:300])
    status, answer = new_folder(fresh, 'reg-archtop', 'a/b', 'c/d/e')
    check('New folder nested (a/b + c/d/e)', answer['folder'] == 'a/b/c/d/e' and answer['existed'] is False)
    status, answer = new_folder(fresh, 'reg-archtop', 'Course/start/latest', 'extra')
    check('New folder inside a saved state (the lab states\'s latest): created in the folder above and the answer says so (adjusted above-state)', status == 200 and answer['folder'] == 'Course/start/extra'
          and answer['adjusted'] == 'above-state', str(answer)[:300])
    status, answer = new_folder(sb, 'reg-bgp', 'BGP/checkpoints/ospf-up', 'x')
    check('New folder inside another lab\'s saved checkpoint (BGP/checkpoints/ospf-up): the lab folder above, BGP/x', answer['folder'] == 'BGP/x' and answer['adjusted'] == 'above-state')
    status, answer = new_folder(fresh, 'reg-archtop', '', 'notes')
    check('New folder with a name that exists: that folder is selected, never refused (existed true)', status == 200 and answer['folder'] == 'notes' and answer['existed'] is True)
    status, answer = new_folder('', 'reg-bgp', 'BGP', 'zzz')
    check('New folder with no lab (the repository browser): works', status == 200 and answer['folder'] == 'BGP/zzz')
    status, answer = new_folder(fresh, 'reg-archtop', '/'.join(['x' * 100] * 6), 'z')
    check('New folder over 500 characters: the length sentence, a 400', status == 400, f'{status} {answer}')

    # --- a large repository: every folder through `dirs`
    status, tree = call('GET', f'/api/labs/{fresh}/git/places?repository=reg-big')
    paths = {f['path'] for f in tree['tree']['folders']}
    listed_files = {f['path'] for f in tree['tree']['files']}
    check('the large repository: the file list stops at 4000 (truncated) and every folder is still offered (dirs, not files)',
          tree['tree']['truncated'] is True and len(listed_files) == 4000 and 'docs/week-22/topic-269' in paths and not any(p.startswith('docs/week-22/topic-269/') for p in listed_files), f"{tree['tree']['truncated']} {len(paths)}")
    check('...and a folder only in the cut-off part answers as an ordinary folder', check_place(fresh, 'reg-big', 'docs/week-22/topic-269')['kind'] == 'free')
    status, answer = place(fresh, repository='reg-big', folder='docs/week-22/topic-269', acknowledge=True)
    check('...and a lab can be placed in it', status == 200 and answer['binding']['repository']['prefix'] == 'docs/week-22/topic-269', str(answer)[:200])

    # --- an empty repository, by its address
    status, answer = place(solo, url='https://github.com/ArchRuger/New-Empty.git', folder='solo-lab', acknowledge=True)
    check('an empty repository by address: the question is {kind: empty} with the repository\'s name, nothing is refused', status == 200 and answer['question']['kind'] == 'empty' and answer['question']['name'] == 'New-Empty', str(answer)[:300])
    check('...the question names no registration, prefix or overlap (PROMPT 6.3)', not any(w in json.dumps(answer).lower() for w in ('registration', 'prefix', 'overlap')))
    status, answer = place(solo, url='https://github.com/ArchRuger/New-Empty.git', folder='solo-lab', acknowledge=True, initialize=True)
    check('...Start the repository (initialize): the repository is started with its README and the lab is placed in its folder', status == 200 and answer.get('saved') is True
          and answer['binding']['repository']['prefix'] == 'solo-lab' and answer['binding']['repository']['path'].endswith('/New-Empty'), str(answer)[:300])
    check('...the README commit is on the remote with the fixed message', helper('', mode='connect', url='https://github.com/ArchRuger/New-Empty.git', prefix='')['prefix'] == ''
          and helper(next(r['id'] for r in call('GET', '/api/git/repositories')[1]['repositories'] if r['path'].endswith('/New-Empty') and r['prefix'] == ''), mode='history')['head'])
    status, answer = place(edge, url='https://github.com/ArchRuger/Late-README.git', folder='edge-lab', acknowledge=True)
    check('an empty repository that is empty at first (Late-README) asks the same question', answer['question']['kind'] == 'empty')
    action('remote_readme', url='https://github.com/ArchRuger/Late-README.git')
    status, answer = place(edge, url='https://github.com/ArchRuger/Late-README.git', folder='edge-lab', acknowledge=True)
    check('...once someone added a README on GitHub, the next try finishes the clone (no initialize) and places the lab', status == 200 and answer.get('saved') is True
          and answer['binding']['repository']['path'].endswith('/Late-README'), str(answer)[:300])
    status, answer = place(edge, url='https://github.com/ArchRuger/Spare-Lab.git', folder='edge-lab')
    check('a pasted address needs the exposure acknowledgement (400), as connect-by-URL always did', status == 400 and 'Acknowledge' in json.dumps(answer), f'{status} {answer}')
    status, answer = place(edge, url='https://github.com/ArchRuger/forbidden-one.git', folder='x', acknowledge=True)
    check('an address the VM account may not push to is refused with the helper\'s sentence (a 409, the one real refusal)', status == 409 and 'cannot push' in json.dumps(answer), f'{status} {answer}')
    status, answer = place(edge, url='https://github.com/ArchRuger/missing-one.git', folder='x', acknowledge=True)
    check('an address that cannot be cloned is refused with the helper\'s sentence', status == 409 and 'Cloning failed' in json.dumps(answer), f'{status} {answer}')
    switch(initialize_fails=True)
    status, answer = place(solo, url='https://github.com/ArchRuger/Spare-Lab.git', folder='solo-lab', acknowledge=True)
    check('a repository that is reachable and not empty connects (Spare-Lab), whatever initialize_fails says', status == 200 and answer.get('saved') is True)
    switch(initialize_fails=None)
    status, answer = call('GET', f'/api/labs/{fresh}/git/places?repository=reg-nope')
    check('a repository the VM does not know is a 404 with its own sentence', status == 404, f'{status} {answer}')


# --- saves: names, summary, review, upload, rename, checkpoint, lab states -------------------------------------------------------

def saves():
    ids = lab_ids()
    sq, fresh, edge, solo, shared_b = ids['restore-square'], ids['square-fresh'], ids['edge-lab'], ids['solo-lab'], ids['shared-b']
    switch(capture_seconds=1)
    idle()
    job = save(sq)
    check('Save with nothing changed since an uploaded save is `unchanged`', job['status'] == 'unchanged', f"{job['status']}: {job['message']}")
    # --- the first save of a never-saved lab: the owner's exact case
    place(fresh, repository='reg-archtop', folder='square-fresh', acknowledge=True)
    first = save(fresh)
    check('a save with no label is named by the manager from what changed: "First save" (note_auto), review_pending (never uploaded by itself)',
          first['status'] == 'review_pending' and first['note'] == 'First save' and first['note_auto'] is True and first['pushed'] is False, f"{first['status']} {first['note']} {first.get('note_auto')}")
    check('...its summary: counts and labels only (4 devices, topology and map, first)', first['summary']['devices'] == ['ceos', 'cjunosevolved', 'vjunos-switch', 'xrv9k'] and first['summary']['first'] is True
          and first['summary']['topology'] is True and first['summary']['map'] is True and first['summary']['added'] > 0 and first['summary']['removed'] == 0, json.dumps(first.get('summary')))
    check('...the public fields: captured, capture_kept, capture_whole (the save read the devices itself and kept a whole capture); the private binding never leaves', first['captured'] is True and first['capture_kept'] is True
          and first['capture_whole'] is True and 'binding' not in first and 'binding' not in json.dumps(state()['git_jobs']), str({k: first.get(k) for k in ('captured', 'capture_kept', 'capture_whole')}))
    r = review(fresh, first)
    check('the review: files with the real text, the HEAD it shows, the save to upload and nothing else to send', r['head'] == first['commit'] and r['upload_job'] == first['id']
          and r['also_sends'] == [] and r['also_sends_count'] == 0 and {f['name'] for f in r['files']} >= {'ceos.cfg', 'manifest.json', 'square-fresh.clab.yml'}, json.dumps({k: r[k] for k in r if k != 'files'})[:300])
    code, answer = upload(first, '0' * 40)
    check('the upload is bound to the HEAD the review showed: another HEAD is refused with the sentence that sends the person back to the review', code == 409 and 'Another save was made' in json.dumps(answer), f'{code} {answer}')
    code, answer = upload(first, r['head'], reviewed=False)
    check('...and without a review (reviewed false, none recorded) there is no upload at all', code == 409 and 'Review the changes' in json.dumps(answer), f'{code} {answer}')
    code, up = upload(first, r['head'])
    chip = lab_state('square-fresh')['git_status']
    check('Upload with head: uploaded (synced); git_status says ready and nothing waits', code == 200 and up['status'] == 'synced' and up['pushed'] is True and chip['ready'] is True and chip['waiting'] == 0, f'{code} {str(up)[:200]} {chip}')
    check('...the lab\'s own save is a normal save in its own folder beside the top-level registration (square-fresh/latest), the course states untouched',
          {v['path'] for v in helper('reg-archtop', mode='history')['versions']} >= {'square-fresh/latest', 'Course/start/latest', 'Course/broken/latest', 'Course/final/latest'})

    # --- two labs of one checkout: a second lab's save while the first waits, and one upload carrying both
    edit('ceos', '   ip route 0.0.0.0/0 10.0.0.1')
    a = save(sq)
    check('a save named from what changed: "ceos changed", with the one-line summary (ceos, 1 added)', a['status'] == 'review_pending' and a['note'] == 'ceos changed' and a['note_auto'] is True
          and a['summary']['devices'] == ['ceos'] and a['summary']['added'] == 1 and a['summary']['first'] is False and a['summary']['topology'] is False, json.dumps(a.get('summary')))
    edit('clab-edge-lab-r1', '   ip route 0.0.0.0/0 10.0.0.1')
    b = save(edge, 'edge note')
    check('a second lab\'s save while the first waits is not refused (the sibling refusal is gone); a name typed is kept as typed', b['status'] == 'review_pending' and b['note'] == 'edge note' and b['note_auto'] is False, f"{b['status']} {b.get('message')}")
    ra, rb = review(sq, a), review(edge, b)
    check('the review of the first names the second as part of the same upload (also_sends: job_id, lab, name, kind, target), count 1, one from another lab',
          ra['head'] == rb['head'] == b['commit'] and ra['upload_job'] == b['id'] and ra['also_sends'] == [dict(job_id=b['id'], lab='edge-lab', name='edge note', kind='save', target='latest')]
          and ra['also_sends_count'] == 1 and ra['also_sends_other_labs'] == 1, json.dumps({k: ra[k] for k in ra if k != 'files'})[:500])
    check('...and the review of the second names the first, so each row can be opened from either lab', rb['also_sends'] == [dict(job_id=a['id'], lab='restore-square', name='ceos changed', kind='save', target='latest')]
          and rb['upload_job'] == b['id'] and [f['name'] for f in rb['files']][:1] == ['r1.cfg'], json.dumps({k: rb[k] for k in rb if k != 'files'})[:300])
    check('git_status.waiting counts the checkout\'s waiting saves, whichever lab made them (2 for both labs)', lab_state('restore-square')['git_status']['waiting'] == 2 and lab_state('edge-lab')['git_status']['waiting'] == 2)
    code, answer = upload(a, ra['head'])
    check('Upload through the first save: the save at HEAD (the second lab\'s) is the one pushed and carries both; both end uploaded', code == 200 and answer['status'] == 'synced' and answer['id'] == b['id']
          and all(call('GET', f'/api/git/jobs/{j["id"]}')[1]['pushed'] is True and call('GET', f'/api/git/jobs/{j["id"]}')[1]['status'] == 'synced' for j in (a, b)), f'{code} {str(answer)[:200]}')

    # --- rename, checkpoint from a save
    edit('ceos', '   ip route 10.9.9.0/24 10.0.0.2')
    d = save(sq)
    check('the next save is named "ceos changed" again (only ceos differs from the uploaded latest)', d['note'] == 'ceos changed' and d['note_auto'] is True, d['note'])
    code, renamed = call('POST', f'/api/git/jobs/{d["id"]}/name', dict(note='My own name'))
    check('rename: the name changes and is no longer automatic; the commit is untouched', code == 200 and renamed['note'] == 'My own name' and renamed['note_auto'] is False and renamed['commit'] == d['commit'], str(renamed)[:200])
    code, renamed = call('POST', f'/api/git/jobs/{d["id"]}/name', dict(note=''))
    check('rename to an empty name returns to the one the manager wrote', code == 200 and renamed['note'] == 'ceos changed' and renamed['note_auto'] is True, str(renamed.get('note')))
    code, renamed = call('POST', f'/api/git/jobs/{d["id"]}/name', dict(note='Kept name'))
    names = call('GET', f'/api/labs/{sq}/git/history')[1]['commits']
    check('the history names the commit with the name it has now', [c.get('name') for c in names if c['commit'] == d['commit']] == ['Kept name'], str([(c.get('name'), c['message']) for c in names][:3]))
    code, answer = call('POST', f'/api/git/jobs/{d["id"]}/name', dict(note='two\nlines'))
    check('a name is one line (400)', code == 400, f'{code} {answer}')
    check('renaming a save that does not exist is a 404', call('POST', '/api/git/jobs/nope/name', dict(note='x'))[0] == 404)
    # A newer save lands first, so the save kept as a checkpoint is an OLDER one: `latest` must stay the newer save's.
    edit('ceos', '   ip route 10.9.10.0/24 10.0.0.2')
    newer = save(sq, 'Newer than the kept one')
    latest_before = helper('reg-bgp', mode='read-version', commit=newer['commit'], path='BGP/latest')['snapshot']
    cp = save(sq, '', target='checkpoint', backup_job_id=d['backup_job_id'])
    latest_after = helper('reg-bgp', mode='read-version', commit=cp['commit'], path='BGP/latest')['snapshot']
    kept = helper('reg-bgp', mode='read-version', commit=cp['commit'], path='BGP/checkpoints/kept-name')['snapshot']
    older = helper('reg-bgp', mode='read-version', commit=d['commit'], path='BGP/latest')['snapshot']
    check('Keep as a checkpoint from an OLDER save leaves latest as the newest save wrote it (the helper\'s checkpoint_only): only the checkpoint folder changes',
          newer['status'] == 'review_pending' and cp['commit'] != newer['commit'] and latest_after == latest_before and latest_before['files'] != older['files']
          and cp['changed_files'] and all(p.startswith('BGP/checkpoints/kept-name/') for p in cp['changed_files']), f"{cp.get('status')} {cp.get('message')} {cp.get('changed_files')}")
    check('...the checkpoint holds the older capture with its topology and map, and the review lists the checkpoint folder only', kept['files'] == older['files']
          and any(f.get('kind') == 'topology' for f in kept['manifest']['files']) and any(f.get('kind') == 'annotations' for f in kept['manifest']['files'])
          and sorted(f['path'] for f in review(sq, cp)['files']) == sorted(cp['changed_files']), str(sorted(kept['files']))[:200])
    refused = helper('reg-bgp', mode='publish', operation_id=uuid.uuid4().hex, target='latest', checkpoint_only=True, expected_head=cp['commit'], snapshot=older)
    check('...the helper refuses the option for any target but a checkpoint (Invalid save option.)', refused.get('status') == 'needs_attention' and refused.get('message') == 'Invalid save option.', str(refused)[:200])
    check('Keep as a checkpoint from a save: no device is read again (captured false), the folder is made from the save\'s name (kept-name)', cp['status'] == 'review_pending' and cp['target'] == 'checkpoint'
          and cp['checkpoint'] == 'kept-name' and cp['captured'] is False and cp['snapshot_path'] == 'BGP/checkpoints/kept-name', f"{cp['status']} {cp.get('checkpoint')} {cp.get('captured')} {cp.get('snapshot_path')} {cp.get('message')}")
    cp2 = save(sq, '', target='checkpoint', backup_job_id=d['backup_job_id'])
    check('...a second one from the same save takes the next free name (kept-name-2)', cp2['checkpoint'] == 'kept-name-2', str(cp2.get('checkpoint')))
    r = review(sq, cp2)
    code, up = upload(cp2, r['head'])
    check('...the checkpoints and the save upload together (every waiting save of the checkout), and the history lists the checkpoints', code == 200 and up['status'] == 'synced'
          and {'BGP/checkpoints/kept-name', 'BGP/checkpoints/kept-name-2'} <= {v['path'] for v in helper('reg-bgp', mode='history')['versions']} and call('GET', f'/api/git/jobs/{d["id"]}')[1]['pushed'] is True)
    again = call('GET', f'/api/git/jobs/{first["id"]}')[1]
    check('...a save made earlier still holds its whole capture (capture_kept, capture_whole), so a checkpoint can be made from it', again['capture_kept'] is True and again['capture_whole'] is True)

    # --- Save as a lab state
    status, answer = lab_state_save(sq, 'BGP/mine', 'Mine')
    check('Save as a lab state: a free folder is saved at once, the job is of kind state and the lab\'s own folder is untouched', status == 200 and answer['kind'] == 'state' and answer['snapshot_path'] == 'BGP/mine/latest'
          and answer['status'] == 'review_pending' and answer['note'] == 'Mine' and lab_state('restore-square')['git_binding']['repository']['prefix'] == 'BGP', f'{status} {str(answer)[:300]}')
    helper_states = {v['path']: v['summary'] for v in helper('reg-bgp', mode='history')['versions']}
    check('...its manifest carries `state: Mine` (the helper\'s summary says so) and it is a normal complete state (4 devices with restore data)', helper_states['BGP/mine/latest']['state'] == 'Mine'
          and len(helper_states['BGP/mine/latest']['devices']) == 4 and all(d['restore'] for d in helper_states['BGP/mine/latest']['devices']))
    status, answer = lab_state_save(sq, 'BGP/start', 'Start')
    check('Save as a lab state into a folder that holds the state "Start": one question (kind state, label Start), not an error', status == 200 and answer['question']['kind'] == 'state' and answer['question']['label'] == 'Start', f'{status} {answer}')
    status, answer = lab_state_save(sq, 'BGP/start', 'Start', choice='take')
    check('...Replace it: saved there, and the state the helper lists at BGP/start/latest is now complete (4 devices with restore data)', status == 200 and answer['snapshot_path'] == 'BGP/start/latest' and answer['status'] == 'review_pending'
          and all(d['restore'] for d in {v['path']: v['summary'] for v in helper('reg-bgp', mode='history')['versions']}['BGP/start/latest']['devices']), f'{status} {str(answer)[:200]}')
    status, answer = lab_state_save(sq, 'BGP', 'Inside')
    check('Save as a lab state into the lab\'s own folder: the state goes to <folder>/<name> and the answer says so (BGP/Inside)', status == 200 and answer['snapshot_path'] == 'BGP/Inside/latest', f'{status} {str(answer)[:200]}')
    status, answer = lab_state_save(fresh, 'Course/mine', 'Mine', repository='reg-archtop')
    check('a lab state of a lab that saves elsewhere (square-fresh into Archtop-Lab through the repository)', status == 200 and answer['snapshot_path'] == 'Course/mine/latest', f'{status} {str(answer)[:200]}')
    status, answer = lab_state_save(shared_b, 'x', 'No source')
    check('a lab without a save location must say which repository (400)', status == 400, f'{status} {answer}')
    # the three lab states wait for upload together with the lab's own saves: one review names them
    waiting = [j for j in state()['git_jobs'] if j.get('kind') == 'state' and j['status'] == 'review_pending' and j['lab_id'] == sq]
    r = review(sq, waiting[-1])
    check('lab states count as saves to upload: one review names every waiting one, kind state', len(waiting) == 3 and {x['kind'] for x in r['also_sends']} == {'state'} and len(r['also_sends']) == 2, json.dumps(r['also_sends'])[:300])

    rs = call('GET', f'/api/labs/{sq}/restore/states')[1]
    rows = {r['path']: r for r in rs['states']}
    order = ['latest', 'checkpoint', 'baseline', 'state', 'other-lab']
    check('restore/states: the lab\'s own latest first, then checkpoints, the starting point, lab states by name, other labs\' saves', [r['group'] for r in rs['states']] == sorted((r['group'] for r in rs['states']), key=order.index)
          and rs['states'][0]['group'] == 'latest' and rs['lab_devices'] == 4 and rs['head'] and rs['truncated'] is False, str([(r['group'], r['name']) for r in rs['states']]))
    check('...a lab state written by Save as a lab state is group `state` named from its mark (Mine), with 4 of 4 devices loadable', rows['BGP/mine/latest']['group'] == 'state' and rows['BGP/mine/latest']['name'] == 'Mine'
          and rows['BGP/mine/latest']['saved_devices'] == 4 and rows['BGP/mine/latest']['loadable_devices'] == 4 and rows['BGP/mine/latest']['view_only'] is False)
    check('...the course states read as lab states for every lab: Start, Broken, Final (group state)', all(rows[p]['group'] == 'state' for p in ('BGP/start/latest', 'BGP/broken/latest', 'BGP/final/latest'))
          and rows['BGP/broken/latest']['name'] == 'Broken' and rows['BGP/final/latest']['name'] == 'Final · BGP' and rows['BGP/start/latest']['name'] == 'Start')
    check('...two states of one name each say where they are (Final · BGP, Final · Top level)', rows['Final']['name'] == 'Final · Top level')
    check('...the lab\'s own checkpoints and the starting point keep their groups and names', rows['BGP/checkpoints/kept-name']['group'] == 'checkpoint' and rows['BGP/checkpoints/ospf-up']['name'] == 'ospf-up'
          and rows['BGP/baseline']['group'] == 'baseline' and rows['BGP/baseline']['name'] == 'Baseline')
    check('...the subset state: 2 saved devices, 2 loadable of this lab\'s 4', rows['BGP/junos-only/latest']['saved_devices'] == 2 and rows['BGP/junos-only/latest']['loadable_devices'] == 2)
    check('...the other-topology state: 4 saved, 3 loadable (one device matches no node of the lab)', rows['BGP/other-topology/latest']['saved_devices'] == 4 and rows['BGP/other-topology/latest']['loadable_devices'] == 3)
    check('...a design export is view only (design) and an unreadable manifest is unknown, not view only', rows['BGP/checkpoints/plan-sept']['view_only'] is True and rows['BGP/checkpoints/plan-sept']['view_only_reason'] == 'design'
          and rows['BGP/legacy']['view_only'] is False and rows['BGP/legacy']['view_only_reason'] == 'unknown' and rows['BGP/legacy']['saved_devices'] is None)
    check('...other labs\' saves are group other-lab with the lab\'s name', rows['BGP/edge/latest']['group'] == 'other-lab' and rows['BGP/edge/latest']['lab'] == 'edge-lab')
    check('...every row carries the commit the list was read at; no summary, lab id or topology digest leaves the manager', all(r['commit'] == rs['head'] for r in rs['states'])
          and not any(k in r for r in rs['states'] for k in ('summary', 'lab_id', 'topology_digest')))
    fresh_rows = call('GET', f'/api/labs/{fresh}/restore/states?repository=reg-archtop')[1]
    fr = {r['path']: r for r in fresh_rows['states']}
    check('a repository\'s states by `repository`: Start (view only: no restore data), Broken, Final, and the lab\'s own latest', fr['Course/start/latest']['view_only'] is True
          and fr['Course/start/latest']['view_only_reason'] == 'no_restore_data' and fr['Course/start/latest']['name'] == 'Start' and fr['Course/broken/latest']['view_only'] is False
          and fr['Course/final/latest']['loadable_devices'] == 4 and fr['square-fresh/latest']['group'] == 'latest')
    check('...a lab with no save location needs the repository (409 without it) and with it lists every state', call('GET', f'/api/labs/{shared_b}/restore/states')[0] == 409
          and call('GET', f'/api/labs/{shared_b}/restore/states?repository=reg-archtop')[0] == 200)
    check('a state written by a save names the capture it is (source.capture_id, a real id); one an instructor wrote names none', preflight(sq, 'BGP/mine/latest')['source']['capture_id'] not in ('', None)
          and preflight(sq, 'BGP/other-topology/latest')['source']['capture_id'] == '')
    switch(capture_seconds=None)
    idle()


# --- causes: what stops a save, as the code the manager maps it to ---------------------------------------------------------------

def git_status_of(lab):
    status, body = call('GET', f'/api/labs/{lab_ids()[lab]}/git')
    return body.get('repository_status', {}), lab_state(lab)['git_status']


def causes():
    from app.git_progress import problem_code
    import fake_git
    ids = lab_ids()
    sq, solo = ids['restore-square'], ids['solo-lab']
    switch(capture_seconds=1)
    # --- every sentence the fake says is a sentence the helper writes, mapped to the code its stage promises
    expected = {'operation': 'busy', 'staged': 'busy', 'edits': 'busy', 'settings': 'settings', 'files': 'files', 'identity': 'account', 'diverged': 'diverged'}
    check('every sentence of the fake\'s problems is in the manager\'s table of the helper\'s sentences, with the code its cause is shown as',
          all(problem_code(fake_git.PROBLEMS[k][0]) == code and fake_git.PROBLEMS[k][0] in __import__('app.git_progress', fromlist=['x']).HELPER_PROBLEMS for k, code in expected.items()),
          str({k: problem_code(fake_git.PROBLEMS[k][0]) for k in expected}))
    for text, code in ((fake_git.PUSH_FAILED, 'account'), (fake_git.REMOTE_UNAVAILABLE, 'account')):
        check(f'...{code}: "{text[:50]}…" is in the table', problem_code(text) == code)
    # --- the chip's code, through the real settings route (the one place the manager asks `status`)
    status, chip = git_status_of('solo-lab')
    check('nothing wrong: git_status is ready, no code, nothing waiting', chip['ready'] is True and chip['code'] == '' and chip['problem'] == '' and chip['waiting'] == 0, str(chip))
    switch(vm_unreachable=True)
    status, chip = git_status_of('solo-lab')
    check('the VM cannot be reached: ready false, code vm', status['ready'] is False and chip['ready'] is False and chip['code'] == 'vm' and 'Cannot reach the VM Git helper' in chip['problem'], str(chip))
    switch(vm_unreachable=None)
    for key, code in (('staged', 'busy'), ('edits', 'busy'), ('operation', 'busy'), ('settings', 'settings'), ('files', 'files'), ('diverged', 'diverged')):
        switch(status_problem=key)
        status, chip = git_status_of('solo-lab')
        check(f'status_problem={key}: the helper\'s own sentence, code {code}', status['ready'] is False and status['problem'] == fake_git.PROBLEMS[key][0] and chip['code'] == code, f'{status["problem"][:60]} {chip}')
    switch(status_problem='Something the manager has never heard of.')
    status, chip = git_status_of('solo-lab')
    check('a sentence nobody listed: code other', chip['code'] == 'other' and chip['ready'] is False)
    # --- the same causes met by Save itself (what the browser pass does): the save stops after its capture and the chip's code follows
    for values, code in (({'vm_unreachable': True}, 'vm'), ({'status_problem': 'staged'}, 'busy'), ({'status_problem': 'edits'}, 'busy'), ({'status_problem': 'operation'}, 'busy'),
                         ({'status_problem': 'settings'}, 'settings'), ({'status_problem': 'files'}, 'files'), ({'status_problem': 'diverged'}, 'diverged')):
        action('reset')
        switch(capture_seconds=1, **values)
        job = save(solo)
        chip = lab_state('solo-lab')['git_status']
        check(f'Save with {list(values.items())[0][0]}={list(values.values())[0]}: the capture is kept, the save ends `export_pending` (not failed) with the helper\'s sentence and the chip\'s code is {code}',
              job['status'] == 'export_pending' and job['capture_kept'] is True and chip['code'] == code and chip['ready'] is False and chip['problem'][:60] == job['message'][:60], f"{job['status']} {job['message'][:60]} {chip}")
    action('reset')
    switch(capture_seconds=1)
    # --- the stages: what a problem blocks (the helper's own order)
    switch(status_problem='staged')
    h = helper('reg-solo', mode='history')
    check('a problem of the clean stage (staged changes) stops status, publish and update but NOT history, browse or read-version (the helper only validates there)',
          'versions' in h and 'files' in helper('reg-solo', mode='browse') and helper('reg-solo', mode='update', expected_head=h['head']).get('error') == fake_git.PROBLEMS['staged'][0]
          and helper('reg-solo', mode='status')['ready'] is False and helper('reg-solo', mode='status')['head'] == h['head'])
    check('...so the Load panel still lists the states while Save says someone is working in the repository', call('GET', f'/api/labs/{solo}/restore/states?repository=reg-archtop')[0] == 200)
    switch(status_problem='settings')
    check('a problem of the validate stage (the branch changed) stops every mode, and status answers no head', 'error' in helper('reg-solo', mode='history') and 'error' in helper('reg-solo', mode='browse')
          and helper('reg-solo', mode='status')['head'] == '' and call('GET', f'/api/labs/{solo}/restore/states?repository=reg-work')[0] == 409)
    switch(status_problem='identity')
    edit('clab-solo-lab-r1', '   ip route 0.0.0.0/0 10.0.0.1')
    status, chip = git_status_of('solo-lab')
    check('a problem of the write stage (no commit identity) leaves status ready: it is met by the save, not by the chip', status['ready'] is True and chip['code'] == '')
    job = save(solo, 'no identity')
    check('...Save then ends needing attention with the helper\'s sentence and the chip says: the VM account cannot commit (code account)', job['status'] == 'export_pending' and 'commit identity' in job['message']
          and lab_state('solo-lab')['git_status']['code'] == 'account', f"{job['status']} {job['message'][:80]} {lab_state('solo-lab')['git_status']}")
    switch(status_problem=None)
    code, answer = call('POST', f'/api/git/jobs/{job["id"]}/retry', dict(push=True, reviewed=False))
    job = settle(answer['id']) if code == 200 else answer
    check('...Try again (a retry without a commit saves on the VM and waits for the review) works once the cause is gone', code == 200 and job['status'] == 'review_pending', f'{code} {str(job)[:200]}')
    r = review(solo, job)
    code, up = upload(job, r['head'])
    check('...and the save uploads', code == 200 and up['status'] == 'synced')
    # --- upload failures: account, diverged, and the remote that cannot be asked
    edit('ceos', '   ip route 10.8.8.0/24 10.0.0.2')
    a = save(sq)
    r = review(sq, a)
    switch(push_refused=True)
    code, up = upload(a, r['head'])
    check('Upload failed (the account may not push): the save is safe on the VM, push failed, code account', code == 200 and up['status'] == 'push_pending' and 'push failed' in up['message']
          and lab_state('restore-square')['git_status']['code'] == 'account' and lab_state('restore-square')['git_status']['waiting'] == 1, f"{up['status']} {up['message'][:80]}")
    switch(push_refused=None, remote_unreachable=True)
    code, up = upload(a, r['head'])
    check('Upload failed (the remote cannot be reached): the helper\'s sentence, code account', up['status'] == 'push_pending' and 'remote branch is unavailable' in up['message'] and lab_state('restore-square')['git_status']['code'] == 'account', up['message'][:80])
    check('...the review still works with the remote down: outgoing is null (not an empty list)', helper('reg-bgp', mode='compare', operation_id=a['id'])['outgoing'] is None and
          helper('reg-bgp', mode='compare', operation_id=a['id'])['outgoing_truncated'] is False and review(sq, a)['upload_job'] == a['id'])
    switch(remote_unreachable=None, remote_ahead=True)
    code, up = upload(a, r['head'])
    check('The online copy has changes the VM lacks while a save waits: the upload is refused as diverged (code diverged), nothing is forced', up['status'] == 'push_pending' and 'diverged' in up['message']
          and lab_state('restore-square')['git_status']['code'] == 'diverged', up['message'][:80])
    code, answer = call('POST', f'/api/labs/{sq}/git/update')
    check('...Update from the repository is refused while a save waits here (the action is Upload)', code == 409 and 'Upload the waiting saves first' in json.dumps(answer), f'{code} {answer}')
    switch(remote_ahead=None, push_fail_once=True)
    code, up = upload(a, r['head'])
    check('push_fail_once: the next upload fails once ("saved on the VM, but push failed"), the one after works', up['status'] == 'push_pending', up['status'])
    code, up = upload(a, r['head'])
    check('...Try again uploads and the chip data is clean again (ready, no code, nothing waiting)', up['status'] == 'synced' and lab_state('restore-square')['git_status']['code'] == '' and lab_state('restore-square')['git_status']['waiting'] == 0)
    switch(**{'remote_ahead@Nested-Labs': True})
    code, answer = call('POST', f'/api/labs/{sq}/git/update')
    check('The online copy has changes and nothing waits: Update from the repository fast-forwards', code == 200 and answer['status'] == 'updated', f'{code} {answer}')
    # A save first brings the VM copy up to date when nothing waits there, so a commit added online does not end its upload as diverged.
    switch(**{'remote_ahead@Nested-Labs': True})
    before = call('GET', '/fixture/state')[1]['repositories']['Nested-Labs']['commits']
    edit('ceos', '   ip route 10.9.11.0/24 10.0.0.2')
    caught = save(sq)
    after = call('GET', '/fixture/state')[1]['repositories']['Nested-Labs']['commits']
    r = review(sq, caught)
    code, up = upload(caught, r['head'])
    check('A commit added online while nothing waits here: the save fast-forwards the VM copy first (two new commits: the online one, then the save), and the upload ends synced with nothing done by hand',
          caught['status'] == 'review_pending' and after == before + 2 and r['also_sends'] == []
          and code == 200 and up['status'] == 'synced' and lab_state('restore-square')['git_status']['code'] == '' and lab_state('restore-square')['git_status']['waiting'] == 0,
          f"{caught['status']} {before} {after} {code} {str(up)[:160]}")
    events = [e for e in call('GET', '/api/logs?limit=2000')[1]['events'] if e['action'] == 'git.update']
    check('...recorded once as an event with a fixed sentence', len(events) == 1 and events[0]['message'] == 'The VM copy of the repository was brought up to date with the online copy before a save.', str(events)[:200])
    action('reset')
    switch(capture_seconds=1)
    # --- a device that cannot be read, and no save at HEAD
    switch(device_unreadable=['xrv9k'])
    edit('ceos', '   ip route 10.7.7.0/24 10.0.0.2')
    job = save(sq)
    backup = next(j for j in state()['jobs'] if j['id'] == job['backup_job_id'])
    check('a device that cannot be read: nothing is saved (no commit), the save ends `capture_incomplete`, and the capture names the device that failed (the page words it)', job['status'] == 'capture_incomplete'
          and not job.get('commit') and [short(n['name']) for n in backup['nodes'] if n['status'] == 'failed'] == ['xrv9k'], f"{job['status']} {job['message'][:100]} {[(n['name'], n['status']) for n in backup['nodes']]}")
    check('...and it is no help to retry it (a new save is needed)', call('POST', f'/api/git/jobs/{job["id"]}/retry', dict(push=True, reviewed=False))[0] == 409)
    switch(device_unreadable=None)
    job = save(sq)
    r = review(sq, job)
    action('hand_commit', repository='Nested-Labs')
    code, answer = upload(job, r['head'])
    check('somebody committed on the VM after the review: the upload is refused because HEAD is not what the review showed (409, back to the review)', code == 409 and 'Another save was made' in json.dumps(answer), f'{code} {answer}')
    r2 = review(sq, job)
    check('...the review then shows the new HEAD and no save of the manager at it (upload_job null)', r2['head'] != r['head'] and r2['upload_job'] is None, json.dumps({k: r2[k] for k in r2 if k != 'files'})[:300])
    code, answer = upload(job, r2['head'])
    check('no save at HEAD: the upload is refused with the sentence that sends the person to the repository owner (409)', code == 409 and 'changes the manager did not make' in json.dumps(answer), f'{code} {answer}')
    code, answer = upload(job, '')
    check('an upload that names no HEAD is refused before the VM is asked: the review comes first (409)', code == 409 and 'Review the changes of this save' in json.dumps(answer), f'{code} {answer}')
    status, answer = place(ids['shared-b'], repository='reg-bgp', folder='brand-new', acknowledge=True)
    check('a checkout with a commit nobody journaled: registering a new folder answers with the helper\'s sentence (a 409; H2 lets a further folder sit only on manager saves)', status == 409
          and 'not made by manager saves' in json.dumps(answer), f'{status} {answer}')
    edit('ceos', '   ip route 10.6.6.0/24 10.0.0.2')
    third = save(sq)
    r3 = review(sq, third)
    rows = [x for x in r3['also_sends'] if 'commit' in x]
    check('a commit the manager does not hold (made by hand on the VM) is named in the review by its subject and its paths (H6), not by a lab', len(rows) == 1 and rows[0]['name'] == 'Edited by hand' and rows[0]['files'] == ['by-hand.txt'], json.dumps(r3['also_sends'])[:300])
    code, answer = upload(third, r3['head'])
    check('...and the upload of a save on top of it is refused as made up of commits created outside manager saves (code diverged)', code == 200 and answer['status'] == 'push_pending' and 'outside manager saves' in answer['message']
          and lab_state('restore-square')['git_status']['code'] == 'diverged', f'{code} {str(answer)[:300]}')
    helper_compare = helper('reg-bgp', mode='compare', operation_id=third['id'])
    out = helper_compare['outgoing']
    check('the helper\'s compare answers `outgoing` OLDEST FIRST with {commit, operation_id, subject, files, approved} and outgoing_truncated', helper_compare['outgoing_truncated'] is False and len(out) >= 3
          and out[0]['operation_id'] != third['id'] and out[-1]['operation_id'] == third['id'] and all(set(x) == {'commit', 'operation_id', 'subject', 'files', 'approved'} for x in out)
          and [x for x in out if x['subject'] == 'Edited by hand'][0]['approved'] is False and [x for x in out if x['subject'] == 'Edited by hand'][0]['operation_id'] is None and out[-1]['approved'] is True, json.dumps(out)[:500])
    # --- the first-save default moves with every save of another lab; prefer_repository puts it back (SCENARIOS, point 5)
    fresh = ids['square-fresh']

    def default_name():
        places = call('GET', f'/api/labs/{fresh}/git/places')[1]
        return next(r['name'] for r in places['repositories'] if r['id'] == places['default']['repository'])
    check('a save by another lab makes its repository the default of a lab that never saved (the manager\'s rule, not the fixture\'s)', default_name() != 'Archtop-Lab', default_name())
    action('prefer_repository', repository='Archtop-Lab')
    check('...and prefer_repository puts the owner\'s standard install (Archtop-Lab, registered at its top level only) back as the default, with no question',
          default_name() == 'Archtop-Lab' and call('GET', f'/api/labs/{fresh}/git/places')[1]['default']['ask'] is False and not lab_state('square-fresh').get('git_binding')
          and lab_state('square-fresh')['git_status']['ready'] is None)
    action('reset')


# --- helper: registrations, retire, connect (H1 to H7) ---------------------------------------------------------------------------

def helper_rules():
    from app.git_progress import UNREGISTERED
    from app import host_git
    ids = lab_ids()
    sq = ids['restore-square']
    switch(capture_seconds=1)
    idle()
    stale = action('helper', repository='', request={'mode': 'status', 'binding_id': 'reg-bgp', 'revision': 'stale'})
    unknown = action('helper', repository='', request={'mode': 'status', 'binding_id': 'nope', 'revision': 'x'})
    check('a binding id the registry does not hold is the helper\'s `Select a registered Git repository.`; a stale revision is `The repository binding changed.`',
          unknown.get('error') == UNREGISTERED and stale.get('error') == 'The repository binding changed. Select it again.', f'{unknown} {stale}')
    edit('ceos', '   ip route 0.0.0.0/0 10.0.0.1')
    edit('xrv9k', ' router static', '  address-family ipv4 unicast')
    job = save(sq, 'two devices changed')
    names = {f.split('/')[-1] for f in job.get('changed_files', [])}
    check('after two edits Save commits a change: exactly ceos and xrv9k (and their restore artifacts) changed', job['status'] == 'review_pending' and names == {'ceos.cfg', 'ceos.eoscfg', 'xrv9k.cfg', 'xrv9k.xrcfg', 'manifest.json'}, f"{job['status']} {sorted(names)}")
    out = helper('reg-bgp', mode='compare', operation_id=job['id']).get('outgoing')
    check('the save waits for upload (a commit the remote lacks), and it is the newest of outgoing', out and out[-1]['operation_id'] == job['id'] and out[-1]['approved'] is True)
    check('H2: registering a further folder works while saves wait', 'id' in helper('reg-bgp', mode='register-prefix', prefix='BGP/extra-folder'))
    check('H7: retiring the registration a waiting save was made through is refused, with the helper\'s sentence', helper('reg-bgp', mode='register-prefix', prefix='moved', retire=True).get('error') == host_git.SAVE_WAITS)
    check('H7: the refusal leaves everything as it was (the registration is still there, and so is the new folder\'s absence)', 'moved' not in {f['prefix'] for f in helper('reg-bgp', mode='browse')['folders']}
          and 'BGP' in {f['prefix'] for f in helper('reg-bgp', mode='browse')['folders']})
    check('H1: nesting is never refused (inside, above, beside)', all('id' in helper('reg-bgp', mode='register-prefix', prefix=p) for p in ('BGP/edge/deeper', 'BGP-beside', 'shared/inside', 'brand-new')))
    err = helper('reg-bgp', mode='register-prefix', prefix='BGP/checkpoints/x/y').get('error')
    check('H1: only a real collision is refused, with the helper\'s own collision sentence', err == host_git.collision_message('BGP/checkpoints/x/y', 'BGP'), str(err))
    err = helper('reg-bgp', mode='register-prefix', prefix='BGP/latest').get('error')
    check('...and a name a lab writes inside its folder is not a lab folder (base_prefix: "choose the folder above")', 'Choose the folder above' in str(err) and 'BGP/latest' in str(err), str(err))
    check('the same folder again returns the registration it has (reuse, nothing new)', helper('reg-bgp', mode='register-prefix', prefix='BGP-beside')['id'] == helper('reg-bgp', mode='register-prefix', prefix='BGP-beside')['id'])
    # a push carries every earlier waiting commit (the newest only can be pushed)
    edit('ceos', '   ip route 10.9.9.0/24 10.0.0.2')
    second = save(sq, 'a second change')
    outgoing = helper('reg-bgp', mode='compare', operation_id=second['id']).get('outgoing') or []
    check('H6: compare answers every commit not yet uploaded, oldest first, with operation id, subject and files', len(outgoing) == 2 and [o['operation_id'] for o in outgoing] == [job['id'], second['id']]
          and all(o['subject'] and o['files'] and o['approved'] for o in outgoing), json.dumps(outgoing)[:300])
    older = helper('reg-bgp', mode='push', operation_id=job['id'])
    check('only the newest commit can be pushed: the older save is refused', older.get('status') == 'needs_attention' and 'moved since this save' in older.get('message', ''), str(older))
    switch(remote_unreachable=True)
    check('H6: outgoing is null when the remote cannot be asked', helper('reg-bgp', mode='compare', operation_id=second['id']).get('outgoing') is None)
    check('H7: a retire the remote cannot answer is refused with the helper\'s own sentence', helper('reg-bgp', mode='register-prefix', prefix='moved', retire=True).get('error') == host_git.SAVE_UNKNOWN)
    check('H2: a new folder cannot be registered while the remote cannot be asked (the helper\'s remote sentence)', helper('reg-bgp', mode='register-prefix', prefix='cannot-ask').get('error')
          == "The remote branch is unavailable. Check connectivity and the owner's noninteractive HTTPS Git login.")
    check('...and a push fails with the remote sentence', 'remote branch is unavailable' in helper('reg-bgp', mode='push', operation_id=second['id']).get('message', ''))
    switch(remote_unreachable=None, remote_ahead=True)
    check('H2: a further folder beside waiting saves is refused when the online copy has changes this VM lacks (the helper\'s sentence)', helper('reg-bgp', mode='register-prefix', prefix='ahead').get('error') == host_git.REMOTE_AHEAD)
    check('...and a push is refused as diverged, nothing forced', 'diverged' in helper('reg-bgp', mode='push', operation_id=second['id']).get('message', ''))
    switch(remote_ahead=None, push_refused=True)
    check('a new folder is refused with the helper\'s push-probe sentence while the account may not push', 'push preflight failed' in str(helper('reg-bgp', mode='register-prefix', prefix='probe').get('error')))
    switch(push_refused=None, push_fail_once=True)
    failed = helper('reg-bgp', mode='push', operation_id=second['id'])
    check('Upload failed: the next push fails once ("saved on the VM, but push failed")', failed.get('status') == 'needs_attention' and 'push failed' in failed.get('message', ''), str(failed))
    done = helper('reg-bgp', mode='push', operation_id=second['id'])
    check('the next push carries both saves: synced_operations names them all', done.get('pushed') is True and {job['id'], second['id']} <= set(done.get('synced_operations') or []), str(done))
    again = helper('reg-bgp', mode='publish', operation_id=uuid.uuid4().hex, expected_head=helper('reg-bgp', mode='status')['head'], target='latest',
                   snapshot=helper('reg-bgp', mode='read-version', commit=helper('reg-bgp', mode='status')['head'], path='BGP/latest')['snapshot'])
    check('publish of an unchanged capture answers `unchanged`', again.get('status') == 'unchanged' and again.get('changed_files') == [], str(again)[:200])
    check('H7: with nothing waiting a registration can be retired (its folder replaced by the new one) and the old one is gone', 'id' in helper('reg-unused', mode='register-prefix', prefix='moved', retire=True)
          and 'reg-unused' not in {r['id'] for r in call('GET', '/api/git/repositories')[1]['repositories']} and 'moved' in {f['prefix'] for f in helper('reg-bgp', mode='browse')['folders']})
    check('a retired registration is gone: a call with it answers `Select a registered Git repository.`', action('helper', repository='', request={'mode': 'status', 'binding_id': 'reg-unused', 'revision': 'x'}).get('error') == UNREGISTERED)
    # a collision with a registration nothing uses is replaced by the manager, not shown to the person
    status, answer = place(ids['shared-b'], repository='reg-bgp', folder='BGP/extra-folder/latest/x', acknowledge=True)
    folders = {f['prefix'] for f in helper('reg-bgp', mode='browse')['folders']}
    check('a folder the helper refuses as a collision with a folder nothing uses: place retires the unused one and places the lab (no question, no error)', status == 200 and answer.get('saved') is True
          and answer['binding']['repository']['prefix'] == 'BGP/extra-folder/latest/x' and 'BGP/extra-folder' not in folders, f'{status} {str(answer)[:200]} {sorted(folders)}')
    # connect: the fixed sentences
    empty = 'https://github.com/ArchRuger/New-Empty.git'
    check('connect: an empty repository is refused with the helper\'s fixed sentence, the clone stays unborn, then initialize starts it (README on the remote)',
          helper('', mode='connect', url=empty, prefix='').get('error') == host_git.EMPTY_REPOSITORY and 'id' in helper('', mode='connect', url=empty, prefix='', initialize=True))
    check('connect: initialize must be a boolean', helper('', mode='connect', url='https://github.com/ArchRuger/Spare-Lab.git', prefix='', initialize='yes').get('error') == 'Invalid connect option.')
    late = 'https://github.com/ArchRuger/Late-README.git'
    switch(initialize_fails=True)
    check('connect: a failed start says so with the helper\'s sentence', helper('', mode='connect', url=late, prefix='', initialize=True).get('error') == host_git.START_FAILED)
    switch(initialize_fails=None)
    check('...and connecting again retries the clone that was left unborn', 'id' in helper('', mode='connect', url=late, prefix='', initialize=True))
    check('connect with a prefix inside another folder\'s saved state is refused with the helper\'s collision sentence', helper('', mode='connect', url='https://github.com/ArchRuger/Nested-Labs.git', prefix='BGP/latest/z').get('error')
          == host_git.collision_message('BGP/latest/z', 'BGP'))
    check('connect with a folder that exists already returns its registration (reuse)', helper('', mode='connect', url='https://github.com/ArchRuger/Nested-Labs.git', prefix='BGP')['id'] == 'reg-bgp')
    check('an address that is not a clone URL is refused with the helper\'s sentence', 'Use the HTTPS clone URL' in str(helper('', mode='connect', url='http://github.com/x/y', prefix='').get('error')))
    action('reset')


# --- the fixture process -----------------------------------------------------------------------------------------------------------

def start(port):
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


def stop(process):
    process.terminate()
    try:
        process.wait(10)
    except subprocess.TimeoutExpired:
        process.kill()


def free_port(preferred):
    for port in ([preferred] if preferred else []) + list(range(8191, 8200)):
        with socket.socket() as sock:
            if sock.connect_ex(('127.0.0.1', port)) != 0:
                return port
    raise SystemExit('No free port in 8191 to 8199.')


def seed():
    idle()
    labs = labs_and_repositories()
    states(labs)
    devices_and_loads(labs)


SECTIONS = {'seed': seed, 'places': places, 'saves': saves, 'causes': causes, 'helper': helper_rules}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=0)
    parser.add_argument('--keep-logs', action='store_true')
    parser.add_argument('--only', default='', help='comma separated sections: ' + ', '.join(SECTIONS))
    args = parser.parse_args()
    wanted = [s for s in (args.only.split(',') if args.only else SECTIONS) if s]
    unknown = [s for s in wanted if s not in SECTIONS]
    if unknown:
        raise SystemExit('Unknown section: ' + ', '.join(unknown))
    started, logs = time.time(), []
    for name in wanted:
        process, data, log = start(free_port(args.port))
        print(f'--- {name} (fixture on {BASE})', flush=True)
        try:
            idle()
            SECTIONS[name]()
        finally:
            stop(process)
            if args.keep_logs or results['fail']:
                logs.append(os.path.join(data, 'fixture.log'))
            else:
                shutil.rmtree(data, ignore_errors=True)
    print(f'\n{results["ok"]} ok, {results["fail"]} failed in {time.time() - started:.0f} s')
    for path in logs:
        print('fixture log:', path)
    return 1 if results['fail'] else 0


if __name__ == '__main__':
    sys.exit(main())
