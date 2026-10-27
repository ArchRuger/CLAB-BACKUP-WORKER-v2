"""What a generated fragment may reach a device with: the per-platform filters of the provisioning contract.

netlab's per-device files are merge fragments written for a fresh device (docs/netlab-integration/
PROVISIONING.md §1). Before any of them is staged on a real device, :func:`prepare` turns the ordered
fragments of one device into a single candidate text and a list of the *protected settings it left out*,
each with the module it came from and why. The rules are named here, once per platform, and nothing else
in the application decides what is protected:

* the management interface and anything that names it, the device's name, users, AAA, logging targets
  and static host mappings never go: management, identity and access stay containerlab's and the
  manager's; the one exception is netlab's LLDP-off on the management interface where the image accepts it
  (Junos `protocols lldp interface <mgmt> { disable; }`, IOS XR's global `lldp / no management enable`),
  which keeps LLDP off the shared management network; cEOSLab refuses the EOS form under `Management0`,
  so that block is left out there;
* interface MAC addresses never go: runtime identity, disruptive on a running device;
* cEOS's `normalize` file never goes: it shuts and re-addresses interfaces for a fresh deploy;
* Junos `delete: <hierarchy>;` tags never go: they wipe a whole stanza, manual statements included;
  removal is the ownership ledger's job;
* vSRX (campaign 2 B05, :func:`prepare_vsrx`): nothing under `security` may name the management interface, and
  no `functional-zone management` goes (see that function for the management rule of the security zones).

Everything else is candidate text, kept in the fragments' order. The functions are pure (text in, text
out) so the tests can use the real fragments of the acceptance topology.
"""
import re

EOS_MANAGEMENT = re.compile(r'^interface\s+Management\d*\s*$', re.I)
EOS_PROTECTED_LINE = re.compile(r'^(?:hostname\b|aaa\b|username\b|enable\s+password\b|enable\s+secret\b|logging\b|ip\s+host\b|ipv6\s+host\b|'
                                r'ip\s+name-server\b|management\s+(?:api|ssh|console|telnet|security)\b|ip\s+route\s+(?:vrf\s+\S+\s+)?0\.0\.0\.0/0\b|'
                                r'ipv6\s+route\s+::/0\b|tacacs-server\b|radius-server\b|snmp-server\b|ntp\b)', re.I)
EOS_PROTECTED_INSIDE = re.compile(r'^\s+(?:mac-address\b)', re.I)
JUNOS_DELETE_TAG = re.compile(r'^\s*delete:\s*[^;]*;\s*$')
JUNOS_PROTECTED_LEAF = re.compile(r'^\s*(?:host-name|domain-name|name-server|root-authentication|time-zone|authentication-order)\s[^;]*;\s*$')
JUNOS_PROTECTED_BARE_LEAF = re.compile(r'^\s*management-instance;\s*$')
JUNOS_PROTECTED_BLOCK = re.compile(r'^\s*(?:static-host-mapping|login|services|syslog|management-instance|root-authentication|radius-server|'
                                   r'tacplus-server|interface\s+(?:fxp0|em0|re0:mgmt-0|me0)(?:\.\d+)?)\s*\{')
JUNOS_MGMT_ROUTING_INSTANCE = re.compile(r'^\s*mgmt_junos\s*\{')
IOSXR_PROTECTED_LINE = re.compile(r'^(?:hostname\b|domain\s+(?:ipv4|ipv6)\s+host\b|domain\s+name\b|domain\s+name-server\b|username\b|aaa\b|'
                                  r'logging\s+(?:\d|\S+\.\S+|vrf)\b|ssh\s+server\b|line\s+(?:console|default|template)\b|'
                                  r'telnet\b|xml\s+agent\b|netconf\b|grpc\b|vrf\s+clab-mgmt\b|'
                                  r'tacacs-server\b|radius-server\b|snmp-server\b)', re.I)
# Inside `router static` (which the design may use), the management VRF's routes are containerlab's.
IOSXR_PROTECTED_INSIDE = re.compile(r'^\s+vrf\s+clab-mgmt\b', re.I)
IOSXR_MANAGEMENT = re.compile(r'^interface\s+(?:MgmtEth|Mgmt)\S*\s*$', re.I)
SKIPPED_MODULES = ('normalize',)


def _blocks(text):
    """An indented (EOS, IOS XR) text as [(header_line, [lines...])]: a block is a top-level line with the
    indented lines that follow it; a `!` separator or an unindented line starts the next block."""
    blocks, current = [], None
    for raw in (text or '').splitlines():
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith('!'):
            continue   # blank lines and comments carry no configuration and never end a block
        if line.startswith((' ', '\t')) and current is not None:
            current[1].append(line)
            continue
        current = [line, []]
        blocks.append(current)
    return blocks


def prepare_eos(fragments):
    """(candidate, left_out) for Arista EOS fragments (`show running-config` form)."""
    kept, left_out = [], []
    for module, text in fragments:
        if module in SKIPPED_MODULES:
            left_out.append({'module': module, 'statement': '(whole file)', 'reason': "netlab's pre-deploy interface reset; not applied to a running device"})
            continue
        for header, body in _blocks(text):
            head = header.strip()
            if head == 'end':
                continue
            if EOS_MANAGEMENT.match(head):
                # cEOSLab refuses `no lldp transmit` / `no lldp receive` under Management0 (verified on 4.35.0F: the
                # container's management port has no LLDP), so the whole management block is left out on EOS.
                left_out.append({'module': module, 'statement': head, 'reason': 'management interface'}); continue
            if EOS_PROTECTED_LINE.match(head):
                left_out.append({'module': module, 'statement': head, 'reason': 'device identity, access or management'}); continue
            kept.append(header)
            for line in body:
                if EOS_PROTECTED_INSIDE.match(line):
                    left_out.append({'module': module, 'statement': head + ' > ' + line.strip(), 'reason': 'interface MAC address'}); continue
                kept.append(line)
            kept.append('!')
    return '\n'.join(kept) + ('\n' if kept else ''), left_out


def prepare_iosxr(fragments):
    """(candidate, left_out) for Cisco IOS XR fragments (`show running-config` form)."""
    kept, left_out = [], []
    for module, text in fragments:
        if module in SKIPPED_MODULES:
            left_out.append({'module': module, 'statement': '(whole file)', 'reason': 'not applied to a running device'}); continue
        for header, body in _blocks(text):
            head = header.strip()
            if head == 'end':
                continue
            if IOSXR_MANAGEMENT.match(head):
                left_out.append({'module': module, 'statement': head, 'reason': 'management interface'}); continue
            if IOSXR_PROTECTED_LINE.match(head):
                left_out.append({'module': module, 'statement': head, 'reason': 'device identity, access or management'}); continue
            kept.append(header)
            skipping_depth = None
            for line in body:
                depth = len(line) - len(line.lstrip(' '))
                if skipping_depth is not None:
                    if depth > skipping_depth: continue
                    skipping_depth = None
                if IOSXR_PROTECTED_INSIDE.match(line):
                    left_out.append({'module': module, 'statement': head + ' > ' + line.strip(), 'reason': 'management VRF'}); skipping_depth = depth; continue
                kept.append(line)
            kept.append('!')
    return '\n'.join(kept) + ('\n' if kept else ''), left_out


def _junos_blocks(text):
    """Split a Junos curly-brace text into a list of (line, depth) with brace nesting tracked; used to drop
    whole named blocks and single leaves without re-indenting the rest."""
    depth, rows = 0, []
    for raw in (text or '').splitlines():
        line = raw.rstrip()
        stripped = line.strip()
        opens, closes = stripped.endswith('{'), stripped == '}'
        rows.append((line, depth, opens, closes))
        if opens:
            depth += 1
        elif closes:
            depth = max(0, depth - 1)
    return rows


# The management interface named as a whole word anywhere in a line (vSRX security rule).
JUNOS_MGMT_WORD = re.compile(r'(?<![\w/:.-])(?:fxp0|em0|re0:mgmt-0|me0)(?:\.\d+)?(?![\w/:-])')
JUNOS_FUNCTIONAL_ZONE = re.compile(r'^\s*functional-zone\s+management\b')
JUNOS_MGMT_LLDP = re.compile(r'^\s*interface\s+(?:fxp0|em0|re0:mgmt-0|me0)(?:\.\d+)?\s*\{\s*$')
# The management interface as its own block under `interfaces { … }` (netlab never renders it; a fragment that did would be wrong).
JUNOS_MGMT_INTERFACE = re.compile(r'^\s*(?:fxp0|em0|re0:mgmt-0|me0)(?:\.\d+)?\s*\{\s*$')


def prepare_junos(fragments, security_rule=False):
    """(candidate, left_out) for Junos fragments (curly-brace form as `load merge terminal` takes it).

    A block is dropped whole when its header is protected (`static-host-mapping`, `login`, ...). The
    management interface may appear only under `protocols lldp` as `interface <mgmt> { disable; }`, which
    keeps LLDP off the shared management network and is kept; anywhere else a management interface block
    is protected. `name { }` presence blocks are meaningful Junos syntax (`interface lo0.0 { }` puts the
    loopback in an OSPF area) and stay; only a block this filter emptied itself is pruned. `security_rule` adds the
    vSRX rule of :func:`prepare_vsrx`."""
    kept, left_out = [], []
    for module, text in fragments:
        if module in SKIPPED_MODULES:
            left_out.append({'module': module, 'statement': '(whole file)', 'reason': 'not applied to a running device'}); continue
        skip_until = None; stack = []; emptied = set()
        for line, depth, opens, closes in _junos_blocks(text):
            stripped = line.strip()
            if skip_until is not None:
                if closes and depth - 1 == skip_until:
                    skip_until = None
                continue
            if not stripped:
                continue
            if JUNOS_DELETE_TAG.match(line):
                left_out.append({'module': module, 'statement': stripped, 'reason': 'a delete tag wipes a whole stanza; removal is the ledger\'s'})
                _mark_emptied(kept, stack, emptied); continue
            if JUNOS_PROTECTED_LEAF.match(line) or JUNOS_PROTECTED_BARE_LEAF.match(line):
                left_out.append({'module': module, 'statement': stripped, 'reason': 'device identity, access or management'})
                _mark_emptied(kept, stack, emptied); continue
            under_security = any(re.match(r'^\s*security\b', header) for _, header in stack)
            if security_rule and ((under_security and (JUNOS_MGMT_WORD.search(stripped) or JUNOS_FUNCTIONAL_ZONE.match(line)))
                                  or (not stack and re.match(r'^\s*security\s', line) and (JUNOS_MGMT_WORD.search(stripped) or 'functional-zone' in stripped))):
                left_out.append({'module': module, 'statement': stripped.rstrip('{').strip(), 'reason': 'management interface in a security zone or policy'})
                if opens: skip_until = depth
                _mark_emptied(kept, stack, emptied); continue
            under_lldp = any(header.strip().startswith('lldp') for _, header in stack)
            under_interfaces = bool(stack) and stack[-1][1].strip().startswith('interfaces')
            under_routing_instances = bool(stack) and stack[-1][1].strip().startswith('routing-instances')
            if ((JUNOS_PROTECTED_BLOCK.match(line) and not (under_lldp and JUNOS_MGMT_LLDP.match(line)))
                    or (under_interfaces and JUNOS_MGMT_INTERFACE.match(line))
                    or (under_routing_instances and JUNOS_MGMT_ROUTING_INSTANCE.match(line))):
                left_out.append({'module': module, 'statement': stripped.rstrip('{').strip(), 'reason': 'management, access or static host mapping'})
                skip_until = depth; _mark_emptied(kept, stack, emptied); continue
            kept.append(line)
            if opens: stack.append((len(kept) - 1, line))
            elif closes and stack: stack.pop()
        _prune_emptied(kept, emptied)
    return '\n'.join(kept) + ('\n' if kept else ''), left_out


def _mark_emptied(kept, stack, emptied):
    """Remember the innermost open block a protected child was removed from; it is pruned at the end if
    nothing else is left inside it."""
    if stack: emptied.add(stack[-1][0])


def _prune_emptied(kept, emptied):
    """Drop `header {` / `}` pairs whose header index is in `emptied` and that hold nothing else; repeat
    outwards so a parent emptied by the pruning of its only child goes too."""
    changed = True
    while changed:
        changed = False
        for index in sorted(emptied, reverse=True):
            if 0 <= index < len(kept) - 1 and kept[index].rstrip().endswith('{') and kept[index + 1].strip() == '}':
                parent = next((i for i in range(index - 1, -1, -1) if kept[i].rstrip().endswith('{')), None)
                del kept[index:index + 2]
                emptied.discard(index)
                emptied = {i if i < index else i - 2 for i in emptied}
                if parent is not None: emptied.add(parent)
                changed = True
                break


def prepare_vsrx(fragments):
    """(candidate, left_out) for vSRX: :func:`prepare_junos` plus the security rule (campaign 2 B05).

    The management rule of an SRX's security zones, written down here because a zone-less or narrowed configuration
    loses whatever path it guards: an interface that carries management must stay in a zone whose
    `host-inbound-traffic system-services` keeps ssh and ping, or not be in the zone model at all. On the
    containerlab vSRX the management interface is `fxp0`, which is outside the zone model (live, docs/parity-campaign/
    evidence/b03-vsrx-boot-2026-10-27.md: Junos 23.2R2.21 boots with no zone at all and SSH reaches it), so the design
    keeps management by never touching it: anything under `security` that names the management interface, and a
    `functional-zone management` block, is left out here; a `delete:` tag (which could wipe a zone's host-inbound
    services) is left out by :func:`prepare_junos`; and the ownership ledger never removes or replaces an unowned
    statement, so an existing zone's `host-inbound-traffic` (for example a `trust` zone a person configured) is never
    narrowed. netlab 26.09 writes no security zone for vsrx in the modules this design accepts (only its
    firewall.zonebased plugin does, and plugins are refused); it writes `security forwarding-options family iso|mpls
    mode packet-based` for IS-IS and MPLS, which is kept. Data ports the design addresses are therefore left out of
    every zone: on a flow-mode vSRX their traffic, the routing protocols included, is dropped until a zone admits it.
    Whether the design should add such a zone is decided by the live pass of B05 phase 2, not here."""
    return prepare_junos(fragments, security_rule=True)


PREPARERS = {'arista_ceos': prepare_eos, 'cisco_xrv9k': prepare_iosxr,
             'juniper_cjunosevolved': prepare_junos, 'juniper_vjunosswitch': prepare_junos,
             'juniper_vjunosrouter': prepare_junos, 'juniper_vsrx': prepare_vsrx}


def prepare(kind, fragments):
    """The candidate for a device of containerlab `kind` from its ordered (module, text) fragments, and the
    protected settings left out. Raises KeyError for a kind without a provisioning driver."""
    return PREPARERS[kind](list(fragments))
