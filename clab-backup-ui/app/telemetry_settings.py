"""The persistent part of telemetry: a lab's setting and the lines the manager added.

Kept free of imports so the discovery, inventory and VM-file importers can create a
lab with the current default without pulling in the collector.
"""


def default_settings():
    """New labs start with automatic telemetry on; labs saved before 1.23.0 decide first."""
    return {'auto': True, 'decided': True, 'profile_id': '', 'applied': {}}


def settings_of(lab):
    value = lab.get('telemetry') if isinstance(lab.get('telemetry'), dict) else {}
    return {'auto': bool(value.get('auto')), 'decided': bool(value.get('decided')),
            'profile_id': value.get('profile_id', '') or ''}
