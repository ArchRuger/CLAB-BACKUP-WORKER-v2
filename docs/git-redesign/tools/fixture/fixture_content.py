"""Content of the scripted repositories and devices: device configurations in the three NOS forms, saved-state
manifests and the topologies they embed. Pure functions, no application state.

The three platform families keep the form the restore drivers expect, so a state built here is loadable through the
real restore service: Junos has a `display set` text (the capture, the saved `.cfg`) and a hierarchical candidate
(the `.jcfg` restore artifact) made from the same statements; EOS and IOS XR keep one running-config text that is both.
"""
import base64
import hashlib
import json
from datetime import datetime, timedelta, timezone

from app.downloads import FORMATS, component, short_name
from app.inventory import PLATFORMS

# The four devices of the reference boards (PROMPT Appendix A), in the order the boards list them.
SQUARE = (('ceos', 'arista_ceos'), ('cjunosevolved', 'juniper_cjunosevolved'),
          ('vjunos-switch', 'juniper_vjunosswitch'), ('xrv9k', 'cisco_xrv9k'))

# What a tag stands for. 'running' is what the devices run when the fixture starts.
LAYERS = {
    'start': ['base'],
    'baseline': ['base'],
    'broken': ['base', 'ospf-wrong', 'shut'],
    'ospf-up': ['base', 'ospf'],
    'loopbacks-reachable': ['base', 'ospf', 'loop'],
    'latest': ['base', 'ospf', 'loop', 'descr'],
    'other': ['base', 'ospf', 'bgp'],
}
# `final` equals `latest` on the two Junos devices (so they read "Already matches" when it is loaded) and differs on
# EOS and IOS XR.
FINAL = {'junos': LAYERS['latest'], 'eos': ['base', 'ospf', 'loop', 'bgp'], 'xr': ['base', 'ospf', 'loop', 'bgp']}
LAYERS['running'] = LAYERS['latest']


def family(platform):
    return 'junos' if str(platform).startswith('juniper') else 'xr' if platform == 'cisco_xrv9k' else 'eos'


def layers_for(tag, platform):
    return FINAL[family(platform)] if tag == 'final' else LAYERS[tag]


def index_of(label):
    names = [n for n, _ in SQUARE]
    return names.index(label) + 1 if label in names else 5 + int(hashlib.sha1(label.encode()).hexdigest()[:2], 16) % 90


# --- Junos -------------------------------------------------------------------------------------------------------

def junos_statements(label, platform, tag):
    i, iface = index_of(label), ('ge-0/0/0' if platform == 'juniper_vjunosswitch' else 'et-0/0/0')
    other = iface[:-1] + '1'
    out = []
    for layer in layers_for(tag, platform):
        if layer == 'base':
            out += [('system', 'host-name ' + label)]
            out += [('interfaces', iface, 'unit 0', 'family ethernet-switching')] if platform == 'juniper_vjunosswitch' else \
                   [('interfaces', iface, 'unit 0', 'family inet', f'address 10.0.{i}.1/30')]
        elif layer == 'ospf':
            out += [('protocols', 'ospf', 'area 0.0.0.0', f'interface {iface}.0')]
        elif layer == 'ospf-wrong':
            out += [('protocols', 'ospf', 'area 0.0.0.9', f'interface {iface}.0')]
        elif layer == 'shut':
            out += [('interfaces', other, 'disable')]
        elif layer == 'loop':
            out += [('interfaces', 'lo0', 'unit 0', 'family inet', f'address 192.0.2.{i}/32')]
        elif layer == 'descr':
            out += [('interfaces', iface, 'description "uplink to core"')]
        elif layer == 'bgp':
            out += [('protocols', 'bgp', 'group core', f'neighbor 10.0.{i}.2', 'peer-as 65001'), ('routing-options', 'autonomous-system 65000')]
    return out


def junos_set(statements):
    return ''.join('set ' + ' '.join(s) + '\n' for s in statements)


def junos_hier(statements):
    tree = {}
    for path in statements:
        node = tree
        for part in path[:-1]:
            node = node.setdefault(part, {})
        node.setdefault(path[-1], None)

    def render(node, depth):
        pad, out = '    ' * depth, []
        for key, child in node.items():
            if child is None:
                out.append(f'{pad}{key};')
            else:
                out.append(f'{pad}{key} {{')
                out += render(child, depth + 1)
                out.append(f'{pad}}}')
        return out
    return '\n'.join(render(tree, 0)) + '\n'


def junos_parse(text):
    """The statements (tuples of levels) of a hierarchical candidate made by `junos_hier`."""
    stack, out = [], []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.endswith('{'):
            stack.append(line[:-1].strip())
        elif line == '}':
            stack.pop()
        else:
            out.append(tuple(stack + [line.rstrip(';')]))
    return out


def junos_flatten(text):
    """The `display set` statements of a hierarchical candidate made by `junos_hier`."""
    return junos_set(junos_parse(text))


# --- EOS and IOS XR ----------------------------------------------------------------------------------------------

def indented_blocks(label, platform, tag):
    """Ordered {header: [child lines]} of the layers, each child already indented for its NOS."""
    i, eos = index_of(label), family(platform) == 'eos'
    pad = '   ' if eos else ' '
    port1, port2 = ('Ethernet1', 'Ethernet2') if eos else ('GigabitEthernet0/0/0/0', 'GigabitEthernet0/0/0/1')
    blocks = {}

    def add(header, *children):
        lines = blocks.setdefault(header, [])
        for child in children:
            if child not in lines:
                lines.append(child)
    for layer in layers_for(tag, platform):
        if layer == 'base':
            add('interface ' + port1, pad + ('no switchport' if eos else 'no shutdown'),
                pad + (f'ip address 10.0.{i}.1/30' if eos else f'ipv4 address 10.0.{i}.1 255.255.255.252'))
        elif layer in ('ospf', 'ospf-wrong'):
            area = '0.0.0.0' if layer == 'ospf' else '0.0.0.9'
            if eos:
                add('router ospf 1', pad + f'router-id 192.0.2.{i}', pad + f'network 10.0.{i}.0/30 area {area}')
            else:
                add('router ospf 1', pad + f'router-id 192.0.2.{i}', pad + f'area {area.replace("0.0.0.", "")}', pad * 2 + f'interface {port1}')
        elif layer == 'shut':
            add('interface ' + port2, pad + 'shutdown')
        elif layer == 'loop':
            add('interface Loopback0', pad + (f'ip address 192.0.2.{i}/32' if eos else f'ipv4 address 192.0.2.{i} 255.255.255.255'))
        elif layer == 'descr':
            add('interface ' + port1, pad + 'description uplink to core')
        elif layer == 'bgp':
            if eos:
                add('router bgp 65000', pad + f'neighbor 10.0.{i}.2 remote-as 65001', pad + f'network 192.0.2.{i}/32')
            else:
                add('router bgp 65000', pad + f'neighbor 10.0.{i}.2', pad * 2 + 'remote-as 65001')
    return blocks


def indented_text(label, platform, tag):
    eos = family(platform) == 'eos'
    lines = (['! Command: show running-config', f'! device: {label} (cEOSLab, EOS-4.35.0F)', '!', 'hostname ' + label, '!'] if eos else
             ['!! IOS XR Configuration 24.3.1', '!! Last configuration change at Sat Oct  3 09:00:00 2026 by clab', '!', 'hostname ' + label, '!'])
    for header, children in indented_blocks(label, platform, tag).items():
        lines += [header, *children, '!']
    lines.append('end')
    return '\n'.join(lines) + '\n'


# --- one device ---------------------------------------------------------------------------------------------------

def device_texts(platform, label, tag):
    """(capture text, restore candidate) of a device in a state. They are one text for EOS and IOS XR."""
    if family(platform) == 'junos':
        statements = junos_statements(label, platform, tag)
        return junos_set(statements), junos_hier(statements)
    text = indented_text(label, platform, tag)
    return text, text


def candidate_to_capture(platform, candidate):
    """What a device runs once it has loaded `candidate`, in the form its capture shows."""
    return junos_flatten(candidate) if family(platform) == 'junos' else candidate


def odd_capture(platform, label, text):
    """A configuration that is neither the saved one nor the previous one (the `uncertain` outcome)."""
    if family(platform) == 'junos':
        return text + 'set system ntp server 203.0.113.9\n'
    return text.replace('\nend\n', '\nntp server 203.0.113.9\n!\nend\n')


# --- topologies ---------------------------------------------------------------------------------------------------

def square_yaml(lab_name, other=False):
    """The reference square. `other=True` is a different topology: another fourth node and other links."""
    nodes = [(n, k) for n, k in SQUARE]
    links = [('ceos:eth1', 'cjunosevolved:et-0/0/0'), ('cjunosevolved:et-0/0/1', 'xrv9k:Gi0/0/0/0'),
             ('xrv9k:Gi0/0/0/1', 'vjunos-switch:ge-0/0/0'), ('vjunos-switch:ge-0/0/1', 'ceos:eth2')]
    if other:
        nodes[3] = ('ceos2', 'arista_ceos')
        links = [('ceos:eth1', 'cjunosevolved:et-0/0/0'), ('cjunosevolved:et-0/0/1', 'vjunos-switch:ge-0/0/0'),
                 ('vjunos-switch:ge-0/0/1', 'ceos2:eth1'), ('ceos2:eth2', 'ceos:eth2')]
    text = f'name: {lab_name}\ntopology:\n  nodes:\n' + ''.join(f'    {n}:\n      kind: {k}\n' for n, k in nodes) + '  links:\n'
    return text + ''.join(f'    - endpoints: ["{a}", "{b}"]\n' for a, b in links)


def pair_yaml(lab_name, kind='arista_ceos', a='r1', b='r2'):
    return (f'name: {lab_name}\ntopology:\n  nodes:\n    {a}:\n      kind: {kind}\n    {b}:\n      kind: {kind}\n'
            f'  links:\n    - endpoints: ["{a}:eth1", "{b}:eth1"]\n')


# --- saved states -------------------------------------------------------------------------------------------------

def ago(seconds):
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds)).isoformat()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def snapshot_name(platform, label):
    spec = PLATFORMS[platform]
    return f"{label}.{spec.get('snapshot_suffix') or spec['suffix']}"


def build_state(lab_id, lab_name, nodes, tag, *, restore=True, topology=None, annotations=None, captured_ago=1200,
                backup_job_id='fixture', overrides=None, source='manager'):
    """A saved state as the manager's capture builds it: `(manifest, {file name: bytes})`.

    nodes: dicts with name, short_name, platform. `overrides` maps a node name to (capture, candidate) texts that replace
    the generated ones. `topology` and `annotations` are bytes embedded as entries of their own kind."""
    files, entries = {}, []
    for n in sorted(nodes, key=lambda n: n['name']):
        label = component(short_name(n, lab_name))
        capture, candidate = (overrides or {}).get(n['name']) or device_texts(n['platform'], label, tag)
        name = snapshot_name(n['platform'], label)
        files[name] = capture.encode()
        entry = dict(path=name, size=len(files[name]), sha256=sha(files[name]), node=n['name'], short_name=n.get('short_name', ''),
                     platform=n['platform'], format=list(FORMATS[n['platform']]))
        if restore:
            artifact = f"{label}.{PLATFORMS[n['platform']]['restore_suffix']}"
            files[artifact] = candidate.encode()
            entry.update(restore_artifact=artifact, restore_size=len(files[artifact]), restore_sha256=sha(files[artifact]),
                         restore_format=PLATFORMS[n['platform']]['restore_format'], restore_capable=True)
        entries.append(entry)
    digest = ''
    base = component(lab_name, 'lab')
    for key, raw, name in (('topology', topology, base + '.clab.yml'), ('annotations', annotations, base + '.clab.yml.annotations.json')):
        if not raw:
            continue
        files[name] = raw
        entries.append(dict(path=name, size=len(raw), sha256=sha(raw), kind=key, source=source, vm_path=f'/etc/containerlab/{lab_name}/{lab_name}.clab.yml'))
        if key == 'topology':
            digest = sha(raw)
    manifest = dict(schema=2, lab_id=lab_id, lab_name=lab_name, backup_job_id=backup_job_id, captured_at=ago(captured_ago),
                    topology_digest=digest or None, topology_provenance='embedded' if digest else 'unknown',
                    node_names=sorted(n['name'] for n in nodes), excluded_nodes=[],
                    restore_capable_nodes=sum(1 for e in entries if e.get('restore_artifact')), files=entries)
    return manifest, files


def build_design_export(lab_id, lab_name, captured_ago=40 * 86400):
    """A design export as `network_design.design_snapshot` builds it: generated artifacts, no device rows, no restore data."""
    files = {'network-intent.yml': b'containerlab_node_manager:\n  type: network-intent\nnodes: [ceos, xrv9k]\n',
             'plan.json': b'{"modules": ["ospf"]}\n', 'topology.yml': square_yaml(lab_name).encode(), 'mapping.json': b'{"ceos": "clab-' + lab_name.encode() + b'-ceos"}\n',
             'ceos--00-ospf.cfg': b'router ospf 1\n   network 10.0.1.0/30 area 0.0.0.0\n', 'xrv9k--00-ospf.cfg': b'router ospf 1\n area 0\n'}
    kinds = {'network-intent.yml': 'intent', 'plan.json': 'plan', 'topology.yml': 'topology', 'mapping.json': 'mapping'}
    rows = [dict(path=n, size=len(raw), sha256=sha(raw), artifact='network-design', kind=kinds.get(n, 'fragment'),
                 **({} if n in kinds else dict(device=n.split('--')[0], module='ospf'))) for n, raw in sorted(files.items())]
    manifest = dict(schema=2, kind='network-design', lab_id=lab_id, lab_name=lab_name, generation_id='fixture-generation', intent_revision='fixture',
                    topology_digest=sha(files['topology.yml']), engine_version='fixture', generated_at=ago(captured_ago), modules=['ospf'], files=rows)
    return manifest, files


def encode_snapshot(manifest, files):
    """The `snapshot` of a publish or read-version request: {manifest, files: {name: base64}}."""
    return {'manifest': manifest, 'files': {n: base64.b64encode(raw).decode('ascii') for n, raw in files.items()}}


def dumps(manifest):
    return (json.dumps(manifest, sort_keys=True, indent=2, ensure_ascii=False) + '\n').encode()
