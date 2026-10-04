#!/usr/bin/env python3
"""Run EOS commands on a git-redesign cEOS node over SSH (documented cEOS login admin/admin).

    clab-backup-ui/.venv/bin/python docs/git-redesign/tools/live/ceos_cli.py ceos1 'configure' 'interface Ethernet1' 'description x' 'end' 'show running-config interfaces Ethernet1'
"""
import sys
import time

import paramiko

IPS = {'ceos1': '172.20.20.101', 'ceos2': '172.20.20.102'}
name, lines = sys.argv[1], sys.argv[2:]
client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(IPS[name], username='admin', password='admin', timeout=10, look_for_keys=False, allow_agent=False)
channel = client.invoke_shell(width=200, height=50)
channel.settimeout(2)
time.sleep(2)
for line in ['terminal length 0'] + lines:
    channel.send(line + '\n')
    time.sleep(1.2)
out = b''
try:
    while True:
        chunk = channel.recv(65535)
        if not chunk:
            break
        out += chunk
except Exception:
    pass
print(out.decode(errors='replace'))
client.close()
