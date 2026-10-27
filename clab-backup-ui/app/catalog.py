"""The device catalog: the one list the lab builder, the Topology editor and the manager's validation read.

``GET /api/catalog`` answers ``{'entries': [...], 'kinds': [...]}`` and nothing else: read-only, no input,
no secret (a default login is only a boolean here; the credentials stay in ``inventory.DEFAULT_CREDENTIALS``).
Where each field comes from (docs/parity-campaign/TOPOLOGY-EDIT-DESIGN.md section 3 and amendments 12):

- ``kind``, ``image`` and ``template`` (name, baseName, interfacePattern, icon, match, pinned, env): ``IMAGES``
  below, moved from the JavaScript ``BUILDER_TEMPLATES`` constant, which keeps a copy as the offline fallback
  (``tests/test_catalog.py`` asserts the two are equal).
- ``label``: ``inventory.PLATFORMS`` (``Linux host`` for ``linux``).
- ``aliases``: ``inventory.ALIASES`` entries that point at the kind, other than the kind itself.
- ``login_default``: ``kind in inventory.DEFAULT_CREDENTIALS``.
- ``interfaces``: ``topology.PORT_RULES`` (the scheme regex without its inline ``(?i)``, applied with flags
  ``i``; the NOS port prefix; the first port; the container names ``eth1`` .. the image reserves because its
  first data port is offset N) and ``topology.CONTAINER_NAME``; ``None`` when the kind has no rule.
- ``capabilities``: backup = ``PLATFORMS``; restore = ``restore_drivers.supported_kinds()``; design = a
  ``design_capabilities.PROFILES`` entry that is not the support host; console = ``inventory.console_port``.
"""
from . import design_capabilities, restore_drivers
from .inventory import ALIASES, DEFAULT_CREDENTIALS, PLATFORMS, console_port
from .topology import CONTAINER_NAME, PORT_RULES

# kind -> the exact default image and the template fields (name, baseName, interfacePattern, icon, match, pinned, env).
IMAGES = {
    'arista_ceos': {'image': 'n24l/ceos:4.35.0F', 'name': 'Arista cEOS', 'baseName': 'ceos', 'interfacePattern': 'eth{n}',
                    'icon': 'switch', 'match': ['ceos'], 'pinned': True},
    'juniper_cjunosevolved': {'image': 'n24l/cjunosevolved:26.2R1.7-EVO', 'name': 'Juniper cJunosEvolved', 'baseName': 'ptx',
                              'interfacePattern': 'et-0/0/{n:0}', 'icon': 'pe', 'match': ['cjunosevolved'], 'pinned': True,
                              'env': {'CPTX_AUTO_CONFIG': '1'}},
    'juniper_vjunosswitch': {'image': 'n24l/vjunos-switch:23.2R1.14', 'name': 'Juniper vJunos-switch', 'baseName': 'sw',
                             'interfacePattern': 'ge-0/0/{n:0}', 'icon': 'switch',
                             'match': ['vjunos-switch', 'juniper_vjunos-switch', 'vjunosswitch'], 'pinned': True},
    'juniper_vjunosrouter': {'image': 'n24l/juniper_vjunos-router:26.2R1.7', 'name': 'Juniper vJunos-router', 'baseName': 'rtr',
                             'interfacePattern': 'ge-0/0/{n:0}', 'icon': 'pe',
                             'match': ['vjunos-router', 'juniper_vjunos-router', 'vjunosrouter'], 'pinned': True},
    'juniper_vsrx': {'image': 'n24l/juniper_vsrx:23.2R2.21', 'name': 'Juniper vSRX', 'baseName': 'srx',
                     'interfacePattern': 'ge-0/0/{n:0}', 'icon': 'pe', 'match': ['vsrx', 'juniper_vsrx'], 'pinned': True},
    'cisco_xrv9k': {'image': 'n24l/cisco_xrv9k:24.3.1', 'name': 'Cisco XRv9k', 'baseName': 'xr',
                    'interfacePattern': 'Gi0/0/0/{n:0}', 'icon': 'pe', 'match': ['cisco_xrv9k', 'xrv9k'], 'pinned': True},
    'linux': {'image': 'ghcr.io/srl-labs/network-multitool:latest', 'name': 'Linux host', 'baseName': 'host',
              'interfacePattern': 'eth{n}', 'icon': 'client', 'match': ['network-multitool']},
}
TEMPLATE_FIELDS = ('name', 'baseName', 'interfacePattern', 'icon', 'match', 'pinned', 'env')


def _interfaces(kind):
    rule = PORT_RULES.get(kind)
    if rule is None:
        return None
    prefix, pattern, offset = rule
    return {'pattern': pattern.pattern.replace('(?i)', '', 1), 'flags': 'i', 'prefix': prefix, 'first_port': prefix + '0',
            'reserved': ['eth%d' % n for n in range(1, offset)],
            'container_pattern': CONTAINER_NAME.pattern.replace('(?i)', '', 1)}


def _template(kind):
    spec = IMAGES[kind]
    out = {}
    for field in TEMPLATE_FIELDS:
        if field == 'pinned':
            out[field] = bool(spec.get('pinned', False))
        elif field in spec:
            out[field] = list(spec[field]) if field == 'match' else dict(spec[field]) if field == 'env' else spec[field]
    return out


def _entry(kind):
    profile = design_capabilities.PROFILES.get(kind)
    return {
        'kind': kind,
        'label': PLATFORMS[kind]['label'] if kind in PLATFORMS else 'Linux host',
        'image': IMAGES[kind]['image'],
        'aliases': sorted(a for a, target in ALIASES.items() if target == kind and a != kind),
        'login_default': kind in DEFAULT_CREDENTIALS,
        'interfaces': _interfaces(kind),
        'capabilities': {
            'backup': kind in PLATFORMS,
            'restore': kind in restore_drivers.supported_kinds(),
            'design': profile is not None and profile.get('role') != 'host',
            'console': console_port(kind) is not None,
        },
        'template': _template(kind),
    }


def entries():
    return [_entry(kind) for kind in IMAGES]


class Catalog:
    def install(self, app):
        @app.get('/api/catalog')
        def catalog():
            items = entries()
            return {'entries': items, 'kinds': [e['kind'] for e in items]}
