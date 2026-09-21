"""Desired-state comparison for the restore drivers.

Two forms exist. Junos compares ``display set`` statements, each of which already carries its whole
path. EOS and IOS XR print indented blocks, so their lines are compared together with their parents.
Every exclusion is named here and in docs/multi-platform-restore/README.md; a difference that is
not listed is a verification failure, never something to normalise away.
"""
import re

# --- Junos `display set` --------------------------------------------------------------------
# Excluded: comment lines; `set version` (the NOS writes it); the root-authentication the Junos
# driver may have to synthesise (see restore_junos); `last-changed` timestamps.
JUNOS_ROOTAUTH = re.compile(r'^\s*set system root-authentication\b')
JUNOS_VOLATILE = re.compile(r'^\s*set (?:version|system time|.*last-changed)\b')


def set_lines(text):
    """Comparable `display set` statements: nonempty, non-comment, trimmed."""
    return [line.rstrip() for line in (text or '').splitlines()
            if line.strip() and not line.lstrip().startswith('#')]


def compare_junos(desired, actual):
    wanted, found = set(set_lines(desired)), set(set_lines(actual))
    extra = [l for l in sorted(found - wanted) if not JUNOS_ROOTAUTH.match(l) and not JUNOS_VOLATILE.match(l)]
    return sorted(wanted - found), extra


# --- comparison of indented (EOS, IOS XR) configurations ---------------------------------

def indented_statements(text, skip=None):
    """A running-config as a set of statements that keep their hierarchy.

    Every configuration line becomes ``parent > child > line`` using the indentation the NOS
    prints, so the same words under another interface are a different statement and a statement
    that moved is reported. Comment lines (``!`` and ``!!`` banners of the capture: command,
    device, timestamps) and the closing ``end`` carry no configuration and are dropped; ``skip``
    is a pattern of further generated lines a platform documents.
    """
    statements, stack = [], []
    for raw in (text or '').splitlines():
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith('!') or (stripped == 'end' and line == stripped):
            continue
        if skip is not None and skip.search(line):
            continue
        depth = len(line) - len(line.lstrip(' '))
        while stack and stack[-1][0] >= depth:
            stack.pop()
        statements.append(' > '.join([parent for _, parent in stack] + [stripped]))
        stack.append((depth, stripped))
    return statements


def compare_indented(desired, actual, skip=None):
    wanted, found = set(indented_statements(desired, skip)), set(indented_statements(actual, skip))
    return sorted(wanted - found), sorted(found - wanted)


def ordered_blocks_differ(desired, actual, block):
    """True when an order-sensitive block (an ACL, a route policy) has the same lines in another order."""
    def blocks(text):
        found, current, name = {}, None, ''
        for line in (text or '').splitlines():
            if line and not line.startswith(' ') and block.match(line):
                name, current = line.strip(), []
                found[name] = current
            elif current is not None and line.startswith(' '):
                current.append(line.strip())
            else:
                current = None
        return found
    wanted, got = blocks(desired), blocks(actual)
    return sorted(name for name in wanted if name in got and wanted[name] != got[name]
                  and sorted(wanted[name]) == sorted(got[name]))


EOS_ORDERED = re.compile(r'^(?:ip|ipv6|mac) access-list |^route-map |^ip prefix-list |^ipv6 prefix-list ')
