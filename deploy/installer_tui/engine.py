"""Run the phases of one setup action for the full-screen installer (standard library only).

The phases, their helper commands and their order come from install-manager.py
(`action_steps`), exactly as the plain menu runs them. This module decides only how
each phase meets the terminal:

* Non-interactive phases run as a `core.StepProcess`: `sudo -n`, no terminal stdin,
  their own process group, output streamed to the screen as inert text.
* Administrator authentication, the first-time clab-discovery password and Git setup
  (with its GitHub device login) get the real terminal: the screen asks its bridge to
  suspend and run that command natively, then resumes.
* A failure stops the run at that phase and asks the bridge for a recovery choice; the
  choices mirror the plain menu (retry this phase, the package-lock wait, return keeping
  completed work), plus "authenticate, then retry" when sudo needs a password.

The bridge is the screen. Every bridge call blocks this run thread until the screen has
handled it; when the screen is gone (terminal lost), calls return safe defaults so the
active phase finishes and no later phase starts.
"""
import threading
import time
import traceback
from types import SimpleNamespace

from . import core

PENDING = 'Pending'
RUNNING = 'Running'
WAITING = 'Waiting for input'
COMPLETED = 'Completed'
FAILED = 'Failed'
SKIPPED = 'Skipped'
STOPPED = 'Stopped'
NOT_STARTED = 'Not started'

RETRY = 'retry'
AUTH_RETRY = 'auth-retry'
LOCK_WAIT = 'lock-wait'
LOCK_CHECK = 'lock-check'
RETURN = 'return'
SKIP = 'skip'

PASSWORD_NOTICE = ('First setup: the launcher asks you to create the clab-discovery password, then builds the '
                   'manager image in this terminal (several minutes). The dashboard returns when it finishes.')
AUTH_NOTICE = 'Administrator access: sudo asks for your password in this terminal. The dashboard returns afterwards.'
GIT_NOTICE = ('Git setup runs in this terminal as {user} (home {home}): it asks its own questions and may show a '
              'GitHub device code. The dashboard returns when it finishes.')


def holder_report(install, env):
    """apt_lock.py --show, as inert text with its line structure kept (at most 40 lines)."""
    lines = (install.lock_holder_text(env) or '').splitlines()[:40]
    return '\n'.join(core.sanitize.clean_line(line, 400) for line in lines)


def credentials_cached(env, cwd):
    """True when sudo runs commands without a prompt right now. `sudo -n -v` renews a cached
    timestamp; it is refused under sudo's default verifypw=all when any matching rule needs a
    password even though a NOPASSWD rule lets commands run, so `sudo -n true` is the fallback."""
    code, _ = core.run_capture(['sudo', '-n', '-v'], env, cwd, timeout=15)
    if code == 0:
        return True
    code, _ = core.run_capture(['sudo', '-n', 'true'], env, cwd, timeout=15)
    return code == 0


class Failure:
    """Why a phase stopped, and which recovery choices apply."""

    def __init__(self, kind, message, code=None, choices=(RETRY, RETURN), holder=''):
        self.kind = kind          # 'lock', 'auth', 'command', 'verify', 'settings', 'git', 'handoff', 'internal'
        self.message = message
        self.code = code
        self.choices = tuple(choices)
        self.holder = holder      # package-lock holder report (apt_lock.py --show), already inert text


class PhaseState:
    def __init__(self, step):
        self.key = step.key
        self.title = step.title
        self.label = label_for(step)
        self.post = step.post
        self.state = PENDING
        self.started = None
        self.finished = None
        self.attempts = 0
        self.code = None
        self.note = ''
        self.failure = None
        self.outcome = None   # free-form result (manager address, lazydocker outcome)

    @property
    def elapsed(self):
        if self.started is None:
            return None
        return (self.finished or time.monotonic()) - self.started


LABELS = {
    'admin': 'Administrator access',
    'settings': 'Copy previous settings',
    'prereqs': 'VM prerequisites',
    'launch': 'Password, helpers, image and manager',
    'capture': 'Browser Wireshark capture stack',
    'verify': 'Running manager verification',
    'engineer': 'VS Code / Containerlab access',
    'lazydocker': 'lazydocker (optional)',
    'git': 'Git setup',
    'health': 'Installation health check',
}


def label_for(step):
    return LABELS.get(step.key, step.title)


class NullBridge:
    """What the run sees once the screen is gone: no handoffs, no choices, no display."""

    alive = False

    def phase_changed(self, phase):
        pass

    def output(self, key, lines):
        pass

    def activity(self, text):
        pass

    def handoff(self, title, notice, work):
        return None

    def recover(self, phase, failure):
        return RETURN

    def finished(self, run):
        pass


class Run:
    """One action's phases, executed on a background thread."""

    def __init__(self, install, action, env, version, options=None, bridge=None, lock=None):
        self.install = install
        self.action = action
        self.env = env
        self.version = version
        self.bridge = bridge or NullBridge()
        self.lock = lock
        self.options = options
        steps = install.action_steps(action, env, version, options)
        self.steps = [step for step in steps if step.visible]
        self.phases = [PhaseState(step) for step in self.steps]
        self.stop = core.Signal()       # stop after the current phase
        self.hangup = core.Signal()     # the terminal went away
        self.current = None
        self.process = None
        self.outcome = None             # 'completed', 'partial', 'failed', 'stopped', 'returned', 'interrupted'
        self.started = None
        self.finished_at = None
        self.thread = None
        self._lock_waiter = None

    # ---- lifecycle -------------------------------------------------------------------------
    def start(self):
        self.thread = threading.Thread(target=self._main, name='installer-run', daemon=False)
        self.thread.start()
        return self

    @property
    def active(self):
        return self.thread is not None and self.thread.is_alive()

    def request_stop(self, reason='stop after current step'):
        self.stop.set(reason)

    def disconnect(self, reason='terminal disconnected'):
        """The terminal is gone: finish the active phase only, start nothing else, ask nothing."""
        self.hangup.set(reason)
        self.stop.set(reason)
        self.bridge = NullBridge()

    def interrupt_current(self):
        """Ctrl+C for the active piped step, as the plain installer's terminal would deliver it:
        SIGINT to the step's process group (sudo relays it to the helper). Returns False when
        no step process is running (in-process checks, a terminal handoff, between phases).
        The phase then fails with the helper's own status and offers the usual recovery."""
        process = self.process
        if process is None or process.process is None or process.process.poll() is not None:
            return False
        import os
        import signal
        try:
            os.killpg(process.process.pid, signal.SIGINT)
        except (ProcessLookupError, PermissionError):
            return False
        self.interrupted_key = self.current.key if self.current else None
        return True

    def cancel_lock_wait(self):
        """End a package-lock wait with a single SIGINT. apt_lock.py also restores its paused APT
        timers on SIGHUP and SIGTERM, but only SIGKILL leaves them stopped, so never send that."""
        waiter = self._lock_waiter
        if waiter is None or waiter.process is None or waiter.process.poll() is not None:
            return False
        if getattr(waiter, 'cancel_sent', False):
            # Exactly one SIGINT: a second one could land while apt_lock.py restarts the timers.
            return True
        import os
        import signal
        try:
            os.killpg(waiter.process.pid, signal.SIGINT)
            waiter.cancel_sent = True
        except (ProcessLookupError, PermissionError):
            return False
        return True

    # ---- reporting helpers -----------------------------------------------------------------
    def _set(self, phase, state, note=None):
        phase.state = state
        if note is not None:
            phase.note = note
        if state == RUNNING:
            if phase.started is None:
                phase.started = time.monotonic()
            phase.finished = None   # a retry is running again: its clock must move
        if state in (COMPLETED, FAILED, SKIPPED, STOPPED):
            phase.finished = time.monotonic()
        self.bridge.phase_changed(phase)

    def _say(self, key):
        def say(text=''):
            for line in str(text).split('\n'):
                self.bridge.output(key, [core.sanitize.clean_line(line)])
        return say

    # ---- main loop -------------------------------------------------------------------------
    def _main(self):
        self.started = time.time()
        try:
            for index, (step, phase) in enumerate(zip(self.steps, self.phases)):
                if self.stop:
                    # Stop after the current step: nothing later starts; what ran is kept.
                    self._mark_rest(index, STOPPED)
                    self.outcome = 'interrupted' if self.hangup else 'stopped'
                    break
                self.current = phase
                if not self._phase(step, phase):
                    self._mark_rest(index + 1, NOT_STARTED)
                    self.outcome = 'interrupted' if self.hangup else 'returned'
                    break
            else:
                self.outcome = self._summary_outcome()
        except Exception:  # never leave the screen waiting on a dead run
            self.outcome = 'failed'
            if self.current is not None:
                self.current.failure = Failure('internal', traceback.format_exc(limit=3).strip().splitlines()[-1])
                self._set(self.current, FAILED)
        finally:
            self.current = None
            self.finished_at = time.time()
            if self.lock is not None:
                # Close only: a step child that inherited the descriptor keeps the lock until it exits.
                self.lock.release(unlock=False)
            core.write_run_record(self.env, self.record())
            self.bridge.finished(self)

    def _mark_rest(self, start, state):
        for phase in self.phases[start:]:
            if phase.state == PENDING:
                self._set(phase, state)

    def _summary_outcome(self):
        if all(p.state in (COMPLETED, SKIPPED) for p in self.phases if not p.post) and \
                all(p.state == COMPLETED for p in self.phases if p.post and p.key != 'lazydocker'):
            return 'completed'
        if any(p.state == FAILED for p in self.phases if not p.post):
            return 'failed'
        return 'partial'

    def _phase(self, step, phase):
        """Run one phase until it completes or is skipped (True), or until the operator returns
        or the terminal is lost (False). A retry repeats this phase only, never earlier ones."""
        while True:
            phase.attempts += 1
            phase.failure = None
            self._set(phase, RUNNING, '')
            self.bridge.activity(phase.label)
            try:
                failure = self._execute(step, phase)
            except Exception as error:
                failure = Failure('internal', f'{type(error).__name__}: {error}')
            if failure is None:
                if phase.state in (RUNNING, WAITING):
                    self._set(phase, COMPLETED)
                return True
            while True:
                phase.failure = failure
                self._set(phase, FAILED)
                if self.hangup:
                    return False
                choice = self._recover(step, phase, failure)
                if self.hangup:
                    # The terminal went away while a choice or a lock wait was pending: never
                    # repeat the phase without the operator.
                    return False
                if choice == AUTH_RETRY:
                    if self._authenticate(phase, force=True) and not self.hangup:
                        break
                    if self.hangup:
                        return False
                    failure = Failure('auth', 'Administrator access was not confirmed.', choices=(AUTH_RETRY, RETURN))
                    continue
                if choice == RETRY:
                    break
                if choice == SKIP:
                    self._set(phase, SKIPPED, 'not completed; run it again later from the dashboard')
                    return True
                return False

    def _recover(self, step, phase, failure):
        while True:
            choice = self.bridge.recover(phase, failure)
            if choice == LOCK_CHECK:
                if self.install.lock_free(self.env):
                    return RETRY
                failure.holder = holder_report(self.install, self.env)
                continue
            if choice == LOCK_WAIT:
                if self._lock_wait(phase):
                    return RETRY
                failure.holder = holder_report(self.install, self.env)
                continue
            return choice

    # ---- one attempt -----------------------------------------------------------------------
    def _execute(self, step, phase):
        key = step.key
        if key == 'admin':
            return None if self._authenticate(phase) else Failure('auth', 'Administrator access was not confirmed.',
                                                                  choices=(AUTH_RETRY, RETURN))
        if key == 'settings':
            try:
                step.action()   # copy_env(options.env_source): exclusive create, private mode, never displayed
            except (OSError, ValueError) as error:
                return Failure('settings', f'Previous settings were not copied: {error}', choices=(RETRY, RETURN))
            phase.note = 'copied with private permissions; contents not shown'
            return None
        if key == 'verify':
            if not self._authenticate(phase):
                return Failure('auth', 'Administrator access is needed to read the manager container.',
                               choices=(AUTH_RETRY, RETURN))
            try:
                address = self.install.check_manager(self.env, self.version, say=self._say(key), sudo=('sudo', '-n'))
            except (OSError, ValueError) as error:
                return Failure('verify', str(error), choices=(RETRY, RETURN))
            phase.outcome = address
            return None
        if key == 'lazydocker':
            outcome = self.install.setup_lazydocker(self.env, say=self._say(key))
            phase.outcome = outcome
            if outcome and outcome[0] == 'skipped':
                self._set(phase, SKIPPED, outcome[1])
            else:
                phase.note = outcome[1] if outcome else ''
            return None
        if key == 'git':
            user, home = self.env.get('USER', ''), self.env.get('HOME', '')
            self._set(phase, WAITING, 'Git setup has the terminal')
            code = self.bridge.handoff('Git setup', GIT_NOTICE.format(user=user, home=home),
                                       lambda: self.install.git_setup(self.env))
            phase.code = code
            if code == 0:
                return None
            if code is None:
                return Failure('handoff', 'The terminal could not be handed over for Git setup.',
                               choices=(RETRY, SKIP, RETURN) if step.post else (RETRY, RETURN))
            return Failure('git', f'Git setup did not complete (exit status {code}). The manager and any existing '
                                  'checkout remain available.', code, choices=(RETRY, SKIP, RETURN) if step.post else (RETRY, RETURN))
        if step.argv:
            return self._command(step, phase)
        raise ValueError(f'No way to run phase {key!r}')

    def _authenticate(self, phase, force=False):
        """Fresh sudo credentials for this terminal. Uses the cached timestamp when there is one
        (no prompt, no screen change); otherwise hands the terminal to `sudo -v`."""
        if not force and credentials_cached(self.env, str(self.install.SOURCE)):
            return True
        if self.hangup:
            return False
        previous = phase.state
        self._set(phase, WAITING, 'sudo is asking for your password in the terminal')
        code = self.bridge.handoff('Administrator access', AUTH_NOTICE, self._terminal(['sudo', '-v']))
        self._set(phase, previous if previous != WAITING else RUNNING, '')
        return code == 0

    def _terminal(self, argv):
        # The plain installer's own run(): the real terminal on stdin/stdout/stderr, same cwd and env.
        return lambda: self.install.run(list(argv), self.env).returncode

    def _password_needed(self):
        code, text = core.run_capture(['sudo', '-n', 'passwd', '-S', 'clab-discovery'], self.env,
                                      str(self.install.SOURCE), timeout=15)
        fields = text.split()
        return not (code == 0 and len(fields) > 1 and fields[1] == 'P')

    def _command(self, step, phase):
        if not self._authenticate(phase):
            return Failure('auth', 'Administrator access was not confirmed.', choices=(AUTH_RETRY, RETURN))
        if step.interactive == 'password' and self._password_needed():
            # First setup: setup-password.sh reads the new password from the real terminal and the
            # same launcher run then builds the image. Hand over the whole launcher, unchanged.
            self._set(phase, WAITING, 'the launcher has the terminal (password, then image build)')
            code = self.bridge.handoff(phase.label, PASSWORD_NOTICE, self._terminal(step.argv))
            phase.code = code
            if code == 0:
                return None
            if code is None:
                return Failure('handoff', 'The terminal could not be handed over for the password prompt.')
            return Failure('command', f'The launcher stopped with exit status {code}. Completed setup and existing '
                                      'data are retained.', code)
        holder_fd = self.lock.fd if self.lock is not None else None
        process = core.StepProcess(core.noninteractive(step.argv), self.env, str(self.install.SOURCE),
                                   on_lines=lambda lines: self.bridge.output(step.key, lines),
                                   lock_signature=self.install.LOCK_SIGNATURE if step.tee else None,
                                   pass_fds=(holder_fd,))
        self.process = process
        try:
            code = process.run()
        finally:
            self.process = None
        phase.code = code
        if code == 0:
            if step.key == 'engineer':
                phase.note = self.install.ENGINEER_RECONNECT
            return None
        if process.saw_lock:
            holder = holder_report(self.install, self.env)
            if self.install.lock_free(self.env):
                holder = ''
            return Failure('lock', 'The package manager (APT/dpkg) is locked by another process.', code,
                           choices=(LOCK_WAIT, RETRY, LOCK_CHECK, RETURN), holder=holder)
        if process.saw_auth:
            return Failure('auth', 'sudo needs your password again before this step can run.', code,
                           choices=(AUTH_RETRY, RETURN))
        if getattr(self, 'interrupted_key', None) == step.key:
            self.interrupted_key = None
            return Failure('command', f'Interrupted on request (exit status {code}). Completed setup and existing data '
                                      'are retained; retry runs this phase again.', code)
        return Failure('command', f'The step stopped with exit status {code}. Completed setup and existing data '
                                  'are retained.', code)

    def _lock_wait(self, phase):
        if not self._authenticate(phase):
            return False
        self._set(phase, WAITING, 'waiting for the package lock (APT timers paused until it is released)')
        holder_fd = self.lock.fd if self.lock is not None else None
        waiter = core.StepProcess(core.noninteractive(self.install.lock_wait_command()), self.env,
                                  str(self.install.SOURCE), on_lines=lambda lines: self.bridge.output(phase.key, lines),
                                  pass_fds=(holder_fd,))
        self._lock_waiter = waiter
        try:
            code = waiter.run()
        finally:
            self._lock_waiter = None
        self._set(phase, FAILED, '')
        return code == 0

    # ---- results ---------------------------------------------------------------------------
    def record(self):
        """Metadata-only summary persisted after the run (no output, no settings values)."""
        return {
            'schema': 'clab-node-manager-installer-run-v1',
            'action': self.action,
            'version': self.version,
            'started': time.strftime('%Y-%m-%dT%H:%M:%S%z', time.localtime(self.started or time.time())),
            'finished': time.strftime('%Y-%m-%dT%H:%M:%S%z', time.localtime(self.finished_at or time.time())),
            'outcome': self.outcome,
            'interrupted': self.hangup.reason if self.hangup else '',
            'phases': [{'key': p.key, 'state': p.state, 'exit_status': p.code, 'attempts': p.attempts,
                        'seconds': round(p.elapsed, 1) if p.elapsed is not None else None} for p in self.phases],
        }

    def phase(self, key):
        return next((p for p in self.phases if p.key == key), None)


class HealthRun(Run):
    """Check installation: the read-only health report in its structured mode.

    `bash deploy/check-install.sh --json` is the same report the plain menu prints, with the
    same exit statuses (0 passed, 1 a FAIL, 2 a WARN or SKIP); its progress lines (stderr)
    stream to the screen and its JSON report (stdout) becomes the results table. It changes
    nothing, so it takes no installer lock. Without cached sudo credentials the terminal is
    offered to `sudo -v` first; if that is declined the report still runs and marks the
    privileged checks SKIP, exactly as the plain report does without sudo.
    """

    def __init__(self, install, env, version, bridge=None):
        self.install = install
        self.action = 'health'
        self.env = env
        self.version = version
        self.bridge = bridge or NullBridge()
        self.lock = None
        self.options = None
        step = install.Step('health', 'Installation health check', None, argv=install.health_command() + ['--json'])
        self.steps = [step]
        self.phases = [PhaseState(step)]
        self.stop = core.Signal()
        self.hangup = core.Signal()
        self.current = None
        self.process = None
        self.outcome = None
        self.started = None
        self.finished_at = None
        self.thread = None
        self._lock_waiter = None
        self.report = None

    def _execute(self, step, phase):
        self._authenticate(phase)   # best effort: privileged checks are skipped without it
        self._set(phase, RUNNING, '')
        import subprocess
        import json
        process = subprocess.Popen(step.argv, cwd=str(self.install.SOURCE), env=self.env, stdin=subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, process_group=0)
        # The same shape as a StepProcess (`.process` is the Popen), so Interrupt step works here too.
        self.process = SimpleNamespace(process=process)
        chunks = []

        def drain():
            data = process.stdout.read(4 * 1024 * 1024 + 1)
            chunks.append(data)
            while process.stdout.read(65536):   # discard anything beyond the cap so the child never blocks
                pass

        reader = threading.Thread(target=drain, daemon=True)
        reader.start()
        for raw in iter(process.stderr.readline, b''):
            self.bridge.output(step.key, [core.sanitize.clean_line(core.sanitize.decode(raw))])
        code = process.wait()
        reader.join(timeout=30)
        process.stdout.close()
        process.stderr.close()
        self.process = None
        phase.code = code
        data = b''.join(chunks)
        try:
            report = json.loads(data.decode('utf-8', 'replace')) if len(data) <= 4 * 1024 * 1024 else None
        except ValueError:
            report = None
        if not isinstance(report, dict) or report.get('schema') != 'clab-manager-health-v1':
            return Failure('command', f'The health report did not produce its structured result (exit status {code}).',
                           code, choices=(RETRY, RETURN))
        self.report = report
        phase.outcome = report
        counts = report.get('counts') or {}
        phase.note = ', '.join(f'{counts.get(name, 0)} {name}' for name in ('PASS', 'WARN', 'FAIL', 'SKIP') if counts.get(name))
        return None

    def _summary_outcome(self):
        if self.report is None:
            return 'failed'
        code = self.report.get('exit_code')
        return 'completed' if code == 0 else 'partial'
