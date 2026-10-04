"""The fixture's capture: a backup job that reads the scripted device model instead of running Ansible.

It replaces `Runner.submit` (as the first fixture did) but now reads each device's current scripted configuration, so

* a Save with nothing changed since the last save is really `unchanged`,
* `edit_device` makes a Save report exactly the devices that changed,
* a load changes what the next capture reads, and the restore service's pre- and post-restore backups see it, and
* the topology and map travel with every capture through the real `Runner.embed_topology`.

`run_sync` runs one capture to the end at once; the scenarios use it to build saves through the manager's own snapshot code.
"""
import copy
import threading
import uuid

from app.inventory import PLATFORMS
from app.runner import filename, now
import hashlib

from app.downloads import short_name

import fixture_content as content


def install(app, data_dir, devices, control):
    store, runner = app.state.store, app.state.runner
    runner._real_submit = runner.submit

    def new_job(lab_id, operation, source, node_names, progress_id, progress_context):
        with store.lock:
            lab = store.lab(lab_id)
            if not lab:
                raise ValueError('Lab not found')
            if any(j['status'] in ('queued', 'running') for j in store.state['jobs']):
                raise ValueError('A job is already running. Wait for it to finish.')
            nodes = [n for n in lab['nodes'] if (n['name'] in node_names if node_names is not None else n['enabled'])]
            job = dict(id=uuid.uuid4().hex, lab_id=lab_id, lab_name=lab['name'], operation=operation, source=source,
                       created=now(), started=now(), status='running', message='Connecting to the devices…',
                       nodes=[dict(name=n['name'], short_name=n.get('short_name') or n.get('definition_node'), platform=n.get('platform'),
                                   status='running') for n in nodes])
            if progress_id:
                job.update(progress_id=progress_id, progress_context=copy.deepcopy(progress_context or {}))
            store.state['jobs'].insert(0, job)
            store.save()
            return job

    def complete(job_id):
        with store.lock:
            current = next((j for j in store.state['jobs'] if j['id'] == job_id), None)
            if not current:
                return
            lab = copy.deepcopy(store.lab(current['lab_id']) or {})
            operation = current['operation']
            folder = data_dir / 'backups' / current['lab_id'] / 'history' / job_id
            folder.mkdir(parents=True, exist_ok=True)
            done = 0
            for n in current['nodes']:
                stamp = now()
                node = next((x for x in lab.get('nodes', []) if x['name'] == n['name']), {'name': n['name'], 'platform': n.get('platform')})
                if operation != 'backup' or node.get('platform') not in PLATFORMS:
                    n.update(status='succeeded', message='Fixture result', captured_at=stamp)
                    done += 1
                    continue
                if devices.nodes.get(node['name']) is None:
                    devices.add_for(lab.get('name', ''), node['name'], node['platform'], short_name(node, lab.get('name', '')))
                try:
                    capture, candidate = devices.backup_files(node, job_id)
                except OSError as exc:
                    n.update(status='failed', message=str(exc), captured_at=stamp)
                    continue
                name = filename(node)
                (folder / name).write_bytes(capture.encode())
                n.update(status='succeeded', message='Configuration saved', captured_at=stamp, file=name, sha256=hashlib.sha256(capture.encode()).hexdigest())
                rname = name.rsplit('.', 1)[0] + '.' + PLATFORMS[node['platform']]['restore_suffix']
                (folder / rname).write_bytes(candidate.encode())
                n.update(restore_file=rname, restore_sha256=hashlib.sha256(candidate.encode()).hexdigest(),
                         restore_format=PLATFORMS[node['platform']].get('restore_format', ''))
                done += 1
            topology = None
            if operation == 'backup' and done:
                topology = runner.embed_topology(lab, data_dir / 'backups' / current['lab_id'], job_id, lambda *a, **k: None)
            status = 'succeeded' if done == len(current['nodes']) else 'partial' if done else 'failed'
            current.update(status=status, finished=now(), message='Finished (fixture: no device was contacted).' if status == 'succeeded' else
                           'Configuration backup finished; ' + ('one device could not be read.' if status == 'partial' else 'no device could be read.'),
                           **({'topology': topology} if topology else {}))
            store.save()

    def seconds(source):
        if source in ('restore-pre', 'restore-post'):
            return float(control.get('restore_capture_seconds') or 2)
        return float(control.get('capture_seconds') if control.get('capture_seconds') is not None else 6)

    def submit(lab_id, operation='backup', source='manual', node_names=None, progress_id=None, progress_context=None):
        job = new_job(lab_id, operation, source, node_names, progress_id, progress_context)
        threading.Timer(seconds(source), complete, args=(job['id'],)).start()
        return copy.deepcopy(job)

    def run_sync(lab_id, operation='backup', source='git-progress', node_names=None, progress_id=None, progress_context=None):
        job = new_job(lab_id, operation, source, node_names, progress_id, progress_context)
        complete(job['id'])
        with store.lock:
            return copy.deepcopy(next(j for j in store.state['jobs'] if j['id'] == job['id']))

    runner.submit = submit
    return run_sync
