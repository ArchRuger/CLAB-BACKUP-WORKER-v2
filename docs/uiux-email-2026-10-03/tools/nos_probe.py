#!/usr/bin/env python3
"""Read prompts / hostnames from the lab NOSes over SSH (containerlab default logins). Prints, never stores, credentials."""
import sys, time, paramiko
NODES = {'ceos1': ('172.20.20.2', 'admin', 'admin'), 'ptx1': ('172.20.20.3', 'admin', 'admin@123'), 'xr1': ('172.20.20.4', 'clab', 'clab@123'), 'sw1': ('172.20.20.6', 'admin', 'admin@123')}
def run(host, user, pw, cmds, wait=3):
    c = paramiko.SSHClient(); c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(host, username=user, password=pw, timeout=8, banner_timeout=15, auth_timeout=15, look_for_keys=False, allow_agent=False)
    ch = c.invoke_shell(width=200, height=50); time.sleep(wait); out = ch.recv(65535).decode('utf-8', 'replace')
    for cmd in cmds:
        ch.send(cmd + '\n'); time.sleep(wait); out += ch.recv(65535).decode('utf-8', 'replace')
    c.close(); return out
if __name__ == '__main__':
    names = sys.argv[1].split(',') if len(sys.argv) > 1 else list(NODES)
    cmds = sys.argv[2].split(';') if len(sys.argv) > 2 else []
    for n in names:
        h, u, p = NODES[n]
        try: print('=====', n); print(run(h, u, p, cmds)[-900:])
        except Exception as e: print('=====', n, 'ERR', type(e).__name__, str(e)[:100])
