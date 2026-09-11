#!/usr/bin/env python3
"""Read sanitized Git bindings before helper installation, without opening Git."""
import importlib.util
import json
import os
from pathlib import Path
import stat
import sys


FIELDS = ('id', 'label', 'owner', 'path', 'remote', 'push_url', 'branch', 'prefix', 'revision')


def host_helper():
    source = Path(__file__).resolve().parents[1] / 'clab-backup-ui/app/host_git.py'
    spec = importlib.util.spec_from_file_location('registration_host_git', source)
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    return helper


def trusted_parents(path):
    # A missing registry is normal on first setup. Its existing ancestors must
    # still be ordinary root-owned directories, not attacker-controlled paths.
    for parent in path.parents:
        if not parent.exists():
            continue
        metadata = parent.stat()
        if (not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != 0
                or metadata.st_mode & 0o022):
            raise ValueError('The Git registry directory must be root-owned and not writable by other users.')


def registrations(helper):
    registry = helper.no_links(helper.REGISTRY, require=False)
    trusted_parents(registry)
    config = helper.load_registry() if registry.exists() else {'repositories': []}
    repositories = []
    for binding in config['repositories']:
        if not isinstance(binding, dict) or any(not isinstance(binding.get(key), str) for key in FIELDS):
            raise ValueError('Invalid Git registration settings.')
        # Registry data normally passed registration checks already. Reject a
        # malformed URL here rather than exposing embedded credentials in output.
        helper.checked_url(binding['push_url'])
        repositories.append({key: binding[key] for key in FIELDS})
    return {'result': {'protocol': helper.PROTOCOL, 'version': helper.VERSION,
                       'repositories': repositories}}


def main():
    try:
        if len(sys.argv) != 1 or os.name != 'posix' or os.geteuid() != 0:
            raise ValueError('Use sudo bash deploy/setup-git.sh --list on the VM.')
        result = registrations(host_helper())
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (ValueError, OSError, KeyError, TypeError):
        # Do not print registry fields or parser input in diagnostics.
        print(json.dumps({'error': 'Could not read registered Git checkout settings. '
                          'Check the root-owned registry and parent directories; existing settings were not changed.'}))
        return 1


if __name__ == '__main__':
    sys.exit(main())
