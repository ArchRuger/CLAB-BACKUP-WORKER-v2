#!/usr/bin/env python3
"""Does a restored configuration survive a normal restart of the network operating system?

Run it for a node whose LAST configuration change was a confirmed *Replace running configuration*
(so what is tested is what the restore left behind, including its save-to-startup step where a NOS
needs one). The tool records the active configuration and the NOS's own boot identity, restarts the
NOS the way an operator would, waits for management and for the node's two square edges, and compares.
A containerlab redeploy is NOT a restart: it injects the startup configuration and proves nothing here.

    Junos (cjunosevolved, vjunos-switch)   `request system reboot`, answered yes
    IOS XR (xrv9k)                         `reload`, prompts answered
    cEOS (ceos)                            `containerlab restart --node ceos` (the container IS the NOS; this
                                           command restarts a node and keeps its links; never `docker restart`)

    clab-backup-ui/.venv/bin/python docs/multi-platform-restore/tools/persistence_check.py NODE --evidence FILE

Comparison is done here, independently of the application: configuration lines with the generated
ones removed (comment lines; Junos `## Last changed`/`version`; IOS XR timestamp and `!!` banner lines).
Exit status 0 only when the restart really happened (boot identity changed), the configuration is
unchanged and both edges answer again.
"""
import argparse
import json
import pathlib
import re
import subprocess
import sys
import time

from nodecli import Session
from square_check import NEIGHBOURS, PING, received

TOPOLOGY = '/srv/containerlab-node-manager/projects/restore-square/restore-square.clab.yml'
CAPTURE = {'eos': 'show running-config', 'junos': 'show configuration | display set | no-more', 'iosxr': 'show running-config'}
GENERATED = {
    'eos': re.compile(r'^\s*!|^\s*$|^end$'),
    'junos': re.compile(r'^\s*#|^\s*$|^set version '),
    'iosxr': re.compile(r'^\s*!|^\s*$|^end$|^Building configuration|^[A-Z][a-z]{2} [A-Z][a-z]{2} +\d+ '),
}
BOOT = {'eos': 'bash timeout 5 cat /proc/sys/kernel/random/boot_id',      # a new container kernel namespace has the host's id:
        'junos': 'show system uptime | match "System booted"',            # so cEOS also records its agents' start below
        'iosxr': 'show version | include uptime'}


def body(text):
    return '\n'.join(text.split('\n')[1:-1])


def configuration(session):
    lines = [line.rstrip() for line in body(session.run(CAPTURE[session.family], 180)).splitlines()]
    return [line for line in lines if not GENERATED[session.family].search(line)]


def identity(session):
    value = body(session.run(BOOT[session.family])).strip()
    if session.family == 'eos':
        value += ' | ' + body(session.run('show version | include Uptime')).strip()
    if session.family == 'junos':
        value = value.split(' (')[0]
    return value


def uptime_seconds(session):
    """Seconds since the NOS started, from the NOS itself (the proof that a restart happened)."""
    if session.family == 'junos':
        text = body(session.run('show system uptime | match "System booted"'))
        match = re.search(r'\((?:(\d+)w)?(?:(\d+)d )?(\d+):(\d+)(?::(\d+))? ago\)', text)
        if not match:
            return None
        w, d, a, b, c = (int(x) if x else 0 for x in match.groups())
        return w * 604800 + d * 86400 + a * 3600 + b * 60 + c   # "(00:29:10 ago)" or, past a day, "(1d 02:03 ago)"
    if session.family == 'eos':   # `show version` Uptime is not a boot identity on cEOS; the age of PID 1 is
        text = body(session.run('bash timeout 5 ps -o etimes= -p 1')).strip()
        return int(text) if text.isdigit() else None
    text = body(session.run('show version | include ptime'))
    total = 0
    for amount, unit in re.findall(r'(\d+) (week|day|hour|minute|second)', text):
        total += int(amount) * {'week': 604800, 'day': 86400, 'hour': 3600, 'minute': 60, 'second': 1}[unit]
    return total or None


def restart(node, family, log):
    if family == 'eos':
        done = subprocess.run(['sudo', '-n', 'containerlab', 'restart', '-t', TOPOLOGY, '--node', node],
                              capture_output=True, text=True, timeout=600)
        log.append('containerlab restart exit %s' % done.returncode)
        return done.returncode == 0
    session = Session(node, 60)
    try:
        session.channel.sendall(('request system reboot\n' if family == 'junos' else 'reload\n').encode())
        deadline = time.time() + 90
        seen = ''
        while time.time() < deadline:
            try:
                chunk = session.channel.recv(65536)
            except Exception:
                chunk = None
            if chunk == b'':
                break
            if chunk:
                seen += chunk.decode('utf-8', 'replace')
                tail = seen[-160:].lower()
                if re.search(r'\[yes,no\]\s*\(no\)\s*$', tail) or re.search(r'\[no,yes\]\s*$', tail) or re.search(r'\(yes/no\)[^\n]*$', tail):
                    session.channel.sendall(b'yes\n'); seen += '\n<answered yes>\n'
                elif re.search(r'\[confirm\]\s*$', tail):
                    session.channel.sendall(b'\n'); seen += '\n<confirmed>\n'
        log.append(re.sub(r'\s+', ' ', seen)[-600:])
        return True
    finally:
        session.close()


def wait_for(node, minutes, log):
    deadline = time.time() + minutes * 60
    went_down = False
    while time.time() < deadline:
        try:
            session = Session(node, 60)
        except Exception:
            went_down = True
            time.sleep(15)
            continue
        try:
            up = uptime_seconds(session)
            if up is not None and (went_down or up < 1500):
                edges = {n: received(session.family, session.run(PING[session.family](a, ''))) for n, a in NEIGHBOURS[node].items()}
                if all(got == sent and sent for got, sent in edges.values()):
                    return True
        except Exception:
            pass
        finally:
            session.close()
        time.sleep(20)
    log.append('timed out waiting for management and both edges')
    return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('node', choices=sorted(NEIGHBOURS))
    parser.add_argument('--evidence', required=True)
    parser.add_argument('--wait-minutes', type=int, default=45)
    args = parser.parse_args()
    log = []
    session = Session(args.node, 120)
    family = session.family
    before, boot_before, up_before = configuration(session), identity(session), uptime_seconds(session)
    session.close()
    started = time.time()
    restarted = restart(args.node, family, log)
    back = restarted and wait_for(args.node, args.wait_minutes, log)
    record = {'node': args.node, 'restart_command_accepted': restarted, 'back_with_both_edges': back,
              'seconds_until_back': round(time.time() - started), 'boot_before': boot_before, 'uptime_before_s': up_before, 'log': log}
    if back:
        session = Session(args.node, 120)
        after, boot_after, up_after = configuration(session), identity(session), uptime_seconds(session)
        session.close()
        missing, extra = sorted(set(before) - set(after)), sorted(set(after) - set(before))
        if missing or extra:   # the lines themselves may hold hashes: outside Git, like every raw capture
            raw = pathlib.Path.home() / 'research/multi-platform-restore/raw'
            raw.mkdir(parents=True, exist_ok=True)
            (raw / f'persistence-{args.node}-{int(started)}.diff').write_text('\n'.join(['- ' + l for l in missing] + ['+ ' + l for l in extra]) + '\n')
        record.update(boot_after=boot_after, uptime_after_s=up_after,
                      really_restarted=bool(up_before and up_after and up_after < up_before),
                      configuration_lines=len(before), lines_lost=len(missing), lines_new=len(extra),
                      order_changed=(not missing and not extra and before != after))
    record['ok'] = bool(back and record.get('really_restarted') and not record.get('lines_lost') and not record.get('lines_new'))
    pathlib.Path(args.evidence).write_text(json.dumps(record, indent=1) + '\n')
    print(json.dumps(record, indent=1))
    return 0 if record['ok'] else 1


if __name__ == '__main__':
    sys.exit(main())
