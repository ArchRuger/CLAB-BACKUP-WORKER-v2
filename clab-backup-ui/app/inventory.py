"""Bounded data-only importer for containerlab Ansible inventories."""
import json
import re
import yaml

JUNOS_DRIVER = {'os': 'junipernetworks.junos.junos', 'command': 'show configuration | display set | no-more', 'suffix': 'set'}
JUNOS_SWITCHES = ('juniper_vqfx', 'juniper_vjunosswitch')
JUNOS_PLATFORMS = ('juniper_cjunosevolved', *JUNOS_SWITCHES)
GENERIC_JUNOS = ('junos', 'junipernetworks.junos.junos')
PLATFORMS = {
    'juniper_cjunosevolved': {'label': 'Junos', **JUNOS_DRIVER},
    'juniper_vqfx': {'label': 'Junos (vQFX)', **JUNOS_DRIVER},
    'juniper_vjunosswitch': {'label': 'Junos (vJunos-switch)', **JUNOS_DRIVER},
    'cisco_xrv9k': {'label': 'IOS-XR', 'os': 'cisco.iosxr.iosxr', 'command': 'show running-config', 'suffix': 'cfg'},
    'arista_ceos': {'label': 'EOS', 'os': 'arista.eos.eos', 'command': 'show running-config', 'suffix': 'cfg'},
}
ALIASES = {'junos': 'juniper_cjunosevolved', 'junipernetworks.junos.junos': 'juniper_cjunosevolved',
           'vr-vqfx': 'juniper_vqfx', 'vqfx': 'juniper_vqfx',
           'vr-vjunosswitch': 'juniper_vjunosswitch', 'vjunosswitch': 'juniper_vjunosswitch',
           'iosxr': 'cisco_xrv9k', 'cisco.iosxr.iosxr': 'cisco_xrv9k',
           'ceos': 'arista_ceos', 'vr-xrv9k': 'cisco_xrv9k', 'cjunosevolved': 'juniper_cjunosevolved', 'eos': 'arista_ceos', 'arista.eos.eos': 'arista_ceos', **{k:k for k in PLATFORMS}}
SAFE_FIELDS = {'ansible_host','ansible_port','ansible_user','ansible_password','ansible_ssh_pass','ansible_network_os','clab_kind','ansible_become_password'}

def literal(value, label, maximum=4096):
    if not isinstance(value, (str, int)) or isinstance(value, bool):
        raise ValueError(f'{label} must be text or a number')
    value = str(value)
    if len(value) > maximum or '\x00' in value or any(x in value for x in ('{{','{%','{#')):
        raise ValueError(f'{label} contains unsupported template syntax or is too long')
    return value

def address(value):
    value = literal(value, 'SSH address', 253)
    if not re.fullmatch(r'[A-Za-z0-9_.:%-]+', value) or value.startswith('-'):
        raise ValueError('Use an IP address or DNS hostname, without a URL or shell syntax')
    return value

def port(value):
    value = int(value)
    if not 1 <= value <= 65535:
        raise ValueError('SSH port must be between 1 and 65535')
    return value

def read_data(raw):
    if len(raw) > 1024*1024:
        raise ValueError('Inventory must be smaller than 1 MiB')
    try:
        text = raw.decode('utf-8-sig') if isinstance(raw, bytes) else raw
        # Reject aliases to keep nested/repeated structures bounded.
        if any(isinstance(t, (yaml.tokens.AliasToken, yaml.tokens.AnchorToken)) for t in yaml.scan(text)):
            raise ValueError('YAML anchors and aliases are not supported; upload the generated inventory directly')
        data = yaml.safe_load(text)
    except (yaml.YAMLError, UnicodeError, RecursionError) as exc:
        raise ValueError('Upload valid UTF-8 YAML or JSON inventory data') from exc
    if not isinstance(data, dict):
        raise ValueError('Inventory must be a YAML/JSON mapping')
    return data

def parse_inventory(raw, topology=None, *, kind_hints=None):
    data = read_data(raw)
    records = {}
    topo_types = {}
    topo_names = {}
    if topology:
        topo = read_data(topology)
        nodes = topo.get('nodes', {})
        if isinstance(nodes, dict):
            for name, node in nodes.items():
                if isinstance(node, dict):
                    for alias in (name, node.get('longname'), node.get('shortname')):
                        if alias:
                            topo_types[str(alias)] = ALIASES.get(node.get('kind'), '')
                            if node.get('shortname'):
                                topo_names[str(alias)]=literal(node['shortname'],'Device short name',200)
    # VM imports also have the original lab YAML. Its concrete kinds keep a
    # generic Junos Ansible driver from relabeling every Juniper as cJunos.
    if kind_hints:
        topo_types.update({name: kind for name, kind in kind_hints.items() if kind in PLATFORMS})
    def fields(values):
        if values is None:
            return {}
        if not isinstance(values, dict):
            raise ValueError('Inventory vars and host values must be mappings')
        return {k:literal(v, k) for k,v in values.items() if k in SAFE_FIELDS and v is not None}
    def add(name, values, groups):
        name = literal(name, 'Node name', 200)
        if not name.strip():
            raise ValueError('Node names cannot be empty')
        record = records.setdefault(name, {'vars': {}, 'groups': set()})
        # Multiple memberships are fine; conflicting connection data needs review.
        for key, value in values.items():
            if key in record['vars'] and record['vars'][key] != value and key != 'ansible_network_os':
                raise ValueError(f'{name}: conflicting {key} across groups; make the inventory values consistent')
            record['vars'][key] = value
        record['groups'].update(groups)
        if len(records) > 2000:
            raise ValueError('Upload no more than 2000 nodes per lab')
    if '_meta' in data:
        meta = data.get('_meta', {}).get('hostvars', {})
        if not isinstance(meta, dict):
            raise ValueError('Invalid script inventory hostvars')
        for name, values in meta.items():
            add(name, fields(values), [])
        for group, body in data.items():
            if group != '_meta' and isinstance(body, dict):
                for name in body.get('hosts', []):
                    add(name, {**fields(body.get('vars')), **fields(meta.get(name))}, [group])
    else:
        def walk(group, body, inherited, parents, depth=0):
            if depth > 16:
                raise ValueError('Inventory nesting is too deep')
            if body is None:
                return
            if not isinstance(body, dict):
                raise ValueError(f'{group}: group must be a mapping')
            values = {**inherited, **fields(body.get('vars'))}
            hosts = body.get('hosts', {}) or {}
            children = body.get('children', {}) or {}
            if not isinstance(hosts, dict) or not isinstance(children, dict):
                raise ValueError('Static inventory hosts and children must be mappings, not lists')
            groups = [*parents, group]
            for name, hostvars in hosts.items():
                add(name, {**values, **fields(hostvars)}, groups)
            for name, child in children.items():
                walk(name, child, values, groups, depth+1)
        for name, body in data.items():
            walk(name, body, {}, [])
    if not records:
        raise ValueError('No hosts found in the inventory')
    result = []
    for name, record in sorted(records.items()):
        v = record['vars']
        kinds = {ALIASES[g] for g in record['groups'] if g in ALIASES}
        explicit = ALIASES.get(v.get('clab_kind')) or ALIASES.get(v.get('ansible_network_os')) or topo_types.get(name)
        if not ALIASES.get(v.get('clab_kind')) and v.get('ansible_network_os') in GENERIC_JUNOS:
            concrete = {ALIASES[g] for g in record['groups'] if g in ALIASES
                        and g not in GENERIC_JUNOS and ALIASES[g] in JUNOS_PLATFORMS}
            inferred = topo_types.get(name)
            if inferred not in JUNOS_PLATFORMS:
                if len(concrete) > 1:
                    raise ValueError(f'{name}: conflicting Junos kinds across groups; set an explicit clab_kind')
                inferred = next(iter(concrete)) if len(concrete) == 1 else ''
            explicit = inferred or explicit
        kind = explicit or (next(iter(kinds)) if len(kinds) == 1 else '')
        result.append({'name': name, 'short_name':topo_names.get(name,''), 'address': address(v.get('ansible_host', name)),
                       'port': port(v.get('ansible_port',22)), 'platform': kind,
                       'enabled': bool(kind), 'profile_id': '',
                       'username': v.get('ansible_user',''),
                       'password': v.get('ansible_password', v.get('ansible_ssh_pass','')),
                       'enable_password': v.get('ansible_become_password',''),
                       'groups': sorted(record['groups'])})
    return result
