"""Stage, arm and confirm a network-design candidate on Arista EOS: the merge transaction of PROVISIONING.md §2.

The provisioning driver contract (every platform module provides it; :mod:`design_apply` knows no NOS command):

``SUPPORTED_KINDS``
    The containerlab kinds the driver serves.
``snapshot(client, **options) -> str``
    The running configuration in the platform's comparable text (``design_ownership.statements`` turns it
    into the ownership form).
``render_desired(client, candidate, **options) -> str``
    The candidate alone as the device renders it on an empty base, in the same text form; nothing is
    committed (EOS: a throwaway session on ``rollback clean-config``).
``stage(client, candidate, removals, name, confirm_minutes, arm, **options) -> dict``
    One transaction: open the session ``name``, enter the removal lines, merge the candidate, read the
    would-be configuration and the device's own diff; with ``arm`` False the session is aborted (a review),
    with ``arm`` True the timed recovery is armed (``commit timer``). Returns ``{'before', 'would_be',
    'diff', 'no_op', 'armed', 'handle'}``; raises :class:`restore_shell.RestoreError` when the node refused
    (nothing armed) and :class:`restore_shell.SessionLost` when the session died inside the transaction.
``confirm(client, handle, **options) -> dict``, ``pending(client, **options)``, ``cleanup(client, **options)``,
``persist``: as the restore drivers, on a *fresh* connection; ``cleanup`` aborts only this driver's own
orphaned sessions (``clabdsg-`` + 8 hex digits) and never the restore's (``clabmgr-``) or anybody else's.

Device output never leaves this module unscrubbed: callers get controlled messages and texts that they
redact before display or logging.
"""
import re
import secrets
import time

from .restore_eos import (COMMIT_TIMEOUT, CONFIG_PROMPT, LOAD_TIMEOUT, PENDING_SESSION, REJECTED_LINE,
                          EosShell, _minutes_to_hms, capture_shell, pending_shell, reach_cli)
from .restore_shell import ANSI, PROMPT_TIMEOUT, RestoreError, close_channel, open_shell

SUPPORTED_KINDS = ('arista_ceos',)
NAME = re.compile(r'^clabdsg-[0-9a-f]{8}$')
# A row of the session table in state "pending" under this driver's own name shape.
ORPHAN = re.compile(r'(?m)^[*\s]\s*(clabdsg-[0-9a-f]{8})\s+pending\b')
HEADER = re.compile(r'^! Command: show session-configuration')


def session_name():
    return 'clabdsg-' + secrets.token_hex(4)


def _paste(shell, text):
    """`copy terminal: session-config` with `text`, ended by Ctrl-D; raises on any rejected line."""
    shell.send('copy terminal: session-config')
    time.sleep(0.5)
    body = text if text.endswith('\n') else text + '\n'
    shell.send_raw(body.encode())
    shell.send_raw(b'\x04')
    _, load_out = shell.expect([CONFIG_PROMPT], LOAD_TIMEOUT)
    load_text = ANSI.sub('', load_out).replace('\r', '')
    if REJECTED_LINE.search(load_text):
        # Line numbers only: the device's own words may quote configuration text.
        numbers = sorted({int(n) for n in re.findall(r'(?m)^% [^\n]*?\bline (\d+)', load_text)})[:10]
        where = (' at line ' + ', '.join(str(n) for n in numbers)) if numbers else ''
        raise RestoreError('The node rejected part of the generated configuration while loading it' + where + '.')


def _abort(shell):
    try:
        shell.run('abort', PROMPT_TIMEOUT)
    except Exception:
        pass


def snapshot_shell(shell, enable_password=''):
    return capture_shell(shell, enable_password)


def render_desired_shell(shell, candidate, enable_password=''):
    """The candidate on the clean base: (clean_base_text, rendered_text), both `show session-config` outputs."""
    reach_cli(shell, enable_password)
    name = session_name()
    opened = shell.run('configure session %s' % name, PROMPT_TIMEOUT)
    if REJECTED_LINE.search(opened):
        raise RestoreError('The node did not open a configuration session to render the generated configuration.')
    try:
        shell.run('rollback clean-config', LOAD_TIMEOUT)
        clean = shell.run('show session-config', LOAD_TIMEOUT)
        _paste(shell, candidate)
        rendered = shell.run('show session-config', LOAD_TIMEOUT)
        return clean, rendered
    finally:
        _abort(shell)


def stage_shell(shell, candidate, removals, name, confirm_minutes=5, arm=False, enable_password=''):
    """The merge transaction on an already-open EosShell (see the module docstring)."""
    if not NAME.match(name or ''):
        raise RestoreError('The design session name is not usable.')
    reach_cli(shell, enable_password)
    foreign = pending_shell(shell)
    if foreign:
        raise RestoreError('Another change on this node is already pending confirmation; the design was not applied.')
    cleanup_shell(shell)
    before = shell.run('show running-config', LOAD_TIMEOUT)
    opened = shell.run('configure session %s' % name, PROMPT_TIMEOUT)
    if REJECTED_LINE.search(opened):
        raise RestoreError('The node did not open a configuration session for the design.')
    try:
        if removals:
            _paste(shell, '\n'.join(removals) + '\n')
        _paste(shell, candidate)
        would_be = shell.run('show session-config', LOAD_TIMEOUT)
        diff = shell.run('show session-config diffs', LOAD_TIMEOUT)
        no_op = not diff.strip()
        if not arm or no_op:
            _abort(shell)
            return {'before': before, 'would_be': would_be, 'diff': diff, 'no_op': no_op, 'armed': False, 'handle': {'session': name}}
        # EOS has no lock: a concurrent commit between `before` and now would be reverted by ours.
        again = shell.run('show running-config', LOAD_TIMEOUT)
        if _comparable(again) != _comparable(before):
            raise RestoreError('The running configuration changed while the design was being staged; nothing was applied.')
        confirmed = shell.run('commit timer %s' % _minutes_to_hms(confirm_minutes), COMMIT_TIMEOUT)
        if REJECTED_LINE.search(confirmed):
            raise RestoreError('The node did not accept the timed commit of the design.')
        return {'before': before, 'would_be': would_be, 'diff': diff, 'no_op': False, 'armed': True,
                'handle': {'session': name}, 'confirm_minutes': int(confirm_minutes)}
    except RestoreError:
        _abort(shell)
        raise


def _comparable(text):
    return [line for line in (text or '').splitlines() if line.strip() and not line.startswith('!')]


def confirm_shell(shell, handle, enable_password=''):
    """Confirm this driver's pending timed commit over a fresh shell, then save; never another name's."""
    reach_cli(shell, enable_password)
    name = (handle or {}).get('session') or ''
    if not NAME.match(name):
        raise RestoreError('The manager no longer knows which design change to confirm on this node.')
    pending = pending_shell(shell)
    if not pending:
        raise RestoreError('The change was already reverted or was never armed; there is nothing to confirm.')
    if pending != name:
        raise RestoreError('A different pending change is waiting on this node; the design was not confirmed.')
    result = shell.run('configure session %s commit' % name, COMMIT_TIMEOUT)
    if REJECTED_LINE.search(result):
        raise RestoreError('The node did not confirm the commit; it will revert on its own.')
    save_out = shell.run('write memory', COMMIT_TIMEOUT)
    saved = not REJECTED_LINE.search(save_out) and 'Copy completed successfully' in save_out
    return {'confirmed': True, 'saved': saved}


def cleanup_shell(shell):
    """Abort this driver's own abandoned sessions (state pending, name `clabdsg-…`); returns their names."""
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


# --- live entry points: open a channel on a connected paramiko client -----------------------------------

def _open(client):
    return open_shell(client, EosShell)


def _with_shell(client, work, **kw):
    channel, shell = _open(client)
    try:
        return work(shell, **kw)
    finally:
        close_channel(channel)


def snapshot(client, **kw):
    return _with_shell(client, lambda shell, **o: snapshot_shell(shell, o.get('enable_password', '')), **kw)


def render_desired(client, candidate, **kw):
    return _with_shell(client, lambda shell, **o: render_desired_shell(shell, candidate, o.get('enable_password', '')), **kw)


def stage(client, candidate, removals, name, confirm_minutes=5, arm=False, **kw):
    return _with_shell(client, lambda shell, **o: stage_shell(shell, candidate, removals, name, confirm_minutes, arm, o.get('enable_password', '')), **kw)


def confirm(client, handle, **kw):
    return _with_shell(client, lambda shell, **o: confirm_shell(shell, handle, o.get('enable_password', '')), **kw)


def pending(client, **kw):
    def work(shell, **o):
        reach_cli(shell, o.get('enable_password', ''))
        return pending_shell(shell)
    return _with_shell(client, work, **kw)


def cleanup(client, **kw):
    def work(shell, **o):
        reach_cli(shell, o.get('enable_password', ''))
        return cleanup_shell(shell)
    return _with_shell(client, work, **kw)


def persist(client, **kw):
    def work(shell, **o):
        reach_cli(shell, o.get('enable_password', ''))
        out = shell.run('write memory', COMMIT_TIMEOUT)
        return not REJECTED_LINE.search(out) and 'Copy completed successfully' in out
    return _with_shell(client, work, **kw)


def options(creds):
    return {'enable_password': (creds or {}).get('enable_password') or ''}
