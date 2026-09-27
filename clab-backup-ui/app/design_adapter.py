"""From the containerlab topology and the intent to the netlab topology: profiles, endpoint mapping, pins.

The containerlab topology stays the only description of the lab's devices and wiring; the intent
(:mod:`design_intent`) says what to build on it. This module joins the two into the data-only netlab
topology :mod:`design_engine` compiles, and it is the one place that decides identities:

``manager node ↔ containerlab node/kind/image ↔ netlab device profile ↔ containerlab endpoint ↔ NOS interface``

* The profile comes from the capability model (:func:`design_capabilities.profile_for`), never from a
  guess; a kind without a profile is left out of the design with that reason.
* Every link endpoint is mapped explicitly, from the kinds' documented port rules the map already uses
  (:mod:`topology`: cEOS ``ethN = EthernetN``, vJunos-switch ``eth1 = ge-0/0/0``, cJunosEvolved
  ``eth4 = et-0/0/0``, XRv9k ``eth1 = Gi0/0/0/0``), spelled the way the NOS and netlab spell it, or from
  a student's explicit override. An endpoint that cannot be mapped is never guessed: its link is left out
  and both devices are marked *blocked*, so their generated files are not applied.
* Allocations pinned in the intent's ledger (node ids, loopbacks, link prefixes) are passed to the engine
  as explicit assignments; an unpinned node or link is allocated by the engine.
* Management addressing is never designed: the node's management address is passed only so netlab has a
  management identity (``mgmt.ipv4``/``mgmt.ifname``), and no pool may overlap it (checked by the intent).

Nothing here touches a device or the VM; :func:`build` is pure.
"""
import copy
import ipaddress
import re

from .design_intent import MODULES, link_key
from .inventory import read_data
from .topology import CONTAINER_NAME, PORT_RULES, container_interface, displayed_interface

# containerlab link types the design can address: only the point-to-point veth (the default). Everything
# else (management network, host, macvlan, vxlan, dummy) is left out of the design with a note.
VETH_TYPES = ('', 'veth')
# The NOS spelling netlab expects for a data port, per containerlab kind: the map's displayed name is the
# short form on IOS XR (`Gi0/0/0/0`), which netlab's iosxr templates do not use.
LONG_NAMES = {'cisco_xrv9k': (re.compile(r'(?i)^gi(?:gabitethernet)?(0/0/0/\d+)$'), 'GigabitEthernet'),
              'vr-xrv9k': (re.compile(r'(?i)^gi(?:gabitethernet)?(0/0/0/\d+)$'), 'GigabitEthernet')}
# What an explicit interface override may look like, per kind (the NOS's own data-port names only).
OVERRIDE_PATTERNS = {'arista_ceos': re.compile(r'^Ethernet\d+(?:/\d+)*$'),
                     'juniper_vjunosswitch': re.compile(r'^(?:ge|xe|et)-\d+/\d+/\d+$'),
                     'juniper_cjunosevolved': re.compile(r'^(?:ge|xe|et)-\d+/\d+/\d+$'),
                     'cisco_xrv9k': re.compile(r'^(?:GigabitEthernet|TenGigE|HundredGigE)\d+/\d+/\d+/\d+$'),
                     'linux': re.compile(r'^(?:eth|ens|enp)[0-9a-z]+$')}
TOPOLOGY_NAME = 'netdesign'
# Node names that would collide with netlab's own link keys; such a device cannot be part of a design.
RESERVED_NODE_NAMES = frozenset(('prefix', 'pool', 'role', 'type', 'name', 'mtu', 'bandwidth', 'unnumbered',
                                 'ipv4', 'ipv6', 'interfaces', 'linkindex', 'linkid', 'group', 'members', 'bridge',
                                 'disable', 'gateway', 'shutdown', 'ra', 'endpoints', *MODULES))


class AdapterError(ValueError):
    """The lab's topology cannot be read into a design; the message is student-facing."""


# --- reading the containerlab topology -------------------------------------------------------------------

def parse_links(definition_yaml):
    """The containerlab links of a topology text as [{'key', 'type', 'endpoints': [(node, interface), ...]}].

    Endpoint syntaxes: `"node:iface"` strings and `{node, interface}` mappings (also the exporter's
    `node-short-name`/`interface-name` keys). A link whose endpoints cannot be read is reported with an
    empty endpoint list and the reason under 'problem'; the caller leaves it out."""
    data = read_data(definition_yaml.encode() if isinstance(definition_yaml, str) else definition_yaml)
    body = data.get('topology') if isinstance(data.get('topology'), dict) else {}
    rows = body.get('links') or []
    if not isinstance(rows, list): raise AdapterError('The topology links are not a list.')
    result = []
    for index, link in enumerate(rows[:4000]):
        entry = {'index': index, 'type': '', 'endpoints': [], 'problem': ''}
        if not isinstance(link, dict): entry['problem'] = 'not a mapping'; result.append(entry); continue
        entry['type'] = str(link.get('type') or '')
        endpoints = link.get('endpoints')
        if isinstance(endpoints, dict): endpoints = [endpoints[k] for k in ('a', 'z') if k in endpoints]
        if not isinstance(endpoints, list) or len(endpoints) != 2:
            entry['problem'] = 'no two endpoints' if entry['type'] in VETH_TYPES else 'link type ' + entry['type'] + ' is not a device-to-device link'
            result.append(entry); continue
        pair = []
        for end in endpoints:
            if isinstance(end, str): node, _, interface = end.partition(':')
            elif isinstance(end, dict):
                node = end.get('node', end.get('node-short-name', '')); interface = end.get('interface', end.get('interface-name', ''))
            else: node = interface = ''
            if not isinstance(node, str) or not isinstance(interface, str) or not node or not interface or len(node) > 200 or len(interface) > 64:
                entry['problem'] = 'an endpoint could not be read'; break
            pair.append((node, interface))
        if entry['problem']: result.append(entry); continue
        entry['endpoints'] = pair; entry['key'] = link_key(pair)
        if entry['type'] not in VETH_TYPES: entry['problem'] = 'link type ' + entry['type'] + ' is not a device-to-device link'
        result.append(entry)
    return result


# containerlab's default management network when a topology names none (docs: the `clab` Docker network).
DEFAULT_MANAGEMENT = {'ipv4-subnet': '172.20.20.0/24', 'ipv6-subnet': '3fff:172:20:20::/64'}


def management_networks(definition_yaml, lab_nodes):
    """(label, ip_network) pairs no design address may overlap: the topology's management subnets (or
    containerlab's defaults when the topology names none; with `auto` the /24 or /64 around each device
    address as well), and every device's management address."""
    networks = []
    try:
        data = read_data(definition_yaml.encode() if isinstance(definition_yaml, str) else definition_yaml) if definition_yaml else {}
    except ValueError:
        data = {}
    mgmt = data.get('mgmt') if isinstance(data.get('mgmt'), dict) else {}
    auto = False
    for key in ('ipv4-subnet', 'ipv6-subnet'):
        value = mgmt.get(key)
        if value == 'auto': auto = True; continue
        if isinstance(value, str):
            try: networks.append(('mgmt ' + key, ipaddress.ip_network(value, strict=False))); continue
            except ValueError: pass
        networks.append(('containerlab default management ' + key, ipaddress.ip_network(DEFAULT_MANAGEMENT[key])))
    for node in lab_nodes or []:
        address = node.get('address') if isinstance(node, dict) else None
        try: host = ipaddress.ip_network(address)
        except (ValueError, TypeError, AttributeError): continue
        networks.append(('device ' + str(node.get('short_name') or node.get('name')), host))
        if auto: networks.append(('management network of ' + str(node.get('short_name') or node.get('name')), host.supernet(new_prefix=24 if host.version == 4 else 64)))
    return networks


# --- endpoint mapping ------------------------------------------------------------------------------------

def nos_interface(kind, clab_interface):
    """The NOS's own name of the data port a containerlab endpoint names, or '' when the kind has no
    documented rule for it (then the port is never guessed)."""
    if not isinstance(clab_interface, str) or not clab_interface.strip(): return ''
    value = clab_interface.strip()
    if kind == 'linux' or kind not in PORT_RULES and kind not in LONG_NAMES:
        return 'eth' + CONTAINER_NAME.fullmatch(value)[1] if kind == 'linux' and CONTAINER_NAME.fullmatch(value) else ''
    veth = container_interface(kind, value)
    if not veth: return ''
    shown = displayed_interface(kind, veth)
    if shown == veth: return ''      # a veth the image reserves for itself (e.g. cJunosEvolved eth1-eth3)
    rule = LONG_NAMES.get(kind)
    if rule:
        match = rule[0].fullmatch(shown)
        return rule[1] + match[1] if match else ''
    return shown


def map_endpoint(kind, clab_interface, override=None):
    """{'clab', 'veth', 'nos', 'source'} for one link end. `source` is 'rule' (documented port rule),
    'manual' (the student's override, accepted only in the kind's own port spelling) or '' (unresolved)."""
    veth = container_interface(kind, clab_interface) if isinstance(clab_interface, str) else ''
    entry = {'clab': clab_interface, 'veth': veth, 'nos': '', 'source': ''}
    if isinstance(override, str) and override.strip():
        pattern = OVERRIDE_PATTERNS.get(kind)
        if pattern and pattern.fullmatch(override.strip()):
            entry.update(nos=override.strip(), source='manual'); return entry
        entry['reason'] = 'The interface override does not look like a ' + str(kind) + ' data port'
        return entry
    nos = nos_interface(kind, clab_interface)
    if nos: entry.update(nos=nos, source='rule')
    else: entry['reason'] = 'No documented port rule maps ' + str(clab_interface) + ' on kind ' + str(kind or 'unknown')
    return entry


# --- the netlab topology -----------------------------------------------------------------------------------

def _strip_family(value, families):
    """Drop the address families the design switched off from a pool, loopback or prefix mapping."""
    if not isinstance(value, dict): return value
    return {k: v for k, v in value.items() if k not in ('ipv4', 'ipv6') or families.get(k, True)}


def build(definition_yaml, lab_nodes, intent, profile_for, pins=None):
    """The netlab topology for a lab and its intent, with every identity decision made explicit.

    `lab_nodes` are the lab record's nodes (name, short_name, definition_node, kind, platform, address);
    `profile_for(kind)` is the capability model's profile lookup; `pins` is an optional ledger-shaped dict
    laid over the intent's allocations (the service uses it to force link prefixes on a second pass after
    a collision, see collisions()). Nodes are emitted routers first, then hosts, each sorted by name, and
    links sorted by key, so the same semantic input yields the same engine output whatever the order of
    the containerlab file. Returns
    {'topology': dict, 'nodes': {short_name: {'kind', 'profile', 'included', 'role', 'reason', 'blocked'}},
     'links': [{'key', 'included', 'reason', 'endpoints': {node: mapping}}], 'link_keys': [included keys in
     emission order], 'mapping': {key: {node: mapping}} for included links, 'blocked': {node: reason},
     'notes': [str]}. Pure: nothing is read from the VM or a device."""
    from .discovery import parse_definition
    try: parsed = parse_definition(definition_yaml.encode() if isinstance(definition_yaml, str) else definition_yaml)
    except ValueError as exc: raise AdapterError('The lab topology cannot be read: ' + str(exc))
    families = intent.get('families') or {'ipv4': True, 'ipv6': True}
    modules = list(intent.get('modules') or [])
    node_settings = intent.get('nodes') or {}
    ledger = copy.deepcopy(intent.get('allocations') or {})
    for section, values in (pins or {}).items():
        if isinstance(values, dict): ledger.setdefault(section, {}).update(copy.deepcopy(values))
    overrides = intent.get('interfaces') or {}
    by_short = {n.get('definition_node') or n.get('short_name') or n['name']: n for n in (lab_nodes or [])}
    nodes = {}; notes = []; blocked = {}
    for node in parsed['nodes']:
        short = node['definition_node']; kind = node.get('kind') or ''
        settings = node_settings.get(short) or {}
        profile = profile_for(kind)
        row = {'kind': kind, 'image': node.get('image', ''), 'profile': profile['netlab_device'] if profile else '',
               'included': False, 'role': settings.get('role') or ('host' if profile and profile.get('role') == 'host' else 'router'), 'reason': '', 'blocked': ''}
        if short in RESERVED_NODE_NAMES: row['reason'] = 'The device name ' + short + ' is reserved by the design engine'
        elif not profile: row['reason'] = 'No design profile is mapped to the containerlab kind ' + (kind or 'unknown')
        elif row['role'] == 'exclude': row['reason'] = 'Excluded from the design by its settings'
        else: row['included'] = True
        nodes[short] = row
    included = {short for short, row in nodes.items() if row['included']}
    if not included: raise AdapterError('No device of this lab can be part of a design: none has a supported kind.')
    topology = {'name': TOPOLOGY_NAME, 'provider': 'external', 'module': modules,
                'addressing': {name: _strip_family(pool, families) for name, pool in (intent.get('addressing') or {}).items()},
                'nodes': {}, 'links': []}
    if not families.get('ipv4', True): topology['addressing'].setdefault('router_id', {'ipv4': '10.0.0.0/24', 'prefix': 32})
    for module in MODULES:
        if module in intent and intent[module] not in (None, {}, True) and module in modules: topology[module] = copy.deepcopy(intent[module])
    for key in ('vlans', 'vrfs'):
        if intent.get(key): topology[key] = copy.deepcopy(intent[key])
    ordered = sorted(parsed['nodes'], key=lambda n: (nodes[n['definition_node']]['role'] == 'host', n['definition_node']))
    for node in ordered:
        short = node['definition_node']; row = nodes[short]
        if not row['included']: continue
        profile = profile_for(row['kind']); settings = node_settings.get(short) or {}
        entry = {'device': profile['netlab_device'], 'mgmt': {'ifname': profile['mgmt_if']}}
        stored = by_short.get(short) or {}
        address = stored.get('address') or node.get('address') or ''
        try: entry['mgmt']['ipv4'] = str(ipaddress.ip_address(address))
        except ValueError: notes.append(short + ': the management address is not known yet (a name, not an address); it is not part of any generated configuration.')
        if row['role'] == 'host': entry['role'] = 'host'
        ident = (ledger.get('node_ids') or {}).get(short)
        if isinstance(ident, int) and not isinstance(ident, bool): entry['id'] = ident
        loop = settings.get('loopback')
        if loop is None: loop = (ledger.get('loopbacks') or {}).get(short)
        if loop is False: entry['loopback'] = False
        elif isinstance(loop, dict) and _strip_family(loop, families): entry['loopback'] = _strip_family(loop, families)
        own = settings.get('modules')
        # netlab's own rule: a device's `modules` list, when given, is that device's whole module list (a device
        # without the vlan module beside two that carry it; a device with an extra one), not an addition.
        if isinstance(own, list): entry['module'] = [m for m in MODULES if m in own]
        elif row['role'] == 'host': entry['module'] = []
        for module in MODULES:
            if module in settings and settings[module] not in (None, {}): entry[module] = copy.deepcopy(settings[module])
        for key in ('vlans', 'vrfs'):
            if settings.get(key): entry[key] = copy.deepcopy(settings[key])
        topology['nodes'][short] = entry
    links = []; link_keys = []; mapping = {}
    # Link aggregation: a link whose `lag.members` names other links of the lab carries the bundle; the members are
    # emitted inside it (netlab's `lag.members`, each with the real port names) and never as links of their own.
    lag_members = {}
    for key, settings in (intent.get('links') or {}).items():
        members = ((settings or {}).get('lag') or {}).get('members') if isinstance((settings or {}).get('lag'), dict) else None
        if isinstance(members, list):
            for member in members: lag_members[member] = key
    member_ports = {}; bundles = []

    def port_index(nos_name):
        # netlab keeps only `ifindex` on a member's interfaces (its `lag` module rebuilds the physical links from it
        # and names them from the device template: Ethernet{n}, ge-0/0/{n}, et-0/0/{n}, GigabitEthernet0/0/0/{n}),
        # so a member port is named by the trailing number of its device name; `ifname` would leak onto the bundle.
        found = re.findall(r'\d+', nos_name or '')
        return int(found[-1]) if found else None

    for link in sorted(parse_links(definition_yaml), key=lambda l: (l.get('key', ''), l['index'])):
        row = {'key': link.get('key', ''), 'included': False, 'reason': '', 'endpoints': {}}
        if link['problem']: row['reason'] = link['problem']; links.append(row); continue
        ends = link['endpoints']
        missing = [n for n, _ in ends if n not in nodes]
        if missing: row['reason'] = 'Endpoint device not in the topology: ' + ', '.join(missing); links.append(row); continue
        outside = [n for n, _ in ends if not nodes[n]['included']]
        if outside: row['reason'] = 'Left out: ' + ', '.join(outside) + ' is not part of the design'; links.append(row); continue
        if ends[0][0] == ends[1][0]: row['reason'] = 'A link from a device to itself is not designed'; links.append(row); continue
        for node_name, interface in ends:
            row['endpoints'][node_name] = map_endpoint(nodes[node_name]['kind'], interface, (overrides.get(row['key']) or {}).get(node_name))
        unresolved = [n for n, m in row['endpoints'].items() if not m['nos']]
        if unresolved:
            row['reason'] = 'Interface not mapped on ' + ', '.join(unresolved)
            for n in ends:
                blocked.setdefault(n[0], 'Link ' + row['key'] + ' has an interface the manager cannot map to a device port; map it under Advanced or leave the link out.')
            links.append(row); continue
        settings = (intent.get('links') or {}).get(row['key']) or {}
        if row['key'] in lag_members:
            # A member of an aggregation carried by another link: its ports belong to that bundle.
            member_ports[row['key']] = {n: {'ifindex': port_index(m['nos'])} for n, m in row['endpoints'].items()}
            row['included'] = True; row['reason'] = 'Member of the link aggregation carried by ' + lag_members[row['key']]
            links.append(row); mapping[row['key']] = row['endpoints']; continue
        bundle = isinstance(settings.get('lag'), dict) and isinstance(settings['lag'].get('members'), list)
        netlab_link = {}
        for node_name, m in row['endpoints'].items():
            end = {} if bundle else {'ifname': m['nos']}   # a bundle's own interface is the engine's (Port-Channel, ae, Bundle-Ether)
            for k, v in ((settings.get('endpoints') or {}).get(node_name) or {}).items():
                if k in ('ipv4', 'ipv6') and not families.get(k, True): continue
                end[k] = copy.deepcopy(v)
            netlab_link[node_name] = end
        prefix = settings.get('prefix')
        if prefix is None: prefix = (ledger.get('links') or {}).get(row['key'])
        if prefix is False: netlab_link['prefix'] = False
        elif isinstance(prefix, dict) and _strip_family(prefix, families): netlab_link['prefix'] = _strip_family(prefix, families)
        for k in ('pool', 'role', 'type', 'name', 'mtu', 'bandwidth', 'unnumbered'):
            if k in settings: netlab_link[k] = settings[k]
        for k in ('ipv4', 'ipv6'):
            if k in settings and families.get(k, True): netlab_link[k] = settings[k]
        for module in MODULES:
            if module in settings and settings[module] not in (None, {}): netlab_link[module] = copy.deepcopy(settings[module])
        if bundle:
            # Its members may come later in key order: the bundle is emitted after every member port is known.
            bundles.append((row, netlab_link, settings)); continue
        row['included'] = True
        links.append(row); link_keys.append(row['key']); mapping[row['key']] = row['endpoints']
        topology['links'].append(netlab_link)
    for row, netlab_link, settings in sorted(bundles, key=lambda b: b[0]['key']):
        own_ports = {n: {'ifindex': port_index(m['nos'])} for n, m in row['endpoints'].items()}
        netlab_link['lag']['members'] = [own_ports] + [member_ports[k] for k in settings['lag']['members'] if k in member_ports]
        row['included'] = True
        links.append(row); link_keys.append(row['key']); mapping[row['key']] = row['endpoints']
        topology['links'].append(netlab_link)
    for short, reason in blocked.items(): nodes[short]['blocked'] = reason
    for row in links:
        if not row['included'] and row['reason']: notes.append('Link ' + (row['key'] or '#' + str(row.get('index', ''))) + ': ' + row['reason'])
    for short, row in nodes.items():
        if not row['included']: notes.append(short + ': ' + row['reason'])
    return {'topology': topology, 'nodes': nodes, 'links': links, 'link_keys': link_keys, 'mapping': mapping,
            'blocked': blocked, 'notes': notes}


# --- allocation collisions ------------------------------------------------------------------------------

def _link_prefixes(transformed, link_keys):
    """{link_key: {family: ip_network}} for the transformed links, matched to keys by emission order."""
    result = {}
    for index, link in enumerate(transformed.get('links') or []):
        if index >= len(link_keys) or not isinstance(link, dict): break
        prefix = link.get('prefix') if isinstance(link.get('prefix'), dict) else {}
        entry = {}
        for family in ('ipv4', 'ipv6'):
            try: entry[family] = ipaddress.ip_network(prefix[family], strict=False)
            except (KeyError, ValueError, TypeError): pass
        if entry: result[link_keys[index]] = entry
    return result


def link_prefixes(transformed, link_keys):
    """{link_key: {family: 'prefix'}} for every transformed link: what a second pass pins so that nothing moves."""
    return {key: {family: str(network) for family, network in families.items()} for key, families in _link_prefixes(transformed, link_keys).items()}


def collisions(transformed, link_keys, ledger):
    """The links the engine allocated on top of something already taken: netlab's pool allocator does
    not skip statically assigned prefixes, so an unpinned link can receive a prefix a pinned link owns.
    Returns [{'key', 'family', 'prefix', 'with'}] for every unpinned link whose new prefix overlaps a
    pinned link prefix or another link's prefix; pinned links themselves are never reported."""
    pinned = (ledger or {}).get('links') or {}
    current = _link_prefixes(transformed, link_keys)
    found = []
    for key, families in current.items():
        for family, network in families.items():
            if family in (pinned.get(key) or {}): continue
            for other_key, other_families in current.items():
                other = other_families.get(family)
                if other_key == key or other is None or not other.overlaps(network): continue
                if family in (pinned.get(other_key) or {}) or other_key < key:
                    found.append({'key': key, 'family': family, 'prefix': str(network), 'with': other_key}); break
    return found


def _pool_of(network, pools):
    """The (name, pool network) of `pools` that contains `network`, or (None, None)."""
    for name, pool in (pools or {}).items():
        if not isinstance(pool, dict): continue
        value = pool.get('ipv4' if network.version == 4 else 'ipv6')
        try: candidate = ipaddress.ip_network(value, strict=False)
        except (ValueError, TypeError): continue
        if candidate.version == network.version and candidate.supernet_of(network): return name, candidate
    return None, None


def fix_collisions(transformed, link_keys, ledger, pools, avoid=()):
    """Explicit prefixes that resolve collisions(): for each colliding link and family, the first subnet of
    the same size in the same pool that overlaps nothing already used (pinned prefixes, the other links'
    prefixes, the loopback pool, `avoid` networks and the prefixes chosen here). Returns
    {link_key: {family: 'prefix'}}; a link whose pool cannot be found or is exhausted is left out."""
    current = _link_prefixes(transformed, link_keys)
    colliding = collisions(transformed, link_keys, ledger)
    used = list(avoid)
    for key, families in current.items():
        for family, network in families.items():
            if not any(c['key'] == key and c['family'] == family for c in colliding): used.append(network)
    for entry in ((ledger or {}).get('links') or {}).values():
        for value in (entry or {}).values():
            try: used.append(ipaddress.ip_network(value, strict=False))
            except (ValueError, TypeError): pass
    for name, pool in (pools or {}).items():
        if name == 'loopback' and isinstance(pool, dict):
            for family in ('ipv4', 'ipv6'):
                try: used.append(ipaddress.ip_network(pool[family], strict=False))
                except (KeyError, ValueError, TypeError): pass
    chosen = {}
    for entry in colliding:
        network = current[entry['key']][entry['family']]
        _, pool = _pool_of(network, pools)
        if pool is None: continue
        for candidate in pool.subnets(new_prefix=network.prefixlen):
            if any(candidate.version == u.version and candidate.overlaps(u) for u in used): continue
            chosen.setdefault(entry['key'], {})[entry['family']] = str(candidate); used.append(candidate); break
    return chosen


def overlaps(transformed, avoid=()):
    """Link prefixes and loopback addresses that still overlap after allocation (with each other or with the
    `avoid` networks, e.g. the lab's management networks as (label, network) pairs), per family, as
    [{'family', 'a', 'b'}] with a and b naming the link index, the node or the avoided network. Empty means a
    clean plan."""
    guarded = [('ipv4' if net.version == 4 else 'ipv6', 'management ' + str(label), net) for label, net in avoid]
    items = []; segment = {}   # links of one VLAN are one segment: netlab gives them the VLAN's subnet on purpose
    for index, link in enumerate(transformed.get('links') or []):
        prefix = link.get('prefix') if isinstance(link, dict) and isinstance(link.get('prefix'), dict) else {}
        label = 'link ' + str(link.get('linkindex', index + 1))
        access = (link.get('vlan') or {}).get('access') if isinstance(link, dict) and isinstance(link.get('vlan'), dict) else None
        if isinstance(access, str) and access: segment[label] = 'vlan ' + access
        for family in ('ipv4', 'ipv6'):
            try: items.append((family, label, ipaddress.ip_network(prefix[family], strict=False)))
            except (KeyError, ValueError, TypeError): pass
    hosts = []   # every interface address (VRF loopbacks included): checked against the guarded networks only
    for name, node in (transformed.get('nodes') or {}).items():
        if not isinstance(node, dict): continue
        loop = node.get('loopback') if isinstance(node.get('loopback'), dict) else {}
        for family in ('ipv4', 'ipv6'):
            try: items.append((family, 'loopback of ' + str(name), ipaddress.ip_network(loop[family], strict=False)))
            except (KeyError, ValueError, TypeError): pass
        for interface in (node.get('interfaces') or [])[:512]:
            if not isinstance(interface, dict): continue
            for family in ('ipv4', 'ipv6'):
                try: value = ipaddress.ip_interface(interface[family])
                except (KeyError, ValueError, TypeError): continue
                hosts.append((family, str(interface.get('ifname', '')) + ' of ' + str(name), ipaddress.ip_network(value.ip)))
                if value.network.prefixlen < value.network.max_prefixlen: hosts.append((family, 'network of ' + str(interface.get('ifname', '')) + ' of ' + str(name), value.network))
    found = []
    for i, (family, a, na) in enumerate(items):
        for family_b, b, nb in items[i + 1:] + guarded:   # plan items against each other and against the guarded networks, never guarded against guarded
            if segment.get(a) and segment.get(a) == segment.get(b): continue   # two access ports of the same VLAN share its subnet
            if family == family_b and na.version == nb.version and na.overlaps(nb): found.append({'family': family, 'a': a, 'b': b})
    for family, a, na in hosts:
        for family_b, b, nb in guarded:
            if family == family_b and na.version == nb.version and nb.overlaps(na): found.append({'family': family, 'a': a, 'b': b})
    return found[:200]


# --- the plan a student reads ---------------------------------------------------------------------------

def _neighbors(interface):
    return [{'node': n.get('node', ''), 'ifname': n.get('ifname', ''), 'ipv4': n.get('ipv4', ''), 'ipv6': n.get('ipv6', '')}
            for n in interface.get('neighbors') or [] if isinstance(n, dict)][:64]


def plan_summary(transformed, mapping=None):
    """A readable, bounded addressing and adjacency plan from a transformed topology: per device its
    identity, loopback, interfaces with their containerlab port, addresses, neighbours and protocol
    settings, and its BGP sessions; per link its prefix and ends. Data only; timestamps are not part of it."""
    clab_names = {}
    for key, ends in (mapping or {}).items():
        for node, m in ends.items(): clab_names[(node, m.get('nos', ''))] = m.get('clab', '')
    devices = []
    for name, node in sorted((transformed.get('nodes') or {}).items()):
        if not isinstance(node, dict): continue
        loop = node.get('loopback') if isinstance(node.get('loopback'), dict) else {}
        row = {'name': name, 'device': node.get('device', ''), 'id': node.get('id'), 'role': node.get('role', 'router'),
               'modules': list(node.get('module') or []), 'loopback': {f: loop.get(f, '') for f in ('ipv4', 'ipv6')},
               'router_id': '', 'interfaces': [], 'bgp': None, 'ospf': None, 'isis': None}
        for module in ('ospf', 'bgp', 'isis'):
            body = node.get(module)
            if isinstance(body, dict) and isinstance(body.get('router_id'), str) and not row['router_id']: row['router_id'] = body['router_id']
        for interface in (node.get('interfaces') or [])[:256]:
            if not isinstance(interface, dict): continue
            ifname = interface.get('ifname', ''); base = ifname.rsplit('.', 1)[0] if ifname.endswith('.0') else ifname
            entry = {'ifname': ifname, 'clab': clab_names.get((name, base), clab_names.get((name, ifname), '')),
                     'type': interface.get('type', ''), 'name': interface.get('name', ''),
                     'ipv4': interface.get('ipv4', ''), 'ipv6': interface.get('ipv6', ''), 'neighbors': _neighbors(interface)}
            for module in ('ospf', 'isis', 'bgp', 'vlan', 'vrf', 'lag', 'gateway', 'bfd', 'stp', 'dhcp', 'mpls', 'sr', 'evpn', 'vxlan', 'eigrp', 'ripv2'):
                value = interface.get(module)
                if isinstance(value, (dict, str, int, bool)) and value not in ('', {}): entry[module] = copy.deepcopy(value) if isinstance(value, dict) else value
            if isinstance(interface.get('vrf'), str): entry['vrf'] = interface['vrf']
            row['interfaces'].append(entry)
        bgp = node.get('bgp')
        if isinstance(bgp, dict):
            row['bgp'] = {'as': bgp.get('as'), 'router_id': bgp.get('router_id', ''), 'rr': bool(bgp.get('rr')),
                          'neighbors': [{'name': n.get('name', ''), 'as': n.get('as'), 'type': n.get('type', ''),
                                         'ipv4': n.get('ipv4', ''), 'ipv6': n.get('ipv6', ''), 'activate': n.get('activate')}
                                        for n in (bgp.get('neighbors') or [])[:256] if isinstance(n, dict)],
                          'advertise': [a for a in (bgp.get('advertise') or []) if isinstance(a, dict)][:64]}
        for module in ('ospf', 'isis'):
            body = node.get(module)
            if isinstance(body, dict):
                row[module] = {k: copy.deepcopy(v) for k, v in body.items() if k in ('area', 'areas', 'af', 'router_id', 'process', 'net', 'type', 'instance', 'bfd', 'passive', 'reference_bandwidth', 'unnumbered')}
        for key in ('vrfs', 'vlans'):
            value = node.get(key)
            if isinstance(value, dict): row[key] = {k: {kk: vv for kk, vv in v.items() if kk in ('id', 'rd', 'import', 'export', 'af', 'mode', 'prefix', 'vni')} for k, v in list(value.items())[:200] if isinstance(v, dict)}
        devices.append(row)
    links = []
    for link in (transformed.get('links') or [])[:4000]:
        if not isinstance(link, dict): continue
        prefix = link.get('prefix') if isinstance(link.get('prefix'), dict) else {}
        links.append({'index': link.get('linkindex'), 'type': link.get('type', ''), 'name': link.get('name', ''),
                      'prefix': {f: prefix.get(f, '') for f in ('ipv4', 'ipv6')},
                      'ends': [{'node': i.get('node', ''), 'ifname': i.get('ifname', ''), 'ipv4': i.get('ipv4', ''), 'ipv6': i.get('ipv6', '')}
                               for i in (link.get('interfaces') or []) if isinstance(i, dict)]})
    return {'engine_version': str(transformed.get('_netlab_version', '')), 'modules': list(transformed.get('module') or []),
            'addressing': {k: {kk: vv for kk, vv in v.items() if kk in ('ipv4', 'ipv6', 'prefix', 'prefix6', 'allocation', 'unnumbered')}
                           for k, v in (transformed.get('addressing') or {}).items() if isinstance(v, dict) and k != 'mgmt'},
            'devices': devices, 'links': links}
