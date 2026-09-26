#!/usr/bin/env python3
"""Regenerate ``clab-backup-ui/app/design_capability_data.json`` from the pinned netlab engine.

This is the *only* place that runs ``netlab show``; the runtime module (``app/design_capabilities.py``)
only ever reads the committed JSON. Run it with the manager's venv on ``PATH`` so ``shutil.which('netlab')``
finds the pinned ``networklab`` build, never a hard-coded interpreter path::

    cd clab-backup-ui
    PATH="$PWD/.venv/bin:$PATH" python3 ../docs/netlab-integration/tools/build_capability_data.py app/design_capability_data.json

Exact commands run (confirmed against networklab 26.09; recorded here because the *shape* of
``netlab show`` output has changed across releases before, so a future regeneration that silently
picks a different form is a real risk this docstring exists to catch):

* ``netlab version`` — first line's last token is the engine version (``engine_version`` in the JSON).
* ``netlab show module-support --system --format yaml`` — the combined per-device form. This *does*
  work on 26.09 (unlike the per-``-d``/plain-``modules`` fallbacks the assignment allowed for): it
  returns, for every device netlab knows about, a dict of ``{module: <features block>}`` for exactly
  the modules that device supports — i.e. dict-key presence already **is** the module x device support
  matrix, and the value already **is** that module's resolved feature-flag block for that device (the
  two are not two different queries on this release: verified by diffing this output for ``eos``/``bgp``
  against ``netlab show defaults devices.eos.features --format yaml``'s ``bgp`` block byte-for-byte
  identical). No per-device (``-d``) fallback or ``netlab show modules`` call was needed.
* ``netlab show attributes --system --format yaml`` — the whole-topology attribute schema, filtered
  of ``TOP_ATTRIBUTE_DROP`` (validation tests and internal bookkeeping; the manager keeps the level sections, the
  named types behind the routing-policy features; ``_v_entry``, ``_v_option``, ``tools``, ``validate``,
  ``plugin`` and ``defaults`` are dropped defensively by ``_drop_unsafe`` if they ever appear — they did
  not appear in this release's output, but they are exactly the executable/unsafe keys the manager must
  never accept, so the filter stays even though it is a no-op today).
* ``netlab show attributes --system --format yaml -m <module>`` for each of the 18 modules in
  ``MODULES`` (the exact list the assignment names: bfd, bgp, dhcp, eigrp, evpn, gateway, isis, lag,
  mpls, ospf, ripv2, routing, sr, srv6, stp, vlan, vrf, vxlan).
* ``netlab show defaults devices.<device>.features --format yaml`` for each of the four device
  profiles (``eos``, ``vjunos-switch``, ``vptx``, ``iosxr``). This is kept as its own JSON section
  (``device_features``) even though its per-module content overlaps ``module_support`` for those four
  devices, because it is also the only source for feature blocks outside the module registry that
  ``design_capabilities.py`` needs for its ``feature_flag`` lookups (for example ``gateway.protocol``,
  ``lag.mlag``, ``mpls.6pe``): ``module-support`` only ever exposes modules netlab treats as a formal
  module, and always as the same nested block, so reading feature flags out of ``device_features``
  rather than reaching back into ``module_support`` keeps the flag lookup independent of which of the
  two commands happens to carry a given module in a future netlab release.

Needs only the standard library plus PyYAML (already in the manager's venv). Takes the output path as
its only argument.
"""
import json
import shutil
import subprocess
import sys

import yaml

# The 18 modules whose attribute schema and feature flags this integration's FEATURES catalogue
# depends on (docs/netlab-integration/tools/build_capability_data.py is the only place this list is
# hand-copied; app/design_capabilities.py checks every FEATURES module against the JSON's own
# 'modules' list instead of repeating it).
MODULES = [
    'bfd', 'bgp', 'dhcp', 'eigrp', 'evpn', 'gateway', 'isis', 'lag', 'mpls', 'ospf', 'ripv2',
    'routing', 'sr', 'srv6', 'stp', 'vlan', 'vrf', 'vxlan',
]

# The four containerlab-kind stand-in profiles this integration targets (D3.2).
PROFILE_DEVICES = ['eos', 'vjunos-switch', 'vptx', 'iosxr']

# Top-level `netlab show attributes` sections the manager needs: the addressing/vlan/vrf scopes plus
# the named types behind route_policy/prefix_list/aspath_filter/static_routes/redistribution.
# Top-level `netlab show attributes` sections the manager drops: validation tests and their options (they
# name commands to run), and netlab's internal bookkeeping. Everything else stays: the level sections
# (global, node, link, interface, loopback), the VLAN and VRF object schemas and every named type the module
# schemas refer to (bgp_prefix_list, acl_entry, static_entry, ...), so the manager's checker can resolve them.
TOP_ATTRIBUTE_DROP = {'_v_entry', '_v_option', 'internal', 'global_extra_ns', 'can_be_false'}

# Executable or unsafe keys the manager never accepts from engine output, dropped wherever found.
UNSAFE_KEYS = {'_v_entry', '_v_option', 'tools', 'validate', 'plugin', 'defaults'}


def _netlab_bin():
    netlab = shutil.which('netlab')
    if not netlab:
        raise SystemExit(
            "netlab not found on PATH; run with the manager's venv on PATH, e.g.\n"
            '  cd clab-backup-ui && PATH="$PWD/.venv/bin:$PATH" python3 '
            '../docs/netlab-integration/tools/build_capability_data.py app/design_capability_data.json'
        )
    return netlab


def _run(*args):
    """Run `netlab <args>` and return stdout, or fail loudly with the exact argv and stderr."""
    argv = [_netlab_bin(), *args]
    result = subprocess.run(argv, capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit(f"{' '.join(argv)} failed (exit {result.returncode}): {result.stderr.strip()}")
    return result.stdout


def _drop_unsafe(value):
    if isinstance(value, dict):
        return {k: _drop_unsafe(v) for k, v in value.items() if k not in UNSAFE_KEYS}
    if isinstance(value, list):
        return [_drop_unsafe(v) for v in value]
    return value


def _yaml(text):
    return _drop_unsafe(yaml.safe_load(text) or {})


def engine_version():
    first_line = _run('version').splitlines()[0]
    return first_line.split()[-1]


def build():
    version = engine_version()
    module_support = _yaml(_run('show', 'module-support', '--system', '--format', 'yaml'))
    top_attributes = _yaml(_run('show', 'attributes', '--system', '--format', 'yaml'))
    top_attributes = {k: v for k, v in top_attributes.items() if k not in TOP_ATTRIBUTE_DROP}
    attributes = {'top': top_attributes}
    for module in MODULES:
        attributes[module] = _yaml(_run('show', 'attributes', '--system', '--format', 'yaml', '-m', module))
    device_features = {}
    for device in PROFILE_DEVICES:
        device_features[device] = _yaml(
            _run('show', 'defaults', f'devices.{device}.features', '--format', 'yaml')
        )
    return {
        'engine_version': version,
        'modules': sorted(MODULES),
        'module_support': module_support,
        'attributes': attributes,
        'device_features': device_features,
    }


def main():
    if len(sys.argv) != 2:
        raise SystemExit('usage: build_capability_data.py <output-path>')
    data = build()
    with open(sys.argv[1], 'w') as f:
        json.dump(data, f, indent=2, sort_keys=True)
        f.write('\n')


if __name__ == '__main__':
    main()
