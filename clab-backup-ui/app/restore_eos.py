"""Replace a whole-device Arista EOS running-configuration over the interactive CLI.

The manager restores a saved *desired state* onto a running EOS node without a reboot or
a containerlab redeploy. EOS configuration sessions (``configure session <name>``) give the
same "load, review, activate, auto-revert" shape that the Junos driver uses, once the
session is reset to a truly empty base:

1. Reach the operational prompt, going through ``enable`` when the credentials carry an
   enable password (or when EOS still asks for one).
2. Refuse outright when another session's commit timer is already pending: that change is
   someone else's, and this driver never confirms or aborts a session it did not start.
3. ``configure session <name>`` then ``rollback clean-config`` — starting a session copies
   the running configuration into it, so this step is required before the paste, or the
   paste would merge onto the old configuration instead of replacing it.
4. ``copy terminal: session-config`` with the candidate text, ended by Ctrl-D. A rejected
   line is echoed back as ``% Invalid input at line N``; the copy still ends with "Copy
   completed successfully." regardless, so the driver scans the echoed output itself for
   any line starting ``% ``.
5. ``show session-config diffs`` for the review diff (empty output means a no-op restore).
6. ``commit timer HH:MM:SS`` — activates the session with an automatic revert if nobody
   confirms in time; EOS itself reverts the running-config at expiry, no reboot involved.
7. The caller then reconnects (proving management works) and calls :func:`confirm`, which
   runs ``configure session <name> commit`` over a *fresh* connection to cancel the timer.
   Because the image ships with autosave-to-startup disabled, a successful confirmation is
   followed by ``write memory`` so the restored configuration survives a device restart; a
   failed save does not undo the confirmation.

Device output never leaves this module unscrubbed: callers get controlled messages and the
``show session-config diffs`` diff, which they redact before display or logging.
"""
import re
import secrets
import time

from .restore_compare import EOS_ORDERED, compare_indented, ordered_blocks_differ
from .restore_shell import ANSI, PROMPT_TIMEOUT, RestoreError, Shell, close_channel, open_shell

PROMPT = re.compile(r'^[\w.\-]+(?:\([^)\n]*\))?[>#]\s*$', re.M)
CONFIG_PROMPT = re.compile(r'^[\w.\-]+\([^)\n]*\)#\s*$', re.M)
UNPRIV_PROMPT = re.compile(r'^[\w.\-]+>\s*$', re.M)
REJECTED_LINE = re.compile(r'(?m)^% ')
PENDING_SESSION = re.compile(r'Session with pending commit timer:\s*(\S+)')
# A row of the session table in state "pending": a session that was opened and never committed or
# aborted. Only the manager's own names are ever matched (`clabmgr-` + 8 hex digits).
ORPHAN = re.compile(r'(?m)^[*\s]\s*(clabmgr-[0-9a-f]{8})\s+pending\b')

LOAD_TIMEOUT = 90
COMMIT_TIMEOUT = 180
SUPPORTED_KINDS = ('arista_ceos',)
RESTORE_FORMAT = 'eos-running-config'

REQUIRED_HEADER = '! Command: show running-config'
HEADER_SCAN_LINES = 5


def supports_restore(platform):
    return platform in SUPPORTED_KINDS


class EosShell(Shell):
    any_prompt = PROMPT


def validate_candidate(text):
    """Refuse an obviously wrong or truncated candidate before touching the device."""
    if not text.strip():
        raise RestoreError('The saved configuration is empty.')
    header_lines = text.splitlines()[:HEADER_SCAN_LINES]
    if not any(line.startswith(REQUIRED_HEADER) for line in header_lines):
        raise RestoreError('The saved configuration does not look like an EOS running-configuration.')
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines or lines[-1].strip() != 'end':
        raise RestoreError('The saved configuration looks truncated; it does not end with "end".')


def reach_cli(shell, enable_password=''):
    """From login, land on the privileged operational prompt and disable paging."""
    index, _ = shell.expect([UNPRIV_PROMPT, PROMPT], PROMPT_TIMEOUT)
    if index == 0:
        shell.send('enable')
        expected = [re.compile(r'[Pp]assword:\s*$'), PROMPT]
        answer_index, _ = shell.expect(expected, PROMPT_TIMEOUT)
        if answer_index == 0:
            shell.send(enable_password)
            shell.expect([PROMPT], PROMPT_TIMEOUT)
    shell.run('terminal length 0', PROMPT_TIMEOUT)
    shell.run('terminal width 500', PROMPT_TIMEOUT)


def pending_shell(shell):
    """The name of the session with a pending commit timer, or '' when none is pending."""
    detail = shell.run('show configuration sessions detail', PROMPT_TIMEOUT)
    match = PENDING_SESSION.search(detail)
    return match.group(1) if match else ''


def cleanup_shell(shell):
    """Abort the manager's own abandoned sessions; returns their names. Call from the privileged prompt.

    A restore whose SSH session dies between `configure session` and `commit timer` leaves its
    session on the device in state "pending" (seen live), and EOS keeps only a handful of those.
    Sessions under other names are somebody's work and are never touched; a session whose commit
    timer is running is not an orphan either.
    """
    detail = shell.run('show configuration sessions detail', PROMPT_TIMEOUT)
    timer = PENDING_SESSION.search(detail)
    removed = []
    for name in ORPHAN.findall(detail):
        if timer and timer.group(1) == name:
            continue
        shell.run('configure session %s' % name, PROMPT_TIMEOUT)
        shell.run('abort', PROMPT_TIMEOUT)
        removed.append(name)
    return removed


def _minutes_to_hms(confirm_minutes):
    total_seconds = int(confirm_minutes) * 60
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return '%02d:%02d:%02d' % (hours, minutes, seconds)


def apply_shell(shell, candidate, confirm_minutes=5, session_name=None, enable_password='', token=None):
    """Replace the running-configuration on an already-open EosShell.

    Returns a dict: diff (show session-config diffs), no_op, confirm_minutes, handle. Raises
    RestoreError on any load/commit failure or when another session's commit is pending; the
    session is aborted (best-effort) before a failure is raised so nothing is left half-applied.
    """
    validate_candidate(candidate)
    reach_cli(shell, enable_password)
    foreign_pending = pending_shell(shell)
    if foreign_pending:
        raise RestoreError('Another change on this node is already pending confirmation; '
                            'this restore was not started.')
    name = session_name or token or ('clabmgr-%s' % secrets.token_hex(4))
    cleanup_shell(shell)
    try:
        opened = shell.run('configure session %s' % name, PROMPT_TIMEOUT)
        if REJECTED_LINE.search(opened):
            raise RestoreError('The node did not open a configuration session for the restore.')
        shell.run('rollback clean-config', LOAD_TIMEOUT)
        shell.send('copy terminal: session-config')
        time.sleep(0.5)
        body = candidate if candidate.endswith('\n') else candidate + '\n'
        shell.send_raw(body.encode())
        shell.send_raw(b'\x04')  # Ctrl-D ends terminal input
        _, load_out = shell.expect([CONFIG_PROMPT], LOAD_TIMEOUT)
        load_text = ANSI.sub('', load_out).replace('\r', '')
        if REJECTED_LINE.search(load_text):
            raise RestoreError('The node rejected the saved configuration while loading it.')
        diff = shell.run('show session-config diffs', LOAD_TIMEOUT)
        no_op = not diff.strip()
        confirmed = shell.run('commit timer %s' % _minutes_to_hms(confirm_minutes), COMMIT_TIMEOUT)
        if REJECTED_LINE.search(confirmed):
            raise RestoreError('The node did not accept the timed commit of the saved configuration.')
        return {'diff': diff, 'no_op': no_op, 'confirm_minutes': int(confirm_minutes),
                'handle': {'session': name}}
    except RestoreError:
        _safe_abort(shell)
        raise


def confirm_shell(shell, handle, enable_password=''):
    """Confirm a pending timed commit over a fresh EosShell (cancels the auto-revert)."""
    reach_cli(shell, enable_password)
    # After a manager restart only the job's token may be known; the session is named after it.
    name = (handle or {}).get('session') or (handle or {}).get('token') or ''
    if not name:
        raise RestoreError('The manager no longer knows which change to confirm on this node.')
    pending = pending_shell(shell)
    if not pending:
        raise RestoreError('The change was already reverted or was never armed; there is '
                            'nothing to confirm.')
    if pending != name:
        raise RestoreError('A different pending change is waiting on this node; this '
                            'restore was not confirmed.')
    result = shell.run('configure session %s commit' % name, COMMIT_TIMEOUT)
    if REJECTED_LINE.search(result):
        raise RestoreError('The node did not confirm the commit; it will revert on its own.')
    saved = True
    save_out = shell.run('write memory', COMMIT_TIMEOUT)
    if REJECTED_LINE.search(save_out) or 'Copy completed successfully' not in save_out:
        saved = False
    return {'confirmed': True, 'saved': saved}


def compare(desired, actual):
    """(missing, extra) between two `show running-config` texts, hierarchy kept.

    Excluded: `!` comment lines (the capture's command/device banner and separators) and the final
    `end`. An order-sensitive block whose lines only changed order is reported as missing.
    """
    missing, extra = compare_indented(desired, actual)
    missing += ['(order) ' + name for name in ordered_blocks_differ(desired, actual, EOS_ORDERED)]
    return missing, extra


def persist_shell(shell, enable_password=''):
    """Save the running configuration as the startup configuration; True when EOS confirmed it."""
    reach_cli(shell, enable_password)
    out = shell.run('write memory', COMMIT_TIMEOUT)
    return not REJECTED_LINE.search(out) and 'Copy completed successfully' in out


def capture_shell(shell, enable_password=''):
    """Capture the running configuration for verification."""
    reach_cli(shell, enable_password)
    return shell.run('show running-config', LOAD_TIMEOUT)


def _safe_abort(shell):
    try:
        shell.run('abort', PROMPT_TIMEOUT)
    except RestoreError:
        pass


# --- live entry points: open a channel on a connected paramiko client ---------------

def _open(client):
    return open_shell(client, EosShell)


def apply_candidate(client, candidate, confirm_minutes=5, **kw):
    channel, shell = _open(client)
    try:
        return apply_shell(shell, candidate, confirm_minutes, **kw)
    finally:
        _close(channel)


def confirm(client, handle, **kw):
    channel, shell = _open(client)
    try:
        return confirm_shell(shell, handle, **kw)
    finally:
        _close(channel)


def pending(client, **kw):
    channel, shell = _open(client)
    try:
        reach_cli(shell, kw.get('enable_password', ''))
        return pending_shell(shell)
    finally:
        _close(channel)


def cleanup(client, **kw):
    channel, shell = _open(client)
    try:
        reach_cli(shell, kw.get('enable_password', ''))
        return cleanup_shell(shell)
    finally:
        _close(channel)


def persist(client, **kw):
    channel, shell = _open(client)
    try:
        return persist_shell(shell, kw.get('enable_password', ''))
    finally:
        _close(channel)


def capture(client, **kw):
    channel, shell = _open(client)
    try:
        return capture_shell(shell, **kw)
    finally:
        _close(channel)


_close = close_channel
