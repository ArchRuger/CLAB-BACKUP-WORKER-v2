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
from datetime import datetime
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import paramiko

from .discovery import discovery_fresh, lab_status, node_available, uptime_seconds
from .lab_operations import operation_busy
from .node_services import CLI_COMMAND, CLI_TIMEOUT, GENERIC_CLI_COMMAND, cli_answers, connect, node_cli_answers, node_cli_command   # the one CLI check, shared with Test login
from .runner import effective_credentials, now

SCAN_INTERVAL = 5
BOOT_RETRY = 20      # a node that has not answered yet is asked again after this many seconds
AUTH_RETRY = 60      # a node that keeps refusing the saved login is asked again less often
REFUSALS_BEFORE_FAILED = 3   # early boot can refuse a valid login; report a failure only when it persists
# After a restart, start or deploy accepted by the manager, a NOS may answer SSH for minutes before it accepts any login
# (IOS XR does, for 1.5–4.5 minutes): during this window a refused login still reads as booting, with its own words,
# instead of the red "login failed" that would send a student to check credentials that are right (QA-019).
LOGIN_GRACE = 900
MAX_TEST_ATTEMPTS = 3        # automatic login tests per boot cycle before a human has to look
RETRY_LATER = ('already running', 'lab operation', 'manager reset')
MISSING = object()
MESSAGES = {
    'reachable': 'NOS accepted SSH login and answered show version (automatic check)',
    'booting': 'Container is running; the NOS has not answered an SSH login and show version yet',
    'failed': 'SSH login refused with the saved credentials. Assign a credential profile, then Test login.',
    'booting_login': 'Container is running; SSH answers but the saved login is not accepted yet (a NOS accepts logins only late in its boot)',
}


def login_state(lab, node, available, check):
    """Describe whether SSH can be offered for this node right now."""
    if not lab.get('deployment_name'):
        return {'status': 'unmonitored', 'message': 'SSH readiness is only monitored for labs linked to a VM deployment.'}
    if not available:
        return {'status': 'unavailable', 'message': 'Node is not running or discovery is stale.'}
    if not effective_credentials(lab, node).get('username'):
        return {'status': 'needs_credentials', 'message': 'Assign NOS credentials to this node first.'}
    status = (check or {}).get('status')
    # 'checking': a manual Test login or a lab-wide "Test logins" refresh is in flight for this
    # node right now (node_services.py); never a real answer, so it never marks a device ready.
    if status == 'checking':
        return {'status': 'checking', 'message': check.get('message', ''), 'at': check.get('at')}
    if status == 'reachable':
        return {'status': 'ready', 'message': check.get('message', ''), 'at': check.get('at')}
    if status == 'failed':
        return {'status': 'failed', 'message': check.get('message', ''), 'at': check.get('at')}
    # The grace-window words (a login answered but not accepted yet) travel with the state; everything else reads as plain booting.
    message = (check or {}).get('message') if (check or {}).get('message') == MESSAGES['booting_login'] else MESSAGES['booting']
    return {'status': 'booting', 'message': message, 'at': (check or {}).get('at')}


def summarize(states):
    """Lab-level readiness for the deployment bar: ready, booting, failed or idle.

    A node being tested right now ('checking') is neither ready nor failed; it counts
    alongside 'booting' so the deployment bar's total keeps every monitored device
    while a "Test logins" refresh is in flight, instead of the total briefly shrinking.
    """
    bucket = lambda s: 'booting' if s['status'] in ('checking', 'restarting') else s['status']
    monitored = [s for s in states if bucket(s) in ('ready', 'booting', 'failed')]
    counts = {key: sum(bucket(s) == key for s in monitored) for key in ('ready', 'booting', 'failed')}
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
        self.epoch = {}            # (lab id, node) -> monotonic time its login proof was last invalidated

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
            self.reviewed.clear(); self.test_attempts.clear(); self.epoch.clear()

    def loop(self):
        while not self.stopping.is_set():
            try: self.scan()
            except Exception:
                logging.getLogger(__name__).warning('NOS readiness scan failed; retrying on the next pass.')
            self.wake.wait(SCAN_INTERVAL); self.wake.clear()

    def forget(self, key):
        """A node that stopped, restarted or was redeployed must prove its login again.

        Also the start of a new readiness epoch for the node: a probe that began before this moment
        (one still in flight, or one whose answer arrives late) is discarded by run(), so an answer
        from before a restart can never mark the restarted device ready. The next probe is due at once."""
        with self.services.lock: self.services.checks.pop(key, None)
        with self.lock:
            self.retry_at.pop(key, None); self.refusals.pop(key, None); self.epoch[key] = time.monotonic()
        self.wake.set()

    def restarted_since(self, state, node, check):
        """True when the runtime's uptime says the container started after this login proof was recorded.

        containerlab's inspect carries only the runtime's status line ("Up 12 minutes"); a restart done
        outside the manager (VS Code, the CLI) keeps the container id and may finish between two
        discovery passes, so the state signature alone does not show it. The start is derived from the
        moment the discovery pass began (before the runtime was asked) minus the uptime: the uptime is
        floored to the minute at most and was sampled after that moment, so the derived start is late by
        up to 60 s and never early. A proof older than that start, with a minute of margin, is therefore
        from before a real restart. Coarser uptimes (hours) are not used; the device is then checked
        again by the usual signature and job paths only."""
        uptime = uptime_seconds(node.get('runtime_status'))
        if uptime is None or not check or check.get('status') != 'reachable' or not check.get('at'): return False
        info = state.get('discovery', {})
        inspected = info.get('inspected_epoch') or info.get('checked_epoch') or 0
        try: proven = datetime.fromisoformat(str(check['at']).replace('Z', '+00:00')).timestamp()
        except (ValueError, TypeError): return False
        return inspected - uptime - proven > 60

    def scan(self):
        """One pass: drop stale results, launch due probes and run pending login tests."""
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
                if check and check.get('status') == 'reachable':
                    if not self.restarted_since(state, node, check): continue
                    # The container came up again after this proof: an external restart. Prove it again.
                    self.forget(key); cycle_reset = True; check = None
                    self.event('ssh.check', 'Container restarted after the last login check; checking the login again', 'info', lab_id, node['name'])
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
                self.observed.pop(key, None); self.retry_at.pop(key, None); self.refusals.pop(key, None); self.epoch.pop(key, None)
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
        started = time.monotonic()
        try: status = self.probe(node, creds)
        except Exception: status = 'booting'
        finally:
            with self.lock: self.inflight.discard(key)
        if status is None: return      # no SSH client slot was free; try again later
        with self.lock:
            # The node's proof was invalidated (a restart was accepted, a signature changed) while this
            # probe ran: its answer is about the device as it was, and is dropped. The next scan asks again.
            if self.epoch.get(key, 0) > started: return
            message = None
            if status == 'failed':
                since = self.epoch.get(key)
                if since is not None and time.monotonic() - since < LOGIN_GRACE:
                    # The manager itself restarted, started or deployed this device moments ago: a refused login is
                    # the NOS still booting, not wrong credentials (the count starts once the window is over).
                    status = 'booting'; message = MESSAGES['booting_login']
                else:
                    self.refusals[key] = self.refusals.get(key, 0) + 1
                    if self.refusals[key] < REFUSALS_BEFORE_FAILED: status = 'booting'
            else:
                self.refusals.pop(key, None)
        entry = {'status': status, 'at': now(), 'message': message or MESSAGES[status], 'source': 'automatic'}
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
            return 'reachable' if node_cli_answers(client, node) else 'booting'
        except (paramiko.AuthenticationException, ValueError): return 'failed'
        except Exception: return 'booting'
        finally: self.services.release(client)
