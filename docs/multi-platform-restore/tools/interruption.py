#!/usr/bin/env python3
"""Measure what a restore interrupts: 0.2 s pings on management and data paths around one manager restore.

Probes run from the VM (management address of the node) and from the Linux side of the cEOS container,
whose kernel carries the routed interfaces and the OSPF routes (data plane: a directly connected
neighbour and a remote loopback). The node is drifted to B first, then restored to A through the
running manager's API (tools/manager_restore.py), so the restore really changes configuration.
The result (lost probes, longest gap, when it fell relative to the job's phases) is written as JSON.

    python3 docs/multi-platform-restore/tools/interruption.py ceos --backup JOB --evidence FILE

Stdlib only, but it starts nodecli.py with the application's virtual environment for the drift.
"""
import argparse
import json
import pathlib
import re
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[3]
TOOLS = pathlib.Path(__file__).resolve().parent
PYTHON = str(ROOT / 'clab-backup-ui/.venv/bin/python')
MGMT = {'ceos': '172.20.20.101', 'cjunosevolved': '172.20.20.102', 'vjunos-switch': '172.20.20.103', 'xrv9k': '172.20.20.104'}
CEOS = 'clab-restore-square-ceos'
# (label, where the ping runs, target): what each restored node's data plane is judged by.
DATA = {
    'ceos': [('ceos eth1 -> cjunosevolved 10.0.12.1', CEOS, '10.0.12.1'), ('ceos -> vjunos-switch loopback', CEOS, '10.255.0.3')],
    'cjunosevolved': [('ceos -> cjunosevolved et-0/0/0 10.0.12.1', CEOS, '10.0.12.1'), ('ceos -> cjunosevolved loopback', CEOS, '10.255.0.2')],
    'vjunos-switch': [('ceos -> vjunos-switch loopback (two routed hops)', CEOS, '10.255.0.3')],
    'xrv9k': [('ceos eth2 -> xrv9k 10.0.41.0', CEOS, '10.0.41.0'), ('ceos -> xrv9k loopback', CEOS, '10.255.0.4')],
}


def start(where, target):
    command = ['ping', '-D', '-n', '-i', '0.2', '-W', '1', target]
    if where:
        command = ['docker', 'exec', where] + command
    return subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)


def summarise(text, began, ended):
    replies = sorted((float(m.group(1)), int(m.group(2))) for m in re.finditer(r'\[(\d+\.\d+)\].*icmp_seq=(\d+)', text))
    if not replies:
        return {'replies': 0, 'lost': None, 'longest_gap_s': None}
    times = [began] + [t for t, _ in replies] + [ended]
    gaps = [(round(b - a, 2), a) for a, b in zip(times, times[1:])]
    longest, at = max(gaps)
    sent = replies[-1][1] - replies[0][1] + 1
    return {'replies': len(replies), 'lost': sent - len(replies), 'longest_gap_s': longest,
            'longest_gap_started_utc': time.strftime('%H:%M:%S', time.gmtime(at))}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('node', choices=sorted(MGMT))
    parser.add_argument('--backup', required=True)
    parser.add_argument('--evidence', required=True)
    args = parser.parse_args()
    drift = ROOT / 'docs/multi-platform-restore/lab/drift' / f'{args.node}-B.cli'
    subprocess.run([PYTHON, str(TOOLS / 'nodecli.py'), args.node, '--tag', 'drift-b', '--timeout', '240', '--file', str(drift)],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    time.sleep(20)                                   # let the drift's own reconvergence settle before measuring
    probes = [('management ' + MGMT[args.node], '', MGMT[args.node])] + DATA[args.node]
    running = [(label, start(where, target)) for label, where, target in probes]
    time.sleep(5)                                    # a quiet baseline before the restore
    began = time.time()
    restore_file = args.evidence + '.restore.json'
    restore = subprocess.run([sys.executable, str(TOOLS / 'manager_restore.py'), '--backup', args.backup, '--nodes', args.node,
                              '--evidence', restore_file], capture_output=True, text=True)
    time.sleep(20)                                   # convergence after the confirmation
    ended = time.time()
    results = {}
    for label, process in running:
        process.terminate()
        results[label] = summarise(process.communicate(timeout=10)[0], began - 5, ended)
    job = json.load(open(restore_file))
    record = {'node': args.node, 'manager_version': job.get('manager_version'), 'job_status': (job.get('job') or {}).get('status'),
              'timeline': job.get('timeline'), 'window_utc': [time.strftime('%H:%M:%S', time.gmtime(began - 5)), time.strftime('%H:%M:%S', time.gmtime(ended))],
              'probe_interval_s': 0.2, 'probes': results}
    pathlib.Path(args.evidence).write_text(json.dumps(record, indent=1) + '\n')
    pathlib.Path(restore_file).unlink()
    print(json.dumps({'job': record['job_status'], 'probes': results}, indent=1))
    return 0 if restore.returncode == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
