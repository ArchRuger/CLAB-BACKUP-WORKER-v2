"""The shared capability model for the *Network design* feature (netlab integration, D3.1/D3.2).

Answers, for one requested capability and one containerlab kind, what the pinned netlab 26.09 engine
can render, what the exact image accepts, and what this integration has actually validated — kept as
three separate axes, never flattened to one mark:

1. **Engine support** — data-driven, read at build time from the pinned engine by
   ``docs/netlab-integration/tools/build_capability_data.py`` and committed as
   ``design_capability_data.json`` (loaded here, never hand-copied). :func:`engine_supports` is the
   only place that reads it.
2. **Image limits** — ``IMAGE_LIMITS``: narrow, hand-written refusals for a specific (kind, feature),
   each with its own reason. Empty until a limit is actually proven.
3. **Validation level** — ``VALIDATION``: this integration's own evidence record, one of
   ``verified_on_image``, ``generated_not_live_tested``, ``unsupported``,
   ``blocked_missing_prerequisite``. Empty until evidence exists; a feature the engine supports with
   no entry here defaults to ``generated_not_live_tested``.

Nothing in this module runs the engine: :func:`engine_data` only ever reads the committed JSON.

``PROFILES`` is the kind -> netlab device profile table from D3.2, with its evidence per entry:
``arista_ceos`` and ``juniper_vjunosswitch`` are exact profile matches; ``juniper_cjunosevolved`` and
``cisco_xrv9k`` are stand-ins (Junos Evolved / IOS XR lineage, but a different image and containerlab
kind than the netlab profile they borrow), so nothing on them is ``verified_on_image`` until proven
live; ``linux`` is a support host only, never applied by this integration. Any other kind is
unsupported with the reason ``'no netlab profile is mapped to this containerlab kind'``.
"""
import json
from pathlib import Path

DATA_PATH = Path(__file__).parent / 'design_capability_data.json'

_engine_data_cache = None


def engine_data():
    """The committed capability JSON, loaded once and cached for the life of the process."""
    global _engine_data_cache
    if _engine_data_cache is None:
        with open(DATA_PATH) as f:
            _engine_data_cache = json.load(f)
    return _engine_data_cache


# Kind -> netlab device profile (D3.2). Every value below is evidenced, not assumed.
PROFILES = {
    'arista_ceos': {
        'profile': 'eos', 'netlab_device': 'eos', 'exact': True,
        'evidence': "exact: netlab's eos profile targets cEOS/vEOS",
        'mgmt_if': 'Management0', 'interfaces': 'EthernetN',
    },
    'juniper_vjunosswitch': {
        'profile': 'vjunos-switch', 'netlab_device': 'vjunos-switch', 'exact': True,
        'evidence': 'exact profile match',
        'mgmt_if': 'fxp0', 'interfaces': 'ge-0/0/N',
    },
    'juniper_cjunosevolved': {
        'profile': 'vptx', 'netlab_device': 'vptx', 'exact': False,
        'evidence': (
            'stand-in: netlab targets vJunos Evolved / vPTX, kind juniper_vjunosevolved; '
            'cJunosEvolved shares the Junos Evolved lineage, et-0/0/N interfaces and re0:mgmt-0, '
            'but its image and containerlab kind differ, so nothing is verified until proven live'
        ),
        'mgmt_if': 're0:mgmt-0', 'interfaces': 'et-0/0/N',
    },
    'cisco_xrv9k': {
        'profile': 'iosxr', 'netlab_device': 'iosxr', 'exact': False,
        'evidence': (
            "stand-in: netlab targets XRd, kind cisco_xrd; XRv9k shares IOS XR, "
            'GigabitEthernet0/0/0/N and MgmtEth0/RP0/CPU0/0, but is a different image'
        ),
        'mgmt_if': 'MgmtEth0/RP0/CPU0/0', 'interfaces': 'GigabitEthernet0/0/0/N',
    },
    'linux': {
        'profile': 'linux', 'netlab_device': 'linux', 'exact': True,
        'evidence': 'support host: generation only, never applied by this integration',
        'mgmt_if': 'eth0', 'interfaces': 'ethN', 'role': 'host',
    },
}
UNMAPPED_KIND_REASON = 'no netlab profile is mapped to this containerlab kind'

# (kind, feature_id) -> reason. Image-specific refusals narrower than the engine/profile already
# say. Start empty: no entry is proven yet. Shape: IMAGE_LIMITS[('arista_ceos', 'evpn')] = 'reason'.
IMAGE_LIMITS = {}

# (kind, feature_id) -> {'level': ..., 'evidence': ...}. This integration's own evidence record.
# Start empty: no live evidence exists yet. Shape:
# VALIDATION[('arista_ceos', 'bgp')] = {'level': 'verified_on_image', 'evidence': 'docs/netlab-integration/evidence/<file>'}
VALIDATION = {}

# GRE/WireGuard are plugins, not netlab modules, so device support is never in module-support data
# (confirmed live: `netlab show module-support --system -m tunnel` fails with "Unknown module").
# This is the documented constant the assignment allows for that case. Evidence:
# ~/research/netlab-integration/RECON-capabilities.md §1 (requested-capability mapping table, GRE/
# WireGuard rows): GRE has device templates for eos and the whole junos family (vjunos-switch, vptx
# borrow the generic junos.j2 template) but none for iosxr; WireGuard has no template for any of eos,
# iosxr or the junos family.
PLUGIN_DEVICES = {
    # The engine's resolved device features carry a `tunnel.gre` flag for eos only (design_capability_data.json,
    # features.eos.tunnel); the generic junos GRE template exists upstream but no Junos profile declares the flag,
    # so GRE is unsupported on the Junos kinds until the engine says otherwise (fail closed).
    'tunnel.gre': {'eos'},
    'tunnel.wireguard': set(),
}

# feature_id -> list of OR-groups of netlab module names; every group needs at least one member in
# resolve()'s requested_modules for the feature to not be blocked_missing_prerequisite.
PREREQUISITES = {
    'evpn': [{'bgp'}, {'vxlan', 'mpls'}],
    'sr_mpls': [{'isis', 'ospf'}],
    'l3vpn': [{'mpls'}, {'bgp'}, {'vrf'}],
    'anycast_gateway': [{'gateway'}],
}

# Requested-capability catalogue. Each entry: label, family, module (a netlab module name, or None
# for a core/plugin capability), attributes (dotted paths, informational), and for feature-flag
# dependent features, feature_flag (a dotted path inside a device's resolved features block) and
# optionally feature_flag_value (membership test instead of truthiness). 'always': True marks a
# capability with no module to check (core addressing, LLDP's initial template). 'plugin' marks a
# netlab plugin instead of a formal module, checked against PLUGIN_DEVICES.
FEATURES = {
    'ipv4': {
        'label': 'IPv4 addressing', 'family': 'addressing', 'module': None, 'always': True,
        'attributes': ['link.ipv4', 'interface.ipv4', 'loopback.ipv4', 'pool.ipv4'],
    },
    'ipv6': {
        'label': 'IPv6 addressing', 'family': 'addressing', 'module': None, 'always': True,
        'attributes': ['link.ipv6', 'interface.ipv6', 'loopback.ipv6', 'pool.ipv6'],
    },
    'ospfv2': {
        'label': 'OSPFv2', 'family': 'igp', 'module': 'ospf',
        'attributes': ['ospf.af.ipv4'],
    },
    'ospfv3': {
        'label': 'OSPFv3', 'family': 'igp', 'module': 'ospf',
        'attributes': ['ospf.af.ipv6'],
    },
    'eigrp': {
        'label': 'EIGRP', 'family': 'igp', 'module': 'eigrp',
        'attributes': ['eigrp.af.ipv4', 'eigrp.af.ipv6', 'eigrp.as'],
    },
    'isis': {
        'label': 'IS-IS', 'family': 'igp', 'module': 'isis',
        'attributes': ['isis.af.ipv4', 'isis.af.ipv6', 'isis.circuit_type', 'isis.unnumbered'],
    },
    'ripv2': {
        'label': 'RIPv2', 'family': 'igp', 'module': 'ripv2',
        'attributes': ['ripv2.af.ipv4'],
    },
    'ripng': {
        'label': 'RIPng', 'family': 'igp', 'module': 'ripv2',
        'attributes': ['ripv2.af.ipv6'],
    },
    'bgp': {
        'label': 'BGP', 'family': 'bgp', 'module': 'bgp',
        'attributes': ['bgp.as', 'bgp.router_id', 'bgp.activate', 'bgp.community', 'bgp.next_hop_self', 'bgp.rr'],
    },
    'dhcp': {
        'label': 'DHCP', 'family': 'services', 'module': 'dhcp',
        'attributes': ['dhcp.client.ipv4', 'dhcp.server', 'dhcp.subnet.ipv4'],
    },
    'dhcpv6': {
        'label': 'DHCPv6', 'family': 'services', 'module': 'dhcp',
        'attributes': ['dhcp.client.ipv6', 'dhcp.subnet.ipv6'],
    },
    'vlan': {
        'label': 'VLANs', 'family': 'layer2', 'module': 'vlan',
        'attributes': ['vlan.mode', 'vlan.access', 'vlan.native', 'vlan.trunk'],
    },
    'vrf': {
        'label': 'VRFs', 'family': 'services', 'module': 'vrf',
        'attributes': ['vrf.id', 'vrf.rd', 'vrf.import', 'vrf.export', 'vrf.loopback'],
    },
    'lldp': {
        'label': 'LLDP', 'family': 'layer2', 'module': None, 'always': True,
        'attributes': [],
    },
    'bfd': {
        'label': 'BFD', 'family': 'igp', 'module': 'bfd',
        'attributes': ['bfd.min_tx', 'bfd.min_rx', 'bfd.min_echo_rx', 'bfd.multiplier'],
    },
    'static_routes': {
        'label': 'Static routes', 'family': 'igp', 'module': 'routing',
        'attributes': ['routing.static'],
    },
    'lacp': {
        'label': 'LACP', 'family': 'layer2', 'module': 'lag',
        'attributes': ['lag.lacp', 'lag.lacp_mode', 'lag.lacp_system_id'],
    },
    'lag': {
        'label': 'Link aggregation (LAG)', 'family': 'layer2', 'module': 'lag',
        'attributes': ['link.mode', 'link.members'],
    },
    'mlag': {
        'label': 'MLAG', 'family': 'layer2', 'module': 'lag',
        'attributes': ['link.mlag', 'node.mlag'],
        'feature_flag': 'lag.mlag',
    },
    'stp': {
        'label': 'Spanning tree', 'family': 'layer2', 'module': 'stp',
        'attributes': ['stp.protocol', 'stp.port_type', 'stp.priority'],
    },
    'vrrp': {
        'label': 'VRRP', 'family': 'services', 'module': 'gateway',
        'attributes': ['gateway.protocol', 'gateway.vrrp'],
        'feature_flag': 'gateway.protocol', 'feature_flag_value': 'vrrp',
    },
    'anycast_gateway': {
        'label': 'Anycast gateway', 'family': 'services', 'module': 'gateway',
        'attributes': ['gateway.protocol', 'gateway.anycast'],
        'feature_flag': 'gateway.protocol', 'feature_flag_value': 'anycast',
    },
    'vxlan': {
        'label': 'VXLAN', 'family': 'tunnels', 'module': 'vxlan',
        'attributes': ['vxlan.flooding', 'vxlan.domain', 'vxlan.vlans'],
    },
    'gre': {
        'label': 'GRE', 'family': 'tunnels', 'module': None, 'plugin': 'tunnel.gre',
        'attributes': ['tunnel.mode', 'tunnel.af', 'tunnel.source', 'tunnel.vrf'],
    },
    'wireguard': {
        'label': 'WireGuard', 'family': 'tunnels', 'module': None, 'plugin': 'tunnel.wireguard',
        'attributes': ['tunnel.mode', 'private_key', 'public_key', 'listen_port'],
    },
    'route_policy': {
        'label': 'Route policy', 'family': 'policy', 'module': 'routing',
        'attributes': ['routing.policy'],
    },
    'prefix_list': {
        'label': 'Prefix lists', 'family': 'policy', 'module': 'routing',
        'attributes': ['routing.prefix'],
    },
    'aspath_filter': {
        'label': 'AS-path filters', 'family': 'policy', 'module': 'routing',
        'attributes': ['routing.aspath'],
    },
    'redistribution': {
        'label': 'Redistribution', 'family': 'policy', 'module': 'routing',
        'attributes': ['<protocol>.import'],
    },
    'default_originate': {
        'label': 'Default route origination', 'family': 'bgp', 'module': 'bgp',
        'attributes': ['bgp.originate'],
        'feature_flag': 'bgp.default_originate',
    },
    'mpls_ldp': {
        'label': 'MPLS LDP', 'family': 'provider', 'module': 'mpls',
        'attributes': ['mpls.ldp'],
        'feature_flag': 'mpls.ldp',
    },
    'bgp_lu': {
        'label': 'BGP labeled unicast', 'family': 'provider', 'module': 'mpls',
        'attributes': ['mpls.bgp'],
        'feature_flag': 'mpls.bgp',
    },
    'l3vpn': {
        'label': 'L3VPN (VPNv4/VPNv6)', 'family': 'provider', 'module': 'mpls',
        'attributes': ['mpls.vpn'],
        'feature_flag': 'mpls.vpn',
    },
    'sixpe': {
        'label': '6PE', 'family': 'provider', 'module': 'mpls',
        'attributes': ['mpls.6pe'],
        'feature_flag': 'mpls.6pe',
    },
    'evpn': {
        'label': 'EVPN', 'family': 'provider', 'module': 'evpn',
        'attributes': ['evpn.transport', 'vrf.bundle', 'vlan.rd', 'vlan.evi'],
    },
    'sr_mpls': {
        'label': 'SR-MPLS', 'family': 'provider', 'module': 'sr',
        'attributes': ['sr.protocol', 'sr.af', 'sr.node_sid', 'sr.srgb'],
    },
    'srv6': {
        'label': 'SRv6', 'family': 'provider', 'module': 'srv6',
        'attributes': ['srv6.igp', 'srv6.locator', 'srv6.bgp', 'srv6.vpn'],
    },
}


def profile_for(kind):
    """The ``PROFILES`` entry for a containerlab kind, or ``None`` when nothing is mapped to it."""
    entry = PROFILES.get(kind)
    return dict(entry) if entry is not None else None


def _dig(tree, dotted_path):
    """Navigate ``tree`` by a dotted path; ``None`` as soon as a segment is missing."""
    node = tree
    for segment in dotted_path.split('.'):
        if not isinstance(node, dict) or segment not in node:
            return None
        node = node[segment]
    return node


def engine_supports(feature_id, profile):
    """Whether netlab 26.09 can render ``feature_id`` on device profile ``profile``.

    Returns ``(bool, reason)``. A core capability with no module (``always``: True) is always
    supported. A plugin capability is checked against ``PLUGIN_DEVICES``. Otherwise the feature's
    module must be in the profile's supported-module set (``module_support`` in the committed JSON);
    when the feature also names a ``feature_flag``, that path inside the profile's resolved feature
    block (``device_features``) must be truthy, or (with ``feature_flag_value``) must contain that
    value.
    """
    feature = FEATURES[feature_id]
    data = engine_data()
    version = data.get('engine_version', '?')
    if feature.get('always'):
        return True, f"'{feature_id}' is a core capability, not a netlab module"
    plugin = feature.get('plugin')
    if plugin:
        devices = PLUGIN_DEVICES.get(plugin, set())
        if profile in devices:
            return True, f"plugin '{plugin}' has a device template for profile '{profile}'"
        return False, f"plugin '{plugin}' has no device template for profile '{profile}'"
    module = feature['module']
    modules_for_profile = data.get('module_support', {}).get(profile, {})
    if module not in modules_for_profile:
        return False, f"netlab {version} module '{module}' does not support device profile '{profile}'"
    flag_path = feature.get('feature_flag')
    if flag_path:
        value = _dig(data.get('device_features', {}).get(profile, {}), flag_path)
        wanted = feature.get('feature_flag_value')
        if wanted is not None:
            ok = isinstance(value, (list, tuple, set)) and wanted in value
            verb = 'contains' if ok else 'does not contain'
            return ok, f"device feature '{flag_path}' {verb} '{wanted}' on profile '{profile}'"
        ok = bool(value)
        state = 'is set' if ok else 'is not set'
        return ok, f"device feature '{flag_path}' {state} on profile '{profile}'"
    return True, f"module '{module}' is supported on profile '{profile}' (netlab {version})"


def resolve(feature_id, kind, requested_modules=None):
    """Combine engine support, the image limit and the validation record for one (feature, kind).

    Returns a dict with keys ``feature``, ``kind``, ``profile`` (the netlab profile name, or ``''``
    when the kind has none), ``engine`` (bool), ``engine_reason``, ``image_limit`` (``''`` when none),
    ``level`` and ``reason``, and ``evidence``. ``level`` is ``'unsupported'`` when there is no
    profile, the engine cannot render the feature, or an image limit applies;
    ``'blocked_missing_prerequisite'`` when ``requested_modules`` is given and a prerequisite module
    (see ``PREREQUISITES``) is missing from it; otherwise the recorded ``VALIDATION`` level, or
    ``'generated_not_live_tested'`` when there is no validation record.
    """
    profile = profile_for(kind)
    if profile is None:
        return {
            'feature': feature_id, 'kind': kind, 'profile': '',
            'engine': False, 'engine_reason': UNMAPPED_KIND_REASON,
            'image_limit': '', 'level': 'unsupported', 'evidence': '', 'reason': UNMAPPED_KIND_REASON,
        }
    profile_name = profile['profile']
    engine_ok, engine_reason = engine_supports(feature_id, profile_name)
    image_limit = IMAGE_LIMITS.get((kind, feature_id), '')
    if not engine_ok:
        return {
            'feature': feature_id, 'kind': kind, 'profile': profile_name,
            'engine': False, 'engine_reason': engine_reason,
            'image_limit': image_limit, 'level': 'unsupported', 'evidence': '', 'reason': engine_reason,
        }
    if image_limit:
        return {
            'feature': feature_id, 'kind': kind, 'profile': profile_name,
            'engine': True, 'engine_reason': engine_reason,
            'image_limit': image_limit, 'level': 'unsupported', 'evidence': '', 'reason': image_limit,
        }
    if requested_modules is not None:
        for group in PREREQUISITES.get(feature_id, []):
            if not (group & requested_modules):
                missing = ' or '.join(sorted(group))
                reason = f"'{feature_id}' requires module {missing}"
                return {
                    'feature': feature_id, 'kind': kind, 'profile': profile_name,
                    'engine': True, 'engine_reason': engine_reason,
                    'image_limit': '', 'level': 'blocked_missing_prerequisite',
                    'evidence': '', 'reason': reason,
                }
    validated = VALIDATION.get((kind, feature_id))
    if validated:
        level = validated['level']
        evidence = validated.get('evidence', '')
        reason = validated.get('reason') or f"validated on {kind}: {level}"
    else:
        level = 'generated_not_live_tested'
        evidence = ''
        reason = f"netlab renders this on profile '{profile_name}' but it was not validated against the {kind} image"
    return {
        'feature': feature_id, 'kind': kind, 'profile': profile_name,
        'engine': True, 'engine_reason': engine_reason,
        'image_limit': '', 'level': level, 'evidence': evidence, 'reason': reason,
    }


def matrix(kinds, feature_ids=None):
    """``resolve()`` over the cross product of ``kinds`` and ``feature_ids`` (default: all FEATURES)."""
    ids = feature_ids if feature_ids is not None else sorted(FEATURES)
    return [resolve(feature_id, kind) for kind in kinds for feature_id in ids]


def public_catalogue():
    """``FEATURES`` for the UI: id, label, family and module name only, no internal attribute paths."""
    return [
        {'id': feature_id, 'label': feature['label'], 'family': feature['family'], 'module': feature['module']}
        for feature_id, feature in sorted(FEATURES.items())
    ]
