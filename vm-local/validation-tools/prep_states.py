"""Build the course folder structure and reference states: scaffold init, snapshot 'start' (factory), configure the solution, snapshot 'solution'."""
import os, subprocess, sys, time, json, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import junos_ssh
PTX, SW = '172.20.20.3', '172.20.20.2'; SRC = os.path.expanduser('~/projects/clab-manager')
def scaffold(*args):
    r = subprocess.run(['python3', SRC + '/deploy/scaffold-lab.py', '--lab', 'clab-llm-dev2'] + list(args), capture_output=True, text=True); print('$ scaffold', ' '.join(args), '->', r.returncode); print((r.stdout + r.stderr).strip()[-1500:]); return r.returncode
step = sys.argv[1] if len(sys.argv) > 1 else 'all'
if step in ('init', 'all'): scaffold('init', 'clab-llm-dev2')
if step in ('start', 'all'): scaffold('snapshot', 'clab-llm-dev2', 'start')
if step in ('solution', 'all'):
    ptx = junos_ssh.cli(PTX, ['configure', 'set system host-name PTX1', 'set interfaces et-0/0/0 description "to SW1 ge-0/0/0 (release 1.29 validation)"', 'set interfaces et-0/0/0 unit 0 family inet address 10.0.0.1/30', 'set interfaces lo0 unit 0 family inet address 192.168.255.1/32', 'set snmp contact "release-1.29-validation"', 'commit and-quit', 'show configuration | display set | match "et-0/0/0|lo0|snmp|host-name"'])
    print('\n'.join(ptx)[-1200:])
    sw = junos_ssh.cli(SW, ['configure', 'set system host-name SW1', 'set interfaces ge-0/0/0 description "to PTX1 et-0/0/0"', 'delete interfaces ge-0/0/0 unit 0 family ethernet-switching', 'set interfaces ge-0/0/0 unit 0 family inet address 10.0.0.2/30', 'set interfaces lo0 unit 0 family inet address 192.168.255.2/32', 'commit and-quit', 'show configuration | display set | match "ge-0/0/0|lo0|host-name"'])
    print('\n'.join(sw)[-1200:])
    time.sleep(5); print('\n'.join(junos_ssh.cli(PTX, ['ping 10.0.0.2 count 3 rapid']))[-400:])
if step in ('snapshot-solution', 'all'): scaffold('snapshot', 'clab-llm-dev2', 'solution')
