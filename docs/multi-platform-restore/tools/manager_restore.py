#!/usr/bin/env python3
"""Drive one *Replace running configuration* through the running manager's real API and keep the evidence.

What the browser does, without the browser: POST the preflight, POST the restore with the
acknowledgement, poll the job until it ends. The status timeline (with wall-clock times), the
preflight rows and the final public job are written as one JSON evidence file. The public job
holds no configuration text or secrets (that is the API's contract), so the file can be committed.

    manager_restore.py --backup JOB_ID --nodes ceos vjunos-switch --evidence FILE [--minutes 5]
    manager_restore.py --folder labs/x/latest ...      (repository folder source)
    manager_restore.py --commit SHA --path labs/x/latest ...   (saved Git version source)
    manager_restore.py --backup-now                     (just run a normal backup and print its id)

Stdlib only; the manager is addressed at --url (default http://127.0.0.1:8081) with its own Origin.
"""
import argparse
import json
import sys
import time
import urllib.error
import urllib.request
import uuid

LAB = 'restore-square'
ENDED = ('succeeded', 'partial', 'needs_attention', 'failed', 'preflight_failed', 'interrupted')


class Manager:
    def __init__(self, url):
        self.url = url.rstrip('/')

    def call(self, path, body=None, timeout=300):
        request = urllib.request.Request(self.url + '/api' + path, method='POST' if body is not None else 'GET',
                                         data=json.dumps(body).encode() if body is not None else None,
                                         headers={'Origin': self.url, 'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read() or b'{}')

    def lab(self):
        _, state = self.call('/state')
        lab = next(l for l in state['labs'] if l['name'] == LAB)
        return state['version'], lab

    def backup(self, lab_id):
        _, job = self.call(f'/labs/{lab_id}/jobs', {'operation': 'backup'})
        while True:
            _, state = self.call('/state')
            current = next(j for j in state['jobs'] if j['id'] == job['id'])
            if current['status'] not in ('queued', 'running'):
                return current
            time.sleep(2)


def stamp():
    return time.strftime('%H:%M:%S', time.gmtime())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--url', default='http://127.0.0.1:8081')
    parser.add_argument('--backup'); parser.add_argument('--folder'); parser.add_argument('--commit'); parser.add_argument('--path')
    parser.add_argument('--backup-now', action='store_true')
    parser.add_argument('--nodes', nargs='*', default=[])
    parser.add_argument('--minutes', type=int, default=5)
    parser.add_argument('--evidence')
    parser.add_argument('--preflight-only', action='store_true')
    args = parser.parse_args()
    manager = Manager(args.url)
    version, lab = manager.lab()
    if args.backup_now:
        job = manager.backup(lab['id'])
        print(json.dumps({'id': job['id'], 'status': job['status'], 'nodes': [
            {k: n.get(k) for k in ('name', 'status', 'file', 'restore_file', 'restore_format')} for n in job['nodes']]}, indent=1))
        return 0 if job['status'] == 'succeeded' else 1
    source = ({'type': 'backup', 'backup_job_id': args.backup} if args.backup else
              {'type': 'folder', 'path': args.folder} if args.folder else
              {'type': 'git', 'commit': args.commit, 'path': args.path})
    names = ['clab-%s-%s' % (LAB, n) for n in args.nodes]
    record = {'manager_version': version, 'lab': LAB, 'source': source, 'requested': names, 'started_utc': stamp()}
    code, preflight = manager.call(f'/labs/{lab["id"]}/restore/preflight', {'source': source, 'node_names': names or None})
    record['preflight'] = {'http': code, 'body': preflight}
    print('preflight', code, [(t['name'].split(LAB + '-')[-1], t['eligible'], t.get('pending_changes'), t.get('reason'))
                              for t in preflight.get('targets', [])] or preflight)
    if not args.preflight_only and code == 200:
        body = {'request_id': uuid.uuid4().hex, 'source': source, 'node_names': names,
                'confirm_minutes': args.minutes, 'acknowledge': True}
        code, job = manager.call(f'/labs/{lab["id"]}/restore', body)
        record['submit'] = {'http': code, 'body': job if code != 200 else {'id': job['id']}}
        if code == 200:
            # The same request again must return the same job (idempotent request_id), never a second restore.
            again_code, again = manager.call(f'/labs/{lab["id"]}/restore', body)
            record['double_submit'] = {'http': again_code, 'same_job': again.get('id') == job['id']}
            timeline, last = [], None
            while True:
                _, job = manager.call('/restore/jobs/' + job['id'])
                view = (job['status'], tuple((t['name'].split(LAB + '-')[-1], t['status']) for t in job['targets']))
                if view != last:
                    timeline.append({'utc': stamp(), 'job': view[0], 'targets': dict(view[1])})
                    print(stamp(), view[0], dict(view[1]))
                    last = view
                if job['status'] in ENDED:
                    break
                time.sleep(1)
            record.update(timeline=timeline, job=job)
        else:
            print('submit refused', code, job)
    record['finished_utc'] = stamp()
    if args.evidence:
        with open(args.evidence, 'w') as handle:
            json.dump(record, handle, indent=1)
            handle.write('\n')
    job = record.get('job') or {}
    return 0 if job.get('status') == 'succeeded' or args.preflight_only else 1


if __name__ == '__main__':
    sys.exit(main())
