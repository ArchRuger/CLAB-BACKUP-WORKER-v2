"""Print sha256 of the running config of ptx1 (Junos set form) and xr1 (running-config). Hashes only."""
import hashlib, re, sys, time, paramiko
DEV = {'ptx1': ('172.20.20.3', 'admin', 'admin@123', 'show configuration | display set | no-more'),
       'xr1': ('172.20.20.4', 'clab', 'clab@123', 'show running-config'),
       'ceos1': ('172.20.20.2', 'admin', 'admin', 'show running-config')}
def run(name):
    ip, u, p, cmd = DEV[name]
    c = paramiko.SSHClient(); c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(ip, username=u, password=p, timeout=30, look_for_keys=False, allow_agent=False)
    sh = c.invoke_shell(width=500, height=2000); time.sleep(2); sh.recv(65535)
    if name == 'xr1': sh.send('terminal length 0\n'); time.sleep(1); sh.recv(65535)
    if name == 'ceos1': sh.send('terminal length 0\n'); time.sleep(1); sh.recv(65535)
    sh.send(cmd + '\n'); out = b''; end = time.time() + 40; last = time.time()
    while time.time() < end:
        if sh.recv_ready(): out += sh.recv(65535); last = time.time()
        elif time.time() - last > 5 and out: break
        else: time.sleep(0.3)
    c.close(); t = out.decode(errors='replace')
    lines = [l.rstrip() for l in t.splitlines()[1:]]
    # drop prompt lines, timestamps and commit-id/volatile lines
    lines = [l for l in lines if not re.match(r'^(RP/|admin@|.*[#>]\s*$)', l) and not re.search(r'Last configuration change|Building configuration|^!! Last|Mon |Tue |Wed |Thu |Fri |Sat |Sun |Current configuration', l)]
    return hashlib.sha256('\n'.join(lines).encode()).hexdigest()[:16], len(lines)
if __name__ == '__main__':
    for n in (sys.argv[1:] or ['ptx1', 'xr1']):
        try: print(n, *run(n))
        except Exception as e: print(n, 'ERR', repr(e)[:150])
