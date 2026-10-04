#!/usr/bin/env python3
"""Render the project's own frontend (index.html, style.css, the JS at the checked-out release) in
Chromium with the manager's API answered from memory, and screenshot the Progress tab and the save
flow. The state comes from the repo's recorded /api/state dump; the Git answers follow the shapes of
app/host_git.py and docs/redesign/tools/fixture_manager.py. No backend runs and nothing is contacted."""
import base64, copy, hashlib, json, re, sys, time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from playwright.sync_api import sync_playwright

import os
REPO = Path(os.environ.get('CLAB_REPO', str(Path.home() / 'projects' / 'clab-manager')))
UI = REPO / 'clab-backup-ui'
STATIC = UI / 'app' / 'static'
OUT = Path(__file__).resolve().parent / 'shots'
OUT.mkdir(exist_ok=True)
sys.path.insert(0, str(UI))
from app.textdiff import unified  # the project's own diff shape (pure Python)

VERSION = (UI / 'VERSION').read_text().strip()
NOW = datetime.now(timezone.utc)


def ago(seconds):
    return (NOW - timedelta(seconds=seconds)).isoformat()


# ---- state: the recorded dump, with times moved to "now" ------------------------------------
raw = (REPO / 'docs/netlab-ui-qa/acceptance/pass-5/preflight-api-state.json').read_text()
stamps = re.findall(r'20\d\d-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?\+00:00', raw)
newest = max(datetime.fromisoformat(s) for s in stamps)
shift = NOW - newest - timedelta(seconds=90)
raw = re.sub(r'20\d\d-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?\+00:00', lambda m: (datetime.fromisoformat(m.group(0)) + shift).isoformat(), raw)
STATE = json.loads(raw)
STATE['version'] = VERSION
LAB = next(l for l in STATE['labs'] if l['name'] == 'restore-square')
LAB_ID = LAB['id']
BINDING = LAB['git_binding']
REPO_DESC = BINDING['repository']
PREFIX = REPO_DESC['prefix']
TEMPLATE = next(j for j in STATE['git_jobs'] if j['status'] == 'synced' and j['target'] == 'latest')
NODES = [n for n in LAB['nodes'] if n['name'] in BINDING['node_names']]
SUFFIX = {'arista_ceos': ('cfg', 'eoscfg', 'eos-running-config'), 'cisco_xrv9k': ('cfg', 'xrcfg', 'iosxr-running-config')}
FILES = {'README.md': b'# Course labs\n'}

CEOS_A = """hostname ceos
!
vlan 10
   name USERS
!
management api gnmi
   transport grpc default
!
interface Ethernet1
   description to-cjunosevolved
   no switchport
   ip address 10.0.12.0/31
   ip ospf network point-to-point
   ip ospf area 0.0.0.0
!
interface Loopback0
   ip address 10.255.0.1/32
   ip ospf area 0.0.0.0
!
router ospf 1
   router-id 10.255.0.1
!
end
"""
CEOS_B = CEOS_A.replace('!\nmanagement api gnmi', '!\nvlan 777\n   name B-ONLY\n!\nmanagement api gnmi').replace(
    'description to-cjunosevolved', 'description eBGP to cjunosevolved').replace(
    'router ospf 1\n   router-id 10.255.0.1\n!', 'router ospf 1\n   router-id 10.255.0.1\n!\nrouter bgp 65001\n   router-id 10.255.0.1\n   neighbor 10.0.12.1 remote-as 65002\n   network 10.255.0.1/32\n!')
XR_A = """hostname xrv9k
interface Loopback0
 ipv4 address 10.255.0.4 255.255.255.255
!
interface GigabitEthernet0/0/0/0
 description to-vjunos-switch
 ipv4 address 10.0.34.1 255.255.255.254
!
router ospf 1
 area 0
  interface Loopback0
  interface GigabitEthernet0/0/0/0
   network point-to-point
!
end
"""
XR_B = XR_A.replace('router ospf 1', 'router bgp 65004\n bgp router-id 10.255.0.4\n address-family ipv4 unicast\n  network 10.255.0.4/32\n !\n neighbor 10.0.34.0\n  remote-as 65003\n  address-family ipv4 unicast\n !\n!\nrouter ospf 1')


def config(node, tag):
    short, platform = node['short_name'], node['platform']
    if platform == 'arista_ceos':
        return (CEOS_B if tag == 'new' else CEOS_A).encode()
    if platform == 'cisco_xrv9k':
        return (XR_B if tag == 'new' else XR_A).encode()
    return (f'set system host-name {short}\nset interfaces et-0/0/0 unit 0 family inet address 10.0.12.1/31\nset protocols ospf area 0.0.0.0 interface et-0/0/0.0 interface-type p2p\n').encode()


def write_snapshot(folder, tag, restore=True, nodes=None):
    entries = []
    for n in sorted(nodes or NODES, key=lambda n: n['name']):
        short, platform = n['short_name'], n['platform']
        suffix, rsuffix, rformat = SUFFIX.get(platform, ('cfg', 'jcfg', 'junos-hierarchical'))
        name, data = f'{short}.{suffix}', config(n, tag)
        FILES[f'{folder}/{name}'] = data
        entry = dict(path=name, size=len(data), sha256=hashlib.sha256(data).hexdigest(), node=n['name'], short_name=short, platform=platform,
                     format='junos-set' if platform.startswith('juniper') else rformat)
        if restore:
            rname, rdata = f'{short}.{rsuffix}', data if not platform.startswith('juniper') else f'system {{\n    host-name {short};\n}}\n'.encode()
            FILES[f'{folder}/{rname}'] = rdata
            entry.update(restore_artifact=rname, restore_size=len(rdata), restore_sha256=hashlib.sha256(rdata).hexdigest(), restore_format=rformat, restore_capable=True)
        entries.append(entry)
    manifest = dict(schema=2, lab_id=LAB_ID, lab_name=LAB['name'], backup_job_id='emulated', captured_at=ago(90), node_names=sorted(n['name'] for n in (nodes or NODES)),
                    excluded_nodes=[], restore_capable_nodes=sum(1 for e in entries if e.get('restore_artifact')), files=entries)
    FILES[f'{folder}/manifest.json'] = json.dumps(manifest, indent=1).encode()
    return manifest


def sha(text):
    return hashlib.sha1(text.encode()).hexdigest()


def build(scenario):
    """scenario: 'rest' (everything uploaded) or 'review' (the newest save waits for its review)."""
    FILES.clear(); FILES['README.md'] = b'# Course labs\n'
    latest = write_snapshot(f'{PREFIX}/latest', 'new' if scenario == 'review' else 'old')
    write_snapshot(f'{PREFIX}/baseline', 'old')
    write_snapshot(f'{PREFIX}/checkpoints/ospf-up', 'old')
    write_snapshot(f'{PREFIX}/checkpoints/loopbacks-reachable', 'old')
    write_snapshot('restore-square/Final', 'new')
    write_snapshot('restore-square/start/latest', 'old', restore=False)
    write_snapshot('restore-square/Broken/latest', 'old')
    write_snapshot('netlab-test/latest', 'old', nodes=NODES[:2])
    rows = [  # oldest first, like the stored list
        dict(target='baseline', note='Starting configuration from the lab guide', age=26 * 3600, path=f'{PREFIX}/baseline'),
        dict(target='checkpoint', checkpoint='loopbacks-reachable', note='Every loopback answers ping', age=5 * 3600, path=f'{PREFIX}/checkpoints/loopbacks-reachable'),
        dict(target='checkpoint', checkpoint='ospf-up', note='OSPF adjacencies up on every device', age=2 * 3600, path=f'{PREFIX}/checkpoints/ospf-up'),
        dict(target='latest', note='Point-to-point OSPF on all four links', age=47 * 60, path=f'{PREFIX}/latest'),
        dict(target='latest', note='Interface descriptions cleaned up', age=21 * 60, path=f'{PREFIX}/latest'),
    ]
    if scenario == 'review':
        rows.append(dict(target='latest', note='eBGP between ceos and cjunosevolved, xrv9k announces its loopback', age=40, path=f'{PREFIX}/latest', pending=True))
    jobs, commits = [], []
    for i, row in enumerate(rows):
        commit = sha(f'emulated-{i}-{row["note"]}')
        job = copy.deepcopy(TEMPLATE)
        job.update(id=sha('job' + str(i))[:32], created=ago(row['age']), finished=ago(row['age'] - 6), status='synced', message='Saved to Git.',
                   commit=commit, pushed=True, target=row['target'], checkpoint=row.get('checkpoint', ''), note=row['note'], snapshot_path=row['path'],
                   changed_files=[row['path'] + '/' + f for f in ('ceos.cfg', 'ceos.eoscfg', 'xrv9k.cfg', 'xrv9k.xrcfg', 'manifest.json')],
                   reviewed=ago(row['age'] - 4), review_before_push=True)
        job['destination'] = dict(repository='CLAB-MNGR-DEV-LLM', branch=REPO_DESC['branch'], path=row['path'], remote='github.com')
        if row.get('pending'):
            job.update(status='review_pending', pushed=False, message='Saved on the VM. Review the changes before uploading.')
            job.pop('reviewed', None)
        jobs.append(job)
        commits.insert(0, dict(commit=commit, time=int(time.time()) - row['age'], message=row['note']))
    state = copy.deepcopy(STATE)
    state['git_jobs'] = jobs + [j for j in STATE['git_jobs'] if j['lab_id'] != LAB_ID]
    head = commits[0]['commit']
    regs = [dict(REPO_DESC), dict(REPO_DESC, id='reg-netlab', label='CLAB-MNGR-DEV-LLM / netlab-test', prefix='netlab-test', revision='rev-netlab')]
    other = next((l for l in state['labs'] if l['name'] == 'netlab-test'), None)

    def versions():
        out = []
        for path in sorted(FILES):
            if not path.endswith('/manifest.json'):
                continue
            folder = path.rsplit('/', 1)[0]
            cp = PREFIX + '/checkpoints/'
            connected = folder in (PREFIX + '/latest', PREFIX + '/baseline') or (folder.startswith(cp) and '/' not in folder[len(cp):])
            out.append(dict(name=folder, path=folder, commit=head, connected=connected, label=version_label(folder)))
        out.sort(key=lambda v: (not v['connected'], v['path']))
        return out

    saved = dict(latest=int(time.time()) - rows[-1]['age'], baseline=int(time.time()) - 26 * 3600, checkpoints=int(time.time()) - 2 * 3600)
    return dict(state=state, jobs=list(reversed(jobs)), head=head, commits=commits, versions=versions(), regs=regs, latest=latest, saved=saved, other=other)


def version_label(path):
    parts = [p for p in str(path or '').split('/') if p]
    if not parts: return 'repository root'
    if parts[-1] in ('latest', 'baseline'): folder, state = '/'.join(parts[:-1]), parts[-1]
    elif len(parts) >= 2 and parts[-2] == 'checkpoints': folder, state = '/'.join(parts[:-2]), 'checkpoint · ' + parts[-1]
    else: return '/'.join(parts)
    return (folder + ' · ' + state) if folder else state


def snapshot(folder):
    manifest = json.loads(FILES[folder + '/manifest.json'])
    files = {}
    for e in manifest['files']:
        for key in ('path', 'restore_artifact'):
            if e.get(key): files[e[key]] = FILES[folder + '/' + e[key]].decode()
    return manifest, files


UNHANDLED = []


def make_handler(world):
    def api(route, request):
        url = request.url.split('/api', 1)[1].split('?')[0]
        method = request.method
        body = None
        if url == '/state': body = world['state']
        elif url == f'/labs/{LAB_ID}/git' and method == 'GET':
            body = dict(binding=BINDING, repository_status=dict(repository=REPO_DESC, head=world['head'], ready=True, problem='', baseline_revision='base-1', latest_manifest=world['latest']),
                        jobs=world['jobs'], supported_nodes=[{k: n.get(k, '') for k in ('name', 'short_name', 'platform')} for n in NODES],
                        unsupported_nodes=[n['name'] for n in LAB['nodes'] if n not in NODES])
        elif url == '/git/repositories': body = dict(protocol='clab-manager-git-v1', version=VERSION, repositories=world['regs'])
        elif url.endswith('/git/history'): body = dict(commits=world['commits'], versions=world['versions'])
        elif re.fullmatch(r'/git/repositories/[^/]+/tree', url):
            labs = {REPO_DESC['id']: dict(id=LAB_ID, name=LAB['name'])}
            if world['other']: labs['reg-netlab'] = dict(id=world['other']['id'], name=world['other']['name'])
            body = dict(repository=REPO_DESC, head=world['head'], files=[dict(path=p, size=len(b)) for p, b in sorted(FILES.items())], truncated=False, saved=world['saved'],
                        folders=[dict(id=r['id'], label=r['label'], prefix=r['prefix'], lab=labs.get(r['id'])) for r in world['regs']], planned=[])
        elif url.endswith('/git/compare'):
            files = []
            for name, before, after in (('ceos.cfg', CEOS_A, CEOS_B), ('ceos.eoscfg', CEOS_A, CEOS_B), ('xrv9k.cfg', XR_A, XR_B), ('xrv9k.xrcfg', XR_A, XR_B)):
                files.append(dict(name=name, status='changed', before=before, after=after, diff=unified(before, after), label=name.rsplit('.', 1)[0]))
            body = dict(files=files)
        elif url.endswith('/git/version'):
            data = json.loads(request.post_data or '{}')
            path = data.get('path', '')
            folder = path if path + '/manifest.json' in FILES else PREFIX + '/' + path
            manifest, files = snapshot(folder)
            nodes = [f.get('node', '') for f in manifest['files'] if f.get('restore_artifact')]
            body = dict(manifest=manifest, files=[dict(name=n, text=t) for n, t in files.items()], restore_supported=bool(nodes), restore_nodes=nodes)
        elif re.fullmatch(r'/git/jobs/[^/]+', url):
            body = next((j for j in world['jobs'] if j['id'] == url.rsplit('/', 1)[1]), None)
        elif url.endswith('/health'): body = dict(nodes=[])
        elif url == '/capture/status': body = dict(enabled=False, provider='disabled')
        if body is None:
            UNHANDLED.append(method + ' ' + url)
            return route.fulfill(status=404, content_type='application/json', body=json.dumps({'detail': 'Not emulated.'}))
        route.fulfill(status=200, content_type='application/json', body=json.dumps(body))

    def static(route, request):
        path = request.url.split('://', 1)[1].split('/', 1)[1].split('?')[0]
        if path == '': file = STATIC / 'index.html'
        elif path.startswith('static/'): file = STATIC / path[len('static/'):]
        else: return route.fulfill(status=404, body='')
        if not file.is_file(): return route.fulfill(status=404, body='')
        kind = {'.html': 'text/html', '.css': 'text/css', '.js': 'text/javascript', '.svg': 'image/svg+xml', '.json': 'application/json'}.get(file.suffix, 'application/octet-stream')
        route.fulfill(status=200, content_type=kind, body=file.read_bytes())

    def handler(route, request):
        if '/api/' in request.url: return api(route, request)
        return static(route, request)
    return handler


def open_progress(browser, world, width=1440, height=900):
    page = browser.new_page(viewport=dict(width=width, height=height))
    errors = []
    page.on('pageerror', lambda e: errors.append(str(e)))
    page.on('console', lambda m: errors.append(m.text) if m.type == 'error' and 'Failed to load resource' not in m.text else None)
    page.route('**/*', make_handler(world))
    page.goto(f'http://manager.local/#lab={LAB_ID}&view=progress')
    page.wait_for_selector('#git-saved-versions .git-version-row', timeout=15000)
    page.wait_for_timeout(600)
    return page, errors


def main():
    notes = {}
    with sync_playwright() as p:
        browser = p.chromium.launch()
        # 1. Progress tab at rest (full page)
        world = build('rest')
        page, errors = open_progress(browser, world)
        page.screenshot(path=str(OUT / 'now-01-progress.png'), full_page=True)
        notes['progress_height'] = page.evaluate('document.documentElement.scrollHeight')
        notes['controls'] = page.evaluate('''() => { const v = document.getElementById('progress-view'); const vis = e => !!(e.offsetWidth || e.offsetHeight);
          return { buttons: [...v.querySelectorAll('button')].filter(vis).length, links: [...v.querySelectorAll('a, summary')].filter(vis).length,
                   checkboxes: [...v.querySelectorAll('input[type=checkbox]')].filter(vis).length, cards: [...v.querySelectorAll('.card')].filter(vis).length,
                   applyButtons: [...v.querySelectorAll('button')].filter(b => vis(b) && /Apply to running lab/.test(b.textContent)).length }; }''')
        # 2. More menu open
        page.click('#progress-more-button'); page.wait_for_timeout(200)
        page.screenshot(path=str(OUT / 'now-02-more-menu.png'))
        page.keyboard.press('Escape')
        # 3. Save progress -> What changed?
        page.click('#progress-save'); page.wait_for_selector('#git-label-input'); page.wait_for_timeout(300)
        page.screenshot(path=str(OUT / 'now-03-what-changed.png'))
        notes['errors_rest'] = errors[:]
        page.close()
        # 4. Review before uploading (the newest save waits for its review)
        world = build('review')
        page, errors = open_progress(browser, world)
        page.screenshot(path=str(OUT / 'now-04-waiting-review.png'))
        page.evaluate('(id) => gitReviewJob(gitContexts.get(activeId).jobs.find(j => j.id === id))', world['jobs'][0]['id'])
        page.wait_for_timeout(900)
        page.screenshot(path=str(OUT / 'now-05-review-dialog.png'))
        page.keyboard.press('Escape'); page.wait_for_timeout(200)
        # 5. The save (job) window
        page.evaluate('(id) => gitShowJob(id)', world['jobs'][0]['id']); page.wait_for_timeout(700)
        page.screenshot(path=str(OUT / 'now-06-save-window.png'))
        notes['errors_review'] = errors[:]
        page.close(); browser.close()
    notes['unhandled'] = sorted(set(UNHANDLED))
    print(json.dumps(notes, indent=1))


if __name__ == '__main__':
    main()
