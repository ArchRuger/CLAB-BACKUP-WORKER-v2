#!/usr/bin/env python3
"""Measure what a restore interrupts, around ONE manager restore that really changes configuration.

The node is drifted to B, the devices are asked (tools/readback.py) that B is active, probes start, A is
restored through the running manager's API (tools/manager_restore.py), probes stop, and the devices are
asked again: A active, nothing pending, NOS boot identity unchanged. Everything lands in one evidence
file, including the restore's own record (source, per-target status, no_op, statement counts).

Probes, per restored node R:
  management          0.2 s pings from the VM to R's management address
  each edge of R      from the NEIGHBOUR's side to R's address on the shared /31
  transit through R   a destination whose only shortest OSPF path crosses R
A probe whose source is cEOS runs in the container's Linux namespace (its kernel carries the routed
interfaces and the OSPF routes): 0.2 s interval, timestamped, so the longest gap is known. A probe whose
source is a Junos or IOS XR node runs as a CLI ping at 1 s interval: sent/received only.

    python3 docs/multi-platform-restore/tools/interruption.py NODE --backup JOB --evidence FILE [--saved DIR]

A restore that changes addressing or routing on a probed path interrupts it by as much as that change
does. The drift used here does not, so the result is the cost of the replacement transaction itself.
"""
import argparse
import json
import pathlib
import re
import subprocess
import sys
import threading
import time

ROOT = pathlib.Path(__file__).resolve().parents[3]
TOOLS = pathlib.Path(__file__).resolve().parent
PYTHON = str(ROOT / 'clab-backup-ui/.venv/bin/python')
sys.path.insert(0, str(TOOLS))
MGMT = {'ceos': '172.20.20.101', 'cjunosevolved': '172.20.20.102', 'vjunos-switch': '172.20.20.103', 'xrv9k': '172.20.20.104'}
CEOS = 'clab-restore-square-ceos'
INTERVAL = 0.2
# (label, source node, target address). Edges from the neighbour's side; transit = the shortest path crosses R
# (every link costs 1: e.g. ceos -> 10.0.23.1 is 2 via cjunosevolved and 3 the other way round the square).
PROBES = {
    'ceos': [('edge: cjunosevolved -> ceos eth1', 'cjunosevolved', '10.0.12.0'), ('edge: xrv9k -> ceos eth2', 'xrv9k', '10.0.41.1'),
             ('transit through ceos: cjunosevolved -> xrv9k 10.0.41.0', 'cjunosevolved', '10.0.41.0')],
    'cjunosevolved': [('edge: ceos -> cjunosevolved et-0/0/0', 'ceos', '10.0.12.1'), ('edge: vjunos-switch -> cjunosevolved et-0/0/1', 'vjunos-switch', '10.0.23.0'),
                      ('transit through cjunosevolved: ceos -> vjunos-switch 10.0.23.1', 'ceos', '10.0.23.1')],
    'vjunos-switch': [('edge: cjunosevolved -> vjunos-switch ge-0/0/0', 'cjunosevolved', '10.0.23.1'), ('edge: xrv9k -> vjunos-switch ge-0/0/1', 'xrv9k', '10.0.34.0'),
                      ('transit through vjunos-switch: cjunosevolved -> xrv9k 10.0.34.1', 'cjunosevolved', '10.0.34.1')],
    'xrv9k': [('edge: vjunos-switch -> xrv9k Gi0/0/0/0', 'vjunos-switch', '10.0.34.1'), ('edge: ceos -> xrv9k Gi0/0/0/1', 'ceos', '10.0.41.0'),
              ('transit through xrv9k: ceos -> vjunos-switch 10.0.34.0', 'ceos', '10.0.34.0')],
}


class LinuxPing:
    """Timestamped 0.2 s pings: from the VM (where == '') or from the cEOS container's namespace."""
    def __init__(self, where, target):
        command = ['ping', '-D', '-n', '-i', str(INTERVAL), '-W', '1', target]
        self.began = time.time()
        self.process = subprocess.Popen((['docker', 'exec', where] if where else []) + command,
                                        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)

    def stop(self):
        ended = time.time()
        self.process.terminate()
        text = self.process.communicate(timeout=10)[0]
        replies = sorted((float(m.group(1)), int(m.group(2))) for m in re.finditer(r'\[(\d+\.\d+)\].*icmp_seq=(\d+)', text))
        expected = int((ended - self.began) / INTERVAL)
        if not replies:
            return {'kind': 'linux 0.2 s', 'expected_about': expected, 'replies': 0, 'lost': 'all', 'longest_gap_s': round(ended - self.began, 2)}
        times = [self.began] + [t for t, _ in replies] + [ended]
        longest, at = max((round(b - a, 2), a) for a, b in zip(times, times[1:]))
        highest = replies[-1][1]
        # Sequence numbers start at 1: a missing number is a lost probe wherever it fell, the head included.
        # The tail (probes after the last reply) shows up in longest_gap_s through the end bookend.
        return {'kind': 'linux 0.2 s', 'expected_about': expected, 'replies': len(replies), 'lost': highest - len(replies),
                'longest_gap_s': longest, 'longest_gap_started_utc': time.strftime('%H:%M:%S', time.gmtime(at))}


class CliPing(threading.Thread):
    """A 1 s CLI ping from a Junos or IOS XR node for a fixed number of probes: sent/received only."""
    def __init__(self, source, target, count):
        super().__init__(daemon=True)
        self.source, self.target, self.count, self.result = source, target, count, {'kind': 'cli 1 s', 'error': 'did not finish'}
        self.start()

    def run(self):
        from nodecli import Session
        try:
            session = Session(self.source, self.count + 60)
            try:
                command = (f'ping {self.target} count {self.count} wait 1' if session.family == 'junos'
                           else f'ping {self.target} count {self.count} timeout 1')
                text = session.run(command, self.count * 2 + 60)
            finally:
                session.close()
            match = re.search(r'(\d+) packets transmitted, (\d+) (?:packets )?received', text) or re.search(r'Success rate is \d+ percent \((\d+)/(\d+)\)', text)
            if not match:
                self.result = {'kind': 'cli 1 s', 'error': 'no summary in the ping output'}
                return
            a, b = int(match.group(1)), int(match.group(2))
            sent, got = (a, b) if 'transmitted' in match.group(0) else (b, a)
            self.result = {'kind': 'cli 1 s', 'sent': sent, 'replies': got, 'lost': sent - got}
        except Exception as exc:
            self.result = {'kind': 'cli 1 s', 'error': type(exc).__name__}

    def stop(self):
        self.join(timeout=self.count * 2 + 120)
        return self.result


def main():
    from manager_restore import build_identity, readback
    parser = argparse.ArgumentParser()
    parser.add_argument('node', choices=sorted(MGMT))
    parser.add_argument('--backup', required=True)
    parser.add_argument('--evidence', required=True)
    parser.add_argument('--saved', help='saved folder for the independent whole-configuration comparison (tools/readback.py)')
    parser.add_argument('--cli-probe-seconds', type=int, default=75, help='how long the 1 s CLI probes run; must outlast the restore')
    args = parser.parse_args()
    drift = ROOT / 'docs/multi-platform-restore/lab/drift' / f'{args.node}-B.cli'
    subprocess.run([PYTHON, str(TOOLS / 'nodecli.py'), args.node, '--tag', 'drift-b', '--timeout', '240', '--file', str(drift)],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    time.sleep(20)                                   # let the drift's own reconvergence settle before measuring
    record = {'node': args.node, 'build': build_identity(), 'probe_interval_s': INTERVAL,
              'device_readback_before': readback([args.node])}
    running = [('management ' + MGMT[args.node], LinuxPing('', MGMT[args.node]))]
    for label, source, target in PROBES[args.node]:
        running.append((label, LinuxPing(CEOS, target) if source == 'ceos' else CliPing(source, target, args.cli_probe_seconds)))
    time.sleep(8)                                    # a quiet baseline (and the CLI probes' logins) before the restore
    began = time.time()
    restore_file = args.evidence + '.restore.json'
    restore = subprocess.run([sys.executable, str(TOOLS / 'manager_restore.py'), '--backup', args.backup, '--nodes', args.node,
                              '--evidence', restore_file], capture_output=True, text=True)
    restore_seconds = round(time.time() - began, 1)
    time.sleep(15)                                   # convergence after the confirmation
    record['probes'] = {label: probe.stop() for label, probe in running}
    job = json.load(open(restore_file))
    pathlib.Path(restore_file).unlink()
    target = ((job.get('job') or {}).get('targets') or [{}])[0]
    record.update(manager_version=job.get('manager_version'), restore_seconds=restore_seconds,
                  restore={'source': job.get('source'), 'job_status': (job.get('job') or {}).get('status'), 'timeline': job.get('timeline'),
                           'preflight_pending_changes': next((t.get('pending_changes') for t in (job.get('preflight', {}).get('body', {}).get('targets') or [])
                                                              if t.get('name', '').endswith(args.node)), None),
                           'target_status': target.get('status'), 'no_op': target.get('no_op'),
                           'missing_statements': target.get('missing_statements'), 'extra_statements': target.get('extra_statements')},
                  device_readback_after=readback([args.node], args.saved))
    before = (record['device_readback_before'] or {}).get('nodes', {}).get(args.node, {})
    after = (record['device_readback_after'] or {}).get('nodes', {}).get(args.node, {})
    record['summary'] = {'b_was_active_before': before.get('active') == 'B', 'a_is_active_after': after.get('active') == 'A',
                         'nothing_pending_after': after.get('pending_confirmation') is False,
                         'restore_changed_configuration': target.get('no_op') is False,
                         'boot_before': before.get('boot'), 'boot_after': after.get('boot')}
    pathlib.Path(args.evidence).write_text(json.dumps(record, indent=1) + '\n')
    print(json.dumps({'summary': record['summary'], 'restore': record['restore']['target_status'], 'probes': record['probes']}, indent=1))
    return 0 if restore.returncode == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
