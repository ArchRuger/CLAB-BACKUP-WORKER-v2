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

from app.discovery import reconcile, stamp  # noqa: E402
from app.main import create_app  # noqa: E402
from app.runner import now  # noqa: E402

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
                for n in current['nodes']:
                    n.update(status='succeeded', message='Fixture result', captured_at=now())
                store.save()
        threading.Timer(6, finish).start()
        return copy.deepcopy(job)
    runner.submit = fake_submit
    runner._real_submit = real_submit

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
