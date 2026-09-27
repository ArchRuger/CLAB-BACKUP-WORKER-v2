#!/usr/bin/env python3
"""Independent traffic probe for a Restart device run: from one device of restore-square, ping two loopbacks
every few seconds and log the results with timestamps, so the run's job times can be laid over them.
One target's path crosses the device being restarted, the other's does not (or reaches a neighbour).
Uses docs/multi-platform-restore/tools/nodecli.py (a real SSH session per round, never the manager).

    clab-backup-ui/.venv/bin/python docs/netlab-ui-qa/tools/traffic_probe.py --from cjunosevolved \\
        --crossing 10.255.0.1 --other 10.255.0.4 --minutes 8 --out /path/to/log.jsonl
"""
import argparse, json, re, subprocess, sys, time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
NODECLI = HERE.parents[1] / 'multi-platform-restore' / 'tools' / 'nodecli.py'
PING = {'junos': 'ping {ip} count 2 wait 1', 'eos': 'ping {ip} repeat 2 timeout 1', 'iosxr': 'ping {ip} count 2 timeout 1'}
KIND = {'ceos': 'eos', 'cjunosevolved': 'junos', 'vjunos-switch': 'junos', 'xrv9k': 'iosxr'}


def loss(text):
    m = re.search(r'(\d+) packets transmitted, (\d+) (?:packets )?received', text) or re.search(r'Success rate is (\d+) percent \((\d+)/(\d+)\)', text)
    if not m: return None
    if 'Success rate' in m.group(0): return 100 - int(m.group(1))
    sent, got = int(m.group(1)), int(m.group(2))
    return int(100 * (sent - got) / sent) if sent else None


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--from', dest='source', required=True); p.add_argument('--crossing', required=True); p.add_argument('--other', required=True)
    p.add_argument('--minutes', type=float, default=6); p.add_argument('--out', required=True)
    a = p.parse_args(); kind = KIND[a.source]; out = Path(a.out); deadline = time.monotonic() + a.minutes * 60
    with out.open('a') as log:
        while time.monotonic() < deadline:
            started = datetime.now(timezone.utc).isoformat(timespec='seconds')
            cmds = [PING[kind].format(ip=a.crossing), PING[kind].format(ip=a.other)]
            r = subprocess.run([sys.executable, str(NODECLI), a.source, *cmds, '--timeout', '40'], capture_output=True, text=True)
            text = r.stdout + r.stderr
            parts = text.split(cmds[1], 1)
            row = {'at': started, 'from': a.source, 'crossing': a.crossing, 'crossing_loss': loss(parts[0]), 'other': a.other, 'other_loss': loss(parts[1]) if len(parts) > 1 else None, 'ssh_ok': r.returncode == 0}
            log.write(json.dumps(row) + '\n'); log.flush(); print(json.dumps(row), flush=True)
            time.sleep(4)


if __name__ == '__main__': main()
