#!/usr/bin/env python3
"""Saved vs unsaved configuration across a Restart device, read back independently (nodecli.py, never the manager).

cEOS is the one baseline image with a running configuration distinct from its startup configuration, so the
saved marker is written to startup (`write memory`) and the unsaved marker only to running. Junos and IOS XR
commit straight into the persistent configuration, so for them a single committed marker is the saved one
and there is no unsaved-only running state to test (the candidate is not running configuration).

    persistence_markers.py ceos set      # write both markers (saved: Loopback99 "restart-saved-marker"; unsaved: Loopback98 "restart-unsaved-marker")
    persistence_markers.py ceos read     # print which markers are present now
    persistence_markers.py cjunosevolved set|read   (committed marker only: lo0 unit 0 description)

Run with the application venv (paramiko). Record the outcome in RESTART-PARITY.md as the image's behaviour, not a defect.
"""
import subprocess, sys
from pathlib import Path

NODECLI = Path(__file__).resolve().parents[2] / 'multi-platform-restore' / 'tools' / 'nodecli.py'
SET = {
    'ceos': ['configure', 'interface Loopback99', 'description restart-saved-marker', 'exit', 'end', 'write memory',
             'configure', 'interface Loopback98', 'description restart-unsaved-marker', 'exit', 'end'],
    'cjunosevolved': ['configure', 'set interfaces lo0 unit 0 description restart-saved-marker', 'commit and-quit'],
    'vjunos-switch': ['configure', 'set interfaces lo0 unit 0 description restart-saved-marker', 'commit and-quit'],
    'xrv9k': ['configure', 'interface Loopback0', 'description restart-saved-marker', 'commit', 'end'],
}
READ = {
    'ceos': ['show running-config | include marker', 'show startup-config | include marker'],
    'cjunosevolved': ['show configuration interfaces lo0 | display set | match marker'],
    'vjunos-switch': ['show configuration interfaces lo0 | display set | match marker'],
    'xrv9k': ['show running-config interface Loopback0 | include marker'],
}


def main():
    node, action = sys.argv[1], sys.argv[2]
    lines = SET[node] if action == 'set' else READ[node]
    r = subprocess.run([sys.executable, str(NODECLI), node, *lines, '--timeout', '120'], capture_output=True, text=True)
    text = r.stdout + r.stderr
    print(text[-1500:])
    if action == 'read':
        print('SAVED marker present:', 'restart-saved-marker' in text)
        print('UNSAVED marker present:', 'restart-unsaved-marker' in text)


if __name__ == '__main__': main()
