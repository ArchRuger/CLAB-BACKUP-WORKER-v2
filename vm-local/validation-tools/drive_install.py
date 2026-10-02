import os, sys, time, pexpect
pw = open(os.path.expanduser('~/.clab-discovery-password')).read().strip()
log = open(os.environ['INSTALL_LOG'], 'ab')
child = pexpect.spawn('bash', [os.path.expanduser('~/projects/clab-manager/deploy/install.sh')],
                      env=dict(os.environ, TERM='dumb'), encoding=None, timeout=5400, dimensions=(50, 200))
child.logfile_read = log
pats = [r'Choose \[\d\]: ', r'\(y/N\): ', r'[Nn]ew password: ', r'Retype new password: ', pexpect.EOF, pexpect.TIMEOUT]
done_install = False
while True:
    i = child.expect(pats)
    before = child.before.decode(errors='replace')
    tail = before[-1500:]
    if i == 4:
        print('EOF; exit status', child.exitstatus, child.signalstatus); break
    if i == 5:
        print('TIMEOUT waiting for a prompt'); child.terminate(force=True); sys.exit(2)
    if i in (2, 3):
        child.sendline(pw); continue
    if i == 1:
        child.sendline('y'); continue
    # menu prompt: decide by the title in the preceding text
    if 'Recovery' in tail and 'Retry this step' in tail:
        print('RECOVERY MENU REACHED — returning to menu and exiting'); child.sendline('2'); continue
    if 'Next step' in tail:
        child.sendline('2'); done_install = True; continue
    if 'Setup menu' in tail:
        child.sendline('6' if done_install else '1'); continue
    for title in ('Manager bind/port settings', 'Lab operation access', 'VS Code / Containerlab extension access'):
        if title in tail:
            child.sendline('1'); break
    else:
        print('UNKNOWN menu, sending default'); child.sendline('')
child.close()
sys.exit(0 if done_install and child.exitstatus == 0 else 1)
