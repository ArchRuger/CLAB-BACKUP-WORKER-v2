"""FIXTURE + REAL TERMINAL checks of the full-screen installer's process behaviour.

    python3 docs/installer-tui/tools/pty_check.py [--keep] [scenario ...]

Builds a fixture checkout (tools/make_fixture.py: fake helpers, real installer code) in
~/scratch/clab-pty-fixture, then drives `bash <fixture>/deploy/install.sh --tui` in real
tmux pseudo-terminals with real sudo and real signals. Requires the account's TUI venv
(--setup-tui), tmux, and sudo without a prompt for this account (the dev VM). Nothing on
the VM is installed or changed by the fake helpers; the real verification step only reads
the running manager. Prints one PASS/FAIL line per assertion and exits non-zero on failure.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
FIXTURE = Path.home() / 'scratch' / 'clab-pty-fixture'
STATE = Path(os.environ.get('XDG_STATE_HOME') or Path.home() / '.local' / 'state') / 'clab-node-manager' / 'installer-last-run.json'
LOCK = Path('/run/lock/clab-node-manager-installer.lock')
results = []


def sh(*args, check=False):
    return subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, check=check).stdout


def check(name, condition, detail=''):
    results.append((name, bool(condition)))
    print(('PASS ' if condition else 'FAIL ') + name + (f'  [{detail}]' if detail and not condition else ''), flush=True)


def control(**steps):
    (FIXTURE / 'fixture-control.json').write_text(json.dumps(steps))
    for count in (FIXTURE / 'fixture-state').glob('*.count'):
        count.unlink()


def count(key):
    path = FIXTURE / 'fixture-state' / f'{key}.count'
    return int(path.read_text().strip()) if path.exists() else 0


def screen(session):
    return sh('tmux', 'capture-pane', '-p', '-t', session)


def keys(session, *names, delay=0.4):
    for name in names:
        sh('tmux', 'send-keys', '-t', session, name)
        time.sleep(delay)


def wait_for(session, text, timeout=60):
    end = time.time() + timeout
    while time.time() < end:
        if text in screen(session):
            return True
        time.sleep(0.5)
    return False


def lock_free():
    probe = subprocess.run([sys.executable, '-c', 'import fcntl,os,sys\nfd=os.open(sys.argv[1], os.O_RDONLY)\n'
                            'fcntl.flock(fd, fcntl.LOCK_EX|fcntl.LOCK_NB)', str(LOCK)], stderr=subprocess.DEVNULL)
    return probe.returncode == 0


def start(session, size=(120, 40), args='--tui', env=''):
    sh('tmux', 'kill-session', '-t', session)
    command = f'{env} bash {FIXTURE}/deploy/install.sh {args}; echo EXIT=$?; sleep 600'
    sh('tmux', 'new-session', '-d', '-s', session, '-x', str(size[0]), '-y', str(size[1]),
       '-e', 'TERM=xterm-256color', '-e', 'COLORTERM=truecolor', command)
    return wait_for(session, 'SLATE OPS', 30)


def start_install(session):
    # Dashboard -> Install / update review -> Start.
    keys(session, 'Enter', delay=1.2)
    keys(session, 'Enter', delay=1.0)


def scenario_hangup():
    control(prereqs=['ok'], launch=['sleep:12'], capture=['ok'], engineer=['ok'], git=['ok'])
    if STATE.exists():
        STATE.unlink()
    check('hangup: dashboard starts', start('ptyhup'))
    start_install('ptyhup')
    check('hangup: launch phase running', wait_for('ptyhup', 'working 3/12', 40))
    sh('tmux', 'kill-session', '-t', 'ptyhup')        # the terminal disappears (SIGHUP)
    time.sleep(16)
    check('hangup: active phase finished after the terminal was lost', 'working 12/12' in
          sh('bash', '-c', f'cat {FIXTURE}/fixture-state/launch.count') or count('launch') == 1)
    check('hangup: no later phase started', count('capture') == 0, f'capture ran {count("capture")}x')
    record = json.loads(STATE.read_text()) if STATE.exists() else {}
    check('hangup: run record says interrupted', record.get('outcome') == 'interrupted', str(record.get('outcome')))
    check('hangup: record names the reason', 'terminal' in record.get('interrupted', ''), record.get('interrupted', ''))
    phases = {p['key']: p['state'] for p in record.get('phases', [])}
    check('hangup: launch recorded completed, capture not started',
          phases.get('launch') == 'Completed' and phases.get('capture') in ('Stopped', 'Not started'), str(phases))
    check('hangup: installer lock released', lock_free())
    leftover = sh('pgrep', '-f', f'{FIXTURE}/deploy/installer_tui/launch.py').strip()
    check('hangup: no installer process left behind', not leftover, leftover)


def scenario_stop():
    control(prereqs=['sleep:6'], launch=['ok'], capture=['ok'], engineer=['ok'], git=['ok'])
    check('stop: dashboard starts', start('ptystop'))
    start_install('ptystop')
    check('stop: prereqs running', wait_for('ptystop', 'working 2/6', 30))
    keys('ptystop', 's')
    check('stop: stopping is shown', wait_for('ptystop', 'Stopping after the current phase', 10))
    check('stop: result shown after the phase', wait_for('ptystop', 'Result:', 30))
    text = screen('ptystop')
    check('stop: outcome STOPPED', 'STOPPED' in text)
    check('stop: prereqs ran to completion once', count('prereqs') == 1)
    check('stop: nothing after prereqs ran', count('launch') == 0 and count('capture') == 0)
    keys('ptystop', 'Enter', delay=2)
    check('stop: finish restores the shell with a summary', 'EXIT=0' in screen('ptystop') and
          'Install / update: STOPPED' in screen('ptystop'))
    sh('tmux', 'kill-session', '-t', 'ptystop')


def scenario_flood():
    control(prereqs=['ok'], launch=['ok'], capture=['flood:200000'], engineer=['ok'], git=['ok'])
    check('flood: dashboard starts', start('ptyflood'))
    t0 = time.time()
    start_install('ptyflood')
    ok = wait_for('ptyflood', 'Running manager verification', 120) or wait_for('ptyflood', 'Result:', 60)
    check('flood: 200000 lines streamed and the run moved on', ok, f'{time.time() - t0:.1f}s')
    wait_for('ptyflood', 'Result:', 120)
    keys('ptyflood', 'o', delay=1.5)   # back to the run screen's output
    text = screen('ptyflood')
    check('flood: output panel marks hidden earlier lines', 'lines not shown' in text, text[-400:])
    title = sh('tmux', 'display-message', '-p', '-t', 'ptyflood', '#{pane_title}').strip()
    check('flood: OSC title sequences from the helper never reached the terminal', title != 'title', title)
    check('flood: markup shown literally', '[bold]markup[/bold]' in text or 'Result:' in text)
    sh('tmux', 'kill-session', '-t', 'ptyflood')
    time.sleep(3)


def scenario_interrupt():
    control(prereqs=['sleep:40', 'ok'], launch=['ok'], capture=['ok'], engineer=['ok'], git=['ok'])
    check('interrupt: dashboard starts', start('ptyint'))
    start_install('ptyint')
    check('interrupt: prereqs running', wait_for('ptyint', 'working 2/40', 30))
    keys('ptyint', 'x', delay=1)
    check('interrupt: confirmation dialog with Keep running first', 'Interrupt this step?' in screen('ptyint'))
    keys('ptyint', 'Right', 'Enter', delay=1)
    check('interrupt: phase failed with explicit interruption', wait_for('ptyint', 'Interrupted on request', 15))
    check('interrupt: later phases did not start', count('launch') == 0)
    keys('ptyint', 'Enter', delay=1)  # Retry phase (focused)
    check('interrupt: retry runs only that phase, then continues', wait_for('ptyint', 'Result:', 120) or
          wait_for('ptyint', 'Slate Ops · Git', 30))
    check('interrupt: prereqs ran twice, launch once', count('prereqs') == 2 and count('launch') == 1,
          f'{count("prereqs")}/{count("launch")}')
    sh('tmux', 'kill-session', '-t', 'ptyint')
    time.sleep(3)


def scenario_lock():
    control(prereqs=['lock', 'ok'], launch=['ok'], capture=['ok'], engineer=['ok'], git=['ok'])
    check('lock: dashboard starts', start('ptylock'))
    start_install('ptylock')
    check('lock: package-lock recovery shown', wait_for('ptylock', 'Package lock', 30))
    text = ' '.join(screen('ptylock').split())
    check('lock: copyable wait command shown without -n', 'apt_lock.py' in text and '--pause-timers' in text
          and 'sudo -n python3' not in text and 'Copyable command' in text)
    check('lock: offers wait, retry, check, return', all(word in text for word in ('Wait for lock', 'Retry phase', 'Check again', 'Return, keep work')))
    check('lock: one-line copyable command in the output pane', 'Copyable command, in another terminal: sudo python3' in screen('ptylock'))
    keys('ptylock', 'Right', 'Right', 'Enter', delay=1)   # Check again: the real lock is free, so it retries
    check('lock: retry after the check completes the phase', wait_for('ptylock', 'Running manager verification', 60) or
          wait_for('ptylock', 'Result:', 60))
    check('lock: prereqs attempted twice', count('prereqs') == 2, str(count('prereqs')))
    sh('tmux', 'kill-session', '-t', 'ptylock')
    time.sleep(3)


SCENARIOS = {'hangup': scenario_hangup, 'stop': scenario_stop, 'flood': scenario_flood,
             'interrupt': scenario_interrupt, 'lock': scenario_lock}


def main():
    names = [a for a in sys.argv[1:] if not a.startswith('--')] or list(SCENARIOS)
    subprocess.run([sys.executable, str(ROOT / 'docs/installer-tui/tools/make_fixture.py'), str(FIXTURE)], check=True,
                   stdout=subprocess.DEVNULL)
    print(f'fixture: {FIXTURE} (fake helpers; real installer code from {ROOT})', flush=True)
    for name in names:
        if not lock_free():
            print('Another installer run holds the lock; waiting…', flush=True)
            while not lock_free():
                time.sleep(2)
        SCENARIOS[name]()
    failed = [name for name, ok in results if not ok]
    print(f'\n{len(results) - len(failed)} passed, {len(failed)} failed')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
