#!/usr/bin/env python3
"""Item 1 live reproduction (docs/ui-ux-changes-2): hold /var/lib/dpkg/lock-frontend with a harmless fcntl lock (what apt and
dpkg use), run the real installer under a pseudo-terminal, choose the standard path, let the VM
prerequisites phase meet the lock, record the Package lock recovery screen, choose 3 (return to menu)
and exit. Nothing is killed, deleted or restarted; the holder is released at the end."""
import os, subprocess, sys, time
import pexpect
repo = sys.argv[1]; out = sys.argv[2]  # usage: installer_lock_repro.py <checkout> <screen log>  (dev VM only: removes and reinstalls curl)
# A fresh VM lacks the basic packages, which is what makes the prerequisites phase call apt-get install
# and meet the lock. On this installed VM one basic package (curl, with the metapackages that depend on
# it) is removed for the run and reinstalled afterwards.
RESTORE = ['curl', 'pollinate', 'ubuntu-server', 'ubuntu-server-minimal']
subprocess.run(['sudo', 'apt-get', 'remove', '-y', '-q', 'curl'], check=True, stdout=subprocess.DEVNULL)
holder = subprocess.Popen(['sudo', 'python3', '-c',
    "import fcntl,os,time,sys; fd=os.open('/var/lib/dpkg/lock-frontend', os.O_RDWR|os.O_CREAT, 0o640); fcntl.lockf(fd, fcntl.LOCK_EX); print('held', flush=True); time.sleep(600)"],
    stdout=subprocess.PIPE, text=True)
assert holder.stdout.readline().strip() == 'held'
log = open(out, 'w')
try:
    child = pexpect.spawn('bash', [os.path.join(repo, 'deploy/install.sh')], encoding='utf-8', timeout=240, dimensions=(50, 200))
    child.logfile_read = log
    i = child.expect([r'Choose \[\d\]: ', pexpect.EOF, pexpect.TIMEOUT])
    assert i == 0, 'no setup menu'
    child.sendline('1')
    i = child.expect([r'Package lock recovery[\s\S]*Choose \[1\]: ', r'Choose \[\d\]: ', pexpect.EOF, pexpect.TIMEOUT])
    screen = child.before + (child.after if isinstance(child.after, str) else '')
    print('MENU_SEEN' if i == 0 else 'NO_LOCK_MENU (index %s)' % i)
    for needle in ('Package lock held by pid', 'Never stop unattended-upgrades.service', 'snapshot rollback', 'restart of the VM', 'every completed setup step is kept', 'Copyable command'):
        print(('ok   ' if needle in screen else 'FAIL ') + needle)
    if i == 0:
        child.sendline('3')
        child.expect([r'Choose \[\d\]: ', pexpect.EOF, pexpect.TIMEOUT])
        after = child.before
        print('returned to menu:', 'Returned to menu' in after or 'Setup menu' in after or 'Choose' in after)
        # the last menu option exits
        child.sendline('6')
        child.expect([pexpect.EOF, pexpect.TIMEOUT], timeout=30)
finally:
    holder.terminate()
    try: holder.wait(5)
    except Exception: pass
    subprocess.run(['sudo', 'kill', str(holder.pid)], stderr=subprocess.DEVNULL)  # by pid: never pkill -f (it matches the calling shell)
    log.close()
    time.sleep(1)
    restored = subprocess.run(['sudo', 'apt-get', 'install', '-y', '-q', '--no-install-recommends', *RESTORE], stdout=subprocess.DEVNULL)
    print('packages restored:', restored.returncode == 0)
print('holder released; lock-frontend still present:', os.path.exists('/var/lib/dpkg/lock-frontend'))
