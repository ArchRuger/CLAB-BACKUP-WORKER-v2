"""Ownership algebra of *Network design*: what the manager put on a device, what it may remove, how.

docs/netlab-integration/PROVISIONING.md §3 is the contract; this module is its pure implementation, with no
device I/O, so its rules can be tested statement by statement. Every device snapshot is turned into a set of
statements in the platform's *ownership form*:

* EOS and IOS XR: running-configuration lines with their parents joined by ` > `
  (``restore_compare.indented_statements``: `interface Ethernet1 > ip address 10.0.0.1/30`);
* Junos: `display set` statements (``restore_compare.set_lines``, the `[edit]` banner removed).

A statement's *ancestors* are its path prefixes: for the indented form every parent chain, for a set
statement every shorter `set …` prefix cut at a word boundary outside quotes. The *created ancestors* of an
apply are the prefixes of its added statements that no statement of the device's earlier configuration
started with: the containers the manager brought into being, recorded with the owned set so a later removal
can take a whole container in one command instead of leaving a presence line behind (Junos) or removing
leaves one by one.

The functions here decide; the drivers only render the resulting removal commands in their NOS's syntax.
"""
import re

from .restore_compare import JUNOS_VOLATILE, indented_statements, set_lines

INDENTED_KINDS = ('arista_ceos', 'cisco_xrv9k')
SET_KINDS = ('juniper_cjunosevolved', 'juniper_vjunosswitch')
JUNOS_BANNER = re.compile(r'^\s*\[edit\]\s*$')
XR_HEADER = re.compile(r'^(?:!!|!\s*$|\w{3}\s+\w{3}\s+\d{1,2}\s+\d\d:\d\d:\d\d)')
# Where two values would both stay beside each other on a merge (Junos every address, IPv6 addresses on all
# three platforms) or where an addition changes how unowned siblings behave: an addition next to an unowned
# sibling under one of these parents is a conflict, never a silent supplement (PROVISIONING §3, review S1).
EXCLUSIVE = {
    'arista_ceos': (re.compile(r'^interface \S+ > ipv6 address '), re.compile(r'^interface \S+ > ip address '),
                    re.compile(r'^router bgp \d+ > no bgp default ipv4-unicast$'), re.compile(r'^router bgp \d+ > no bgp default ipv6-unicast$')),
    'cisco_xrv9k': (re.compile(r'^interface \S+ > ipv6 address '), re.compile(r'^interface \S+ > ipv4 address ')),
    'juniper_cjunosevolved': (re.compile(r'^set interfaces \S+ unit \d+ family inet6? address '), re.compile(r'^set protocols bgp group \S+ export ')),
    'juniper_vjunosswitch': (re.compile(r'^set interfaces \S+ unit \d+ family inet6? address '), re.compile(r'^set protocols bgp group \S+ export ')),
}
# Leaves whose inverse changes something beyond themselves: never removed silently while an unowned sibling
# sits under the same parent (review M3). `switchport` back on a Layer-3 interface drops its addresses.
SIDE_EFFECT_LEAVES = {'arista_ceos': (re.compile(r'^interface \S+ > no switchport$'),)}
# Administrative state is an expected change of a first apply (XRv9k data ports ship `shutdown`) and is never
# re-applied on removal (review S3): a stale `no shutdown` is left alone and reported as expected.
ADMIN_STATE = {'cisco_xrv9k': re.compile(r'^interface \S+ > no shutdown$'), 'arista_ceos': re.compile(r'^interface \S+ > no shutdown$')}
# EOS BGP (verified live on cEOS 4.35.0F): a neighbour's lines at the process level and under the address families
# belong together (`no neighbor X` takes them all, while per-line negation leaves an explicit `no neighbor X
# activate` behind), and `no address-family F` keeps the family's `network` statements by moving them to the
# process level, so they are removed by name first.
EOS_NEIGHBOR = re.compile(r'^(router bgp \d+) > (?:address-family \S+ > )?neighbor (\S+) ')
EOS_AF = re.compile(r'^router bgp \d+ > address-family \S+$')


def statements(kind, text):
    """The ownership-form statement set of a device snapshot or a would-be configuration."""
    if kind in SET_KINDS:
        return {line for line in set_lines(text) if not JUNOS_BANNER.match(line) and not JUNOS_VOLATILE.match(line)}
    if kind == 'cisco_xrv9k':
        text = '\n'.join(line for line in (text or '').splitlines() if not XR_HEADER.match(line) and line.strip() != 'end')
    return set(indented_statements(text))


def _split_words(statement):
    """Words of a set statement, quoted values kept together."""
    return re.findall(r'"[^"]*"|\S+', statement)


def ancestors(kind, statement):
    """Every proper path prefix of a statement, shortest first."""
    if kind in SET_KINDS:
        words = _split_words(statement)
        return [' '.join(words[:n]) for n in range(2, len(words))]   # `set a` … `set a b c`
    parts = statement.split(' > ')
    return [' > '.join(parts[:n]) for n in range(1, len(parts))]


def _under(kind, prefix, statement):
    """True when `statement` lies under the path `prefix`."""
    if statement == prefix: return True
    return statement.startswith(prefix + (' ' if kind in SET_KINDS else ' > '))


def created_ancestors(kind, added, before, containers=None):
    """The path prefixes of `added` that no statement of `before` starts with: containers this apply created.

    `containers`, when given, is the set of paths that are real containers on the device (Junos: the blocks of
    the device's own hierarchical rendering, see :func:`junos_blocks`); a set statement's word prefixes also
    include keyword-only levels (`set protocols bgp group X neighbor`) that the NOS cannot delete, so on the
    set-form kinds only the paths in `containers` count."""
    found = set()
    for statement in added:
        for prefix in ancestors(kind, statement):
            if containers is not None and prefix not in containers: continue
            if not any(_under(kind, prefix, old) for old in before):
                found.add(prefix)
    return found


def junos_blocks(text):
    """The `set …` paths of every block of a Junos hierarchical configuration text (`show` output or a fragment):
    the containers a `delete <path>` may name. Comments, `inactive:`/`protect:` markers and `delete:` tags are
    ignored; an `X.N {` interface shorthand under `interfaces` becomes the two blocks `X` and `X unit N`."""
    paths, stack = set(), []   # stack entries: (name, pops) — a shorthand unit carries 0 and is popped with its interface
    for raw in (text or '').splitlines():
        line = raw.strip()
        if not line or line.startswith(('#', '/*', '*', 'delete:')): continue
        for marker in ('inactive: ', 'protect: ', 'apply-flags omit '):
            if line.startswith(marker): line = line[len(marker):]
        if line.endswith('{'):
            name = line[:-1].strip()
            if [n for n, _ in stack] == ['interfaces'] and ' ' not in name and re.fullmatch(r'[A-Za-z][\w/:-]*\.\d+', name):
                base, unit = name.rsplit('.', 1)
                stack.append((base, 1)); paths.add('set ' + ' '.join(n for n, _ in stack))
                stack.append(('unit ' + unit, 0))
            else:
                stack.append((name, 1))
            paths.add('set ' + ' '.join(n for n, _ in stack)); continue
        if line == '}':
            while stack:
                _, pops = stack.pop()
                if pops: break
    return paths


def diff(kind, before, would_be, owned, desired, anc=()):
    """The sets of PROVISIONING §3 for one device: added, removed, stale, conflicts, expected, plus the
    exclusive-hierarchy conflicts. `owned`/`anc` are the ledger's statements and created ancestors, `desired`
    the device-rendered candidate."""
    before, would_be, owned, desired = set(before), set(would_be), set(owned), set(desired)
    owned_all = owned | set(anc)   # a created ancestor is owned as a presence line; what appears under it later is not
    added = would_be - before
    removed = before - would_be
    stale = (owned - desired) & before
    expected = set()
    admin = ADMIN_STATE.get(kind)
    if admin is not None:
        for statement in list(removed):
            if statement.rsplit(' > ', 1)[-1] == 'shutdown' and statement.split(' > ')[0].startswith('interface') and any(admin.match(a) and a.rsplit(' > ', 1)[0] == statement.rsplit(' > ', 1)[0] for a in added):
                expected.add(statement); removed.discard(statement)
    if kind == 'cisco_xrv9k':
        # IOS XR shows a port's admin state only as `shutdown`; the design's `no shutdown` is the line's absence in
        # the merged view, so a `shutdown` that disappears under an interface the design configures is expected.
        for statement in list(removed):
            parts = statement.split(' > ')
            if len(parts) == 2 and parts[0].startswith('interface ') and parts[1] == 'shutdown' and any(d.startswith(parts[0] + ' > ') for d in desired):
                expected.add(statement); removed.discard(statement)
    for statement in list(removed):
        # A device default the design switches on (`no ip routing` -> `ip routing`) is an expected first change.
        leaf = statement.rsplit(' > ', 1)[-1]
        if kind in INDENTED_KINDS and leaf.startswith('no ') and (statement[:-len(leaf)] + leaf[3:]) in added:
            expected.add(statement); removed.discard(statement)
    conflicts = {s for s in removed if s not in owned_all}
    for pattern in EXCLUSIVE.get(kind, ()):
        for statement in added:
            if not pattern.match(statement): continue
            parent = statement.rsplit(' > ', 1)[0] if kind in INDENTED_KINDS else ' '.join(_split_words(statement)[:-1])
            for old in before:
                if old == statement or old in owned_all: continue
                if (old.rsplit(' > ', 1)[0] if kind in INDENTED_KINDS else ' '.join(_split_words(old)[:-1])) == parent and pattern.match(old):
                    conflicts.add(old)
    return {'added': added, 'removed': removed, 'stale': stale, 'conflicts': conflicts, 'expected': expected}


def plan_removals(kind, before, owned, anc, desired):
    """What to remove, and at which level, before the candidate is merged (PROVISIONING §3).

    Returns {'remove': [paths, highest owned-and-stale ancestor first], 'leaves': [stale leaves removed one by
    one], 'kept_manual': [stale statements kept because an unowned statement sits under the same container and
    the leaf's inverse would touch it], 'skipped': [stale statements that are administrative state]}. Every
    element is in ownership form; the driver renders the commands."""
    before, owned, desired, anc = set(before), set(owned), set(desired), set(anc)
    owned_all = owned | anc
    stale = {s for s in (owned_all - desired) & before}
    admin = ADMIN_STATE.get(kind)
    skipped = {s for s in stale if admin is not None and admin.match(s)}
    stale -= skipped
    remove, covered = [], set()
    # Highest created ancestor whose whole subtree in `before` is owned and stale.
    for prefix in sorted(anc, key=lambda p: (len(p.split(' > ' if kind in INDENTED_KINDS else ' ')), p)):
        if any(_under(kind, done, prefix) for done in remove): continue
        subtree = {s for s in before if _under(kind, prefix, s)}
        if subtree and subtree <= stale | skipped and subtree & stale:
            remove.append(prefix); covered |= subtree
    leaves, kept = [], []
    if kind == 'arista_ceos':
        for prefix in remove:
            if EOS_AF.match(prefix):   # the family's `network` statements go by name before the family itself
                leaves += sorted(s for s in before if s != prefix and _under(kind, prefix, s) and s.rsplit(' > ', 1)[-1].startswith('network '))
    side_effects = SIDE_EFFECT_LEAVES.get(kind, ())
    for statement in sorted(stale - covered, key=lambda s: (-len(s), s)):
        if any(s != statement and _under(kind, statement, s) for s in before):
            kept.append(statement); continue   # a container that could not go whole: something unowned lives under it
        parent = statement.rsplit(' > ', 1)[0] if kind in INDENTED_KINDS else ' '.join(_split_words(statement)[:-1])
        siblings = {s for s in before if s != statement and s != parent and _under(kind, parent, s)}
        if any(p.match(statement) for p in side_effects) and any(s not in owned_all for s in siblings):
            kept.append(statement); continue
        leaves.append(statement)
    if kind == 'arista_ceos':
        groups = {}
        for statement in leaves:
            match = EOS_NEIGHBOR.match(statement)
            # `neighbor interface Ethernet1 …` (unnumbered) and `neighbor default …` are not peers named `interface`/`default`.
            if match and match.group(2) not in ('interface', 'default'): groups.setdefault((match.group(1), match.group(2)), []).append(statement)
        for (process, peer), members in groups.items():
            every = {s for s in before if (m := EOS_NEIGHBOR.match(s)) and (m.group(1), m.group(2)) == (process, peer)}
            if every <= stale:   # the whole neighbour is the manager's and stale: one `no neighbor X`
                leaves = [s for s in leaves if s not in members] + [process + ' > neighbor ' + peer]
    return {'remove': remove, 'leaves': leaves, 'kept_manual': kept, 'skipped': sorted(skipped)}


def takeover_leftovers(conflicts, would_be):
    """The taken-over conflicts a merge alone would leave in place: unowned siblings inside an exclusive hierarchy (a
    second IPv6 address, a Junos address) stay beside the design's addition, so a take-over must remove them as
    leaves in a second pass of the review; a conflict the merge itself replaces or removes needs nothing more."""
    return sorted(c for c in conflicts if c in set(would_be))


def after_apply(kind, owned, added, after):
    """The owned set once a change was confirmed and the device read back: what the manager put there and what is
    still there. Ancestors are recomputed by the caller from the new owned set against the pre-apply snapshot."""
    owned, added, after = set(owned), set(added), set(after)
    return (owned & after) | (added & after)


def render_removals(kind, plan):
    """The removal text for the NOS, children first: EOS `no`/`default` lines under their parent context, IOS XR
    `no` lines under their parents, Junos `delete <path>` lines. Returns a list of lines (the driver pastes them
    before the candidate)."""
    lines = []
    items = list(plan.get('leaves', [])) + list(plan.get('remove', []))
    if kind in SET_KINDS:
        for statement in items:
            words = _split_words(statement)
            lines.append('delete ' + ' '.join(words[1:]) if words and words[0] == 'set' else 'delete ' + statement)
        return lines
    for statement in items:
        parts = statement.split(' > ')
        leaf = parts[-1]
        if kind == 'arista_ceos':
            negation = 'default ' + leaf[3:] if leaf.startswith('no ') else 'no ' + leaf
        else:
            negation = 'no ' + leaf[3:] if leaf.startswith('no ') else 'no ' + leaf
            if leaf == 'shutdown': negation = 'no shutdown'
        for depth, parent in enumerate(parts[:-1]):
            lines.append(' ' * depth + parent)
        lines.append(' ' * (len(parts) - 1) + negation)
        lines.append('!')
    return lines


def split_negations(kind, desired):
    """(present, absent): what a desired set asks to see and what it asks not to see. IOS XR's target buffer echoes
    the typed negations (`no shutdown`, `no management enable`) although the running configuration never shows
    them (live fact, XRv9k 24.3.1): such a statement means its positive form must be absent. The other kinds render
    the desired set on the device, so nothing needs translating."""
    desired = set(desired)
    if kind != 'cisco_xrv9k': return desired, set()
    present, absent = set(), set()
    for statement in desired:
        leaf = statement.rsplit(' > ', 1)[-1]
        if leaf.startswith('no '): absent.add(statement[:-len(leaf)] + leaf[3:])
        else: present.add(statement)
    return present, absent


def verify(kind, after, desired, stale, removed_ancestors=(), kept=()):
    """Read-back check: every desired statement present, every stale statement gone, and nothing left under a
    removed ancestor except what the design itself put back there (a container removed and re-created with new
    leaves); a container kept on purpose because manual configuration sits under it (`kept`) is not a failure.
    Returns (missing, remaining)."""
    after = set(after); kept = set(kept); desired = set(desired)
    present, absent = split_negations(kind, desired)
    missing = sorted(s for s in present if s not in after)
    remaining = sorted(s for s in stale if s in after and s not in kept)
    remaining += sorted(s for s in absent if s in after)   # a negated statement that is still there
    remaining += sorted(s for a in removed_ancestors for s in after if _under(kind, a, s) and s not in desired)
    return missing, remaining
