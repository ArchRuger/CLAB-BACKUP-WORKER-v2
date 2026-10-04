#!/usr/bin/env python3
"""Independent readiness check of the git-redesign lab: a real `show version` over SSH on each node.

Run with the application's virtual environment (needs paramiko):
    clab-backup-ui/.venv/bin/python docs/git-redesign/tools/live/show_version.py [node ...]
Logins are the kinds' published containerlab defaults (containerlab.dev); no personal credentials.
Prints one line per node: the first lines of the answer that name the NOS and version.
"""
import re
import sys
import time

import paramiko

NODES = {
    'ceos1': ('172.20.20.101', 'admin', 'admin', 'show version'),
    'ceos2': ('172.20.20.102', 'admin', 'admin', 'show version'),
    'cjunos': ('172.20.20.103', 'admin', 'admin@123', 'show version'),
    'xrv9k': ('172.20.20.104', 'clab', 'clab@123', 'show version'),
}
ANSI = re.compile(r'(\x1b\[[0-9;?]*[A-Za-z])|[\x07\x00]')


def ask(name):
    ip, user, password, command = NODES[name]
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(ip, username=user, password=password, timeout=10, banner_timeout=20, auth_timeout=20,
                   look_for_keys=False, allow_agent=False)
    try:
        channel = client.invoke_shell(width=200, height=50)
        channel.settimeout(2)
        time.sleep(3)
        for line in ('terminal length 0', command):
            if name.startswith('cjunos') and line.startswith('terminal'):
                line = 'set cli screen-length 0'
            channel.send(line + '\n')
            time.sleep(2)
        out = b''
        end = time.time() + 12
        while time.time() < end:
            try:
                data = channel.recv(65535)
            except Exception:
                break
            if not data:
                break
            out += data
        return ANSI.sub('', out.decode('utf-8', 'replace')).replace('\r', '')
    finally:
        client.close()


if __name__ == '__main__':
    status = 0
    for name in sys.argv[1:] or NODES:
        try:
            text = ask(name)
            lines = [l.strip() for l in text.splitlines() if re.search(r'(Arista|Software image version|Junos:|Hostname:|Model|Cisco IOS XR|Version)', l)]
            print(f'{name}: OK  ' + ' | '.join(lines[:4]))
        except Exception as error:  # noqa: BLE001 - report and continue
            status = 1
            print(f'{name}: NOT READY ({type(error).__name__}: {str(error)[:80]})')
    sys.exit(status)
