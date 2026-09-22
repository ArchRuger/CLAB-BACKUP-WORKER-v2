"""Tiny cEOS SSH helper for authoring evidence (admin/admin, direct node SSH)."""
import re, sys, time
import paramiko

def _drain(chan, quiet=0.6, limit=20):
    out = b''; last = time.time(); start = time.time()
    while time.time() - start < limit:
        if chan.recv_ready():
            out += chan.recv(65535); last = time.time()
        elif time.time() - last > quiet:
            break
        else:
            time.sleep(0.05)
    return out.decode('utf-8', 'replace')

def session(host, user='admin', password='admin'):
    c = paramiko.SSHClient(); c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(host, username=user, password=password, look_for_keys=False, allow_agent=False, timeout=20)
    ch = c.invoke_shell(width=200, height=60)
    _drain(ch); ch.send('terminal length 0\n'); _drain(ch)
    return c, ch

def run(host, lines, quiet=0.8):
    """Send lines one by one on a shell; return the whole transcript."""
    c, ch = session(host)
    out = ''
    for line in lines:
        ch.send(line + '\n'); out += _drain(ch, quiet)
    c.close()
    return out

def configure(host, config_lines):
    return run(host, ['enable', 'configure terminal'] + config_lines + ['end', 'write memory'])

def show(host, cmd):
    return run(host, ['enable', cmd])

if __name__ == '__main__':
    print(run(sys.argv[1], sys.argv[2:]))
