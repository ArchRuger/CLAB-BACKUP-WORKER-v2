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

The Git save and load redesign adds (docs/git-redesign/tools/fixture/SCENARIOS.md describes every one): the scripted VM Git
helper `FakeGit` answers like the redesigned helper over six repositories, six more labs (restore-square, square-fresh,
edge-lab, shared-a, shared-b, solo-lab) with a four-device lab that is running and Ready, scripted devices the real restore
service loads, and a small control (GET /fixture/state, POST /fixture/switch, POST /fixture/action) to put the fixture into
a state while it runs. `--classic` seeds only the labs and the Course-Labs repository the first fixture had.
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
sys.path.insert(0, str(HERE.parents[1] / 'git-redesign' / 'tools' / 'fixture'))
os.environ.setdefault('CAPTURE_PROVIDER', 'disabled')

from fastapi.testclient import TestClient  # noqa: E402

from app import __version__  # noqa: E402
from app import git_progress as gp  # noqa: E402
from app.discovery import reconcile, stamp  # noqa: E402
from app.downloads import FORMATS, component, short_name  # noqa: E402
from app.git_progress import PROTOCOL, digest, host_identity  # noqa: E402
from app.host_git import colliding, collision_message  # noqa: E402
from app.inventory import PLATFORMS  # noqa: E402
from app.main import create_app  # noqa: E402
from app.runner import filename, now  # noqa: E402

import fixture_backups  # noqa: E402
import fixture_control  # noqa: E402
import fixture_devices  # noqa: E402
import fixture_scenarios  # noqa: E402
from fake_git import FakeGit  # noqa: E402,F401  (the scripted VM Git helper; other tools import the name from here)

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


def build(data_dir, port, classic=False):
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

    # The scripted VM Git helper, the scripted devices the real restore service loads, and the capture that reads them
    # (docs/git-redesign/tools/fixture/): one control for all three.
    control = fixture_control.Control()
    devices = fixture_devices.Devices(control)
    fake_git = FakeGit(control)
    gp.remote_git = fake_git
    run_sync = fixture_backups.install(app, data_dir, devices, control)
    fixture_devices.install(app, devices)
    seeder = fixture_scenarios.seed(app, client, store, data_dir, register, profile, devices, fake_git, control, run_sync, services, extra=not classic)

    # The restore job the first fixture seeded (one Junos node applied, one waiting for its rollback).
    with store.lock:
        jobs = store.state.setdefault('git_jobs', [])
        jobs.append(dict(id=uuid.uuid4().hex, lab_id=bgp_id, status='dismissed', created=ago(600), finished=ago(590), message='Repository updated from remote.', target='update'))
        junos = [n for n in bgp_lab['nodes'] if str(n.get('platform', '')).startswith('juniper')]
        backup_id = next(j['id'] for j in store.state['jobs'] if j['operation'] == 'backup' and j['lab_id'] == bgp_id and j.get('source') == 'manual')
        store.state.setdefault('restore_jobs', []).append(dict(
            id=uuid.uuid4().hex, lab_id=bgp_id, lab_name=bgp_lab['name'], created=ago(3000), finished=ago(2900), status='partial',
            message='Configuration applied on 1 of 2 nodes.', source={'type': 'folder', 'path': 'labs/BGP/solution/latest', 'captured_at': ago(9000)},
            confirm_minutes=5, pre_backup_job_id=backup_id, post_backup_job_id='', host_identity=host_identity(store.state['host']), request_id='fixture-restore',
            targets=[dict(name=junos[0]['name'], short_name=junos[0].get('short_name'), platform=junos[0]['platform'], status='verified', message='Applied and verified.'),
                     dict(name=junos[1]['name'], short_name=junos[1].get('short_name'), platform=junos[1]['platform'], status='rollback_expected',
                          message='Commit was armed but not confirmed; the node rolls back automatically.')]))
        store.save()

    # Discovery: keep the seeded snapshot fresh instead of inspecting a VM.
    def fresh_refresh(wait=False):
        with store.lock:
            info = store.state.setdefault('discovery', {})
            info.update(ok=True, error='', checked_at=stamp(), checked_epoch=time.time(), last_success=stamp())
            reconcile(store.state)
            store.save()
        return discovery.public()
    discovery.refresh = fresh_refresh

    # Jobs: a backup or login check runs for a few seconds and succeeds without Ansible: fixture_backups.install above.

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
            if lab['name'] in ('BGP_TheoryToPractice', 'vlan-lab') + fixture_scenarios.NEW_LABS:
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
        # The VM's images (read-only): a fixed list, and an answer per reference (ghcr.io images are "in a
        # registry", anything else unknown to the list is "not found"), like the helper's two image modes.
        FIXTURE_IMAGES = ['ceos:4.35.0F', 'ghcr.io/srl-labs/network-multitool:latest', 'n24l/cisco_xrv9k:24.3.1', 'ghcr.io/nokia/srlinux:24.10.1']
        if mode == 'images':
            return {'available': True, 'images': list(FIXTURE_IMAGES)}
        if mode == 'image-check':
            refs = (request.get('options') or {}).get('references') or []
            return {'available': True, 'images': [
                {'reference': r, 'local': True, 'registry': 'skipped', 'detail': ''} if r in FIXTURE_IMAGES else
                {'reference': r, 'local': False, 'registry': 'found' if r.startswith('ghcr.io/') else 'unreachable' if r.startswith('unreachable.example/') else 'not-found',
                 'detail': '' if r.startswith('ghcr.io/') else 'denied: requested access to the resource is denied'} for r in refs]}
        if mode == 'preview':
            return ops_preview(request)
        if mode == 'run':
            return ops_run(request, output or (lambda chunk: None))
        raise ValueError('Unsupported helper mode: ' + str(mode))
    lo.remote = fake_remote

    # The control: switches and one-time actions, mounted by the fixture only (see fixture_control.py).
    def lab_state(lab, state):
        if state not in ('running', 'stopped'):
            raise ValueError('state is running or stopped')
        with store.lock:
            found = next((l for l in store.state['labs'] if l['name'] == lab), None)
            if not found:
                raise ValueError('No such lab: ' + str(lab))
            rows = store.state['discovery'].setdefault('labs', {})
            key = found.get('deployment_name') or found['name']
            if state == 'stopped':
                rows.pop(key, None)
            else:
                rows[key] = [dict(name=n['name'], address=f'172.20.40.{10 + i}', state='running', kind=n.get('kind', '')) for i, n in enumerate(found['nodes'])]
            reconcile(store.state)
            store.save()
        return {'lab': lab, 'state': state}

    def hand_commit(repository, message='Edited by hand'):
        checkout = fake_git.checkouts.get(repository)
        if not checkout:
            raise ValueError('No such repository: ' + str(repository))
        with fake_git.lock:
            return {'commit': checkout.add_commit(message, {'by-hand.txt': ('edited on the VM at %s\n' % time.time()).encode()})}

    def reset():
        control.reset()
        devices.reset()
        return {'switches': {}, 'devices': 'reset'}

    def helper(request, repository=''):
        """A raw request to the scripted VM Git helper, as the manager would send it: `repository` is a registration id
        (binding id and revision are filled in). Returns the helper's answer, or {'error': sentence} where the helper refuses."""
        request = dict(request)
        if repository:
            reg = next((r for r in fake_git.registrations() if r['id'] == repository), None)
            if not reg:
                raise ValueError('No such registration: ' + repository)
            request.update(binding_id=reg['id'], revision=reg['revision'])
        try:
            return fake_git(None, request)
        except ValueError as exc:
            return {'error': str(exc)}

    def remote_readme(url):
        """Someone adds a README on GitHub: an empty repository reachable by address now has its branch."""
        return fake_git.add_readme(url)

    def prefer_repository(repository, lab='square-fresh'):
        """Make `repository` (a checkout name, `Archtop-Lab`) the one the manager offers `lab` first. The manager chooses the default of a
        first save as: the repository the lab used last, else the one any save used most recently, else the first by name. A save by another
        lab therefore moves the default; this puts it back (a finished `update` of the lab in that checkout, which the chip ignores)."""
        checkout = fake_git.checkouts.get(repository)
        if not checkout:
            raise ValueError('No such repository: ' + str(repository))
        with store.lock:
            found = next((l for l in store.state['labs'] if l['name'] == lab), None)
            if not found:
                raise ValueError('No such lab: ' + str(lab))
            stamp = now()
            store.state.setdefault('git_jobs', []).append(dict(
                id=uuid.uuid4().hex, lab_id=found['id'], status='dismissed', created=stamp, finished=stamp, target='update',
                message='Repository updated from remote.', destination=dict(checkout=checkout.path, repository=repository)))
            store.save()
        return {'lab': lab, 'repository': repository}

    actions = {'helper': helper, 'edit_device': devices.edit, 'device_config': devices.set_tag, 'lab_state': lab_state, 'hand_commit': hand_commit, 'reset': reset,
               'remote_readme': remote_readme, 'prefer_repository': prefer_repository}

    def describe():
        with store.lock:
            labs = {l['name']: l['id'] for l in store.state['labs']}
        return {'labs': labs, 'repositories': fake_git.describe()['repositories'], 'remote_only': fake_git.describe()['remote_only'],
                'devices': {n: dict(label=d.label, platform=d.platform, outcome=devices.outcome(d), lines=len(d.config.splitlines()), armed=bool(d.armed))
                            for n, d in sorted(devices.nodes.items())}}
    fixture_control.install(app, control, actions, describe)

    print(f'fixture manager ready on http://127.0.0.1:{port}/  data={data_dir}', flush=True)
    for lab in store.state['labs']:
        print(f"  {lab['name']}: {lab['id']}", flush=True)
    return app


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--port', type=int, default=int(os.environ.get('FIXTURE_PORT', '8090')))
    parser.add_argument('--data', default=os.environ.get('FIXTURE_DATA', ''))
    parser.add_argument('--keep', action='store_true', help='reuse the data directory instead of starting fresh')
    parser.add_argument('--classic', action='store_true', help='seed only the labs and the Course-Labs repository the first fixture had')
    args = parser.parse_args(argv)
    data_dir = Path(args.data) if args.data else Path(os.environ.get('TMPDIR', '/tmp')) / 'clab-fixture-manager'
    if not args.keep and data_dir.exists():
        shutil.rmtree(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    app = build(data_dir, args.port, classic=args.classic)
    import uvicorn
    uvicorn.run(app, host='127.0.0.1', port=args.port, log_level='warning')


if __name__ == '__main__':
    main()
