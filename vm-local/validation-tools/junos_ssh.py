"""Direct Junos CLI helper for validation (paramiko shell, admin/admin@123)."""
import re, sys, time, paramiko
ANSI = re.compile(r'\x1b\[[0-9;?]*[A-Za-z]|\r')
def shell(host, user='admin', password='admin@123'):
    c = paramiko.SSHClient(); c.set_missing_host_key_policy(paramiko.AutoAddPolicy()); c.connect(host, username=user, password=password, look_for_keys=False, allow_agent=False, timeout=30, banner_timeout=60, auth_timeout=60)
    ch = c.invoke_shell(width=250, height=200); time.sleep(2); ch.recv(65535); return c, ch
def run(ch, cmd, prompt=r'[>#%]\s*$', timeout=90):
    ch.send(cmd + '\n'); out = ''; t = time.time()
    while time.time() - t < timeout:
        if ch.recv_ready(): out += ch.recv(65535).decode('utf-8', 'replace'); t2 = time.time()
        else: time.sleep(0.2)
        clean = ANSI.sub('', out)
        if re.search(prompt, clean.strip().split('\n')[-1] if clean.strip() else '') and not ch.recv_ready():
            time.sleep(0.4)
            if not ch.recv_ready(): break
    return ANSI.sub('', out)
def cli(host, commands, password='admin@123'):
    c, ch = shell(host, password=password); out = []
    run(ch, 'set cli screen-length 0'); run(ch, 'set cli screen-width 250')
    for cmd in commands: out.append(run(ch, cmd))
    c.close(); return out
if __name__ == '__main__':
    host = sys.argv[1]; cmds = sys.argv[2:]
    for o in cli(host, cmds): print(o)
