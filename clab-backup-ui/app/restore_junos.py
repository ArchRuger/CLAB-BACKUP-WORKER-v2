"""Apply a whole-device Junos configuration over the interactive CLI.

The manager restores a saved *desired state* onto a running Junos node without a
reboot or a containerlab redeploy. Junos ``show configuration | display set`` output
can only be merged (``load set``) and cannot remove statements a snapshot dropped, so
it is unsuitable for a desired-state restore. This driver loads the hierarchical
(curly-brace) candidate with ``load override terminal`` — a complete replacement that
removes stale statements — and activates it with a confirmed commit so the node rolls
back on its own if management is lost.

Sequence, proven live on ``juniper_cjunosevolved`` and ``juniper_vjunosswitch``:

1. ``configure exclusive`` (falls back to ``configure``), ``rollback 0``.
2. ``load override terminal`` with the candidate, ended by Ctrl-D.
3. Ensure the mandatory ``system root-authentication`` exists. The cJunosEvolved lab
   image commits without it at boot but rejects any later commit ("missing mandatory
   statements"); when the candidate lacks it, synthesise one from the candidate's own
   superuser login password so the node stays reachable and self-consistent.
4. ``show | compare`` for the review diff, then ``commit check``.
5. ``commit confirmed <minutes>`` — activates with an automatic rollback timer.
6. The caller then reconnects (proving management works) and calls :func:`confirm`,
   which runs a plain ``commit`` to cancel the rollback. If the reconnect never
   happens, the node rolls back by itself.

Device output never leaves this module unscrubbed: callers get controlled messages and
the ``show | compare`` diff, which they redact before display or logging.
"""
import re
import socket
import time

ANSI = re.compile(r'(\x1b\[[0-9;?]*[A-Za-z])|[\x07\x00]')
OPER = re.compile(r'^[\w.\-]+@[\w.\-]+>\s*$', re.M)          # operational prompt
CONF = re.compile(r'^[\w.\-]+@[\w.\-]+#\s*$', re.M)          # configuration prompt
ANY_PROMPT = re.compile(r'(^[\w.\-]+@[\w.\-]+[>#]\s*$)|([%$]\s*$)', re.M)
SHELL = re.compile(r'[%$]\s*$')                              # root shell before `cli`
LOAD_ERROR = re.compile(r'(?im)^\s*(?:error:|syntax error|load: |unknown command|missing\b)')
COMMIT_ERROR = re.compile(r'(?im)^\s*(?:error:|.*\bfailed\b)')   # not used: a commit is judged by COMMIT_OK being present
CHECK_OK = 'configuration check succeeds'
COMMIT_OK = 'commit complete'
SECRET_HASH = re.compile(r'encrypted-password "([^"]+)"')

PROMPT_TIMEOUT = 30
LOAD_TIMEOUT = 90
COMMIT_TIMEOUT = 180
LIMIT = 4 * 1024 * 1024
SUPPORTED_KINDS = ('juniper_cjunosevolved', 'juniper_vjunosswitch')


class RestoreError(Exception):
    """A controlled, user-facing reason; never raw device configuration."""


def supports_restore(platform):
    return platform in SUPPORTED_KINDS


class JunosShell:
    """Prompt-driven wrapper over a paramiko channel (or any recv/sendall object)."""

    def __init__(self, channel, timeout=PROMPT_TIMEOUT):
        self.channel = channel
        self.timeout = timeout
        self.received = 0

    def expect(self, patterns, timeout=None):
        deadline = time.monotonic() + (timeout or self.timeout)
        buffer = ''
        while True:
            try:
                chunk = self.channel.recv(65536)
            except socket.timeout:
                chunk = None
            if chunk == b'':
                raise RestoreError('The SSH session to the node closed before it answered.')
            if chunk:
                self.received += len(chunk)
                if self.received > LIMIT:
                    raise RestoreError('The node returned more output than expected; the session was closed.')
                buffer += chunk.decode('utf-8', 'replace')
                text = ANSI.sub('', buffer).replace('\r', '')
                last = text.rstrip().rsplit('\n', 1)[-1] if text.strip() else ''
                for index, pattern in enumerate(patterns):
                    if pattern.search(last):
                        return index, text
            if time.monotonic() > deadline:
                raise RestoreError('The node did not return to its prompt in time.')

    def send(self, line):
        self.channel.sendall((line + '\n').encode())

    def send_raw(self, data):
        self.channel.sendall(data)

    def run(self, command, timeout=None):
        """Send one command; return its output without the echo or the trailing prompt."""
        self.send(command)
        _, text = self.expect([ANY_PROMPT], timeout)
        lines = ANSI.sub('', text).replace('\r', '').split('\n')
        while lines and not lines[0].strip():
            lines.pop(0)
        if lines and command.strip() and lines[0].strip().endswith(command.strip()):
            lines.pop(0)
        return '\n'.join(lines[:-1]) if lines else ''


def reach_cli(shell):
    """From login, land on the operational prompt (handle a root shell and config mode)."""
    index, _ = shell.expect([OPER, CONF, SHELL], PROMPT_TIMEOUT)
    if index == 2:
        shell.send('cli')
        shell.expect([OPER], PROMPT_TIMEOUT)
    elif index == 1:
        shell.run('rollback 0', PROMPT_TIMEOUT)
        shell.send('exit')
        shell.expect([OPER], PROMPT_TIMEOUT)
    shell.run('set cli screen-length 0', PROMPT_TIMEOUT)
    shell.run('set cli screen-width 0', PROMPT_TIMEOUT)
    shell.run('set cli complete-on-space off', PROMPT_TIMEOUT)


def enter_config(shell):
    """Enter configuration mode with an exclusive lock, discarding any stale candidate."""
    shell.send('configure exclusive')
    index, text = shell.expect([CONF, OPER], PROMPT_TIMEOUT)
    if index == 1:
        # Some builds refuse `configure exclusive`; job serialisation still guards us.
        shell.send('configure')
        index, text = shell.expect([CONF, OPER], PROMPT_TIMEOUT)
        if index == 1:
            raise RestoreError('The node did not enter configuration mode.')
    shell.run('rollback 0', PROMPT_TIMEOUT)


ROOT_AUTH = re.compile(r'(?m)^\s*root-authentication\s*\{|^\s*set system root-authentication\b')


def _ensure_root_authentication(shell, candidate):
    """Guarantee the mandatory `system root-authentication` is in the candidate.

    After ``load override`` the candidate equals ``candidate``, so its own text is the
    reliable source (querying the device in configuration mode is not: the echoed command
    name itself contains "root-authentication"). Junos rejects a commit that drops the
    mandatory statement, and the cJunosEvolved lab image ships without it. Returns
    'present', 'synthesized' (added from the candidate's superuser login password), or
    raises when neither is possible.
    """
    if ROOT_AUTH.search(candidate):
        return 'present'
    match = SECRET_HASH.search(candidate)
    if not match:
        raise RestoreError('The saved configuration has no root-authentication and no login '
                           'password to derive one from; this Junos node cannot commit without it.')
    shell.run('set system root-authentication encrypted-password "%s"' % match.group(1), PROMPT_TIMEOUT)
    return 'synthesized'


def apply_shell(shell, candidate, confirm_minutes=5):
    """Load and confirm-commit a candidate on an already-open JunosShell.

    Returns a dict: diff (show | compare), root_authentication, no_op. Raises
    RestoreError on any load/check/commit failure, after discarding the candidate.
    """
    if not candidate.strip():
        raise RestoreError('The saved configuration is empty.')
    reach_cli(shell)
    enter_config(shell)
    try:
        shell.send('load override terminal')
        time.sleep(1.5)  # device prints "[Type ^D at a new line to end input]"
        body = candidate if candidate.endswith('\n') else candidate + '\n'
        shell.send_raw(body.encode())
        shell.send_raw(b'\x04')  # Ctrl-D ends terminal input
        _, load_out = shell.expect([CONF], LOAD_TIMEOUT)
        load_text = ANSI.sub('', load_out).replace('\r', '')
        if LOAD_ERROR.search(load_text):
            raise RestoreError('The node rejected the saved configuration while loading it.')
        root_auth = _ensure_root_authentication(shell, candidate)
        diff = shell.run('show | compare', LOAD_TIMEOUT)
        no_op = not diff.strip() or diff.strip() == '[edit]'
        check = shell.run('commit check', COMMIT_TIMEOUT)
        if CHECK_OK not in check:
            raise RestoreError('The node failed the configuration check for the saved configuration.')
        confirmed = shell.run('commit confirmed %d' % int(confirm_minutes), COMMIT_TIMEOUT)
        if COMMIT_OK not in confirmed:
            raise RestoreError('The node did not accept the confirmed commit of the saved configuration.')
        # The commit is armed. Leaving configuration mode is cosmetic, and activating a
        # whole new configuration can briefly disrupt this SSH session, so a failure of the
        # trailing exit must NOT be reported as "nothing changed": the caller reconnects and
        # confirms, and an unconfirmed armed commit rolls back on its own.
        try:
            shell.run('exit', PROMPT_TIMEOUT)
        except RestoreError:
            pass
        return {'diff': diff, 'root_authentication': root_auth, 'no_op': no_op,
                'confirm_minutes': int(confirm_minutes)}
    except RestoreError:
        _safe_abort(shell)
        raise


def confirm_shell(shell):
    """Confirm a pending commit-confirmed over a fresh JunosShell (cancels the rollback)."""
    reach_cli(shell)
    pending = shell.run('show configuration | compare rollback 1 | no-more', PROMPT_TIMEOUT)
    shell.send('configure')
    index, _ = shell.expect([CONF, OPER], PROMPT_TIMEOUT)
    if index == 1:
        raise RestoreError('The node did not enter configuration mode to confirm the commit.')
    result = shell.run('commit', COMMIT_TIMEOUT)
    shell.run('exit', PROMPT_TIMEOUT)
    if COMMIT_OK not in result:
        raise RestoreError('The node did not confirm the commit; it will roll back on its own.')
    return {'confirmed': True, 'had_pending_rollback': 'rolled back' in pending.lower()}


def pending_rollback_shell(shell):
    """True when a confirmed commit is still awaiting confirmation on the node.

    Not called yet: kept as the probe an interrupted restore would need (a manager restart between
    `commit confirmed` and the confirming `commit`). Wiring it is a feature decision, not cleanup.
    """
    reach_cli(shell)
    out = shell.run('show system commit | no-more', PROMPT_TIMEOUT)
    return 'rollback' in out.lower() and 'confirmed' in out.lower()


def capture_shell(shell, display_set=True):
    """Capture the running configuration for verification (display-set by default)."""
    reach_cli(shell)
    command = ('show configuration | display set | no-more' if display_set
               else 'show configuration | no-more')
    return shell.run(command, LOAD_TIMEOUT)


def _safe_abort(shell):
    for step in ('rollback 0', 'exit'):
        try:
            shell.run(step, PROMPT_TIMEOUT)
        except RestoreError:
            break


# --- live entry points: open a channel on a connected paramiko client ---------------

def _open(client):
    channel = client.invoke_shell(term='vt100', width=240, height=100000)
    channel.settimeout(1.0)
    return channel, JunosShell(channel)


def apply_candidate(client, candidate, confirm_minutes=5):
    channel, shell = _open(client)
    try:
        return apply_shell(shell, candidate, confirm_minutes)
    finally:
        _close(channel)


def confirm(client):
    channel, shell = _open(client)
    try:
        return confirm_shell(shell)
    finally:
        _close(channel)


def capture(client, display_set=True):
    channel, shell = _open(client)
    try:
        return capture_shell(shell, display_set)
    finally:
        _close(channel)


def _close(channel):
    try:
        channel.close()
    except Exception:
        pass
