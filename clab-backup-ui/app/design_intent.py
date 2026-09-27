"""The network intent document of *Network design*: schema, validation and the allocation ledger.

Intent is what the student asked for (pools, address families, protocols, services, per-node and per-link
settings); it is the manager's own data-only document, stored on the lab record under the private key
``network_design`` and never a netlab topology file. :mod:`design_adapter` derives the netlab topology
from the containerlab topology plus this document; nothing here runs the engine.

Two layers of validation:

* the *core* (this module's own rules): the allowlisted top-level shape, pools and address families,
  targets, per-node roles and explicit addresses, per-link prefixes and endpoint addresses, VLAN and VRF
  objects, and the semantic checks netlab does not make (pool overlap, duplicates, exhaustion, a pool that
  overlaps the lab's management network);
* the *advanced* fields: any attribute of an enabled netlab module, at the global, node, link or
  interface level, checked against the engine's own attribute schema (``design_capability_data.json``)
  with a generic type checker, so the long tail round-trips without a hand-written copy of the schema.
  Executable or unsafe keys are refused by name (``DENIED_KEYS``) whatever the schema says.

Errors are collected, not raised one by one: :func:`validate` returns every problem as ``{'path', 'message'}``
so the page can show them all; :class:`IntentError` carries that list.

The *allocation ledger* (``allocations``) pins what earlier plans allocated: node ids, loopbacks, link
prefixes and router ids. The adapter passes them to the engine as explicit assignments, so an unrelated
node or link added or reordered later does not renumber existing devices; :func:`ledger_from_plan` derives
a new ledger from a transformed topology and :func:`renumbering` lists what a plan changed against the
previous ledger, for review.
"""
import copy
import hashlib
import ipaddress
import json
import re

SCHEMA = 1
# netlab configuration modules the design may enable, in the order the engine is asked for them. Plugins
# (GRE, WireGuard) are not modules and are not accepted in this schema version.
MODULES = ('ospf', 'bgp', 'isis', 'eigrp', 'ripv2', 'bfd', 'dhcp', 'vlan', 'vrf', 'lag', 'stp', 'gateway',
           'vxlan', 'evpn', 'mpls', 'sr', 'srv6', 'routing')
# Pools the student may define. `mgmt` is never one of them: management addressing stays the manager's.
POOLS = ('loopback', 'p2p', 'lan', 'vrf_loopback', 'router_id')
POOL_KEYS = ('ipv4', 'ipv6', 'prefix', 'prefix6', 'start', 'allocation', 'unnumbered')
ALLOCATIONS = ('p2p', 'sequential', 'id_based')
DEFAULT_POOLS = {'loopback': {'ipv4': '10.255.0.0/24', 'ipv6': '2001:db8:ff::/48'},
                 'p2p': {'ipv4': '10.1.0.0/16', 'ipv6': '2001:db8:1::/48', 'prefix': 31},
                 'lan': {'ipv4': '172.16.0.0/16', 'ipv6': '2001:db8:2::/48', 'prefix': 24}}
ROLES = ('router', 'host', 'exclude')
LINK_ROLES = ('stub', 'passive', 'external', 'core', 'edge')
LINK_TYPES = ('lan', 'p2p', 'stub')
TOP_KEYS = ('schema', 'revision', 'updated', 'label', 'families', 'addressing', 'modules', 'targets', 'nodes',
            'links', 'vlans', 'vrfs', 'interfaces', 'allocations', *MODULES)
NODE_KEYS = ('role', 'loopback', 'modules', 'vlans', 'vrfs', *MODULES)
LINK_KEYS = ('prefix', 'pool', 'role', 'type', 'name', 'mtu', 'bandwidth', 'unnumbered', 'ipv4', 'ipv6',
             'endpoints', *MODULES)
ENDPOINT_KEYS = ('ipv4', 'ipv6', *MODULES)
# Keys never accepted at any level, whatever the engine schema says: they run code, load files, change
# the engine's own settings or belong to the manager (identity, mapping, management).
DENIED_KEYS = frozenset(('config', 'plugin', 'plugins', 'validate', 'tools', 'message', 'defaults', 'provider',
                         'device', 'id', 'ifname', 'ifindex', 'mgmt', 'box', 'image', 'cpu', 'memory',
                         'skip_config', 'unmanaged', 'group', 'groups', 'members', 'bridge', 'disable',
                         'include', '_include', 'template', 'password', 'private_key'))
ID = re.compile(r'^[A-Za-z_][A-Za-z0-9_]{0,63}$')
# netlab's own identifier rule (`must_be_id` in netsim/data/types.py, `max_length` 16) for every name the engine
# types as `id`: VRFs, VLANs, address pools, named prefixes, routing policies and the like. The manager refuses a
# longer name with its own words instead of letting the engine fail the plan later with a raw schema message.
NAME = re.compile(r'^[A-Za-z_][A-Za-z0-9_]{0,15}$')
NAME_RULE = 'a name of up to 16 characters: letters, digits and underscores, starting with a letter or an underscore'
NODE_NAME = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.-]{0,199}$')
MAX_NODES = 2000
MAX_LINKS = 4000
MAX_DOCUMENT = 512 * 1024
MAX_NODE_ID = 250


class IntentError(ValueError):
    """The intent is not acceptable; ``errors`` lists every problem as {'path', 'message'}."""
    def __init__(self, errors):
        self.errors = list(errors)
        super().__init__('; '.join(e['path'] + ': ' + e['message'] for e in self.errors[:6]) or 'Invalid design')


def empty_intent():
    """A new design: dual stack, the default pools, no protocol yet."""
    return {'schema': SCHEMA, 'label': '', 'families': {'ipv4': True, 'ipv6': True},
            'addressing': copy.deepcopy(DEFAULT_POOLS), 'modules': [], 'targets': None,
            'nodes': {}, 'links': {}, 'vlans': {}, 'vrfs': {}, 'interfaces': {}, 'allocations': {}}


def link_key(endpoints):
    """The stable identity of a containerlab link: its two `node:interface` ends, sorted.

    Parallel links between the same nodes differ by interface, so the key is unique in a valid topology;
    renaming a node changes the key on purpose (a design entry for the old name is reported unmatched)."""
    return '--'.join(sorted(node + ':' + interface for node, interface in endpoints))


def canonical(intent):
    """The content that identifies a design: everything but the volatile envelope and the allocation
    ledger (the manager writes the ledger after each plan; a student's edits are what the revision guards,
    and every generation records the ledger it used in its own snapshot)."""
    return {k: v for k, v in intent.items() if k not in ('revision', 'updated', 'allocations')}


def revision(intent):
    return hashlib.sha256(json.dumps(canonical(intent), sort_keys=True, separators=(',', ':')).encode()).hexdigest()[:24]


# --- generic checks --------------------------------------------------------------------------------------

def _prefix(value, family):
    """A CIDR prefix of the family, or the reason it is not."""
    try:
        network = ipaddress.ip_network(value, strict=True)
    except (ValueError, TypeError):
        return None, 'Use a CIDR prefix such as 10.0.0.0/24'
    if network.version != (4 if family == 'ipv4' else 6): return None, 'The prefix does not belong to ' + family
    return network, ''


def _address(value, family):
    """An interface address (with or without prefix length) of the family."""
    try:
        interface = ipaddress.ip_interface(value)
    except (ValueError, TypeError):
        return None, 'Use an address such as 10.0.0.1 or 10.0.0.1/31'
    if interface.version != (4 if family == 'ipv4' else 6): return None, 'The address does not belong to ' + family
    return interface, ''


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


# Characters no design string may carry: control characters, and the quote, brace, semicolon, backslash and
# backtick that could close a statement or open another one once the value is rendered into a NOS
# configuration (a VLAN name, a link description, a policy name all end up in the generated text).
UNSAFE_CHARS = frozenset('"\'{};`\\')


def _text(value, limit=200):
    return isinstance(value, str) and len(value) <= limit and all(c == ' ' or (c.isprintable() and c not in UNSAFE_CHARS) for c in value)


LEVELS = ('global', 'node', 'link', 'interface', 'loopback')
MAX_DEPTH = 16
MAX_ITEMS = 50000


def scan(document):
    """The recursive guard that runs before anything else looks at a design: every key at every depth is a
    plain identifier-like string that does not start with `_` and is not one of DENIED_KEYS (`id` is left to
    the level checks, which allow it only on VLAN and VRF objects), every string value is safe text, and the
    document is bounded in depth and size. Returns the problems found (a non-empty list stops validation)."""
    problems = []; count = 0

    def walk(value, path, depth, parent=''):
        nonlocal count
        count += 1
        if count > MAX_ITEMS: problems.append({'path': path, 'message': 'The design has too many items'}); return
        if depth > MAX_DEPTH: problems.append({'path': path, 'message': 'The design is nested too deeply'}); return
        if isinstance(value, dict):
            for key, item in value.items():
                here = path + '.' + str(key) if path else str(key)
                # `members` names the member links of a link aggregation (checked by the link level) and nothing else.
                denied = key in DENIED_KEYS and key != 'id' and not (key == 'members' and parent == 'lag')
                if not isinstance(key, str) or not key or len(key) > 200 or key.startswith('_') or denied or not _text(key, 200):
                    problems.append({'path': here, 'message': 'This name is not accepted in a design: ' + (key if isinstance(key, str) and _text(key, 200) else 'unreadable key')}); continue
                walk(item, here, depth + 1, key)
        elif isinstance(value, list):
            if len(value) > 2000: problems.append({'path': path, 'message': 'The list is too long'}); return
            for index, item in enumerate(value): walk(item, path + '[' + str(index) + ']', depth + 1, parent)
        elif isinstance(value, str):
            if not _text(value, 4096): problems.append({'path': path, 'message': 'Text may not contain control characters, quotes, braces, semicolons, backslashes or backticks'})
        elif value is not None and not isinstance(value, (bool, int, float)):
            problems.append({'path': path, 'message': 'Unsupported value type'})
    walk(document, '', 0)
    return problems[:50]


# --- the advanced fields: netlab's attribute schema ------------------------------------------------------

class SchemaChecker:
    """Checks a value against netlab's attribute schema dialect (`netlab show attributes --format yaml`).

    A schema node is either a *typed leaf* (a dict with `type`, or a bare type name / named-type reference
    string) or a *mapping of attribute names* to schema nodes. Understood: `type` (str, int, bool, ipv4,
    ipv6, id, asn, net, mac, list, dict, prefix_str, node_id, device, and the named types of the top-level
    schema), `_alt_types`, `valid_values` (list or dict), `min_value`/`max_value`, `min_length`/`max_length`,
    `_subtype` (list elements or dict values), `_keytype` (dict keys), `_keys` (a dict's own attributes),
    `_list_to_dict` (a list of names accepted for a dict of booleans). Anything the checker does not
    understand fails closed: the attribute is refused rather than passed through unchecked."""
    SIMPLE = ('str', 'int', 'bool', 'ipv4', 'ipv6', 'id', 'asn', 'net', 'mac', 'list', 'dict', 'prefix_str',
              'node_id', 'device', 'addr_pool', 'named_pfx', 'bool_false', 'NoneType', 'r_proto')

    def __init__(self, named_types, management=()):
        self.named = named_types or {}
        self.management = list(management)

    def guard_address(self, value, path, errors):
        """No address or prefix anywhere in the settings may fall inside the lab's management networks."""
        try: network = ipaddress.ip_network(value, strict=False)
        except (ValueError, TypeError): return
        if network.prefixlen == 0: return   # a default route (`0.0.0.0/0`, `::/0`) is a prefix to originate, never an address
        for label, net in self.management:
            if net.version == network.version and net.overlaps(network):
                errors.append({'path': path, 'message': 'Overlaps the lab management network ' + label}); return

    def check(self, value, schema, path, errors, depth=0):
        if depth > 12: errors.append({'path': path, 'message': 'The value is nested too deeply'}); return
        if isinstance(schema, str):
            self.leaf(value, {'type': schema}, path, errors, depth); return
        last = path.rsplit('.', 1)[-1]
        if last == 'import' and isinstance(value, dict) and any(v is None for v in value.values()):
            # The engine's schema allows an empty entry, its BGP templates crash on it (eos, iosxr): ask for the form that renders.
            errors.append({'path': path, 'message': 'Set a redistributed protocol to true or to a mapping with its policy'}); return
        if schema is None and last == 'prefix' and '_prefix' in self.named:
            self.check(value, self.named['_prefix'], path, errors, depth + 1); return   # netlab types a VLAN prefix loosely
        if last == 'loopback' and isinstance(schema, dict) and 'type' in schema and '_keys' not in schema and '_subtype' not in schema and isinstance(value, dict):
            # netlab types a VRF loopback loosely (bool, prefix or dict): a dict takes ipv4/ipv6 prefixes and a pool.
            self.mapping(value, {'ipv4': {'type': 'ipv4', 'use': 'prefix'}, 'ipv6': {'type': 'ipv6', 'use': 'prefix'}, 'pool': 'addr_pool'}, path, errors, depth + 1); return
        if schema is None and last == 'trunk':
            # A VLAN trunk is a list of VLAN names or a mapping of VLAN names to their (empty) per-trunk settings.
            names = value if isinstance(value, list) else list(value) if isinstance(value, dict) else None
            if names is None or len(names) > 500 or any(not (_text(n, 64) and NAME.match(n)) for n in names) or (isinstance(value, dict) and any(v not in (None, {}) for v in value.values())):
                errors.append({'path': path, 'message': 'A trunk lists VLAN names'})
            return
        if not isinstance(schema, dict):
            errors.append({'path': path, 'message': 'This attribute cannot be checked by the manager'}); return
        if 'type' in schema or '_alt_types' in schema and (not isinstance(value, dict) or not any(not k.startswith('_') and k not in ('type',) for k in schema)):
            self.leaf(value, schema, path, errors, depth); return
        self.mapping(value, schema, path, errors, depth)

    def mapping(self, value, schema, path, errors, depth):
        if not isinstance(value, dict):
            errors.append({'path': path, 'message': 'Expected a set of named settings'}); return
        for key, item in value.items():
            here = path + '.' + str(key)
            if not isinstance(key, str) or not ID.match(key) or key in DENIED_KEYS or key.startswith('_'):
                errors.append({'path': here, 'message': 'This setting name is not accepted'}); continue
            if key not in schema or key.startswith('_'):
                errors.append({'path': here, 'message': 'Unknown setting for this module'}); continue
            if key == 'pool' and item == 'mgmt': errors.append({'path': here, 'message': 'The management pool is never a design pool'}); continue
            self.check(item, schema[key], here, errors, depth + 1)

    def typed(self, value, kind, schema, path, errors, depth):
        """True when `value` is a `kind`; appends nothing (the caller words the failure)."""
        if kind == 'NoneType': return value is None
        if kind == 'bool': return isinstance(value, bool)
        if kind == 'bool_false': return value is False
        if kind == 'int':
            if not _is_int(value): return False
            low, high = schema.get('min_value'), schema.get('max_value')
            return (low is None or value >= low) and (high is None or value <= high)
        if kind == 'addr_pool' and value == 'mgmt': return False
        if kind in ('str', 'id', 'node_id', 'device', 'addr_pool', 'named_pfx', 'r_proto'):
            if not _text(value): return False
            if kind != 'str' and not (ID.match(value) if kind == 'node_id' else NAME.match(value)): return False
            low, high = schema.get('min_length'), schema.get('max_length')
            return (low is None or len(value) >= low) and (high is None or len(value) <= high)
        if kind == 'asn': return _is_int(value) and 1 <= value <= 4294967295
        if kind == 'mac': return _text(value, 40) and re.fullmatch(r'[0-9A-Fa-f]{2}([:.-][0-9A-Fa-f]{2}){5}|[0-9A-Fa-f]{4}\.[0-9A-Fa-f]{4}\.[0-9A-Fa-f]{4}', value) is not None
        # A NET, or an IS-IS area (`49.0001`): netlab types `isis.area` as `net` but takes the area and builds the NET.
        if kind == 'net': return _text(value, 80) and (re.fullmatch(r'[0-9a-fA-F]{2}(\.[0-9a-fA-F]{4}){3,9}\.00', value) is not None or re.fullmatch(r'[0-9a-fA-F]{2}(\.[0-9a-fA-F]{4}){0,6}', value) is not None)
        if kind == 'rd': return _text(value, 60) and re.fullmatch(r'(?:\d{1,10}|\d{1,3}(?:\.\d{1,3}){3}):\d{1,10}', value) is not None
        if kind in ('ipv4', 'ipv6'):
            use = schema.get('use', '')
            if use == 'id' and kind == 'ipv4': return _is_int(value) and 0 <= value <= 4294967295 or _text(value, 40) and _prefix(value + '/32', 'ipv4')[0] is not None
            if use in ('prefix', 'subnet_prefix'):
                ok = _text(value, 60) and _prefix(value, kind)[0] is not None
                if ok: self.guard_address(value, path, errors)
                return ok
            if isinstance(value, bool): return True    # enable the family without an address (netlab's own rule)
            if _is_int(value): return value >= 0        # the N-th address of the link prefix
            ok = _text(value, 60) and _address(value, kind)[0] is not None
            if ok:
                address = _address(value, kind)[0]; before = len(errors)
                self.guard_address(str(address.ip), path, errors)
                if len(errors) == before and '/' in value: self.guard_address(str(address.network), path, errors)   # the whole subnet too
            return ok
        if kind == 'prefix_str':
            ok = _text(value, 60) and (_prefix(value, 'ipv4')[0] or _prefix(value, 'ipv6')[0]) is not None
            if ok: self.guard_address(value, path, errors)
            return ok
        if kind == 'list':
            if not isinstance(value, list) or len(value) > 500: return False
            sub = schema.get('_subtype')
            if sub is None: return all(_text(v, 200) or _is_int(v) or isinstance(v, bool) for v in value)
            for index, item in enumerate(value):
                inner = []
                self.check(item, sub, path + '[' + str(index) + ']', inner, depth + 1)
                if inner: errors.extend(inner); return True   # reported in detail already
            return True
        if kind == 'dict':
            if not isinstance(value, dict) or len(value) > 500: return False
            keys = schema.get('_keys'); sub = schema.get('_subtype'); keytype = schema.get('_keytype', 'id')
            if isinstance(keytype, dict): keytype = keytype.get('type', 'id')
            for key, item in value.items():
                here = path + '.' + str(key)
                if not isinstance(key, str) or not (ID.match(key) if keytype in ('node_id', 'device') else NAME.match(key) if keytype == 'id' else _text(key, 80)) or key in DENIED_KEYS:
                    errors.append({'path': here, 'message': 'This name is not accepted' if not isinstance(key, str) or key in DENIED_KEYS or keytype != 'id' else 'Use ' + NAME_RULE}); continue
                if keys is not None:
                    if key not in keys: errors.append({'path': here, 'message': 'Unknown setting'}); continue
                    self.check(item, keys[key], here, errors, depth + 1)
                elif sub is not None: self.check(item, sub, here, errors, depth + 1)
                elif not (_text(item, 200) or _is_int(item) or isinstance(item, bool) or item is None):
                    errors.append({'path': here, 'message': 'Use a simple value here'})
            return True
        if kind in self.named:
            inner = []
            self.check(value, self.named[kind], path, inner, depth + 1)
            if inner: errors.extend(inner)
            return True
        return None   # unknown type name

    def leaf(self, value, schema, path, errors, depth):
        kinds = []
        if 'type' in schema: kinds.append(schema['type'])
        for alt in schema.get('_alt_types') or []: kinds.append(alt)
        if not kinds and '_keys' in schema: kinds.append('dict')
        if schema.get('_list_to_dict') and isinstance(value, list):
            if all(_text(v, 60) and NAME.match(v) for v in value) and len(value) <= 100: return
            errors.append({'path': path, 'message': 'Use a list of names'}); return
        valid = schema.get('valid_values')
        if valid is not None and not isinstance(value, (list, dict)):
            allowed = list(valid.keys()) if isinstance(valid, dict) else list(valid)
            if value not in allowed:
                errors.append({'path': path, 'message': 'Choose one of: ' + ', '.join(str(a) for a in allowed[:12])}); return
        before = len(errors)
        for kind in kinds:
            if not isinstance(kind, str): continue
            result = self.typed(value, kind, schema, path, errors, depth)
            if result: return
            if result is None:
                errors.append({'path': path, 'message': 'This attribute cannot be checked by the manager'}); return
            if len(errors) > before: return
        errors.append({'path': path, 'message': 'The value has the wrong type (expected ' + ' or '.join(str(k) for k in kinds) + ')'})


def module_schema(schema, module, level):
    """The attribute schema of `module` at `level` (global, node, link, interface, loopback, vrf), or None."""
    if not schema: return None
    attributes = (schema.get('attributes') or {}).get(module) or {}
    return attributes.get(level)


def named_types(schema):
    """netlab's named types (everything of the top-level attribute schema that is not a level section)."""
    top = ((schema or {}).get('attributes') or {}).get('top') or {}
    types = {k: v for k, v in top.items() if k not in LEVELS and isinstance(v, (dict, str))}
    for k, v in ((schema or {}).get('types') or {}).items():   # a caller-built schema may carry them separately
        if k not in LEVELS and isinstance(v, (dict, str)): types.setdefault(k, v)
    return types


# Keys of a VLAN or VRF object the design never accepts: they create links or members behind the mapping.
OBJECT_DENIED = frozenset(('links', 'members', 'interfaces', 'nodes'))


def object_schema(schema, kind):
    """The attribute schema of a VLAN or VRF object (`attributes.top.vlan` / `.vrf`), minus the keys the
    design never accepts, or None when the data is not there (then no body is accepted)."""
    body = named_types(schema).get(kind)
    if not isinstance(body, dict): return None
    return {k: v for k, v in body.items() if not k.startswith('_') and k not in OBJECT_DENIED and k != 'id'}


# --- the core -------------------------------------------------------------------------------------------

def _check_modules(intent, errors):
    modules = intent.get('modules', [])
    if not isinstance(modules, list) or len(modules) > len(MODULES) or any(m not in MODULES for m in modules) or len(set(modules)) != len(modules):
        errors.append({'path': 'modules', 'message': 'Choose protocols and services from the supported list, each once'}); return []
    return modules


def _check_pools(intent, errors, management):
    pools = intent.get('addressing', {})
    if not isinstance(pools, dict) or len(pools) > 12:
        errors.append({'path': 'addressing', 'message': 'Address pools must be a set of named pools'}); return {}
    families = intent.get('families', {})
    networks = []
    for name, pool in pools.items():
        here = 'addressing.' + str(name)
        if not isinstance(name, str) or not (name in POOLS or NAME.match(name) and name != 'mgmt' and not name.startswith('_')):
            errors.append({'path': here, 'message': 'Pool names are loopback, p2p, lan, vrf_loopback, router_id or ' + NAME_RULE + ' (never mgmt)'}); continue
        if not isinstance(pool, dict) or any(k not in POOL_KEYS for k in pool):
            errors.append({'path': here, 'message': 'A pool takes ipv4, ipv6, prefix, prefix6, start, allocation and unnumbered'}); continue
        for family, limit in (('ipv4', 32), ('ipv6', 128)):
            value = pool.get(family)
            if value is None or value is True: continue
            if value is False: errors.append({'path': here + '.' + family, 'message': 'Leave the family out instead of setting it to false'}); continue
            network, why = _prefix(value, family)
            if not network: errors.append({'path': here + '.' + family, 'message': why}); continue
            size = pool.get('prefix' if family == 'ipv4' else 'prefix6')
            if size is not None and (not _is_int(size) or not network.prefixlen <= size <= limit):
                errors.append({'path': here + '.' + ('prefix' if family == 'ipv4' else 'prefix6'), 'message': 'The allocation size must be between the pool length and /' + str(limit)})
            if not families.get(family, True):
                errors.append({'path': here + '.' + family, 'message': family + ' is switched off in this design; remove the prefix or enable the family'})
            for other_name, other in networks:
                if other.version == network.version and (other.overlaps(network)):
                    errors.append({'path': here + '.' + family, 'message': 'Overlaps the ' + other_name + ' pool'})
            for label, net in management:
                if net.version == network.version and net.overlaps(network):
                    errors.append({'path': here + '.' + family, 'message': 'Overlaps the lab management network ' + label})
            networks.append((str(name), network))
        if 'start' in pool and not (_is_int(pool['start']) and 0 <= pool['start'] <= 65535):
            errors.append({'path': here + '.start', 'message': 'start is a small whole number'})
        if 'allocation' in pool and pool['allocation'] not in ALLOCATIONS:
            errors.append({'path': here + '.allocation', 'message': 'Choose p2p, sequential or id_based'})
        if 'unnumbered' in pool and not isinstance(pool['unnumbered'], bool):
            errors.append({'path': here + '.unnumbered', 'message': 'unnumbered is yes or no'})
    return pools


def _check_named_objects(intent, key, errors, schema, checker, ids):
    objects = intent.get(key, {})
    if not isinstance(objects, dict) or len(objects) > 500:
        errors.append({'path': key, 'message': 'Must be a set of named ' + key}); return
    seen_ids = {}
    level = object_schema(schema, key[:-1])
    for name, body in objects.items():
        here = key + '.' + str(name)
        if not isinstance(name, str) or not NAME.match(name) or name in DENIED_KEYS:
            errors.append({'path': here, 'message': 'Use a plain identifier as the name: ' + NAME_RULE}); continue
        if not isinstance(body, dict):
            errors.append({'path': here, 'message': 'Settings must be a mapping'}); continue
        ident = body.get('id')
        if ident is not None:
            if not _is_int(ident) or not ids[0] <= ident <= ids[1]:
                errors.append({'path': here + '.id', 'message': 'The id must be between ' + str(ids[0]) + ' and ' + str(ids[1])})
            elif ident in seen_ids: errors.append({'path': here + '.id', 'message': 'Duplicate id, already used by ' + seen_ids[ident]})
            else: seen_ids[ident] = name
        for k in body:
            if k in OBJECT_DENIED: errors.append({'path': here + '.' + str(k), 'message': 'Links and members are designed on the lab topology, not inside a VLAN or VRF'})
        rest = {k: v for k, v in body.items() if k != 'id' and k not in OBJECT_DENIED}
        if level is not None: checker.mapping(rest, level, here, errors, 1)
        elif rest: errors.append({'path': here, 'message': 'Settings cannot be checked without the engine schema'})


def link_nodes(key):
    """The two device names a link key joins (`a:if--b:if`), or () when the key is not of that shape."""
    ends = str(key or '').split('--')
    if len(ends) != 2 or not all(':' in e for e in ends): return ()
    return tuple(sorted(e.split(':', 1)[0] for e in ends))


def _lag_members(body, here, errors, link_key, link_keys):
    """`links.<key>.lag.members`: the other member links of the aggregation this link carries — one to eight keys of
    this lab's links, distinct, not the link itself, each joining the same two devices. Returns the body without
    `members` for the engine schema check."""
    body = dict(body); members = body.pop('members', None)
    if members is None: return body
    path = here + '.members'
    if not isinstance(members, list) or not members or len(members) > 8 or not all(isinstance(m, str) for m in members):
        errors.append({'path': path, 'message': 'List one to eight member links by their link key'}); return body
    if len(set(members)) != len(members): errors.append({'path': path, 'message': 'A member link is listed twice'})
    pair = link_nodes(link_key)
    for member in members:
        if member == link_key: errors.append({'path': path, 'message': 'The link that carries the aggregation is a member by itself; list the other links'})
        elif link_keys is not None and member not in link_keys: errors.append({'path': path, 'message': 'No link with this key in the lab: ' + member})
        elif pair and link_nodes(member) != pair: errors.append({'path': path, 'message': 'A member link must join the same two devices: ' + member})
    return body


def _module_settings(container, path, modules, level, errors, checker, schema, allow_unlisted=False, vrf_names=(), link_key='', link_keys=None):
    """Check every enabled module's settings in `container` at `level`; a module that is not enabled is an error.
    `False` switches a module off at that level (netlab's own rule); at the node, link and interface levels the
    `vrf` module also takes the name of a VRF defined in the design (the attachment); at the link level `lag`
    may name its member links."""
    for module in MODULES:
        if module not in container: continue
        here = path + '.' + module if path else module
        if module not in modules and not allow_unlisted:
            errors.append({'path': here, 'message': 'Enable ' + module + ' in the design before setting its options'}); continue
        body = container[module]
        if body is None or body is True: continue
        if module == 'lag' and isinstance(body, dict) and 'members' in body:
            if level != 'link': errors.append({'path': here + '.members', 'message': 'Member links are listed on the link that carries the aggregation'}); continue
            body = _lag_members(body, here, errors, link_key, link_keys)
        if body is False:
            if level in ('link', 'interface'): continue
            errors.append({'path': here, 'message': 'Switch a module off per link or per link end; a device drops a module from its modules list'}); continue
        if module == 'vrf' and isinstance(body, str):
            if level not in ('link', 'interface'): errors.append({'path': here, 'message': 'A VRF is attached to a link or a link end'})
            elif body not in vrf_names: errors.append({'path': here, 'message': 'No VRF named ' + body + ' is defined in this design'})
            continue
        if not isinstance(body, dict):
            errors.append({'path': here, 'message': 'Module settings must be a mapping'}); continue
        level_schema = module_schema(schema, module, level)
        if level_schema is None:
            if body: errors.append({'path': here, 'message': 'This module has no settings at this level in the manager\'s schema'})
            continue
        checker.mapping(body, level_schema, here, errors, 1)


def _vlan_references(body, path, vlan_names, errors):
    """access, native and trunk name VLANs that the design defines."""
    if not isinstance(body, dict): return
    for key in ('access', 'native'):
        if isinstance(body.get(key), str) and body[key] not in vlan_names: errors.append({'path': path + '.' + key, 'message': 'No VLAN named ' + body[key] + ' is defined in this design'})
    trunk = body.get('trunk')
    names = trunk if isinstance(trunk, list) else list(trunk) if isinstance(trunk, dict) else []
    for name in names:
        if isinstance(name, str) and name not in vlan_names: errors.append({'path': path + '.trunk', 'message': 'No VLAN named ' + name + ' is defined in this design'})


AS_RANGE = (1, 4294967295)


def _check_bgp_as(intent, modules, errors):
    """A BGP design needs one AS number in the 1..4294967295 range, globally and on any device that sets its own.

    The engine schema types the field but does not bound it, and a form that lets 0 or a blank through
    would otherwise reach the engine (or, worse, be silently replaced by a look-alike default)."""
    # One problem per field: a value the schema checker already reported (wrong type, its own range) is left to it.
    flagged = {e['path'] for e in errors}
    def out_of_range(value):
        return isinstance(value, int) and not isinstance(value, bool) and not AS_RANGE[0] <= value <= AS_RANGE[1]
    settings = intent.get('bgp')
    nodes = intent.get('nodes')
    per_node = False
    if isinstance(nodes, dict):
        for name, node in nodes.items():
            bgp = node.get('bgp') if isinstance(node, dict) else None
            if isinstance(bgp, dict) and 'as' in bgp:
                per_node = True
                path = 'nodes.' + str(name) + '.bgp.as'
                if out_of_range(bgp['as']) and path not in flagged: errors.append({'path': path, 'message': 'The BGP AS number must be a whole number from 1 to 4294967295'})
    if 'bgp' in modules and isinstance(settings, dict):
        # netlab takes the AS globally or per device; a design with neither cannot be generated.
        if 'as' not in settings:
            if not per_node: errors.append({'path': 'bgp.as', 'message': 'Enter the BGP AS number (1 to 4294967295), globally or on each device'})
        elif out_of_range(settings['as']) and 'bgp.as' not in flagged: errors.append({'path': 'bgp.as', 'message': 'The BGP AS number must be a whole number from 1 to 4294967295'})


def validate(intent, *, lab_nodes=None, lab_links=None, schema=None, management=()):
    """Every problem with `intent` as a list of {'path', 'message'}; an empty list means acceptable.

    `lab_nodes` maps the lab's definition node names to their containerlab kinds and `lab_links` lists the
    lab's link keys (both optional: without them, references to nodes and links are not checked).
    `schema` is the engine attribute schema (design_capability_data.json's content) for the advanced
    fields; without it, module settings other than an empty mapping are refused. `management` lists
    (label, ip_network) of the lab's management networks that no pool may overlap."""
    errors = []
    if not isinstance(intent, dict): return [{'path': '', 'message': 'The design must be a mapping'}]
    try: size = len(json.dumps(intent))
    except (TypeError, ValueError): return [{'path': '', 'message': 'The design must be plain data'}]
    if size > MAX_DOCUMENT: return [{'path': '', 'message': 'The design is larger than 512 KiB'}]
    guard = scan(intent)
    if guard: return guard
    management = list(management)

    def outside_management(value, family, path):
        """False (and one problem appended) when `value` touches a management network."""
        try: network = ipaddress.ip_network(value, strict=False)
        except (ValueError, TypeError): return True
        for label, net in management:
            if net.version == network.version and net.overlaps(network):
                errors.append({'path': path, 'message': 'Overlaps the lab management network ' + label}); return False
        return True
    if intent.get('schema') != SCHEMA: errors.append({'path': 'schema', 'message': 'Unsupported design schema; this manager writes schema ' + str(SCHEMA)})
    for key in intent:
        if key not in TOP_KEYS: errors.append({'path': str(key), 'message': 'Unknown design field'})
    if 'label' in intent and not _text(intent['label'], 120): errors.append({'path': 'label', 'message': 'Use a short label'})
    families = intent.get('families', {'ipv4': True, 'ipv6': True})
    if not isinstance(families, dict) or set(families) - {'ipv4', 'ipv6'} or not any(families.get(f) for f in ('ipv4', 'ipv6')) or not all(isinstance(v, bool) for v in families.values()):
        errors.append({'path': 'families', 'message': 'Enable IPv4, IPv6 or both'}); families = {'ipv4': True, 'ipv6': True}
    modules = _check_modules(intent, errors)
    pools = _check_pools(intent, errors, list(management))
    checker = SchemaChecker(named_types(schema), management)
    _module_settings(intent, '', modules, 'global', errors, checker, schema)
    _check_named_objects(intent, 'vlans', errors, schema, checker, (1, 4094))
    _check_named_objects(intent, 'vrfs', errors, schema, checker, (1, 65535))
    vlan_names = set(intent.get('vlans', {}) or {}) if isinstance(intent.get('vlans', {}), dict) else set()
    vrf_names = set(intent.get('vrfs', {}) or {}) if isinstance(intent.get('vrfs', {}), dict) else set()
    if vlan_names and 'vlan' not in modules: errors.append({'path': 'vlans', 'message': 'Enable the vlan module to define VLANs'})
    if vrf_names and 'vrf' not in modules: errors.append({'path': 'vrfs', 'message': 'Enable the vrf module to define VRFs'})
    known_nodes = set(lab_nodes or {}) if lab_nodes is not None else None
    targets = intent.get('targets')
    if targets is not None:
        if not isinstance(targets, list) or len(targets) > MAX_NODES or any(not _text(t) for t in targets) or len(set(targets)) != len(targets):
            errors.append({'path': 'targets', 'message': 'Targets are a list of distinct device names'})
        elif known_nodes is not None:
            for t in targets:
                if t not in known_nodes: errors.append({'path': 'targets', 'message': 'No such device in this lab: ' + t})
    nodes = intent.get('nodes', {})
    loopbacks = {}
    if not isinstance(nodes, dict) or len(nodes) > MAX_NODES:
        errors.append({'path': 'nodes', 'message': 'Per-device settings must be a mapping of device names'}); nodes = {}
    for name, node in nodes.items():
        here = 'nodes.' + str(name)
        if not isinstance(name, str) or not NODE_NAME.match(name): errors.append({'path': here, 'message': 'Invalid device name'}); continue
        if known_nodes is not None and name not in known_nodes: errors.append({'path': here, 'message': 'This device is not in the lab topology (renamed or removed?)'})
        if not isinstance(node, dict): errors.append({'path': here, 'message': 'Device settings must be a mapping'}); continue
        for key in node:
            if key not in NODE_KEYS: errors.append({'path': here + '.' + str(key), 'message': 'Unknown device setting'})
        if 'role' in node and node['role'] not in ROLES: errors.append({'path': here + '.role', 'message': 'Choose router, host or exclude'})
        if 'modules' in node:
            extra = node['modules']
            if not isinstance(extra, list) or any(m not in MODULES for m in extra) or len(set(extra)) != len(extra):
                errors.append({'path': here + '.modules', 'message': 'Device modules come from the supported list'})
        node_modules = set(node['modules']) if isinstance(node.get('modules'), list) else set(modules)   # a device's list replaces the design's (netlab's rule)
        loop = node.get('loopback')
        if loop is not None:
            if loop is False: pass
            elif not isinstance(loop, dict) or set(loop) - {'ipv4', 'ipv6'}:
                errors.append({'path': here + '.loopback', 'message': 'A loopback takes ipv4 and ipv6 addresses, or false for none'})
            else:
                for family in ('ipv4', 'ipv6'):
                    if family not in loop or loop[family] in (True, False): continue
                    address, why = _address(loop[family], family)
                    if not address: errors.append({'path': here + '.loopback.' + family, 'message': why}); continue
                    if str(address.ip) in loopbacks: errors.append({'path': here + '.loopback.' + family, 'message': 'Duplicate loopback address, already used by ' + loopbacks[str(address.ip)]})
                    loopbacks[str(address.ip)] = name
                    if outside_management(str(address.ip), family, here + '.loopback.' + family): outside_management(str(address.network), family, here + '.loopback.' + family)
        _module_settings(node, here, sorted(node_modules), 'node', errors, checker, schema, vrf_names=vrf_names)
        for key in ('vlans', 'vrfs'):
            if key in node:
                body = node[key]
                if not isinstance(body, dict) or any(not (isinstance(k, str) and NAME.match(k)) for k in body):
                    errors.append({'path': here + '.' + key, 'message': 'Use a mapping of ' + key + ' names (each ' + NAME_RULE + ')'}); continue
                level = object_schema(schema, key[:-1])
                for vname, vbody in body.items():
                    if vbody in (None, {}): continue
                    if not isinstance(vbody, dict): errors.append({'path': here + '.' + key + '.' + vname, 'message': 'Settings must be a mapping'}); continue
                    for k in vbody:
                        if k in OBJECT_DENIED: errors.append({'path': here + '.' + key + '.' + vname + '.' + str(k), 'message': 'Links and members are designed on the lab topology, not inside a VLAN or VRF'})
                    rest = {k: v for k, v in vbody.items() if k != 'id' and k not in OBJECT_DENIED}
                    if 'id' in vbody and not (_is_int(vbody['id']) and 1 <= vbody['id'] <= (4094 if key == 'vlans' else 65535)): errors.append({'path': here + '.' + key + '.' + vname + '.id', 'message': 'Invalid id'})
                    if level is not None: checker.mapping(rest, level, here + '.' + key + '.' + vname, errors, 1)
                    elif rest: errors.append({'path': here + '.' + key + '.' + vname, 'message': 'Settings cannot be checked without the engine schema'})
    links = intent.get('links', {})
    known_links = set(lab_links) if lab_links is not None else None
    link_prefixes = {}
    if not isinstance(links, dict) or len(links) > MAX_LINKS:
        errors.append({'path': 'links', 'message': 'Per-link settings must be a mapping of link keys'}); links = {}
    for key, link in links.items():
        here = 'links.' + str(key)
        if not _text(key, 500) or '--' not in key: errors.append({'path': here, 'message': 'Invalid link key'}); continue
        if known_links is not None and key not in known_links: errors.append({'path': here, 'message': 'This link is not in the lab topology any more'})
        if not isinstance(link, dict): errors.append({'path': here, 'message': 'Link settings must be a mapping'}); continue
        for field in link:
            if field not in LINK_KEYS: errors.append({'path': here + '.' + str(field), 'message': 'Unknown link setting'})
        networks = {}
        prefix = link.get('prefix')
        if prefix is not None:
            if prefix is False: pass
            elif not isinstance(prefix, dict) or set(prefix) - {'ipv4', 'ipv6', 'allocation'}:
                errors.append({'path': here + '.prefix', 'message': 'A link prefix takes ipv4, ipv6 and allocation, or false for a layer-2 link'})
            else:
                for family in ('ipv4', 'ipv6'):
                    if family not in prefix: continue
                    network, why = _prefix(prefix[family], family)
                    if not network: errors.append({'path': here + '.prefix.' + family, 'message': why}); continue
                    networks[family] = network
                    outside_management(str(network), family, here + '.prefix.' + family)
                    for other_key, other in link_prefixes.items():
                        if other.version == network.version and other.overlaps(network):
                            errors.append({'path': here + '.prefix.' + family, 'message': 'Overlaps the prefix of link ' + other_key})
                    link_prefixes[key + '/' + family] = network
                if 'allocation' in prefix and prefix['allocation'] not in ALLOCATIONS:
                    errors.append({'path': here + '.prefix.allocation', 'message': 'Choose p2p, sequential or id_based'})
        if 'pool' in link and not (_text(link['pool'], 64) and NAME.match(link['pool']) and link['pool'] != 'mgmt' and (link['pool'] in POOLS or link['pool'] in pools)):
            errors.append({'path': here + '.pool', 'message': 'Choose a pool defined in this design'})
        if 'role' in link and link['role'] not in LINK_ROLES: errors.append({'path': here + '.role', 'message': 'Choose stub, passive, external, core or edge'})
        if 'type' in link and link['type'] not in LINK_TYPES: errors.append({'path': here + '.type', 'message': 'Choose lan, p2p or stub'})
        if 'name' in link and not _text(link['name'], 120): errors.append({'path': here + '.name', 'message': 'Use a short name'})
        if 'mtu' in link and not (_is_int(link['mtu']) and 64 <= link['mtu'] <= 9216): errors.append({'path': here + '.mtu', 'message': 'MTU is between 64 and 9216'})
        if 'bandwidth' in link and not (_is_int(link['bandwidth']) and 1 <= link['bandwidth'] <= 10 ** 9): errors.append({'path': here + '.bandwidth', 'message': 'Bandwidth is a positive number'})
        if 'unnumbered' in link and not isinstance(link['unnumbered'], bool): errors.append({'path': here + '.unnumbered', 'message': 'unnumbered is yes or no'})
        for family in ('ipv4', 'ipv6'):
            if family in link and not isinstance(link[family], bool): errors.append({'path': here + '.' + family, 'message': 'At link level ' + family + ' switches the family on or off; put addresses under endpoints'})
        _module_settings(link, here, modules, 'link', errors, checker, schema, vrf_names=vrf_names, link_key=key, link_keys=set(lab_links) if lab_links is not None else None)
        _vlan_references(link.get('vlan'), here + '.vlan', vlan_names, errors)
        endpoints = link.get('endpoints', {})
        if not isinstance(endpoints, dict): errors.append({'path': here + '.endpoints', 'message': 'Endpoints are a mapping of device names'}); continue
        ends = key.split('--')
        for node_name, endpoint in endpoints.items():
            ehere = here + '.endpoints.' + str(node_name)
            if not any(e.startswith(str(node_name) + ':') for e in ends): errors.append({'path': ehere, 'message': 'This device is not on this link'}); continue
            if not isinstance(endpoint, dict): errors.append({'path': ehere, 'message': 'Endpoint settings must be a mapping'}); continue
            for field in endpoint:
                if field not in ENDPOINT_KEYS: errors.append({'path': ehere + '.' + str(field), 'message': 'Unknown endpoint setting'})
            for family in ('ipv4', 'ipv6'):
                value = endpoint.get(family)
                if value is None or isinstance(value, bool): continue
                if _is_int(value):
                    if value < 1: errors.append({'path': ehere + '.' + family, 'message': 'The address number counts from 1'})
                    continue
                address, why = _address(value, family)
                if not address: errors.append({'path': ehere + '.' + family, 'message': why}); continue
                if family in networks and address.ip not in networks[family]: errors.append({'path': ehere + '.' + family, 'message': 'The address is outside the link prefix'})
                if str(address.ip) in loopbacks: errors.append({'path': ehere + '.' + family, 'message': 'Duplicate address, already used as a loopback by ' + loopbacks[str(address.ip)]})
                loopbacks[str(address.ip)] = node_name + ' on ' + key
                if outside_management(str(address.ip), family, ehere + '.' + family) and '/' in str(value): outside_management(str(address.network), family, ehere + '.' + family)
            _module_settings(endpoint, ehere, modules, 'interface', errors, checker, schema, allow_unlisted=False, vrf_names=vrf_names)
            _vlan_references(endpoint.get('vlan'), ehere + '.vlan', vlan_names, errors)
    interfaces = intent.get('interfaces', {})
    if not isinstance(interfaces, dict) or len(interfaces) > MAX_LINKS: errors.append({'path': 'interfaces', 'message': 'Interface overrides are a mapping of link keys'})
    else:
        for key, ends in interfaces.items():
            here = 'interfaces.' + str(key)
            if not _text(key, 500) or not isinstance(ends, dict): errors.append({'path': here, 'message': 'Invalid interface override'}); continue
            if known_links is not None and key not in known_links: errors.append({'path': here, 'message': 'This link is not in the lab topology any more'})
            for node_name, ifname in ends.items():
                if not _text(node_name) or not _text(ifname, 64) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9/:._-]*', ifname):
                    errors.append({'path': here + '.' + str(node_name), 'message': 'Use the interface name the device itself shows'})
    _check_ledger(intent.get('allocations', {}), errors, outside_management)
    _check_bgp_as(intent, modules, errors)   # after the schema passes, so a field they reported is not reported twice
    return errors


def _check_ledger(ledger, errors, outside_management=lambda value, family, path: None):
    if not isinstance(ledger, dict) or set(ledger) - {'node_ids', 'loopbacks', 'links', 'router_ids', 'planned'}:
        errors.append({'path': 'allocations', 'message': 'The allocation ledger has an unexpected shape'}); return
    ids = ledger.get('node_ids', {})
    if not isinstance(ids, dict) or any(not (_text(k) and _is_int(v) and 1 <= v <= MAX_NODE_ID) for k, v in ids.items()) or len(set(ids.values())) != len(ids):
        errors.append({'path': 'allocations.node_ids', 'message': 'Node ids are distinct whole numbers between 1 and ' + str(MAX_NODE_ID)})
    for section, families in (('loopbacks', ('ipv4', 'ipv6')), ('links', ('ipv4', 'ipv6'))):
        body = ledger.get(section, {})
        if not isinstance(body, dict): errors.append({'path': 'allocations.' + section, 'message': 'Must be a mapping'}); continue
        for name, entry in body.items():
            if not isinstance(entry, dict) or set(entry) - set(families):
                errors.append({'path': 'allocations.' + section + '.' + str(name), 'message': 'Unexpected entry'}); continue
            for family, value in entry.items():
                ok = (_address if section == 'loopbacks' else _prefix)(value, family)[0]
                if not ok: errors.append({'path': 'allocations.' + section + '.' + str(name) + '.' + family, 'message': 'Not a valid ' + family + ' value'})
                else: outside_management(str(ok.ip) if section == 'loopbacks' else str(ok), family, 'allocations.' + section + '.' + str(name) + '.' + family)
    rids = ledger.get('router_ids', {})
    if not isinstance(rids, dict) or any(not (_text(k) and _text(v, 40) and _address(v, 'ipv4')[0]) for k, v in rids.items()):
        errors.append({'path': 'allocations.router_ids', 'message': 'Router ids are IPv4 addresses'})


def normalize(intent):
    """A validated document in its stored form: the schema stamp, defaults for absent sections, a fresh
    revision. Does not validate; call validate() first."""
    result = copy.deepcopy(empty_intent())
    result.update({k: copy.deepcopy(v) for k, v in intent.items() if k in TOP_KEYS and k not in ('revision', 'updated')})
    result['schema'] = SCHEMA
    result['revision'] = revision(result)
    return result


# --- the ledger -------------------------------------------------------------------------------------------

def ledger_from_plan(transformed, link_keys):
    """The allocations a transformed topology made: node ids, loopbacks, link prefixes (matched to the
    manager's link keys by the order the adapter emitted the links in) and router ids."""
    ledger = {'node_ids': {}, 'loopbacks': {}, 'links': {}, 'router_ids': {}}
    for name, node in (transformed.get('nodes') or {}).items():
        if not isinstance(node, dict): continue
        if _is_int(node.get('id')): ledger['node_ids'][name] = node['id']
        loop = node.get('loopback') if isinstance(node.get('loopback'), dict) else {}
        entry = {f: loop[f] for f in ('ipv4', 'ipv6') if isinstance(loop.get(f), str)}
        if entry: ledger['loopbacks'][name] = entry
        for module in ('ospf', 'bgp', 'isis'):
            body = node.get(module)
            rid = body.get('router_id') if isinstance(body, dict) else None
            if isinstance(rid, str) and name not in ledger['router_ids']: ledger['router_ids'][name] = rid
    for index, link in enumerate(transformed.get('links') or []):
        if index >= len(link_keys) or not isinstance(link, dict): break
        prefix = link.get('prefix')
        if not isinstance(prefix, dict): prefix = {}
        entry = {f: prefix[f] for f in ('ipv4', 'ipv6') if isinstance(prefix.get(f), str)}
        if entry: ledger['links'][link_keys[index]] = entry
    return ledger


def renumbering(previous, current):
    """What `current` allocated differently from `previous`: a list of {'kind', 'name', 'family', 'before',
    'after'}; empty when every pinned allocation was kept. New names are not changes."""
    changes = []
    for kind, families in (('node_ids', None), ('loopbacks', ('ipv4', 'ipv6')), ('links', ('ipv4', 'ipv6')), ('router_ids', None)):
        old = (previous or {}).get(kind, {}) or {}; new = (current or {}).get(kind, {}) or {}
        for name, before in old.items():
            if name not in new: continue
            after = new[name]
            if families is None:
                if before != after: changes.append({'kind': kind, 'name': name, 'family': '', 'before': before, 'after': after})
                continue
            for family in families:
                if family in before and family in after and before[family] != after[family]:
                    changes.append({'kind': kind, 'name': name, 'family': family, 'before': before[family], 'after': after[family]})
    return changes
