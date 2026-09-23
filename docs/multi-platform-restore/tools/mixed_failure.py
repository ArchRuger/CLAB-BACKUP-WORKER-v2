#!/usr/bin/env python3
"""A mixed four-platform restore with ONE controlled failure, through the running manager.

All four nodes are drifted to B and selected. Nodes are changed side by side (RESTORE_NODE_WORKERS, default 4),
so "the node applied last" no longer exists: the trigger is the victim target's own `stage` in the job. As soon
as xrv9k's stage is `backing_up` or `backed_up` (the manager's submit-time look at the device is over, and its
driver has not connected yet), somebody else's timed change is armed on it (a small `commit confirmed` from an
ordinary CLI session). The expected, honest outcome: the other three nodes are replaced and verified, xrv9k is
refused by its driver ("not changed": a pending change that is not the manager's is never touched), the job is
`partial`, management stays usable everywhere, the foreign change is left alone and rolls back by itself, and a
later restore of that node alone succeeds. Nothing is atomic across nodes, and the evidence shows exactly that.

The run is valid only when the foreign change was armed before the manager's driver connected to xrv9k
(`timeline.connecting` of that target, on the manager's clock, which is this VM's clock); otherwise the race was
lost, the evidence says so (`armed_before_victim_connected: false`) and the run proves nothing about the refusal.
The evidence also records whether the other nodes overlapped (their `[connecting, settled]` intervals).

    clab-backup-ui/.venv/bin/python docs/multi-platform-restore/tools/mixed_failure.py --evidence FILE [--saved DIR]
"""
import argparse
import json
import pathlib
import subprocess
import sys
import threading
import time
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[3]
TOOLS = pathlib.Path(__file__).resolve().parent
PYTHON = str(ROOT / 'clab-backup-ui/.venv/bin/python')
sys.path.insert(0, str(TOOLS))
NODES = ['ceos', 'cjunosevolved', 'vjunos-switch', 'xrv9k']
VICTIM = 'xrv9k'
FOREIGN = ['configure', 'interface Loopback778', 'description foreign pending change', 'root', 'commit confirmed 120']
# The other user then stays in their session, as a person would. (Leaving it asks "You are exiting after a 'commit
# confirm' with an active rollback session ... Do you wish to exit? [no]:" and, answered yes, rolls back at once.)
BASE = 'http://127.0.0.1:8081'


def state():
    return json.load(urllib.request.urlopen(BASE + '/api/state', timeout=30))


def restore_job(job_id):
    return json.load(urllib.request.urlopen(BASE + '/api/restore/jobs/' + job_id, timeout=30))


def victim_target(job):
    return next((t for t in (job or {}).get('targets', []) if t['name'].split('square-')[-1] == VICTIM), {})


def nodecli(node, *lines, tag='mixed'):
    return subprocess.run([PYTHON, str(TOOLS / 'nodecli.py'), node, '--tag', tag, '--timeout', '240', *lines], capture_output=True, text=True).stdout


def main():
    from manager_restore import build_identity, readback
    parser = argparse.ArgumentParser()
    parser.add_argument('--evidence', required=True)
    parser.add_argument('--folder', default='restore-square/work/latest')
    parser.add_argument('--saved')
    args = parser.parse_args()
    record = {'build': build_identity(), 'victim': VICTIM, 'steps': []}
    note = lambda text, **more: (print(time.strftime('%H:%M:%S', time.gmtime()), text, more or '', flush=True),
                                 record['steps'].append({'utc': time.strftime('%H:%M:%S', time.gmtime()), 'step': text, **more}))
    for node in NODES:
        subprocess.run([PYTHON, str(TOOLS / 'nodecli.py'), node, '--tag', 'drift-b', '--timeout', '240', '--file',
                        str(ROOT / 'docs/multi-platform-restore/lab/drift' / f'{node}-B.cli')], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    record['device_readback_before'] = readback(NODES)
    note('all four drifted', active={k: v.get('active') for k, v in record['device_readback_before']['nodes'].items()})
    known = {j['id'] for j in state()['restore_jobs']}
    restore_file = args.evidence + '.restore.json'
    runner = threading.Thread(target=lambda: subprocess.run([sys.executable, str(TOOLS / 'manager_restore.py'), '--folder', args.folder, '--nodes', *NODES,
                                                             '--evidence', restore_file], capture_output=True, text=True), daemon=True)
    runner.start()
    job_id, stage = None, ''
    deadline = time.time() + 300
    while time.time() < deadline and not job_id:        # the job this run started
        job_id = next((j['id'] for j in state()['restore_jobs'] if j['id'] not in known), None)
        time.sleep(0.2)
    while job_id and time.time() < deadline:            # ... until the victim is past the submit check, before its change
        stage = victim_target(restore_job(job_id)).get('stage', '')
        if stage in ('backing_up', 'backed_up', 'connecting', 'failed', 'skipped', 'uncertain'):
            break
        time.sleep(0.2)
    note('victim reached stage ' + repr(stage) + '; arming a foreign timed change on it', job=job_id)
    from nodecli import Session
    other_user = Session(VICTIM, 60)
    for line in FOREIGN:
        other_user.run(line)
    armed_at = time.time()
    note('foreign `commit confirmed 120` armed on ' + VICTIM + '; that session stays open and never confirms')
    runner.join(timeout=1500)
    restore = json.load(open(restore_file))
    pathlib.Path(restore_file).unlink()
    final = restore.get('job') or {}
    if not final:   # the request never became a job: keep what the manager answered, and stop
        record['refused'] = {'preflight': [(r.get('name'), r.get('eligible'), r.get('reason')) for r in restore.get('preflight', {}).get('body', {}).get('targets', [])],
                             'submit': restore.get('submit')}
        other_user.close()
        pathlib.Path(args.evidence).write_text(json.dumps(record, indent=1) + '\n')
        print('the manager refused the request:', json.dumps(record['refused'])[:900])
        return 1
    record['restore'] = {'source': restore.get('source'), 'timeline': restore.get('timeline'), 'job_status': final.get('status'), 'job_message': final.get('message'),
                         'targets': [{k: t.get(k) for k in ('name', 'platform', 'status', 'message', 'no_op', 'missing_statements', 'extra_statements', 'persistence')}
                                     for t in final.get('targets', [])]}
    record['job_id'] = final.get('id')
    record['stages'] = {t['name'].split('square-')[-1]: {'stage': t.get('stage'), 'timeline': t.get('timeline'), 'worker': t.get('worker')}
                        for t in final.get('targets', [])}
    connected = (victim_target(final).get('timeline') or {}).get('connecting')
    record['foreign_armed_at'] = armed_at
    others = [record['stages'][n]['timeline'] or {} for n in NODES if n != VICTIM and n in record['stages']]
    spans = [(t['connecting'], t['settled']) for t in others if 'connecting' in t and 'settled' in t]
    record['others_overlapped'] = bool(len(spans) > 1 and max(s for s, _ in spans) < min(e for _, e in spans))
    note('job ended', status=final.get('status'), targets={t['name'].split('square-')[-1]: t['status'] for t in final.get('targets', [])})
    record['device_readback_after_job'] = readback(NODES, args.saved)
    note('devices after the job', active={k: (v.get('active'), v.get('pending_confirmation')) for k, v in record['device_readback_after_job']['nodes'].items()})
    time.sleep(max(0, 150 - (time.time() - armed_at)))  # the foreign change's own 120 s window, untouched by the manager
    other_user.close()
    record['device_readback_after_foreign_window'] = readback([VICTIM])
    victim = record['device_readback_after_foreign_window']['nodes'][VICTIM]
    note('after the foreign window', victim_active=victim.get('active'), pending=victim.get('pending_confirmation'))
    recovery_file = args.evidence + '.recovery.json'
    subprocess.run([sys.executable, str(TOOLS / 'manager_restore.py'), '--folder', args.folder, '--nodes', VICTIM, '--readback',
                    *(['--saved', args.saved] if args.saved else []), '--evidence', recovery_file], capture_output=True, text=True)
    recovery = json.load(open(recovery_file))
    pathlib.Path(recovery_file).unlink()
    target = ((recovery.get('job') or {}).get('targets') or [{}])[0]
    record['recovery'] = {'job_status': (recovery.get('job') or {}).get('status'), 'target_status': target.get('status'), 'no_op': target.get('no_op'),
                          'device_readback_after': recovery.get('device_readback_after')}
    note('recovery restore of the failed node alone', status=record['recovery']['job_status'], target=target.get('status'))
    statuses = {t['name'].split('square-')[-1]: t['status'] for t in final.get('targets', [])}
    after = record['device_readback_after_job']['nodes']
    record['summary'] = {
        # Precondition: the foreign change was on the device before the manager's driver connected to it.
        'armed_before_victim_connected': connected is None or armed_at < connected,
        'three_replaced_and_verified': all(statuses.get(n) == 'verified' for n in NODES if n != VICTIM),
        'victim_failed_not_changed': statuses.get(VICTIM) == 'failed',
        'job_partial': final.get('status') == 'partial',
        'devices_agree': all(after[n].get('active') == 'A' for n in NODES if n != VICTIM) and after[VICTIM].get('active') != 'A',
        'foreign_change_left_alone_and_rolled_back_by_itself': victim.get('active') == 'B' and victim.get('pending_confirmation') is False,
        'recovery_verified': target.get('status') == 'verified'}
    record['ok'] = all(record['summary'].values())
    pathlib.Path(args.evidence).write_text(json.dumps(record, indent=1) + '\n')
    print(json.dumps(record['summary'], indent=1))
    return 0 if record['ok'] else 1


if __name__ == '__main__':
    sys.exit(main())
