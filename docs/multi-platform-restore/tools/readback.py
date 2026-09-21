#!/usr/bin/env python3
"""Independent, sanitized readback of one restore-square node: is configuration A or B active?

Reads the active configuration over a fresh SSH connection through tools/nodecli.py (no code of the
application is involved) and answers with booleans only, so the result can be committed: which of
A's marker statements are present, which of B's drift markers are present, whether anything awaits
confirmation on the node, and the NOS's own boot identity. No configuration text leaves this tool.

The markers are the three kinds of drift in lab/drift/<node>-B.cli: an A value that B modifies, an A
statement that B removes, and B-only stanzas that a merge-only restore would leave behind.

With --saved DIR the whole active configuration is also compared with the saved one, by this tool's own
comparator (no import from the application): DIR is a saved folder of the lab's repository checkout
(for example ~/labs/CLAB-MNGR-DEV-LLM/restore-square/work/latest) holding <node>.set (Junos display set)
or <node>.cfg (EOS, IOS XR running-config). Only counts are reported. Exclusions, the same the README
documents for the product: comment and generated lines; Junos `set version` and, reported separately
because the driver may have to add it, `set system root-authentication`.

    clab-backup-ui/.venv/bin/python docs/multi-platform-restore/tools/readback.py NODE [NODE ...] [--expect A|B] [--saved DIR]

Exit status 0 when every node matches --expect (and, with --saved, has no difference); without --expect: always 0.
"""
import argparse
import json
import re
import sys
import time

from nodecli import Session

CAPTURE = {'eos': 'show running-config', 'junos': 'show configuration | display set | no-more', 'iosxr': 'show running-config'}
MARKERS = {
    'ceos': {
        'a_value_modified_by_b': r'^\s+description A to-cjunosevolved$',
        'a_statement_removed_by_b': r'^ip prefix-list RESTORE-A seq 10 permit 10\.255\.0\.0/24 le 32$',
        'b_only': [r'^vlan 777$', r'^\s+name B-ONLY$', r'^ip route 198\.51\.100\.0/24 Null0$', r'^\s+description B changed$'],
    },
    'cjunosevolved': {
        'a_value_modified_by_b': r'^set interfaces et-0/0/0 description "A to-ceos"$',
        'a_statement_removed_by_b': r'^set routing-options static route 192\.0\.2\.2/32 discard$',
        'b_only': [r'^set policy-options prefix-list B-ONLY ', r'^set routing-options static route 198\.51\.100\.0/24 discard$',
                   r'^set interfaces et-0/0/0 description "B changed"$'],
    },
    'vjunos-switch': {
        'a_value_modified_by_b': r'^set interfaces ge-0/0/0 description "A to-cjunosevolved"$',
        'a_statement_removed_by_b': r'^set routing-options static route 192\.0\.2\.3/32 discard$',
        'b_only': [r'^set policy-options prefix-list B-ONLY ', r'^set vlans B-ONLY vlan-id 777$',
                   r'^set interfaces ge-0/0/0 description "B changed"$'],
    },
    'xrv9k': {
        'a_value_modified_by_b': r'^\s+description A to-vjunos-switch$',
        'a_statement_removed_by_b': r'^\s+192\.0\.2\.4/32 Null0$',
        'b_only': [r'^prefix-set B-ONLY$', r'^interface Loopback777$', r'^\s+description B changed$'],
    },
}
PENDING = {
    'eos': ('show configuration sessions detail', lambda text: bool(re.search(r'Session with pending commit timer', text))),
    'junos': ('show system commit | no-more', lambda text: bool(re.search(r'(?m)^0\s.*\n(?:\s+\S.*\n)*?\s+rollback pending', text))),
    # While a `commit confirmed` trial is outstanding, the detail view lists an extra session whose client is
    # "commit-confirm" (evidence/xr-live-facts.md, session-table shapes).
    'iosxr': ('show configuration sessions detail', lambda text: bool(re.search(r'Client:\s*commit-confirm', text))),
}
LEFTOVER = {'eos': lambda text: len(re.findall(r'(?m)^[*\s]\s*clabmgr-[0-9a-f]{8}\s+pending\b', text))}
# The NOS's own boot identity. On cEOS `show version` "Uptime" is NOT one (it was seen restarting from zero while the
# container, PID 1 and every agent kept running), so cEOS answers with the age of PID 1: the container is the NOS.
BOOT = {'eos': 'bash timeout 5 ps -o etimes= -p 1', 'junos': 'show system uptime | match "System booted"', 'iosxr': 'show version | include uptime'}
UNITS = {'week': 604800, 'day': 86400, 'hour': 3600, 'minute': 60, 'second': 1}


def up_seconds(family, boot):
    """Seconds the NOS has been up, where it says so (cEOS: PID 1; IOS XR: uptime to the minute); Junos gives a boot time instead."""
    if family == 'eos':
        return int(boot) if boot.strip().isdigit() else None
    if family == 'iosxr':
        return sum(int(a) * UNITS[u] for a, u in re.findall(r'(\d+) (week|day|hour|minute|second)', boot)) or None
    return None


def body(text):
    return '\n'.join(text.split('\n')[1:-1])


GENERATED = re.compile(r'^\s*(?:!|#)|^\s*$|^end$|^Building configuration|^[A-Z][a-z]{2} [A-Z][a-z]{2} +\d+ +\d+:\d+')


def statements(text, family):
    """The configuration as a set of statements. Junos `display set` lines carry their whole path;
    indented configurations get theirs from the indentation (parent > child > line)."""
    found, stack = set(), []
    for raw in text.splitlines():
        line = raw.rstrip()
        if GENERATED.search(line) or (family == 'junos' and line.startswith('set version ')):
            continue
        if family == 'junos':
            found.add(line.strip())
            continue
        depth = len(line) - len(line.lstrip(' '))
        while stack and stack[-1][0] >= depth:
            stack.pop()
        found.add(' > '.join([parent for _, parent in stack] + [line.strip()]))
        stack.append((depth, line.strip()))
    return found


def compare_saved(node, family, active_text, saved_dir):
    import pathlib
    folder = pathlib.Path(saved_dir).expanduser()
    saved = next((folder / f'{node}.{suffix}' for suffix in ('set', 'cfg') if (folder / f'{node}.{suffix}').exists()), None)
    if saved is None:
        return {'saved_file': None}
    wanted, active = statements(saved.read_text(), family), statements(active_text, family)
    extra = active - wanted
    tolerated = {line for line in extra if family == 'junos' and line.startswith('set system root-authentication ')}
    return {'saved_file': saved.name, 'saved_statements': len(wanted), 'active_statements': len(active),
            'missing': len(wanted - active), 'extra': len(extra - tolerated), 'tolerated_root_authentication': len(tolerated)}


def read(node, saved_dir=None):
    session = Session(node, 180)
    try:
        family, marks = session.family, MARKERS[node]
        lines = body(session.run(CAPTURE[family], 180))
        has = lambda pattern: bool(re.search(pattern, lines, re.M))
        command, judge = PENDING[family]
        pending_text = session.run(command)
        boot = body(session.run(BOOT[family])).strip().split('\n')[-1].split(' (')[0]
        result = {'a_value_present': has(marks['a_value_modified_by_b']), 'a_statement_present': has(marks['a_statement_removed_by_b']),
                  'b_only_present': sum(1 for pattern in marks['b_only'] if has(pattern)), 'b_only_markers': len(marks['b_only']),
                  'configuration_lines': len([l for l in lines.splitlines() if l.strip()]),
                  'pending_confirmation': judge(pending_text),
                  'boot': ('PID 1 up %s s' % boot.strip()) if family == 'eos' else boot, 'up_seconds': up_seconds(family, boot)}
        if family in LEFTOVER:
            result['own_sessions_left_pending'] = LEFTOVER[family](pending_text)
        if saved_dir:
            result['compared_with_saved'] = compare_saved(node, family, lines, saved_dir)
        if result['a_value_present'] and result['a_statement_present'] and not result['b_only_present']:
            result['active'] = 'A'
        elif not result['a_value_present'] and not result['a_statement_present'] and result['b_only_present'] == result['b_only_markers']:
            result['active'] = 'B'
        else:
            result['active'] = 'mixed'
        return result
    finally:
        session.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('nodes', nargs='+', choices=sorted(MARKERS))
    parser.add_argument('--expect', choices=['A', 'B'])
    parser.add_argument('--saved', help='a saved folder of the repository checkout to compare the whole configuration with')
    args = parser.parse_intermixed_args()
    report = {'read_at_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'nodes': {}}
    for node in args.nodes:
        try:
            report['nodes'][node] = read(node, args.saved)
        except Exception as exc:
            report['nodes'][node] = {'active': 'unreadable', 'error': type(exc).__name__}
    print(json.dumps(report, indent=1))
    if args.expect:
        same = lambda n: not args.saved or (n.get('compared_with_saved', {}).get('missing') == 0 and n['compared_with_saved'].get('extra') == 0)
        return 0 if all(n.get('active') == args.expect and not n.get('pending_confirmation') and same(n) for n in report['nodes'].values()) else 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
