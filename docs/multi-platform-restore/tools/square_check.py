#!/usr/bin/env python3
"""Health of the restore-square lab, read from the devices themselves (never through the manager).

For every node: boot identity (the NOS's own boot time, which a container's uptime cannot show for a
virtual router running inside it), ping of both directly connected neighbours (so each of the four
edges is proven in both directions) and ping of the three remote loopbacks from its own loopback
(end-to-end through OSPF). Prints one JSON document; exit status 0 only when everything passed.

    clab-backup-ui/.venv/bin/python docs/multi-platform-restore/tools/square_check.py [--json FILE]
"""
import argparse
import json
import re
import sys
import time

from nodecli import Session

LOOPBACK = {'ceos': '10.255.0.1', 'cjunosevolved': '10.255.0.2', 'vjunos-switch': '10.255.0.3', 'xrv9k': '10.255.0.4'}
NEIGHBOURS = {  # node -> {neighbour: the neighbour's address on the shared /31}
    'ceos': {'cjunosevolved': '10.0.12.1', 'xrv9k': '10.0.41.0'},
    'cjunosevolved': {'ceos': '10.0.12.0', 'vjunos-switch': '10.0.23.1'},
    'vjunos-switch': {'cjunosevolved': '10.0.23.0', 'xrv9k': '10.0.34.1'},
    'xrv9k': {'vjunos-switch': '10.0.34.0', 'ceos': '10.0.41.1'},
}
PING = {
    'eos': lambda dst, src: f'ping {dst}' + (f' source {src}' if src else '') + ' repeat 3 timeout 2',
    'junos': lambda dst, src: f'ping {dst}' + (f' source {src}' if src else '') + ' count 3 wait 2',
    'iosxr': lambda dst, src: f'ping {dst}' + (f' source {src}' if src else '') + ' count 3 timeout 2',
}
BOOT = {
    'eos': ('show version | include Uptime|uptime', None),
    'junos': ('show system uptime | match "System booted"', re.compile(r'System booted: (\S+ \S+)')),
    'iosxr': ('show version | include uptime', None),
}


def received(family, text):
    if family == 'iosxr':
        match = re.search(r'Success rate is \d+ percent \((\d+)/(\d+)\)', text)
    else:
        match = re.search(r'(\d+) packets transmitted, (\d+) (?:packets )?received', text)
        if match:
            return int(match.group(2)), int(match.group(1))
    return (int(match.group(1)), int(match.group(2))) if match else (0, 0)


def check(node):
    session = Session(node, 60)
    try:
        family = session.family
        command, pattern = BOOT[family]
        boot_text = '\n'.join(session.run(command).split('\n')[1:-1]).strip()
        result = {'boot': (pattern.search(boot_text).group(1) if pattern and pattern.search(boot_text) else boot_text),
                  'edges': {}, 'loopbacks': {}}
        if family == 'eos':  # uptime is relative on EOS; the kernel boot id of the container's NOS is absolute
            result['boot_id'] = '\n'.join(session.run('bash timeout 5 cat /proc/sys/kernel/random/boot_id').split('\n')[1:-1]).strip()
            result['agent_start'] = '\n'.join(session.run('show agent uptime | include Sysdb|ConfigAgent').split('\n')[1:-1]).strip()
        for neighbour, address in NEIGHBOURS[node].items():
            got, sent = received(family, session.run(PING[family](address, '')))
            result['edges'][neighbour] = f'{got}/{sent}'
        for other, address in LOOPBACK.items():
            if other != node:
                got, sent = received(family, session.run(PING[family](address, LOOPBACK[node])))
                result['loopbacks'][other] = f'{got}/{sent}'
        values = list(result['edges'].values()) + list(result['loopbacks'].values())
        result['ok'] = all(v.split('/')[0] != '0' and v.split('/')[0] == v.split('/')[1] for v in values)
        return result
    finally:
        session.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--json', help='also write the result here')
    parser.add_argument('--nodes', nargs='*', default=sorted(NEIGHBOURS))
    args = parser.parse_args()
    report = {'checked_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'nodes': {}}
    for node in args.nodes:
        try:
            report['nodes'][node] = check(node)
        except Exception as exc:  # an unreachable node is a result, not a crash
            report['nodes'][node] = {'ok': False, 'error': type(exc).__name__}
    report['ok'] = all(n.get('ok') for n in report['nodes'].values())
    text = json.dumps(report, indent=1)
    print(text)
    if args.json:
        open(args.json, 'w').write(text + '\n')
    sys.exit(0 if report['ok'] else 1)


if __name__ == '__main__':
    main()
