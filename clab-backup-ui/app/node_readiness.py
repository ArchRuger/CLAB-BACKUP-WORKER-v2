"""Automatic NOS login readiness for deployed labs.

Containerlab reports a container as running long before its network OS accepts an
SSH login: cEOS, vJunos and XRv9k keep booting for one to several minutes. Until
1.21.1 the manager offered SSH as soon as credentials existed, and a lab saved from
its topology YAML had no credentials at all. This monitor probes the SSH login of
every running node in a linked lab (with its profile, inventory or containerlab
default login) and asks for `show version` over an exec channel until the NOS
answers, records each result as the node's SSH check, and runs one NOS login test
job (show version through the backup driver) once every node of a lab has answered
after a deployment. SSH actions open once a node has answered; a node that stops or
restarts must answer again, and a failed automatic test sends its nodes back to
booting with a bounded number of retries.
"""
import copy
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import paramiko

from .discovery import discovery_fresh, lab_status, node_available
from .node_services import connect
from .runner import CLI_ERROR, effective_credentials, now

SCAN_INTERVAL = 5
BOOT_RETRY = 20      # a node that has not answered yet is asked again after this many seconds
AUTH_RETRY = 60      # a node that keeps refusing the saved login is asked again less often
REFUSALS_BEFORE_FAILED = 3   # early boot can refuse a valid login; report a failure only when it persists
MAX_TEST_ATTEMPTS = 3        # automatic login tests per boot cycle before a human has to look
CLI_COMMAND = 'show version'
# A node with no NOS platform (a plain Linux image, generic SSH profile or the
# image-based defaults in inventory.py) has no NOS CLI to answer `show version`;
# a real, harmless shell command still proves the SSH login answers a real command,
# without faking readiness for a host that was never a NOS in the first place.
GENERIC_CLI_COMMAND = 'echo readiness-check'
CLI_TIMEOUT = 25
RETRY_LATER = ('already running', 'lab operation', 'manager reset')
MISSING = object()
MESSAGES = {
    'reachable': 'NOS accepted SSH login and answered show version (automatic check)',
    'booting': 'Container is running; the NOS has not answered an SSH login and show version yet',
    'failed': 'SSH login refused with the saved credentials. Assign a credential profile, then Test login.',
}


def cli_answers(client, command=CLI_COMMAND, timeout=CLI_TIMEOUT):
    """True when the NOS CLI returns a real answer to show version over an exec channel.

    SSH can accept a login while the CLI is still starting (cEOS agents, Junos
    daemons); an empty or not-ready reply keeps the node in booting.
    """
    try:
        stdin, stdout, _ = client.exec_command(command, timeout=timeout)
        stdin.close()
        output = stdout.read(65536).decode('utf-8', 'replace')
    except Exception:
        return False
    return bool(output.strip()) and not CLI_ERROR.search(output)


def login_state(lab, node, available, check):
    """Describe whether SSH can be offered for this node right now."""
    if not lab.get('deployment_name'):
        return {'status': 'unmonitored', 'message': 'SSH readiness is only monitored for labs linked to a VM deployment.'}
    if not available:
        return {'status': 'unavailable', 'message': 'Node is not running or discovery is stale.'}
    if not effective_credentials(lab, node).get('username'):
        return {'status': 'needs_credentials', 'message': 'Assign NOS credentials to this node first.'}
    status = (check or {}).get('status')
    if status == 'reachable':
        return {'status': 'ready', 'message': check.get('message', ''), 'at': check.get('at')}
    if status == 'failed':
        return {'status': 'failed', 'message': check.get('message', ''), 'at': check.get('at')}
    return {'status': 'booting', 'message': MESSAGES['booting'], 'at': (check or {}).get('at')}


def summarize(states):
    """Lab-level readiness for the deployment bar: ready, booting, failed or idle."""
    monitored = [s for s in states if s['status'] in ('ready', 'booting', 'failed')]
    counts = {key: sum(s['status'] == key for s in monitored) for key in ('ready', 'booting', 'failed')}
    if not monitored: status = 'idle'
    elif counts['ready'] == len(monitored): status = 'ready'
    elif counts['booting']: status = 'booting'
    else: status = 'failed'
    return {'status': status, 'total': len(monitored), **counts}


class ReadinessMonitor:
    def __init__(self, store, services, runner, probe=None):
        self.store = store; self.services = services; self.runner = runner
        self.probe = probe or self.ssh_probe
        self.stopping = threading.Event(); self.wake = threading.Event()
        self.thread = None
        self.pool = ThreadPoolExecutor(max_workers=4)
        self.lock = threading.Lock()
        self.inflight = set()      # probes running right now
        self.retry_at = {}         # (lab id, node) -> monotonic time of the next allowed probe
        self.observed = {}         # (lab id, node) -> last runtime signature, None while not running
        self.refusals = {}         # (lab id, node) -> consecutive authentication refusals
        self.tested = set()        # labs whose automatic login test ran for the current boot cycle
        self.reviewed = set()      # automatic test jobs whose outcome has been acted on
        self.test_attempts = {}    # lab id -> automatic tests started in the current boot cycle

    def start(self):
        self.thread = threading.Thread(target=self.loop, daemon=True)
        self.thread.start()

    def close(self):
        self.stopping.set(); self.wake.set()
        self.pool.shutdown(wait=False, cancel_futures=True)
        if self.thread: self.thread.join(timeout=2)

    def reset(self):
        with self.lock:
            self.retry_at.clear(); self.observed.clear(); self.refusals.clear(); self.tested.clear()
            self.reviewed.clear(); self.test_attempts.clear()

    def loop(self):
        while not self.stopping.is_set():
            try: self.scan()
            except Exception:
                logging.getLogger(__name__).warning('NOS readiness scan failed; retrying on the next pass.')
            self.wake.wait(SCAN_INTERVAL); self.wake.clear()

    def forget(self, key):
        """A node that stopped, restarted or was redeployed must prove its login again."""
        with self.services.lock: self.services.checks.pop(key, None)
        with self.lock:
            self.retry_at.pop(key, None); self.refusals.pop(key, None)

    def scan(self):
        """One pass: drop stale results, launch due probes and run pending login tests."""
        from .lab_operations import operation_busy
        if self.store.reset_pending: return
        state = self.store.snapshot()
        fresh = discovery_fresh(state)
        present = set()
        for lab in state['labs']:
            if not lab.get('deployment_name'): continue
            lab_id = lab['id']; cycle_reset = False
            busy = operation_busy(state, lab_id)
            self.review_tests(state, lab)
            for node in lab['nodes']:
                key = (lab_id, node['name']); present.add(key)
                running = fresh and node_available(state, lab, node)
                signature = (node.get('runtime_state'), node.get('discovered_address')) if running else None
                previous = self.observed.get(key, MISSING)
                if previous is not MISSING and previous != signature:
                    self.forget(key); cycle_reset = True
                self.observed[key] = signature
                if not running or busy: continue      # busy: a deploy or destroy is still running on the VM
                creds = effective_credentials(lab, node)
                if not creds.get('username'): continue
                with self.services.lock: check = copy.deepcopy(self.services.checks.get(key))
                if check and check.get('status') == 'reachable': continue
                with self.lock:
                    if key in self.inflight or self.retry_at.get(key, 0) > time.monotonic(): continue
                    self.inflight.add(key)
                    self.retry_at[key] = time.monotonic() + (AUTH_RETRY if check and check.get('status') == 'failed' else BOOT_RETRY)
                try: self.pool.submit(self.run, key, copy.deepcopy(node), copy.deepcopy(creds))
                except RuntimeError:
                    with self.lock: self.inflight.discard(key)
            # Count after launching: a probe may already have answered (a reachable
            # answer also wakes the loop, so a threaded probe is counted promptly).
            ready, pending = self.counts(state, lab, fresh)
            if cycle_reset or not (ready or pending):
                self.tested.discard(lab_id); self.test_attempts.pop(lab_id, None)
            if ready and not pending and lab_id not in self.tested and not busy and lab_status(state, lab)['status'] == 'Running':
                self.login_test(lab)
        with self.lock:
            for key in [k for k in self.observed if k not in present]:
                self.observed.pop(key, None); self.retry_at.pop(key, None); self.refusals.pop(key, None)
            self.tested &= {lab['id'] for lab in state['labs']}
            self.reviewed &= {job['id'] for job in state['jobs']}

    def review_tests(self, state, lab):
        """A failed automatic login test sends its nodes back to booting; a few retries per boot."""
        lab_id = lab['id']
        job = next((j for j in state['jobs'] if j.get('lab_id') == lab_id and j.get('source') == 'automatic'
                    and j.get('operation') == 'test'), None)   # jobs are newest first
        if not job or job['status'] in ('queued', 'running') or job['id'] in self.reviewed: return
        self.reviewed.add(job['id'])
        if job['status'] == 'succeeded': return
        failed = [n['name'] for n in job.get('nodes', []) if n.get('status') != 'succeeded'] or [n['name'] for n in lab['nodes']]
        for name in failed: self.forget((lab_id, name))
        attempts = self.test_attempts.get(lab_id, 0) + 1
        self.test_attempts[lab_id] = attempts
        if attempts < MAX_TEST_ATTEMPTS:
            self.tested.discard(lab_id)
            self.event('nos.ready', f'Automatic NOS login test failed on {len(failed)} node(s); checking them again before another test', 'warning', lab_id)
        else:
            self.event('nos.ready', 'Automatic NOS login test failed repeatedly; check the credentials and run Test NOS login by hand', 'warning', lab_id)

    def counts(self, state, lab, fresh):
        """(nodes that answered, nodes still waiting) among running nodes with a login."""
        ready = pending = 0
        for node in lab['nodes']:
            if not (fresh and node_available(state, lab, node)) or not effective_credentials(lab, node).get('username'): continue
            with self.services.lock: status = (self.services.checks.get((lab['id'], node['name'])) or {}).get('status')
            if status == 'reachable': ready += 1
            else: pending += 1
        return ready, pending

    def login_test(self, lab):
        """Run Test NOS login once when every node of a running lab accepts SSH."""
        lab_id = lab['id']
        try:
            self.runner.submit(lab_id, 'test', source='automatic')
        except ValueError as exc:
            message = str(exc)
            if any(reason in message for reason in RETRY_LATER): return
            self.tested.add(lab_id)
            self.event('nos.ready', 'All nodes accept SSH login, but the automatic NOS login test was not started: ' + message, 'warning', lab_id)
            return
        self.tested.add(lab_id)
        self.event('nos.ready', 'All nodes accept SSH login; automatic NOS login test started', 'info', lab_id)

    def event(self, action, message, level, lab_id, node=''):
        try: self.store.event(action, message, level=level, lab_id=lab_id, node=node)
        except OSError: pass   # the audit log never gates readiness

    def run(self, key, node, creds):
        lab_id, name = key
        try: status = self.probe(node, creds)
        except Exception: status = 'booting'
        finally:
            with self.lock: self.inflight.discard(key)
        if status is None: return      # no SSH client slot was free; try again later
        with self.lock:
            if status == 'failed':
                self.refusals[key] = self.refusals.get(key, 0) + 1
                if self.refusals[key] < REFUSALS_BEFORE_FAILED: status = 'booting'
            else:
                self.refusals.pop(key, None)
        entry = {'status': status, 'at': now(), 'message': MESSAGES[status], 'source': 'automatic'}
        with self.services.lock:
            previous = self.services.checks.get(key)
            self.services.checks[key] = entry
        if not previous or previous.get('status') != status:
            self.event('ssh.check', entry['message'], 'info' if status == 'reachable' else 'warning', lab_id, name)
        if status == 'reachable': self.wake.set()

    def ssh_probe(self, node, creds):
        """'reachable', 'failed' (login refused), 'booting' (no SSH answer) or None (no slot)."""
        try: client = self.services.reserve()
        except Exception: return None
        try:
            connect(client, node, creds)
            command = CLI_COMMAND if node.get('platform') else GENERIC_CLI_COMMAND
            return 'reachable' if cli_answers(client, command) else 'booting'
        except (paramiko.AuthenticationException, ValueError): return 'failed'
        except Exception: return 'booting'
        finally: self.services.release(client)
