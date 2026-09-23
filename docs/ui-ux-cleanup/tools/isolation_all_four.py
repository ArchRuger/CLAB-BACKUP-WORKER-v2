#!/usr/bin/env python3
"""Live isolation proof for the parallel restore (E7): submit a REAL restore of all four
restore-square nodes, cut management to exactly one of them once its target reaches `applying`
(the same technique and `finally`-guarded iptables rule as
docs/multi-platform-restore/tools/failure_harness.py submit-cut), and record the full per-target
timeline for every node -- not just the blocked one -- to show the other three settle
independently while the blocked one is isolated.

Reuses (imports, never edits) docs/multi-platform-restore/tools/manager_restore.py and
failure_harness.py for the Manager client, the iptables block/unblock helpers and readback.

    clab-backup-ui/.venv/bin/python docs/ui-ux-cleanup/tools/isolation_all_four.py \\
        --victim xrv9k --commit SHA --path restore-square/qa-1-30-37/latest \\
        --saved /tmp/r37b-config-a-checkout --evidence docs/ui-ux-cleanup/evidence/r37b-failure-xrv9k.json
"""
import argparse
import json
import pathlib
import sys
import time
import uuid

TOOLS = pathlib.Path(__file__).resolve().parents[2] / 'multi-platform-restore' / 'tools'
sys.path.insert(0, str(TOOLS))
import manager_restore as mr  # noqa: E402
import failure_harness as fh  # noqa: E402

ALL_NODES = ['ceos', 'cjunosevolved', 'vjunos-switch', 'xrv9k']


def stamp():
    return fh.stamp()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--url', default='http://127.0.0.1:8081')
    ap.add_argument('--victim', required=True, choices=ALL_NODES)
    ap.add_argument('--commit', required=True)
    ap.add_argument('--path', required=True)
    ap.add_argument('--minutes', type=int, default=2)
    ap.add_argument('--saved', help='saved folder for readback.py --saved (independent whole-config comparison)')
    ap.add_argument('--evidence', required=True)
    args = ap.parse_args()

    manager = mr.Manager(args.url)
    version, lab = manager.lab()
    victim_name = fh.target_name(args.victim)
    names = [fh.target_name(n) for n in ALL_NODES]
    source = {'type': 'git', 'commit': args.commit, 'path': args.path}

    record = {'trigger': 'isolation_all_four (submit-cut technique, all nodes in one job)',
              'victim': args.victim, 'nodes': ALL_NODES, 'minutes': args.minutes,
              'manager_version': version, 'build': mr.build_identity(), 'started_utc': stamp(),
              'readback_before': {n: fh.device_readback(n, args.saved) for n in ALL_NODES}}

    body = {'request_id': uuid.uuid4().hex, 'source': source, 'node_names': names,
            'confirm_minutes': args.minutes, 'acknowledge': True}
    t0 = time.monotonic()
    code, job = manager.call('/labs/%s/restore' % lab['id'], body)
    record['submit'] = {'http': code, 'id': job.get('id')}
    if code != 200:
        record['submit_body'] = job
        json.dump(record, open(args.evidence, 'w'), indent=1)
        print('submit refused', code, job)
        return 1
    job_id = job['id']

    # Wait for the victim to reach 'applying' (mandatory backup already done for it).
    _, target = fh.poll_job(manager, job_id, victim_name, lambda j, t: t['status'] == 'applying', timeout=60, interval=0.02)
    record['victim_reached_applying'] = target is not None
    if target is None:
        record['note'] = 'Victim never reached applying within 60s; nothing was blocked.'
    else:
        record['victim_reached_applying_at_rel_s'] = time.monotonic() - t0
        ip = fh.NODES[args.victim]['ip']
        tight_deadline = time.monotonic() + 15
        blocked_at = None
        while time.monotonic() < tight_deadline and blocked_at is None:
            if fh.local_ports(ip):
                fh.block(ip)
                blocked_at = time.monotonic() - t0
        if blocked_at is None:
            fh.block(ip)
            record['note'] = 'Apply connection not observed within 15s; blocked late.'
        record['blocked_at_rel_s'] = blocked_at

    # Drain to completion, recording every target's status/stage changes (not just the victim's).
    timeline = []
    last = {}
    deadline = time.monotonic() + args.minutes * 60 + 90 + 60
    final_job = None
    while time.monotonic() < deadline:
        _, cur = fh.try_call(manager, '/restore/jobs/' + job_id, timeout=5)
        if not cur or 'targets' not in cur:
            time.sleep(0.5)
            continue
        view = {t['name']: (t.get('status'), t.get('stage')) for t in cur['targets']}
        if view != last:
            timeline.append({'t': round(time.monotonic() - t0, 2), 'utc': stamp(), 'job_status': cur.get('status'), 'targets': view})
            last = view
        settling = cur.get('status') == 'interrupted' and any(t.get('status') == 'interrupted' for t in cur['targets'])
        if cur.get('status') in mr.ENDED and not settling:
            final_job = cur
            break
        time.sleep(1)
    if final_job is None:
        _, final_job = fh.try_call(manager, '/restore/jobs/' + job_id, timeout=5)
    record['timeline'] = timeline
    record['final_job'] = final_job

    if target is not None:
        record['rule_present_before_unblock'] = fh.rule_present(fh.NODES[args.victim]['ip'])
        fh.unblock(fh.NODES[args.victim]['ip'])
        record['rule_present_after_unblock'] = fh.rule_present(fh.NODES[args.victim]['ip'])

    record['readback_after'] = {n: fh.device_readback(n, args.saved) for n in ALL_NODES}
    record['finished_utc'] = stamp()
    with open(args.evidence, 'w') as handle:
        json.dump(record, handle, indent=1)
        handle.write('\n')

    print('job status:', (final_job or {}).get('status'))
    for t in (final_job or {}).get('targets', []):
        print(' ', t['name'], t.get('status'), t.get('stage'))
    return 0


if __name__ == '__main__':
    sys.exit(main())
