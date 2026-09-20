#!/usr/bin/env python3
"""Fixture manager: the real application with seeded labs and no VM, for browser validation.

Runs ``create_app`` on a scratch data directory, seeds labs in several states through the same API the
UI uses, replaces the three VM-facing hooks (discovery refresh, device login probes, job execution)
with scripted answers, and serves the UI on 127.0.0.1. Nothing here reaches a VM or a device; the
manager's own code paths for state, readiness words, jobs and the map are the real ones.

    clab-backup-ui/.venv/bin/python docs/redesign/tools/fixture_manager.py [--port 8090] [--data DIR]

Labs after seeding:
  BGP_TheoryToPractice  linked, Running, the tests' map fixture (13 devices); most devices Ready,
                        PE1 Starting, GTW-2 Needs attention (login failed), Backup-Worker without
                        credentials; one finished backup and one automatic login check.
  ospf-basics           linked, Not deployed (Stopped), no map imported, a failed deploy operation.
  vlan-lab              linked, Partially running (one container exited).
  switching-basics      not linked (imported from an Ansible inventory), one device without login.
The VM also reports a lab that is not in My labs (extra-lab) and one hidden earlier (old-lab).
"""
import argparse
import copy
import os
import shutil
import sys
import threading
import time
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
APP_ROOT = HERE.parents[2] / 'clab-backup-ui'
sys.path.insert(0, str(APP_ROOT))
os.environ.setdefault('TELEMETRY_COLLECTOR', 'disabled')
os.environ.setdefault('TELEMETRY_STACK', 'disabled')
os.environ.setdefault('CAPTURE_PROVIDER', 'disabled')

from fastapi.testclient import TestClient  # noqa: E402

from app import __version__  # noqa: E402
from app import git_progress as gp  # noqa: E402
from app.discovery import reconcile, stamp  # noqa: E402
from app.downloads import FORMATS, component, short_name  # noqa: E402
from app.git_progress import PROTOCOL, digest, host_identity  # noqa: E402
from app.inventory import PLATFORMS  # noqa: E402
from app.main import create_app  # noqa: E402
from app.runner import filename, now  # noqa: E402

import base64  # noqa: E402
import hashlib  # noqa: E402
import json  # noqa: E402
from datetime import datetime, timedelta, timezone  # noqa: E402

CONFIG_TEXT = {
    'juniper_cjunosevolved': 'set system host-name {name}\nset interfaces et-0/0/0 unit 0 family inet address 10.0.0.1/30\n',
    'juniper_vjunosswitch': 'set system host-name {name}\nset interfaces ge-0/0/0 unit 0 family ethernet-switching\n',
    'juniper_vqfx': 'set system host-name {name}\n',
    'cisco_xrv9k': 'hostname {name}\ninterface GigabitEthernet0/0/0/0\n ipv4 address 10.0.0.2 255.255.255.252\n!\n',
    'arista_ceos': 'hostname {name}\ninterface Ethernet1\n   no switchport\n   ip address 10.0.0.3/30\n',
}
JCFG_TEXT = 'system {{\n    host-name {name};\n    root-authentication {{ encrypted-password "$6$fixture"; }}\n}}\n'


def ago(seconds):
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds)).isoformat()


def config_text(node, tag):
    label = component(short_name(node, ''))
    return (CONFIG_TEXT.get(node['platform'], 'hostname {name}\n').format(name=label) + f'! saved as {tag}\n').encode()


class FakeGit:
    """The VM Git helper, answered from memory: one checkout with this lab's saves, an instructor's
    solution folder, a starting-state folder without restore artifacts and a free lab folder."""

    def __init__(self, lab):
        self.lab = lab
        self.head = hashlib.sha1(b'fixture-head-0').hexdigest()
        self.commits = []
        checkout = '/home/clabllm/labs/Course-Labs'
        base = dict(owner='clabllm', path=checkout, remote='origin', push_url='https://github.com/example/Course-Labs.git', branch='main')
        self.registrations = [dict(base, id='reg-work', label='Course-Labs / labs/BGP/work', prefix='labs/BGP/work', revision='rev-work'),
                              dict(base, id='reg-vlan', label='Course-Labs / labs/VLAN', prefix='labs/VLAN', revision='rev-vlan')]
        self.files = {'README.md': b'# Course labs\n'}
        stamp_now = int(time.time())
        self.saved = {'latest': stamp_now - 1200, 'baseline': stamp_now - 86400, 'checkpoints': stamp_now - 7200}
        nodes = [n for n in lab['nodes'] if n.get('platform') in PLATFORMS]
        junos = [n for n in nodes if str(n['platform']).startswith('juniper')]
        self.write_snapshot('labs/BGP/work/latest', nodes, 'latest')
        self.write_snapshot('labs/BGP/work/checkpoints/ospf-done', nodes, 'ospf-done')
        self.write_snapshot('labs/BGP/work/baseline', nodes, 'baseline')
        self.write_snapshot('labs/BGP/solution/latest', junos, 'solution')
        self.write_snapshot('labs/BGP/start/latest', nodes, 'start', restore=False)
        for message in ('Set baseline', "Checkpoint 'ospf-done'", 'Save BGP_TheoryToPractice progress'):
            self.commit(message)

    def write_snapshot(self, folder, nodes, tag, restore=True, lab=None):
        lab = lab or self.lab
        entries = []
        for n in sorted(nodes, key=lambda n: n['name']):
            label, platform = component(short_name(n, lab['name'])), n['platform']
            name = f"{label}.{PLATFORMS[platform]['suffix']}"
            raw = config_text(n, tag)
            self.files[folder + '/' + name] = raw
            entry = dict(path=name, size=len(raw), sha256=hashlib.sha256(raw).hexdigest(), node=n['name'], short_name=n.get('short_name', ''),
                         platform=platform, format=FORMATS[platform])
            if restore and 'restore_suffix' in PLATFORMS[platform]:
                rname, rraw = f"{label}.{PLATFORMS[platform]['restore_suffix']}", JCFG_TEXT.format(name=label).encode()
                self.files[folder + '/' + rname] = rraw
                entry.update(restore_artifact=rname, restore_size=len(rraw), restore_sha256=hashlib.sha256(rraw).hexdigest(),
                             restore_format=PLATFORMS[platform]['restore_format'], restore_capable=True)
            entries.append(entry)
        manifest = dict(schema=2, lab_id=lab['id'], lab_name=lab['name'], backup_job_id='fixture', captured_at=ago(1200),
                        node_names=sorted(n['name'] for n in nodes), excluded_nodes=[], restore_capable_nodes=sum(1 for e in entries if e.get('restore_artifact')), files=entries)
        self.files[folder + '/manifest.json'] = json.dumps(manifest, indent=1).encode()

    def commit(self, message):
        self.head = hashlib.sha1((self.head + message + str(len(self.commits))).encode()).hexdigest()
        self.commits.insert(0, dict(commit=self.head, time=int(time.time()) - 600 * len(self.commits), message=message))
        return self.head

    def registration(self, request):
        return next((r for r in self.registrations if r['id'] == request.get('binding_id')), self.registrations[0])

    def snapshot(self, folder):
        raw = self.files.get(folder + '/manifest.json')
        if not raw:
            raise ValueError('No saved version at this path.')
        manifest, files = json.loads(raw), {}
        for entry in manifest['files']:
            for key in ('path', 'restore_artifact'):
                if entry.get(key):
                    files[entry[key]] = base64.b64encode(self.files[folder + '/' + entry[key]]).decode('ascii')
        return {'snapshot': {'manifest': manifest, 'files': files}}

    def versions(self, reg):
        prefix, out = reg['prefix'], []
        for path in sorted(self.files):
            if not path.endswith('/manifest.json'):
                continue
            folder = path.rsplit('/', 1)[0]
            checkpoints = prefix + '/checkpoints/'
            connected = folder in (prefix + '/latest', prefix + '/baseline') or (folder.startswith(checkpoints) and '/' not in folder[len(checkpoints):])
            out.append(dict(name=folder, path=folder, commit=self.head, connected=connected))
        out.sort(key=lambda v: (not v['connected'], v['path']))
        return out

    def __call__(self, host, request, stopping=None):
        mode, reg = request.get('mode'), self.registration(request)
        if mode == 'list':
            return {'protocol': PROTOCOL, 'version': __version__, 'repositories': [dict(r) for r in self.registrations]}
        if mode == 'status':
            latest = self.files.get(reg['prefix'] + '/latest/manifest.json')
            return {'repository': dict(reg), 'head': self.head, 'ready': True, 'problem': '',
                    'baseline_revision': 'base-1' if (reg['prefix'] + '/baseline/manifest.json') in self.files else '',
                    'latest_manifest': json.loads(latest) if latest else None}
        if mode == 'browse':
            return {'repository': dict(reg), 'head': self.head, 'files': [dict(path=p, size=len(b)) for p, b in sorted(self.files.items())],
                    'truncated': False, 'saved': dict(self.saved), 'folders': [dict(id=r['id'], label=r['label'], prefix=r['prefix']) for r in self.registrations]}
        if mode == 'history':
            return {'commits': list(self.commits), 'versions': self.versions(reg)}
        if mode == 'read-version':
            return self.snapshot(str(request.get('path', '')).strip('/'))
        if mode == 'compare':
            return {'files': []}
        if mode == 'publish':
            snap, target = request.get('snapshot') or {}, request.get('target', 'latest')
            folder = reg['prefix'] + '/' + ('checkpoints/' + request['checkpoint'] if target == 'checkpoint' and request.get('checkpoint') else target)
            changed = []
            for name, b64 in (snap.get('files') or {}).items():
                self.files[folder + '/' + name] = base64.b64decode(b64)
                changed.append(folder + '/' + name)
            self.files[folder + '/manifest.json'] = json.dumps(snap.get('manifest', {}), indent=1).encode()
            changed.append(folder + '/manifest.json')
            self.saved[target if target in ('latest', 'baseline') else 'checkpoints'] = int(time.time())
            commit = self.commit(request.get('message') or 'Save progress')
            return {'status': 'committed', 'commit': commit, 'pushed': False, 'changed_files': changed, 'snapshot_path': folder}
        if mode == 'push':
            return {'status': 'synced', 'commit': self.head, 'pushed': True, 'synced_operations': [request.get('operation_id', '')], 'message': 'Saved to Git.'}
        if mode == 'register-prefix':
            prefix = request.get('prefix', '')
            existing = next((r for r in self.registrations if r['prefix'] == prefix and r['path'] == reg['path']), None)
            # Like app/host_git.py: lab folders of one checkout cannot overlap unless the source registration
            # is being retired, and a retire removes it (an empty folder the lab leaves is then known to nobody
            # but the manager's planned-folder list).
            retire = request.get('retire') is True
            if not existing:
                for other in self.registrations:
                    if other['path'] != reg['path'] or (other is reg and retire):
                        continue
                    if not prefix or not other['prefix'] or prefix.startswith(other['prefix'] + '/') or other['prefix'].startswith(prefix + '/'):
                        raise ValueError('Lab folders in one repository cannot overlap: ' + (other['prefix'] or 'the repository root') + ' is already a lab folder. Choose a folder beside it.')
            if retire and (not existing or existing is not reg):
                self.registrations.remove(reg)
            if existing:
                return dict(existing)
            new = dict(reg, id='reg-' + hashlib.sha1(prefix.encode()).hexdigest()[:8], label=f"Course-Labs / {prefix or 'top level'}", prefix=prefix,
                       revision='rev-' + hashlib.sha1(prefix.encode()).hexdigest()[:6])
            self.registrations.append(new)
            return dict(new)  # the helper answers with the registration itself (host_git.register_prefix)
        if mode == 'connect':
            url, prefix = str(request.get('url', '')), request.get('prefix', '')
            name = url.rstrip('/').split('/')[-1].removesuffix('.git') or 'repo'
            new = dict(id='reg-' + hashlib.sha1((url + prefix).encode()).hexdigest()[:8], label=f"{name} / {prefix or 'top level'}", owner='clabllm',
                       path=f'/home/clabllm/labs/{name}', remote='origin', push_url=url, branch='main', prefix=prefix, revision='rev-' + hashlib.sha1(url.encode()).hexdigest()[:6])
            self.registrations.append(new)
            return dict(new)
        if mode == 'move':
            return {'status': 'committed', 'commit': self.commit('Move saved folders'), 'pushed': False, 'changed_files': [],
                    'snapshot_path': (request.get('prefix') or reg['prefix']) + '/latest'}
        if mode == 'update':
            return {'status': 'updated', 'head': self.head, 'message': 'Updated from remote using fast-forward only.'}
        raise ValueError('Fixture Git helper: unsupported mode ' + str(mode))

FIXTURES = APP_ROOT / 'tests' / 'fixtures' / 'map'
OSPF_YAML = b"""name: ospf-basics
topology:
  nodes:
    r1:
      kind: arista_ceos
    r2:
      kind: arista_ceos
    r3:
      kind: cisco_xrv9k
  links:
    - endpoints: ["r1:eth1", "r2:eth1"]
    - endpoints: ["r2:eth2", "r3:Gi0/0/0/0"]
"""
VLAN_YAML = b"""name: vlan-lab
topology:
  nodes:
    sw1:
      kind: arista_ceos
    sw2:
      kind: arista_ceos
    host1:
      kind: linux
  links:
    - endpoints: ["sw1:eth1", "sw2:eth1"]
    - endpoints: ["sw2:eth2", "host1:eth1"]
"""
INVENTORY_YAML = b"""all:
  children:
    arista_ceos:
      hosts:
        clab-switching-basics-sw1:
          ansible_host: 192.0.2.11
          ansible_user: admin
          ansible_password: admin
        clab-switching-basics-sw2:
          ansible_host: 192.0.2.12
          ansible_user: admin
          ansible_password: admin
    cisco_xrv9k:
      hosts:
        clab-switching-basics-core:
          ansible_host: 192.0.2.13
"""


def build(data_dir, port):
    app = create_app(str(data_dir))
    store, monitor, discovery, runner, services = (app.state.store, app.state.readiness, app.state.discovery,
                                                   app.state.runner, app.state.node_services)
    client = TestClient(app)   # no lifespan: seeds through the routes before the threads start

    with store.lock:
        store.state['host'] = dict(address='192.0.2.1', port=22, username='clab-discovery', auth='password',
                                   password='fixture-not-a-secret', enabled=True, command_mode='helper',
                                   fingerprint='SHA256:fixture', revision='fixture')
        store.state['discovery'] = dict(ok=True, error='', checked_epoch=time.time(), checked_at=stamp(),
                                        last_success=stamp(), labs={}, file_import_supported=True,
                                        file_reader='helper', helper_version=store.state.get('version', ''))
        store.state['ignored_labs'] = ['old-lab']
        store.state.setdefault('operations', [])
        store.save()

    def register(yaml_bytes, filename, annotations=None):
        files = {'definition': (filename, yaml_bytes, 'text/yaml')}
        if annotations is not None:
            files['annotations'] = (filename + '.annotations.json', annotations, 'application/json')
        response = client.post('/api/lab-definitions', files=files)
        assert response.status_code == 200, response.text
        return response.json()

    def profile(lab_id, platform, label='Lab login'):
        response = client.post(f'/api/labs/{lab_id}/profiles', data={
            'label': f'{label} ({platform})', 'platform': platform, 'username': 'admin', 'password': 'admin',
            'auth': 'password', 'make_default': 'true'})
        assert response.status_code == 200, response.text

    bgp = register((FIXTURES / 'lab.yaml').read_bytes(), 'BGP_TheoryToPractice.clab.yaml',
                   (FIXTURES / 'annotations.json').read_bytes())
    ospf = register(OSPF_YAML, 'ospf-basics.clab.yaml')
    vlan = register(VLAN_YAML, 'vlan-lab.clab.yaml')
    for platform in ('arista_ceos', 'cisco_xrv9k', 'juniper_cjunosevolved'):
        profile(bgp['id'], platform)
        profile(vlan['id'], platform)
    profile(ospf['id'], 'arista_ceos')
    response = client.post('/api/inventory', data={'name': 'switching-basics'},
                           files={'inventory': ('ansible-inventory.yml', INVENTORY_YAML, 'text/yaml')})
    assert response.status_code == 200, response.text

    def rows(lab, exited=()):
        return [dict(name=n['name'], address=f'172.20.20.{10 + i}', state='exited' if n['name'].endswith(tuple(exited)) else 'running',
                     kind=n.get('kind', '')) for i, n in enumerate(lab['nodes'])]

    with store.lock:
        labs = {l['name']: l for l in store.state['labs']}
        ospf_lab = labs['ospf-basics']
        ospf_lab['drawing'] = None           # no map imported yet
        store.state['discovery']['labs'] = {
            'BGP_TheoryToPractice': rows(labs['BGP_TheoryToPractice']),
            'vlan-lab': rows(labs['vlan-lab'], exited=('-host1',)),
            'extra-lab': [dict(name='clab-extra-lab-r1', address='172.20.20.50', state='running', kind='ceos'),
                          dict(name='clab-extra-lab-r2', address='172.20.20.51', state='running', kind='ceos')],
        }
        reconcile(store.state)
        bgp_lab = labs['BGP_TheoryToPractice']
        bgp_id = bgp_lab['id']
        booting = next(n['name'] for n in bgp_lab['nodes'] if n['name'].endswith('-PE1'))
        failed = next(n['name'] for n in bgp_lab['nodes'] if n['name'].endswith('-GTW-2'))
        # A finished backup and the automatic login check that ran when every device answered.
        started = now()
        store.state['jobs'].insert(0, dict(
            id=uuid.uuid4().hex, lab_id=bgp_id, lab_name=bgp_lab['name'], operation='backup', source='manual',
            created=started, started=started, finished=started, status='partial',
            message='Configuration backup finished; one device could not be read.',
            nodes=[dict(name=n['name'], short_name=n.get('short_name') or n.get('definition_node'), platform=n.get('platform'),
                        status='failed' if n['name'] == failed else 'succeeded',
                        message='SSH login failed' if n['name'] == failed else 'Configuration saved', captured_at=started)
                   for n in bgp_lab['nodes'] if n.get('platform')]))
        store.state['jobs'].insert(0, dict(
            id=uuid.uuid4().hex, lab_id=bgp_id, lab_name=bgp_lab['name'], operation='test', source='automatic',
            created=started, started=started, finished=started, status='succeeded', message='Every device answered show version.',
            nodes=[dict(name=n['name'], short_name=n.get('short_name') or n.get('definition_node'), status='succeeded', message='show version answered')
                   for n in bgp_lab['nodes'] if n.get('platform')]))
        store.state['operations'].append(dict(
            id=uuid.uuid4().hex, lab_id=ospf_lab['id'], action='deploy', name='ospf-basics', path='/etc/containerlab/ospf-basics.clab.yaml',
            created=stamp(), finished=stamp(), status='failed', exit_code=1, options={},
            output='INFO containerlab deploy\nERROR image not found: ceos:4.35.0F\n', message='Host command returned an error'))
        store.save()

    # Login probes: scripted per device, the readiness monitor does the rest (words, gating, tests).
    answers = {booting: 'booting', failed: 'failed'}
    monitor.probe = lambda item, creds: answers.get(item['name'], 'reachable')
    with monitor.lock:
        monitor.refusals[(bgp_id, failed)] = 3     # the refusal is persistent, not an early-boot blip
    with services.lock:
        for lab in (bgp_lab, labs['vlan-lab']):
            for n in lab['nodes']:
                key = (lab['id'], n['name'])
                if n['name'] == booting:
                    services.checks[key] = dict(status='booting', message='SSH answered but the CLI is still starting.', at=now(), source='automatic')
                elif n['name'] == failed:
                    services.checks[key] = dict(status='failed', message='Authentication failed for admin.', at=now(), source='automatic')
                else:
                    services.checks[key] = dict(status='reachable', message='show version answered.', at=now(), source='automatic')

    # Git: the VM helper answered from memory; the lab is bound to labs/BGP/work with two saves.
    fake_git = FakeGit(bgp_lab)
    gp.remote_git = fake_git
    with store.lock:
        binding = dict(binding_id='reg-work', revision='rev-work', repository=dict(fake_git.registrations[0]),
                       host_identity=host_identity(store.state['host']), node_names=[n['name'] for n in bgp_lab['nodes'] if n.get('platform') in PLATFORMS],
                       review_before_push=False)
        bgp_lab['git_binding'] = binding
        jobs = store.state.setdefault('git_jobs', [])
        common = dict(lab_id=bgp_id, lab_name=bgp_lab['name'], backup_job_id='', pushed=True, review_before_push=False, binding_digest=digest(binding),
                      node_names=list(binding['node_names']), request={}, capture_context={})
        jobs.append(dict(common, id=uuid.uuid4().hex, created=ago(7200), finished=ago(7150), status='synced', message='Saved to Git.',
                         commit=fake_git.commits[1]['commit'], target='checkpoint', checkpoint='ospf-done', note='OSPF adjacencies up on every device',
                         changed_files=['labs/BGP/work/checkpoints/ospf-done/manifest.json'], snapshot_path='labs/BGP/work/checkpoints/ospf-done'))
        jobs.append(dict(common, id=uuid.uuid4().hex, created=ago(1200), finished=ago(1150), status='synced', message='Saved to Git.',
                         commit=fake_git.head, target='latest', checkpoint='', note='', changed_files=['labs/BGP/work/latest/manifest.json'], snapshot_path='labs/BGP/work/latest'))
        jobs.append(dict(id=uuid.uuid4().hex, lab_id=bgp_id, status='dismissed', created=ago(600), finished=ago(590), message='Repository updated from remote.', target='update'))
        junos = [n for n in bgp_lab['nodes'] if str(n.get('platform', '')).startswith('juniper')]
        backup_id = next(j['id'] for j in store.state['jobs'] if j['operation'] == 'backup')
        store.state.setdefault('restore_jobs', []).append(dict(
            id=uuid.uuid4().hex, lab_id=bgp_id, lab_name=bgp_lab['name'], created=ago(3000), finished=ago(2900), status='partial',
            message='Configuration applied on 1 of 2 nodes.', source={'type': 'folder', 'path': 'labs/BGP/solution/latest', 'captured_at': ago(9000)},
            confirm_minutes=5, pre_backup_job_id=backup_id, post_backup_job_id='', host_identity=host_identity(store.state['host']), request_id='fixture-restore',
            targets=[dict(name=junos[0]['name'], short_name=junos[0].get('short_name'), platform=junos[0]['platform'], status='verified', message='Applied and verified.'),
                     dict(name=junos[1]['name'], short_name=junos[1].get('short_name'), platform=junos[1]['platform'], status='rollback_expected',
                          message='Commit was armed but not confirmed; the node rolls back automatically.')]))
        vlan_lab = labs['vlan-lab']
        fake_git.write_snapshot('labs/VLAN/latest', [n for n in vlan_lab['nodes'] if n.get('platform') in PLATFORMS], 'vlan', lab=vlan_lab)
        vlan_binding = dict(binding_id='reg-vlan', revision='rev-vlan', repository=dict(fake_git.registrations[1]), host_identity=host_identity(store.state['host']),
                            node_names=[n['name'] for n in vlan_lab['nodes'] if n.get('platform') in PLATFORMS], review_before_push=False)
        vlan_lab['git_binding'] = vlan_binding
        jobs.append(dict(id=uuid.uuid4().hex, lab_id=vlan_lab['id'], lab_name=vlan_lab['name'], created=ago(4000), finished=ago(3950), status='synced', message='Saved to Git.',
                         backup_job_id='', commit=fake_git.head, pushed=True, target='latest', checkpoint='', note='', changed_files=['labs/VLAN/latest/manifest.json'],
                         snapshot_path='labs/VLAN/latest', review_before_push=False, binding_digest=digest(vlan_binding), node_names=list(vlan_binding['node_names']), request={}, capture_context={}))
        store.save()

    # Restore preflight: the live probe answers from the fixture instead of SSH. The first Junos device
    # already matches the saved state, the second differs by one line, the third does not answer.
    junos_names = [n['name'] for n in bgp_lab['nodes'] if str(n.get('platform', '')).startswith('juniper')]

    def fake_capture(node, creds):
        index = junos_names.index(node['name']) if node['name'] in junos_names else 0
        if index >= 2:
            raise ConnectionError('fixture: no device here')
        text = config_text(node, 'solution').decode()
        return text + ('set system services ssh\n' if index == 1 else '')
    app.state.restore._capture = fake_capture

    # Discovery: keep the seeded snapshot fresh instead of inspecting a VM.
    def fresh_refresh(wait=False):
        with store.lock:
            info = store.state.setdefault('discovery', {})
            info.update(ok=True, error='', checked_at=stamp(), checked_epoch=time.time(), last_success=stamp())
            reconcile(store.state)
            store.save()
        return discovery.public()
    discovery.refresh = fresh_refresh

    # Jobs: a backup or login check runs for a few seconds and succeeds, without Ansible.
    real_submit = runner.submit

    def fake_submit(lab_id, operation='backup', source='manual', node_names=None, progress_id=None, progress_context=None):
        with store.lock:
            lab = store.lab(lab_id)
            if not lab:
                raise ValueError('Lab not found')
            if any(j['status'] in ('queued', 'running') for j in store.state['jobs']):
                raise ValueError('A job is already running. Wait for it to finish.')
            nodes = [n for n in lab['nodes'] if (n['name'] in node_names if node_names is not None else n['enabled'])]
            job = dict(id=uuid.uuid4().hex, lab_id=lab_id, lab_name=lab['name'], operation=operation, source=source,
                       created=now(), started=now(), status='running', message='Connecting to the devices…',
                       nodes=[dict(name=n['name'], short_name=n.get('short_name') or n.get('definition_node'), platform=n.get('platform'), status='running') for n in nodes])
            store.state['jobs'].insert(0, job)
            store.save()

        def finish():
            with store.lock:
                current = next((j for j in store.state['jobs'] if j['id'] == job['id']), None)
                if not current:
                    return
                current.update(status='succeeded', finished=now(), message='Finished (fixture: no device was contacted).')
                folder = data_dir / 'backups' / lab_id / 'history' / job['id']
                folder.mkdir(parents=True, exist_ok=True)
                for n in current['nodes']:
                    n.update(status='succeeded', message='Fixture result', captured_at=now())
                    if operation != 'backup' or n.get('platform') not in PLATFORMS:
                        continue
                    name = filename(n)
                    (folder / name).write_bytes(config_text(n, 'backup ' + job['id'][:6]))
                    n['file'] = name
                    if 'restore_suffix' in PLATFORMS[n['platform']]:
                        rname = name.rsplit('.', 1)[0] + '.' + PLATFORMS[n['platform']]['restore_suffix']
                        (folder / rname).write_bytes(JCFG_TEXT.format(name=component(short_name(n, ''))).encode())
                        n['restore_file'] = rname
                store.save()
        threading.Timer(6, finish).start()
        return copy.deepcopy(job)
    runner.submit = fake_submit
    runner._real_submit = real_submit

    # Lab operations: the VM helper is answered in-process (capabilities, browse, read, preview, run) so the
    # review dialogs, the banner-first confirm flow, the output window and the topology browser can be
    # exercised in a browser. Nothing here touches a VM; a run only prints a few lines and succeeds.
    from app import lab_operations as lo
    EXAMPLE_YAML = 'name: srl-ceos\ntopology:\n  nodes:\n    srl:\n      kind: nokia_srlinux\n      image: ghcr.io/nokia/srlinux\n    ceos:\n      kind: arista_ceos\n      image: ceos:4.35.0F\n  links:\n    - endpoints: ["srl:e1-1", "ceos:eth1"]\n'
    vm_files = {}
    with store.lock:
        for lab in store.state['labs']:
            if lab.get('definition_yaml'):
                vm_files[f"/etc/containerlab/{lab['name']}/{lab['name']}.clab.yaml"] = lab['definition_yaml']
        vm_files['/etc/containerlab/examples/srl-ceos.clab.yaml'] = EXAMPLE_YAML
        for lab in store.state['labs']:
            if lab['name'] in ('BGP_TheoryToPractice', 'vlan-lab'):
                lab['vm_project_path'] = f"/etc/containerlab/{lab['name']}/{lab['name']}.clab.yaml"
        store.save()
    roots = ['/etc/containerlab', '/srv/containerlab-node-manager/projects']

    def ops_lab_rows(name):
        running = {d['name'] for d in discovery.public().get('discovered', []) if d.get('running')}
        with store.lock:
            lab = next((l for l in store.state['labs'] if (l.get('deployment_name') or l['name']) == name), None)
            if not lab or name not in running:
                return []
            return [dict(name=n['name'], container_id='f1x7ur3' + str(i), state='running', kind=n.get('platform') or 'linux',
                         image=(n.get('platform') or 'linux') + ':fixture', ipv4_address=n.get('address', '') + '/24',
                         lab_name=name, labPath=lab.get('vm_project_path', '')) for i, n in enumerate(lab['nodes'])]

    def ops_browse(path):
        if not path:
            return {'path': '', 'parent': '', 'entries': [{'name': r, 'path': r, 'directory': True} for r in roots]}
        path = path.rstrip('/')
        if path == '/srv/containerlab-node-manager/projects':
            names = sorted({f.split('/')[4] for f in vm_files if f.startswith(path + '/') and f.endswith('.clab.yml')})
            return {'path': path, 'parent': '', 'entries': [{'name': n, 'path': f'{path}/{n}', 'directory': True} for n in names]}
        if path == '/etc/containerlab':
            names = sorted({f.split('/')[3] for f in vm_files})
            return {'path': path, 'parent': '', 'entries': [{'name': n, 'path': f'/etc/containerlab/{n}', 'directory': True} for n in names]}
        entries = [{'name': f.rsplit('/', 1)[1], 'path': f, 'directory': False} for f in sorted(vm_files) if f.rsplit('/', 1)[0] == path and f.endswith(('.clab.yaml', '.clab.yml'))]
        if not entries and not any(f.startswith(path + '/') for f in vm_files):
            raise ValueError('The requested project directory no longer exists.')
        return {'path': path, 'parent': path.rsplit('/', 1)[0], 'entries': entries}

    def ops_read(path):
        if path not in vm_files:
            raise ValueError('The requested project directory no longer exists.')
        text = vm_files[path]
        return {'path': path, 'text': text, 'sha256': hashlib.sha256(text.encode()).hexdigest()}

    def ops_preview(req):
        action, options, name, path = req['action'], req.get('options') or {}, req.get('name', 'manager'), req.get('path', '')
        affected, argv, warnings, source_hash = [], [], [], ''
        if action == 'clone':
            raise ValueError('Repository downloads are disabled in host operations setup.')
        extra = {}
        if action == 'create':
            source_hash = 'new'
        elif action == 'publish':
            # The lab builder's first save, scripted after app/host_operations.py: the paths are derived
            # from the lab name, nothing existing is replaced, the same content again is a no-op.
            root = options.get('root')
            if root not in roots:
                raise ValueError('Choose one of the trusted lab folders for the new lab.')
            path = f'{root}/{name}/{name}.clab.yml'
            wanted = {path: options.get('text')}
            if options.get('annotations') is not None:
                wanted[path + '.annotations.json'] = options['annotations']
            present = {f: t for f, t in vm_files.items() if f.startswith(f'{root}/{name}/')}
            if present and present != wanted:
                raise ValueError(f'A lab folder with this name already exists on the VM: {root}/{name}. Choose another lab name.')
            if present:
                warnings.append('This lab is already saved on the VM with the same content; nothing will be written.')
            source_hash = 'new'
            extra = {'folder': f'{root}/{name}', 'files': sorted(f.rsplit('/', 1)[1] for f in wanted), 'folder_mode': 0o755}
        elif action == 'inspect-all':
            argv = ['/usr/bin/containerlab', 'inspect', '--all', '--format', 'json']
        else:
            source_hash = ops_read(path)['sha256']
            rows = ops_lab_rows(name)
            affected = [{'name': r['name'], 'id': r['container_id'], 'state': r['state']} for r in rows]
            if action == 'delete' and rows:
                raise ValueError('Destroy the deployment before deleting its source YAML.')
            if action == 'revise':
                if rows:
                    raise ValueError('This lab is deployed. Destroy it before saving topology changes.')
                opened = options.get('base') or {}
                side = vm_files.get(path + '.annotations.json')
                current = hashlib.sha256(side.encode()).hexdigest() if side is not None else ''
                if opened.get('yaml') != source_hash or (options.get('annotations') is not None and opened.get('annotations', '') != current):
                    raise ValueError('The topology changed on the VM after it was opened. Open it again before saving.')
                extra = {'annotations_hash': current}
            elif action != 'delete':
                argv = ['/usr/bin/containerlab', action, '-t', path, '--name', name]
                if action == 'inspect':
                    argv += ['--format', 'json']
                if options.get('cleanup'):
                    argv.append('--cleanup')
                if action in ('deploy', 'redeploy', 'apply'):
                    warnings.append('Runs this trusted topology with host privileges, including its configured hooks, mounts and image pulls.')
                if options.get('cleanup'):
                    warnings.append('Cleanup removes generated lab artifacts. Expected lab directory: ' + path.rsplit('/', 1)[0] + '/clab-' + name + '. Check any custom lab directory configured on the VM.')
        base = {'action': action, 'name': name, 'source_name': req.get('source_name', name), 'path': path, 'options': options,
                'source_hash': source_hash, 'affected': affected, 'argv': argv, 'steps': [], **extra}
        return {**base, 'digest': hashlib.sha256(json.dumps(base, sort_keys=True).encode()).hexdigest(), 'warnings': warnings}

    def ops_run(req, output):
        plan = ops_preview({k: v for k, v in req.items() if k not in ('mode', 'digest')})
        if req.get('digest') != plan['digest']:
            raise ValueError('The topology or deployment changed. Preview the operation again.')
        action, name = req['action'], req.get('name', 'manager')
        if action == 'create':
            vm_files[req['path']] = req['options']['text']
            output('INFO created ' + req['path'] + '\n')
            return {'exit_code': 0}
        if action in ('publish', 'revise'):
            options = req['options']; target = plan['path']
            if action == 'publish' and target in vm_files:
                output('This lab is already saved on the VM. Nothing was written.\n')
                return {'exit_code': 0, 'already_published': True}
            if options.get('annotations') is not None:
                vm_files[target + '.annotations.json'] = options['annotations']
            vm_files[target] = options['text']
            output(('Lab folder saved on the VM: ' + plan['folder'] if action == 'publish' else 'Topology saved on the VM. The previous version was kept.') + '\n')
            return {'exit_code': 0, 'published_path': target, **({'recovery_path': target.rsplit('/', 1)[0] + '/.clab-manager-history/' + target.rsplit('/', 1)[1] + '.fixture'} if action == 'revise' else {})}
        if action == 'delete':
            vm_files.pop(req['path'], None); vm_files.pop(req['path'] + '.annotations.json', None)
            output('INFO removed ' + req['path'] + '\n')
            return {'exit_code': 0, 'recovery_path': '/srv/containerlab-node-manager/recovery/' + name + '.clab.yaml'}
        if action in ('inspect', 'inspect-all'):
            groups = {name: ops_lab_rows(name)} if action == 'inspect' else {l['name']: ops_lab_rows(l['name']) for l in store.state['labs']}
            output(json.dumps({k: v for k, v in groups.items() if v}, indent=2) + '\n')
            return {'exit_code': 0}
        for line in ('INFO[0000] Containerlab (fixture) started', f'INFO[0001] {action} {name}', 'INFO[0003] done'):
            output(line + '\n')
            time.sleep(1.2)
        # What discovery would see next on a real VM: a deployed lab runs, a destroyed one is gone. Without
        # this a lab deployed here never counts as deployed, and "refused while deployed" cannot be shown.
        with store.lock:
            lab = next((l for l in store.state['labs'] if (l.get('deployment_name') or l['name']) == name), None)
            groups = store.state['discovery'].setdefault('labs', {})
            if action in ('deploy', 'redeploy', 'start') and lab:
                groups[name] = [dict(name=n['name'], address=f'172.20.21.{10 + i}', state='running', kind=n.get('kind', '')) for i, n in enumerate(lab['nodes'])]
            elif action == 'destroy':
                groups.pop(name, None)
            reconcile(store.state)
            store.save()
        return {'exit_code': 0}

    def fake_remote(host, request, output=None, stopping=None, timeout=None):
        mode = request.get('mode')
        if mode == 'capabilities':
            actions = {a: {'available': True, 'cleanup': a in ('deploy', 'redeploy', 'destroy')} for a in
                       ('deploy', 'redeploy', 'destroy', 'apply', 'start', 'stop', 'restart', 'save', 'inspect', 'inspect-all', 'create', 'delete', 'publish', 'revise')}
            actions['clone'] = {'available': False}
            return {'protocol': 'clab-manager-operations-v1', 'version': __version__, 'actions': actions, 'roots': roots, 'network': False}
        if mode == 'browse':
            return ops_browse(str(request.get('path', '')))
        if mode == 'read':
            return ops_read(str(request.get('path', '')))
        if mode == 'popular':
            raise ValueError('Enable --allow-downloads on the VM to browse the online popular-lab catalog.')
        if mode == 'preview':
            return ops_preview(request)
        if mode == 'run':
            return ops_run(request, output or (lambda chunk: None))
        raise ValueError('Unsupported helper mode: ' + str(mode))
    lo.remote = fake_remote

    print(f'fixture manager ready on http://127.0.0.1:{port}/  data={data_dir}', flush=True)
    for lab in store.state['labs']:
        print(f"  {lab['name']}: {lab['id']}", flush=True)
    return app


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--port', type=int, default=int(os.environ.get('FIXTURE_PORT', '8090')))
    parser.add_argument('--data', default=os.environ.get('FIXTURE_DATA', ''))
    parser.add_argument('--keep', action='store_true', help='reuse the data directory instead of starting fresh')
    args = parser.parse_args(argv)
    data_dir = Path(args.data) if args.data else Path(os.environ.get('TMPDIR', '/tmp')) / 'clab-fixture-manager'
    if not args.keep and data_dir.exists():
        shutil.rmtree(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    app = build(data_dir, args.port)
    import uvicorn
    uvicorn.run(app, host='127.0.0.1', port=args.port, log_level='warning')


if __name__ == '__main__':
    main()
