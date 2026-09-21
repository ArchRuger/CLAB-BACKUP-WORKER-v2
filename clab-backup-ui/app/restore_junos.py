"""Apply a whole-device Junos configuration over the interactive CLI.

The manager restores a saved *desired state* onto a running Junos node without a
reboot or a containerlab redeploy. Junos ``show configuration | display set`` output
can only be merged (``load set``) and cannot remove statements a snapshot dropped, so
it is unsuitable for a desired-state restore. This driver loads the hierarchical
(curly-brace) candidate with ``load override terminal`` — a complete replacement that
removes stale statements — and activates it with a confirmed commit so the node rolls
back on its own if management is lost.

Sequence, proven live on ``juniper_cjunosevolved`` (26.2R1.7-EVO) and ``juniper_vjunosswitch``
(23.2R1.14); the evidence is in docs/multi-platform-restore/:

1. Refuse when a confirmation is already pending on the node, and when somebody's uncommitted
   edits sit in the shared candidate (looked at from a plain ``configure`` that is left again
   without touching them). Then ``configure exclusive``; there is no fallback to a shared session,
   because discarding the candidate there would destroy another operator's work.
2. ``load override terminal`` with the candidate, ended by Ctrl-D.
3. Ensure the mandatory ``system root-authentication`` exists. On cJunosEvolved a bare ``commit``
   only warns about the missing statement, but ``commit check`` and ``commit confirmed`` reject it
   ("Missing mandatory statement"), and the lab image ships without it; when the candidate lacks
   it, synthesise one from the candidate's own superuser login password so the node stays reachable
   and self-consistent.
4. ``show | compare`` for the review diff, then ``commit check``.
5. ``commit confirmed <minutes> comment <token>``: activates with an automatic rollback timer. The
   comment is the change's identity: ``show system commit`` prints it under entry 0, followed by
   ``rollback pending`` while the timer runs, so a later session (after a lost connection or a
   manager restart) can tell this restore's pending change from anybody else's.
6. The caller reconnects (proving management works) and calls :func:`confirm`, which runs
   ``commit check``: on Junos that confirms a pending confirmed commit *without* committing the
   candidate, so another session's uncommitted edits are not activated (a plain ``commit`` was
   proven to activate them). Success is the disappearance of ``rollback pending``. If the reconnect
   never happens, the node rolls back by itself.

Device output never leaves this module unscrubbed: callers get controlled messages and
the ``show | compare`` diff, which they redact before display or logging.
"""
import re
import time

from .restore_compare import compare_junos as compare  # noqa: F401  (part of the driver contract)
from .restore_shell import ANSI, PROMPT_TIMEOUT, RestoreError, SessionLost, Shell, close_channel, open_shell

OPER = re.compile(r'^[\w.\-]+@[\w.\-]+>\s*$', re.M)          # operational prompt
CONF = re.compile(r'^[\w.\-]+@[\w.\-]+#\s*$', re.M)          # configuration prompt
ANY_PROMPT = re.compile(r'(^[\w.\-]+@[\w.\-]+[>#]\s*$)|([%$]\s*$)', re.M)
SHELL = re.compile(r'[%$]\s*$')                              # root shell before `cli`
LOAD_ERROR = re.compile(r'(?im)^\s*(?:error:|syntax error|load: |unknown command|missing\b)')
CHECK_OK = 'configuration check succeeds'
COMMIT_OK = 'commit complete'
SECRET_HASH = re.compile(r'encrypted-password "([^"]+)"')
COMMIT_FAILED = re.compile(r'(?im)^\s*error:')
EXIT_QUESTION = re.compile(r'\[yes,no\]\s*\(\w+\)\s*$')   # "Exit with uncommitted changes? [yes,no] (yes)"
TOKEN = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_-]{0,39}$')

LOAD_TIMEOUT = 90
COMMIT_TIMEOUT = 180
SUPPORTED_KINDS = ('juniper_cjunosevolved', 'juniper_vjunosswitch')
RESTORE_FORMAT = 'junos-hierarchical'


def supports_restore(platform):
    return platform in SUPPORTED_KINDS


class JunosShell(Shell):
    any_prompt = ANY_PROMPT


def validate_candidate(text):
    """Refuse an obviously wrong or truncated candidate before touching the device.

    `load override` needs the hierarchical form. `display set` text would be refused by the node
    anyway, but a candidate cut off in the middle can still parse as far as it goes, so the braces
    must balance.
    """
    lines = [line for line in (text or '').splitlines() if line.strip() and not line.lstrip().startswith(('#', '/*'))]
    if not lines:
        raise RestoreError('The saved configuration is empty.')
    if lines[0].lstrip().startswith('set ') or '{' not in text:
        raise RestoreError('The saved configuration is not in the hierarchical form a Junos device loads.')
    if text.count('{') != text.count('}') or not lines[-1].rstrip().endswith('}'):
        raise RestoreError('The saved configuration looks truncated; its braces do not balance.')


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


def leave_config(shell):
    """Leave configuration mode. Junos asks before leaving uncommitted changes behind (ours were
    discarded or committed by then, so they are another session's): answer yes, which keeps them."""
    shell.send('exit')
    index, _ = shell.expect([OPER, EXIT_QUESTION], PROMPT_TIMEOUT)
    if index == 1:
        shell.send('yes')
        shell.expect([OPER], PROMPT_TIMEOUT)


def unchanged(diff):
    """True when `show | compare` reported no difference. In configuration mode every answer ends
    with the `[edit]` banner line, so an empty comparison is "nothing but [edit] lines"."""
    return not [line for line in diff.splitlines() if line.strip() and line.strip() != '[edit]']


FOREIGN_EDITS = ('Someone has uncommitted configuration changes open on this node. The restore was '
                 'not started, so their work is not lost.')


def foreign_edits(shell):
    """True when the shared candidate holds uncommitted changes. Looked at from a plain session that
    is left again without touching them. Must be called from the operational prompt."""
    shell.send('configure')
    index, _ = shell.expect([CONF, OPER], PROMPT_TIMEOUT)
    if index == 1:
        raise RestoreError('The node did not enter configuration mode.')
    foreign = shell.run('show | compare', LOAD_TIMEOUT)
    leave_config(shell)
    return not unchanged(foreign)


def enter_config(shell):
    """Enter configuration mode with an exclusive lock, without destroying anybody's work.

    The candidate is shared. Someone's uncommitted edits in it would be lost to a whole-configuration
    load, so the driver looks first and refuses; cJunosEvolved refuses ``configure exclusive`` by
    itself in that case. Our own session cannot be what blocks a later restore: it is always
    exclusive, and Junos discards an exclusive session's uncommitted changes when it ends, a dropped
    connection included (proven on both lab images, tools/driver_junos_live.py).
    """
    if foreign_edits(shell):
        raise RestoreError(FOREIGN_EDITS)
    shell.send('configure exclusive')
    index, _ = shell.expect([CONF, OPER], PROMPT_TIMEOUT)
    if index == 1:
        raise RestoreError('The node did not grant exclusive configuration access; someone else is editing it.')


ROOT_AUTH = re.compile(r'(?m)^\s*root-authentication\s*\{|^\s*set system root-authentication\b')


def _ensure_root_authentication(shell, candidate):
    """Guarantee the mandatory `system root-authentication` is in the candidate.

    After ``load override`` the candidate equals ``candidate``, so its own text is the reliable
    source (querying the device in configuration mode is not: the echoed command name itself
    contains "root-authentication"). ``commit check`` and ``commit confirmed`` reject a candidate
    without the mandatory statement (a bare ``commit`` only warns), and the cJunosEvolved lab image
    ships without it. Returns 'present', 'synthesized' (added from the first login
    encrypted-password of the candidate: the only login in a lab image, but in a multi-user
    configuration not necessarily a superuser's), or raises when neither is possible.
    """
    if ROOT_AUTH.search(candidate):
        return 'present'
    match = SECRET_HASH.search(candidate)
    if not match:
        raise RestoreError('The saved configuration has no root-authentication and no login '
                           'password to derive one from; this Junos node cannot commit without it.')
    shell.run('set system root-authentication encrypted-password "%s"' % match.group(1), PROMPT_TIMEOUT)
    return 'synthesized'


def apply_shell(shell, candidate, confirm_minutes=5, token=None):
    """Load and confirm-commit a candidate on an already-open JunosShell.

    Returns a dict: diff (show | compare), root_authentication, no_op. Raises
    RestoreError on any load/check/commit failure, after discarding the candidate.
    """
    validate_candidate(candidate)
    if token and not TOKEN.match(token):
        raise RestoreError('The restore token is not usable as a commit comment.')
    reach_cli(shell)
    if pending_commit(shell):
        raise RestoreError('Another change is waiting for confirmation on this node; this restore was not started.')
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
        no_op = unchanged(diff)
        check = shell.run('commit check', COMMIT_TIMEOUT)
        if CHECK_OK not in check:
            raise RestoreError('The node failed the configuration check for the saved configuration.')
        confirmed = shell.run('commit confirmed %d%s' % (int(confirm_minutes), ' comment %s' % token if token else ''),
                              COMMIT_TIMEOUT)
        if COMMIT_OK not in confirmed:
            raise RestoreError('The node did not accept the confirmed commit of the saved configuration.')
        if COMMIT_FAILED.search(confirmed):
            # "commit complete" beside an error line (a multi-RE device answers per RE): what is
            # active is unknown, so this must not read as "nothing changed". Hardening: neither lab
            # image prints per-RE sections. The service reads the node back.
            raise SessionLost('The node reported both a completed and a failed commit.')
        # The commit is armed. Leaving configuration mode is cosmetic, and activating a
        # whole new configuration can briefly disrupt this SSH session, so a failure of the
        # trailing exit must NOT be reported as "nothing changed": the caller reconnects and
        # confirms, and an unconfirmed armed commit rolls back on its own.
        try:
            leave_config(shell)
        except RestoreError:
            pass
        return {'diff': diff, 'root_authentication': root_auth, 'no_op': no_op,
                'confirm_minutes': int(confirm_minutes), 'handle': {'token': token} if token else {}}
    except SessionLost:
        raise   # nothing more can be said over this session; the caller reads the node back
    except RestoreError:
        _safe_abort(shell)
        raise


def confirm_shell(shell, handle=None):
    """Confirm this restore's pending confirmed commit over a fresh JunosShell (cancels the rollback).

    ``commit check`` confirms without committing the shared candidate; see the module docstring.
    Nothing is confirmed unless the node shows a pending change, and, when the caller knows its
    token, only when that change carries it.
    """
    reach_cli(shell)
    pending = pending_commit(shell)
    if not pending:
        raise RestoreError('Nothing is waiting for confirmation on this node: the change was already undone or never armed.')
    token = (handle or {}).get('token')
    if token and pending != token:
        raise RestoreError('A different change is waiting for confirmation on this node; it was left alone.')
    shell.send('configure')
    index, _ = shell.expect([CONF, OPER], PROMPT_TIMEOUT)
    if index == 1:
        raise RestoreError('The node did not enter configuration mode to confirm the commit.')
    result = shell.run('commit check', COMMIT_TIMEOUT)
    leave_config(shell)
    if CHECK_OK not in result:
        raise RestoreError('The node did not confirm the commit; it will roll back on its own.')
    if pending_commit(shell):
        raise RestoreError('The node still shows the change as waiting for confirmation; it will roll back on its own.')
    return {'confirmed': True}


def pending_commit(shell):
    """What awaits confirmation: '' (nothing), the pending commit's comment, or True when it has none.

    ``show system commit`` keeps "commit confirmed, rollback in 5mins" on an entry for good, so that
    text alone says nothing. While the timer runs, the newest entry (0) is followed by its comment
    line (if any) and a line "rollback pending"; the latter disappears when the commit is confirmed
    or rolled back. Must be called from the operational prompt.
    """
    lines = [line for line in shell.run('show system commit | no-more', PROMPT_TIMEOUT).splitlines() if line.strip()]
    newest = next((index for index, line in enumerate(lines) if re.match(r'^0\s', line)), None)
    if newest is None or 'commit confirmed' not in lines[newest]:
        return ''
    block = []
    for line in lines[newest + 1:]:
        if re.match(r'^\d+\s', line):
            break
        block.append(line.strip())
    if not any(line.lower() == 'rollback pending' for line in block):
        return ''
    return next((line for line in block if line.lower() != 'rollback pending'), '') or True


def pending_rollback_shell(shell):
    """See :func:`pending_commit`; lands on the operational prompt first."""
    reach_cli(shell)
    return pending_commit(shell)


def capture_shell(shell, display_set=True):
    """Capture the running configuration for verification (display-set by default)."""
    reach_cli(shell)
    command = ('show configuration | display set | no-more' if display_set
               else 'show configuration | no-more')
    return shell.run(command, LOAD_TIMEOUT)


def _safe_abort(shell):
    """Discard our candidate and leave. Only ever called inside our own exclusive session."""
    try:
        shell.run('rollback 0', PROMPT_TIMEOUT)
        leave_config(shell)
    except RestoreError:
        pass


# --- live entry points: open a channel on a connected paramiko client ---------------

def _open(client):
    return open_shell(client, JunosShell)


def apply_candidate(client, candidate, confirm_minutes=5, token=None):
    channel, shell = _open(client)
    try:
        return apply_shell(shell, candidate, confirm_minutes, token)
    finally:
        _close(channel)


def pending(client):
    channel, shell = _open(client)
    try:
        return pending_rollback_shell(shell)
    finally:
        _close(channel)


def blocked(client):
    """A student-readable reason why a restore must not start on this node now, or ''."""
    channel, shell = _open(client)
    try:
        reach_cli(shell)
        return FOREIGN_EDITS if foreign_edits(shell) else ''
    finally:
        _close(channel)


def confirm(client, handle=None):
    channel, shell = _open(client)
    try:
        return confirm_shell(shell, handle)
    finally:
        _close(channel)


def capture(client, display_set=True):
    channel, shell = _open(client)
    try:
        return capture_shell(shell, display_set)
    finally:
        _close(channel)


_close = close_channel
