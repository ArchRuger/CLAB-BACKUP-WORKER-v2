#!/usr/bin/env python3
"""Driver-layer proof of app/restore_junos.py on a real Junos node of the restore-square lab.

Calls the driver exactly as the manager does (a paramiko client per step, connected like
app/node_services.connect). What the device then runs is judged WITHOUT the driver: the active
configuration is read through tools/nodecli.py and compared by tools/readback.py's own comparator
(the driver's capture and the application's comparator are also run, as a cross-check of the product's
own verdict, and must agree). Every step is timestamped. Steps: capture A, drift to B, replace with A under a token, read the pending
view, confirm with a fresh connection, compare; then the two refusals that protect other people's
work (an uncommitted edit in the shared candidate; a pending confirmation that is not ours).
Writes a JSON evidence file without configuration text. The node ends on A with nothing pending.

    clab-backup-ui/.venv/bin/python docs/multi-platform-restore/tools/driver_junos_live.py vjunos-switch EVIDENCE.json
"""
import json
import pathlib
import sys
import time

import paramiko

ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'clab-backup-ui'))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from app import restore_junos as driver          # noqa: E402
from app.restore_compare import compare_junos    # noqa: E402
from app.restore_shell import RestoreError       # noqa: E402
from nodecli import NODES, Session               # noqa: E402
from readback import statements                  # noqa: E402  (independent comparator: no application code)

node, out = sys.argv[1], sys.argv[2]
DRIFT = ROOT / 'docs/multi-platform-restore/lab/drift' / f'{node}-B.cli'
SPARE = {'vjunos-switch': 'ge-0/0/7', 'cjunosevolved': 'et-0/0/7'}[node]   # an unused port for the foreign change
TOKEN = 'clabmgr-' + format(int(time.time()) & 0xffffffff, '08x')
steps = []


def step(name, ok, **detail):
    print(('ok   ' if ok else 'FAIL ') + name, detail if not ok else '', flush=True)
    steps.append({'utc': time.strftime('%H:%M:%S', time.gmtime()), 'step': name, 'ok': bool(ok), **detail})


def independent():
    """The active configuration as the device prints it to an ordinary CLI session: a set of statements."""
    text = cli('show configuration | display set | no-more', timeout=180)[0]
    return statements('\n'.join(text.split('\n')[1:-1]), 'junos')


def differs_from_a():
    """(missing, extra) against A by the independent comparator; the root-authentication the driver may add is tolerated."""
    now = independent()
    extra = {line for line in now - a_independent if not line.startswith('set system root-authentication ')}
    return len(a_independent - now), len(extra)


def client():
    ip, user, password, _ = NODES[node]
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(ip, username=user, password=password, timeout=10, auth_timeout=10, banner_timeout=10,
              allow_agent=False, look_for_keys=False)
    return c


def call(function, *args, **kwargs):
    c = client()
    try:
        return function(c, *args, **kwargs)
    finally:
        c.close()


def cli(*lines, timeout=120):
    s = Session(node, timeout)
    try:
        return [s.run(line) for line in lines]
    finally:
        s.close()


def booted():
    return [l for l in cli('show system uptime | match "System booted"')[0].splitlines() if 'booted' in l][-1].split(' (')[0]


boot = booted()
a_hier = call(driver.capture, display_set=False)
a_set = call(driver.capture, display_set=True)
a_independent = independent()
step('A captured in both forms, and independently through an ordinary CLI session', bool(a_hier.strip()) and bool(a_set.strip()) and len(a_independent) > 10,
     bytes=len(a_hier), independent_statements=len(a_independent))
s = Session(node, 240)
for line in DRIFT.read_text().splitlines():
    s.run(line)
s.close()
missing, extra = differs_from_a()
drift_lines = [l for l in DRIFT.read_text().splitlines() if l.startswith(('set ', 'delete '))]
step('B is active (independent readback): exactly the drift file\'s changes', missing == 2 and extra == len(drift_lines) - 1,
     missing=missing, extra=extra, drift_statements=len(drift_lines))   # a changed value and a deleted statement are missing; every `set` line is extra

started = time.time()
result = call(driver.apply_candidate, a_hier, 3, token=TOKEN)
step('apply: replaced under the job token', result['handle'] == {'token': TOKEN} and not result['no_op'],
     seconds=round(time.time() - started, 1), diff_lines=len(result['diff'].splitlines()))
view = [l.strip() for l in cli('show system commit | no-more')[0].splitlines() if l.strip()][1:4]
step('device shows entry 0 with our comment and "rollback pending"', TOKEN in view and 'rollback pending' in view, view=[v for v in view])
step('driver.pending() returns our token', call(driver.pending) == TOKEN)
try:
    call(driver.confirm, {'token': 'clabmgr-not-ours'})
    step('confirm with another token is refused', False)
except RestoreError as exc:
    step('confirm with another token is refused', 'different change' in str(exc).lower(), message=str(exc))
step('... and the change is still pending afterwards', call(driver.pending) == TOKEN)
confirmed = call(driver.confirm, result['handle'])
step('confirm (commit check) from a fresh connection', confirmed == {'confirmed': True})
step('nothing pending after the confirmation', call(driver.pending) == '')
missing, extra = differs_from_a()
step('active configuration equals A by the independent readback and comparator (0 missing, 0 extra)', (missing, extra) == (0, 0), missing=missing, extra=extra)
product_missing, product_extra = compare_junos(a_set, call(driver.capture, display_set=True))
step('the product\'s own capture and comparator agree', not product_missing and not product_extra, missing=len(product_missing), extra=len(product_extra))
again = call(driver.apply_candidate, a_hier, 3, token=TOKEN)
step('A onto A is a no-op for the device', again['no_op'] is True)
step('... still armed and confirmed like any change', call(driver.confirm, again['handle']) == {'confirmed': True} and call(driver.pending) == '')

# --- our own crashed session must not be what blocks the next restore: an exclusive session's
#     uncommitted changes are discarded when the connection drops
s = Session(node, 120)
s.run('configure exclusive'); s.run('set system location building "OUR-CRASHED-SESSION"')
s.client.get_transport().close()          # the connection dies mid-transaction, no exit, no rollback
time.sleep(8)
step('a dropped exclusive session leaves nothing in the shared candidate', call(driver.blocked) == '')
step('... and nothing of it became active', 'OUR-CRASHED' not in cli('show configuration system location')[0])
step('driver.blocked() is empty on a quiet node, so a restore may start', call(driver.blocked) == '')

# --- somebody's uncommitted edit in the shared candidate: refuse, and leave it exactly where it was
s = Session(node, 120)
s.run('configure'); s.run('set system location building "FOREIGN-UNCOMMITTED"')
s.channel.sendall(b'exit\n'); time.sleep(3); s.channel.recv(65536); s.channel.sendall(b'yes\n'); time.sleep(2); s.close()
step('driver.blocked() names the reason for the review step', 'uncommitted' in call(driver.blocked))
try:
    call(driver.apply_candidate, a_hier, 3, token=TOKEN)
    step('apply refuses while a foreign uncommitted edit exists', False)
except RestoreError as exc:
    step('apply refuses while a foreign uncommitted edit exists', 'uncommitted' in str(exc), message=str(exc))
s = Session(node, 120)
s.run('configure'); kept = 'FOREIGN-UNCOMMITTED' in s.run('show | compare')
step("the bystander's edit is still in the candidate, uncommitted", kept)
s.run('rollback 0'); s.channel.sendall(b'exit\n'); time.sleep(3); s.close()      # the test's own cleanup
step('... and was never activated', 'FOREIGN' not in cli('show configuration system location')[0])

# --- a pending confirmation that is not ours: refuse to start, refuse to confirm
s = Session(node, 240)
s.run('configure'); s.run(f'set interfaces {SPARE} description "foreign-pending"'); s.run('commit confirmed 2'); s.run('exit'); s.close()
step('driver.pending() reports a foreign pending change without an identity', call(driver.pending) is True)
for name, function, args in (('apply', driver.apply_candidate, (a_hier, 3)), ('confirm', driver.confirm, ({'token': TOKEN},))):
    try:
        call(function, *args, **({'token': TOKEN} if name == 'apply' else {}))
        step(f'{name} refuses while a foreign confirmation is pending', False)
    except RestoreError as exc:
        step(f'{name} refuses while a foreign confirmation is pending', True, message=str(exc))
step('the foreign change is still pending, untouched', call(driver.pending) is True)
print('waiting for the foreign 2-minute timer to roll back by itself ...', flush=True)
deadline = time.time() + 240
while time.time() < deadline and call(driver.pending):
    time.sleep(15)
missing, extra = differs_from_a()
step('after its own rollback the node is on A again (independent readback), nothing pending', (missing, extra) == (0, 0) and call(driver.pending) == '',
     missing=missing, extra=extra)
boot_after = booted()
step('the NOS never rebooted', boot_after == boot, boot_before=boot, boot_after=boot_after)
import subprocess                                  # noqa: E402
head = subprocess.run(['git', '-C', str(ROOT), 'rev-parse', '--short=12', 'HEAD'], capture_output=True, text=True).stdout.strip()
dirty = subprocess.run(['git', '-C', str(ROOT), 'status', '--porcelain', '--', 'clab-backup-ui/app/restore_junos.py', 'clab-backup-ui/app/restore_shell.py'],
                       capture_output=True, text=True).stdout.strip()
record = {'node': node, 'driver': 'app/restore_junos.py', 'driver_source': {'git_head': head, 'uncommitted_changes_to_the_driver': bool(dirty)},
          'token': TOKEN, 'steps': steps, 'ok': all(s['ok'] for s in steps),
          'finished_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}
pathlib.Path(out).write_text(json.dumps(record, indent=1) + '\n')
print('ALL OK' if record['ok'] else 'FAILURES', flush=True)
sys.exit(0 if record['ok'] else 1)
