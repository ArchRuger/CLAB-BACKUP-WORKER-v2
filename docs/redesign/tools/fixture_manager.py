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
    from app.lab_operations import LOCK_SENTENCE
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

    # C05 scripted VM state: per-container overrides of a node action ('exited' after Stop device, 'absent' after a
    # filtered destroy), the netem table, the pending-changes plan (set by the `pending_changes` action: none | changes |
    # failed) and how many scripted runs are in flight (the helper's host lock is held while one is).
    from app import host_operations as ho
    ops_state = {'device': {}, 'netem': {}, 'seeded': set(), 'plan': 'none', 'busy': 0}

    def ops_lab_rows(name):
        running = {d['name'] for d in discovery.public().get('discovered', []) if d.get('running')}
        with store.lock:
            lab = next((l for l in store.state['labs'] if (l.get('deployment_name') or l['name']) == name), None)
            if not lab or name not in running:
                return []
            return [dict(name=n['name'], container_id='f1x7ur3' + str(i), state=ops_state['device'].get(n['name'], 'running'), kind=n.get('platform') or 'linux',
                         image=(n.get('platform') or 'linux') + ':fixture', ipv4_address=n.get('address', '') + '/24',
                         lab_name=name, labPath=lab.get('vm_project_path', '')) for i, n in enumerate(lab['nodes'])
                    if ops_state['device'].get(n['name']) != 'absent']

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
        if path not in vm_files and path not in vm_extra:
            raise ValueError('The requested project directory no longer exists.')
        text = vm_files[path] if path in vm_files else vm_extra[path]
        return {'path': path, 'text': text, 'sha256': hashlib.sha256(text.encode()).hexdigest()}

    # C03 diagnostics (read-only helper modes `logs`, `interfaces`, `netem-show`, files-mode `browse`, `images` details),
    # scripted after app/host_operations.py. vm_extra holds the node folders a deployed lab writes beside its topology
    # (shown only by `browse` with the `files` option); a device exists while its lab runs.
    vm_extra = {}
    for _path, _text in list(vm_files.items()):
        if _path.endswith(('.clab.yaml', '.clab.yml')) and _path.startswith('/etc/containerlab/'):
            _lab = _path.split('/')[3]
            vm_extra[f'/etc/containerlab/{_lab}/{_lab}.clab.yaml.annotations.json'] = '{"nodeAnnotations": []}\n'
            with store.lock:
                _row = next((l for l in store.state['labs'] if l['name'] == _lab), None)
                _nodes = [n.get('short_name') or n.get('definition_node') or n['name'] for n in (_row or {}).get('nodes', [])]
            for _node in _nodes:
                vm_extra[f'/etc/containerlab/{_lab}/clab-{_lab}/{_node}/startup-config'] = (
                    f'hostname {_node}\nusername admin secret 0 not-a-real-secret\nsnmp-server community public ro\n!\ninterface Ethernet1\n   no shutdown\n')
    FIXTURE_DETAILS = [dict(reference=r, id='sha256:' + hashlib.sha256(r.encode()).hexdigest()[:12], size=sz, created=c) for r, sz, c in (
        ('ceos:4.35.0F', '2.4GB', '2026-08-14 10:21:07 +0000 UTC'), ('ghcr.io/srl-labs/network-multitool:latest', '189MB', '2026-09-02 08:00:00 +0000 UTC'),
        ('n24l/cisco_xrv9k:24.3.1', '5.9GB', '2026-05-20 16:40:12 +0000 UTC'), ('ghcr.io/nokia/srlinux:24.10.1', '2.2GB', '2026-07-01 12:05:44 +0000 UTC'))]
    boot = time.time() - 300

    def ops_files_browse(path):
        try:
            listing = ops_browse(path)
        except ValueError:
            if not any(f.startswith(path.rstrip('/') + '/') for f in vm_extra):
                raise
            listing = {'path': path.rstrip('/'), 'parent': path.rstrip('/').rsplit('/', 1)[0], 'entries': []}
        entries = []
        for e in listing['entries']:
            kind = 'directory' if e['directory'] else 'topology'
            entry = dict(e, kind=kind)
            if not e['directory']:
                entry['size'] = len(vm_files.get(e['path'], ''))
            entries.append(entry)
        folder = path.rstrip('/')
        children = {}
        for f in vm_extra:
            if f.startswith(folder + '/'):
                head = f[len(folder) + 1:].split('/')
                children.setdefault(head[0], len(head) == 1)
        for name, is_file in sorted(children.items(), key=lambda kv: (kv[1], kv[0])):
            full = f'{folder}/{name}'
            if any(e['name'] == name for e in entries):
                continue
            entries.append(dict(name=name, path=full, directory=not is_file, kind='file' if is_file else 'directory',
                                **({'size': len(vm_extra[full])} if is_file else {})))
        return dict(listing, entries=entries)

    def ops_device(request):
        """(facts, node row) for the requested container, or ({'present': False}, None) when the lab is not running."""
        options = request.get('options') or {}
        name = str(request.get('name', ''))
        with store.lock:
            lab = next((l for l in store.state['labs'] if l.get('deployment_name') == name), None)
            nodes = [dict(n) for n in (lab or {}).get('nodes', [])]
        node = next((n for n in nodes if n.get('definition_node') == options.get('node')), None)
        if not lab or not node or options.get('container') != f"{lab.get('container_prefix', 'clab')}-{name}-{node['definition_node']}":
            raise ValueError('This container does not belong to lab ' + name + '.')
        if not ops_lab_rows(name) or ops_state['device'].get(options['container']) == 'absent':
            return {'present': False}, node
        digest = hashlib.sha256(options['container'].encode()).hexdigest()
        return {'present': True, 'id': digest, 'pid': 4000 + len(options['container']), 'status': ops_state['device'].get(options['container'], 'running'), 'health': 'healthy',
                'started': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(boot)), 'kind': node.get('platform') or 'linux',
                'ports': [{'container': '22/tcp', 'host': '2201'}]}, node

    def ops_logs(request):
        facts, node = ops_device(request)
        if not facts['present']:
            return {'facts': facts, 'text': '', 'truncated': False}
        options = request['options']
        stamp = lambda i: time.strftime('%Y-%m-%dT%H:%M:%S', time.gmtime(boot + i)) + '.%09dZ' % (i * 1000003 % 10 ** 9)
        body = ['Starting containerlab node ' + options['node'], '\x1b[32mINFO\x1b[0m  management interface eth0 is up',
                'PASSWORD=fixture-not-a-secret', '\x1b[1;31mWARN\x1b[0m  slow disk\r', 'login: admin', 'System ready']
        lines = [stamp(i) + ' ' + text for i, text in enumerate(body)]
        # A follow keeps appending one line per second so a second poll has something new after its `since`.
        lines += [stamp(len(body) + i) + ' heartbeat %d' % i for i in range(int(time.time() - boot) % 600 + 1)]
        since = options.get('since')
        if since:
            lines = [l for l in lines if l.split(' ', 1)[0] > since]
        lines = lines[-int(options.get('tail', 200)):]
        return {'facts': facts, 'text': '\n'.join(lines) + ('\n' if lines else ''), 'truncated': False}

    def ops_interfaces(request):
        facts, node = ops_device(request)
        if not facts['present']:
            return {'facts': facts, 'interfaces': []}
        rows = [dict(name=n, alias='', state='up', mac='aa:c1:ab:00:%02x:%02x' % (len(request['options']['container']) % 256, i), type='veth',
                     mtu=1500, ifindex=20 + i) for i, n in enumerate(('eth0', 'eth1'))]
        ticks = int(time.time() - boot)
        counters = {r['name']: dict(rx_bytes=1000 * ticks + 7 * i, rx_packets=10 * ticks, rx_errors=0, rx_dropped=0,
                                    tx_bytes=1200 * ticks + 5 * i, tx_packets=11 * ticks, tx_errors=0, tx_dropped=0) for i, r in enumerate(rows)}
        return {'facts': facts, 'interfaces': rows, 'counters': counters, 'sampled_at': time.time()}

    def netem_rows(container):
        # The first read of a container shows the one impairment the fixture always had (eth1); set and reset change the table.
        if container not in ops_state['seeded']:
            ops_state['seeded'].add(container)
            ops_state['netem'].setdefault((container, 'eth1'), dict(delay='15ms', jitter='2ms', loss=5.0))
        return [dict(interface=i, **row) for (c, i), row in sorted(ops_state['netem'].items()) if c == container]

    def ops_netem(request):
        facts, node = ops_device(request)
        running = facts['present'] and facts['status'] == 'running'
        return {'facts': facts, 'impairments': netem_rows(request['options']['container']) if running else []}

    def go_duration(ms):
        # containerlab prints a Go duration back: 60s reads 1m0s, 1500ms reads 1.5s.
        if ms == 0:
            return '0s'
        if ms < 1000:
            return '%dms' % ms
        minutes, rest = int(ms // 60000), (ms % 60000) / 1000
        return (('%dm' % minutes) if minutes else '') + ('%g' % rest) + 's'

    def ops_netem_all(request):
        pairs = (request.get('options') or {}).get('nodes')
        if not isinstance(pairs, list) or not 1 <= len(pairs) <= ho.NODE_FILTER_LIMIT:
            raise ValueError('Name 1 to %d devices.' % ho.NODE_FILTER_LIMIT)
        devices = []
        for pair in pairs:
            answer = ops_netem({'name': request.get('name'), 'options': pair})
            devices.append({'node': pair['node'], 'container': pair['container'], 'present': answer['facts']['present'], 'impairments': answer['impairments']})
        return {'devices': devices, 'complete': True}

    def ops_netem_change(request):
        """netem-set and netem-reset as the helper answers them: the host lock, the request digest, the container id the drawer showed."""
        reset = request['mode'] == 'netem-reset'
        if ops_state['busy'] or (stopped_at['t'] is not None and time.monotonic() - stopped_at['t'] < LOCK_WINDOW):
            raise ValueError(LOCK_SENTENCE)
        options = request.get('options') or {}
        if set(options) != set(ho.IMPAIRMENT_RESET_KEYS if reset else ho.IMPAIRMENT_SET_KEYS):
            raise ValueError('Unsupported impairment options.')
        if request.get('digest') != ho.digest({k: request.get(k) for k in ('mode', 'name', 'options', 'expected_id')}):
            raise ValueError('Review the impairment again.')
        facts, node = ops_device({'name': request.get('name'), 'options': {k: options[k] for k in ('node', 'container')}})
        if not facts['present'] or facts['status'] != 'running':
            raise ValueError('Device %s is not running; impairments exist only on a running device.' % options['container'])
        if request.get('expected_id') != facts['id']:
            raise ValueError(ho.CHANGED_SENTENCE)
        interface = options['interface']
        if interface == 'eth0':
            raise ValueError('The management interface eth0 cannot be impaired: the manager reaches the device through it.')
        if interface == 'lo' or not ho.IMPAIRMENT_INTERFACE.fullmatch(str(interface)):
            raise ValueError('lo cannot be impaired.' if interface == 'lo' else 'Choose an interface by its literal name.')
        key = (options['container'], interface)
        netem_rows(options['container'])
        if reset:
            changed = ops_state['netem'].pop(key, None) is not None
            return {'facts': facts, 'changed': changed, 'impairments': netem_rows(options['container'])}
        ho.impairment_values(options)
        ops_state['netem'][key] = dict(delay=go_duration(ho.duration_ms(options['delay'])), jitter=go_duration(ho.duration_ms(options['jitter'])),
                                       loss=float(options['loss']), rate=options['rate'], corruption=float(options['corruption']))
        return {'facts': facts, 'impairments': netem_rows(options['container'])}

    def ops_plan():
        # What a dry run would plan. `none` is a lab that matches its file; `changes` and `failed` are put there by the
        # `pending_changes` action. (The design called it a control switch; the shared switch table is not this file's.)
        if ops_state['plan'] == 'failed':
            return None, 'error', 'Failed to read topology file: yaml: line 3: did not find expected key'
        plan = dict(deploys_lab=False, added=[], removed=[], recreated=[], started=[], restarted=[], links_added=[], endpoints_removed=[], reasons={})
        if ops_state['plan'] == 'changes':
            plan.update(added=['r3'], recreated=['r2'], links_added=['r2:eth1 -- r3:eth1'], reasons={'r2': 'config drift: Env'})
        return plan, '', ''

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
            elif action in ho.NODE_ACTIONS:
                # Restart, Start and Stop device as the helper plans them: one literal node bound to one deployed container.
                if set(options) != {'node', 'container'}:
                    raise ValueError('Unsupported operation options.')
                command = action[:-5]
                targets = [r for r in rows if r['name'] == options['container']]
                if len(targets) != 1:
                    raise ValueError('Device ' + str(options['container']) + ' is not deployed in lab ' + name + '. Refresh the lab list and review again.')
                state = targets[0]['state']
                if action == 'stop-node' and state != 'running':
                    raise ValueError('Device ' + options['container'] + ' is ' + state + '; there is nothing to stop.')
                if action == 'start-node' and state == 'running':
                    raise ValueError('Device ' + options['container'] + ' is already running.')
                affected = [{'name': targets[0]['name'], 'id': targets[0]['container_id'], 'state': state}]
                argv = ['/usr/bin/containerlab', command, '-t', path, '--name', name, '--node', options['node']]
                extra = {'node': options['node'], 'container': options['container']}
            elif action != 'delete':
                argv = ['/usr/bin/containerlab', action, '-t', path, '--name', name]
                if action == 'inspect':
                    argv += ['--format', 'json']
                for key, allowed in ho.OPTION_ACTIONS.items():
                    if key in options and action not in allowed:
                        raise ValueError('Unsupported operation options.')
                nodes = options.get('nodes')
                if nodes is not None:
                    if not isinstance(nodes, list) or not 1 <= len(nodes) <= ho.NODE_FILTER_LIMIT or len(set(map(str, nodes))) != len(nodes):
                        raise ValueError('Choose devices by their literal topology node names.')
                    if action == 'deploy' and rows:
                        raise ValueError('This lab is already deployed, so a deploy limited to chosen devices is not possible (containerlab would remove the devices left out). Use Apply topology changes to add the missing devices.')
                    if options.get('cleanup'):
                        raise ValueError('Clean up cannot be combined with chosen devices: containerlab would delete the whole lab folder, which the devices left running still use.')
                    if action in ('destroy', 'save'):
                        chosen = []
                        for node in nodes:
                            matched = [r for r in rows if ho.container_matches(r['name'], name, node)]
                            if len(matched) != 1:
                                raise ValueError('Device ' + str(node) + ' is not deployed in lab ' + name + '. Refresh the lab list and review again.')
                            chosen.append(matched[0])
                        affected = [{'name': r['name'], 'id': r['container_id'], 'state': r['state']} for r in chosen]
                        extra = {'kept': [r['name'] for r in rows if r not in chosen]}
                    argv += ['--node-filter', ','.join(nodes)]
                if 'max_workers' in options:
                    if type(options['max_workers']) is not int or not 1 <= options['max_workers'] <= ho.MAX_WORKERS_LIMIT:
                        raise ValueError('Max workers must be a whole number from 1 to 64.')
                    argv += ['--max-workers', str(options['max_workers'])]
                for flag in ('skip_post_deploy', 'cleanup', 'graceful', 'keep_mgmt_net'):
                    if options.get(flag):
                        argv.append('--' + flag.replace('_', '-'))
                if action == 'apply':
                    plan, failed, error = ops_plan()
                    extra = {'plan': plan, 'plan_failed': failed}
                    if failed == 'error':
                        warnings.append('containerlab could not plan this change: ' + error)
                if action in ('deploy', 'redeploy', 'apply'):
                    warnings.append('Runs this trusted topology with host privileges, including its configured hooks, mounts and image pulls.')
                if options.get('cleanup'):
                    warnings.append('Cleanup removes generated lab artifacts. Expected lab directory: ' + path.rsplit('/', 1)[0] + '/clab-' + name + '. Check any custom lab directory configured on the VM.')
        base = {'action': action, 'name': name, 'source_name': req.get('source_name', name), 'path': path, 'options': options,
                'source_hash': source_hash, 'affected': affected, 'argv': argv, 'steps': [], **extra}
        return {**base, 'digest': hashlib.sha256(json.dumps(base, sort_keys=True).encode()).hexdigest(), 'warnings': warnings}

    # When a scripted run was last stopped: the helper's lock is held for a moment after that, as on a real VM while the command ends.
    stopped_at = {'t': None}
    LOCK_WINDOW = 3.0

    def ops_run(req, output, stopping=None):
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
        def stop_if_asked():
            if stopping is not None and stopping.is_set():
                stopped_at['t'] = time.monotonic()
                raise lo.OperationStopped('Operation stopped. Inspect the lab before retrying.')
        for line in ('INFO[0000] Containerlab (fixture) started', f'INFO[0001] {action} {name}', 'INFO[0003] done'):
            stop_if_asked()
            output(line + '\n')
            end = time.monotonic() + 1.2
            while time.monotonic() < end:   # between the lines, so a stop is seen within a moment
                stop_if_asked()
                time.sleep(0.05)
        stop_if_asked()
        # What discovery would see next on a real VM: a deployed lab runs, a destroyed one is gone. Without
        # this a lab deployed here never counts as deployed, and "refused while deployed" cannot be shown.
        with store.lock:
            lab = next((l for l in store.state['labs'] if (l.get('deployment_name') or l['name']) == name), None)
            groups = store.state['discovery'].setdefault('labs', {})
            chosen_nodes = (req.get('options') or {}).get('nodes')
            if lab and action in ('deploy', 'redeploy', 'start', 'destroy') and not chosen_nodes:
                for n in lab['nodes']:
                    ops_state['device'].pop(n['name'], None)
                    for key in [k for k in ops_state['netem'] if k[0] == n['name']]:
                        ops_state['netem'].pop(key)   # a recreated device has no impairments
            if action in ho.NODE_ACTIONS and lab:
                container = req['options']['container']
                new_state = 'exited' if action == 'stop-node' else 'running'
                ops_state['device'][container] = new_state
                if new_state == 'running':
                    ops_state['device'].pop(container, None)
                for row in groups.get(name, []):
                    if row['name'] == container:
                        row['state'] = new_state
            elif action == 'destroy' and chosen_nodes and lab:
                gone = {r['name'] for r in ops_lab_rows(name) if any(ho.container_matches(r['name'], name, n) for n in chosen_nodes)}
                for container in gone:
                    ops_state['device'][container] = 'absent'
                groups[name] = [r for r in groups.get(name, []) if r['name'] not in gone]
                if not groups[name]:
                    groups.pop(name)
            elif action == 'deploy' and chosen_nodes and lab:
                groups[name] = [dict(name=n['name'], address=f'172.20.21.{10 + i}', state='running', kind=n.get('kind', ''))
                                for i, n in enumerate(lab['nodes']) if any(ho.container_matches(n['name'], name, c) for c in chosen_nodes)]
            elif action in ('deploy', 'redeploy', 'start') and lab:
                groups[name] = [dict(name=n['name'], address=f'172.20.21.{10 + i}', state='running', kind=n.get('kind', '')) for i, n in enumerate(lab['nodes'])]
            elif action == 'destroy':
                groups.pop(name, None)
            reconcile(store.state)
            store.save()
        return {'exit_code': 0}

    def fake_remote(host, request, output=None, stopping=None, timeout=None):
        mode = request.get('mode')
        if mode == 'capabilities':
            actions = {a: {'available': True, 'cleanup': a in ('deploy', 'redeploy', 'destroy'), 'graceful': a in ('redeploy', 'destroy', 'stop', 'restart'),
                           'node_filter': a in ('deploy', 'destroy', 'save'), 'max_workers': a in ('deploy', 'redeploy', 'destroy'),
                           'skip_post_deploy': a in ('deploy', 'redeploy'), 'keep_mgmt_net': a in ('redeploy', 'destroy'), 'dry_run': a in ('deploy', 'apply')} for a in
                       ('deploy', 'redeploy', 'destroy', 'apply', 'start', 'stop', 'restart', 'save', 'inspect', 'inspect-all', 'create', 'delete', 'publish', 'revise')}
            actions['clone'] = {'available': False}
            for a in ho.NODE_ACTIONS:
                actions[a] = {'available': True}
            actions['impairments'] = {'available': True}
            return {'protocol': 'clab-manager-operations-v1', 'version': __version__, 'actions': actions, 'roots': roots, 'network': False,
                    'diagnostics': True, 'lifecycle_options': True, 'containerlab': '0.79.0'}
        if mode == 'browse':
            if (request.get('options') or {}).get('files'):
                return ops_files_browse(str(request.get('path', '')))
            return ops_browse(str(request.get('path', '')))
        if mode == 'logs':
            return ops_logs(request)
        if mode == 'interfaces':
            return ops_interfaces(request)
        if mode == 'netem-show':
            return ops_netem(request)
        if mode == 'netem-show-all':
            return ops_netem_all(request)
        if mode in ('netem-set', 'netem-reset'):
            return ops_netem_change(request)
        if mode == 'apply-plan':
            plan, failed, error = ops_plan()
            return {'plan': plan, 'failed': failed, 'error': error}
        if mode == 'read':
            return ops_read(str(request.get('path', '')))
        if mode == 'popular':
            raise ValueError('Enable --allow-downloads on the VM to browse the online popular-lab catalog.')
        # The VM's images (read-only): a fixed list, and an answer per reference (ghcr.io images are "in a
        # registry", anything else unknown to the list is "not found"), like the helper's two image modes.
        FIXTURE_IMAGES = ['ceos:4.35.0F', 'ghcr.io/srl-labs/network-multitool:latest', 'n24l/cisco_xrv9k:24.3.1', 'ghcr.io/nokia/srlinux:24.10.1']
        if mode == 'images':
            return {'available': True, 'images': list(FIXTURE_IMAGES), 'details': [dict(d) for d in FIXTURE_DETAILS]}
        if mode == 'image-check':
            refs = (request.get('options') or {}).get('references') or []
            return {'available': True, 'images': [
                {'reference': r, 'local': True, 'registry': 'skipped', 'detail': ''} if r in FIXTURE_IMAGES else
                {'reference': r, 'local': False, 'registry': 'found' if r.startswith('ghcr.io/') else 'unreachable' if r.startswith('unreachable.example/') else 'not-found',
                 'detail': '' if r.startswith('ghcr.io/') else 'denied: requested access to the resource is denied'} for r in refs]}
        if mode == 'preview':
            # The manager's follow-up probe after a stop: the helper answers with its lock sentence while the command still ends.
            if stopped_at['t'] is not None and time.monotonic() - stopped_at['t'] < LOCK_WINDOW:
                raise ValueError(LOCK_SENTENCE)
            return ops_preview(request)
        if mode == 'run':
            ops_state['busy'] += 1   # the helper's host lock is held for the whole run
            try:
                return ops_run(request, output or (lambda chunk: None), stopping)
            finally:
                ops_state['busy'] -= 1
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

    def pending_changes(plan='changes'):
        """What the pending-changes check and an apply review find: none (the lab matches its file), changes (r3 to create, r2 recreated) or failed (an error line)."""
        if plan not in ('none', 'changes', 'failed'):
            raise ValueError('plan is none, changes or failed')
        ops_state['plan'] = plan
        for lab in list(store.state['labs']):
            app.state.operations.forget_plan(lab['id'])
        return {'plan': plan}

    def reset():
        control.reset()
        devices.reset()
        ops_state['plan'] = 'none'
        ops_state['device'].clear(); ops_state['netem'].clear(); ops_state['seeded'].clear()
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
               'remote_readme': remote_readme, 'prefer_repository': prefer_repository, 'pending_changes': pending_changes}

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
