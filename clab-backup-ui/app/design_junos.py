"""Stage, arm and confirm a network-design candidate on Junos (cJunosEvolved, vJunos-switch): the merge
transaction of PROVISIONING.md §2, with the provisioning driver contract documented in :mod:`design_eos`.

What differs from EOS, all proven live on the lab images (docs/netlab-integration/evidence/junos-transaction-facts.md):

* the transaction is an exclusive candidate (`configure exclusive`, refused while anybody has uncommitted edits in
  the shared candidate or a confirmed commit is waiting); the running configuration cannot change under it, so
  `before` taken at the operational prompt is compared once more inside the lock and nothing else is re-read;
* removals are `delete <path>` lines entered one by one, then `load merge terminal` with the hierarchical candidate;
* the would-be configuration is `show | display set` inside the candidate (the operational
  `show configuration | display set` renders the same statements: verified on both images), and its hierarchical
  `show` names the real blocks (`design_ownership.junos_blocks`): only those become created ancestors;
* the desired set is the candidate alone: `configure private` + `load override terminal` + `show | display set` +
  `rollback 0`, never committed, so the missing `root-authentication` of a fragment does not matter;
* `commit check` runs only when arming (it would confirm anybody's pending change), then `commit confirmed <min>
  comment <name>`; `show system commit` entry 0 carries the name while `rollback pending` is shown; a fresh
  connection confirms with `commit check` (:func:`restore_junos.confirm_shell`), which never commits the shared
  candidate; the commit itself is persistent;
* there is nothing to clean up: an exclusive or private candidate dies with its session.
"""
import re
import secrets
import time

from .design_eos import NOT_REVIEWED   # the driver contract's words for a refused would-be configuration
from .restore_junos import (CHECK_OK, COMMIT_FAILED, COMMIT_OK, COMMIT_TIMEOUT, CONF, LOAD_ERROR, LOAD_TIMEOUT, OPER,
                            JunosShell, capture_shell, foreign_edits, leave_config, pending_commit, reach_cli, unchanged)
from .restore_junos import confirm_shell as _restore_confirm_shell
from .restore_shell import ANSI, PROMPT_TIMEOUT, RestoreError, SessionLost, close_channel, open_shell

SUPPORTED_KINDS = ('juniper_cjunosevolved', 'juniper_vjunosswitch')
NAME = re.compile(r'^clabdsg-[0-9a-f]{8}$')
FOREIGN_EDITS = ('Someone has uncommitted configuration changes open on this node. The design was not applied, '
                 'so their work is not lost.')
DELETE = re.compile(r'^delete [^\n;{}]+$')


def session_name():
    return 'clabdsg-' + secrets.token_hex(4)


def _load(shell, command, text):
    """`load merge|override terminal` with `text`, ended by Ctrl-D; raises on any error line."""
    shell.send(command)
    time.sleep(1.5)   # the device prints "[Type ^D at a new line to end input]"
    body = text if text.endswith('\n') else text + '\n'
    shell.send_raw(body.encode())
    shell.send_raw(b'\x04')
    _, load_out = shell.expect([CONF], LOAD_TIMEOUT)
    load_text = ANSI.sub('', load_out).replace('\r', '')
    if LOAD_ERROR.search(load_text) or 'load complete' not in load_text:
        raise RestoreError('The node rejected part of the generated configuration while loading it.')


def _delete(shell, lines):
    """The removal statements, one command each; a rejected one names its position only."""
    for index, line in enumerate(lines, 1):
        if not DELETE.match(line.strip()):
            raise RestoreError('Removal %d is not a delete statement; nothing was applied.' % index)
        out = shell.run(line.strip(), PROMPT_TIMEOUT)
        if LOAD_ERROR.search(ANSI.sub('', out)):
            raise RestoreError('The node rejected removal %d of %d; nothing was applied.' % (index, len(lines)))


# The device's `error:` lines of a failed `commit check`, classified into the manager's fixed words: a job message
# never carries device or configuration text (CLAUDE.md), so the reason is named by class, never quoted.
CHECK_PHRASES = (
    (re.compile(r'bridge domains?/vlans|vlan', re.I), 'the device refused the VLAN or bridge-domain part of it'),
    (re.compile(r'license', re.I), 'a licensed feature is not available on this image'),
    (re.compile(r'mandatory|missing', re.I), 'a statement it needs is missing'),
    (re.compile(r'not (?:supported|valid)|unsupported|invalid', re.I), 'a statement is not supported on this image'),
    (re.compile(r'refer|reference|not defined|undefined', re.I), 'it refers to something the device does not have'),
)
GENERIC_CHECK = 'the device refused it on semantic grounds'


def _check_reasons(text):
    """Why `commit check` refused, in the manager's fixed words (at most three classes), or ''."""
    phrases = []
    for line in (text or '').splitlines():
        if not re.match(r'^\s*(?:error|\[edit[^\]]*\]\s*error)\s*:', line, re.I) and 'error' not in line.lower(): continue
        if 'warning' in line.lower() and 'error' not in line.lower(): continue
        phrase = next((words for pattern, words in CHECK_PHRASES if pattern.search(line)), GENERIC_CHECK)
        if phrase not in phrases: phrases.append(phrase)
    return (' The device said, in the manager\'s words: ' + '; '.join(phrases[:3]) + '.') if phrases else ''


def _enter(shell, mode):
    shell.send('configure ' + mode)
    index, _ = shell.expect([CONF, OPER], PROMPT_TIMEOUT)
    if index == 1:
        raise RestoreError('The node did not grant %s configuration access; someone else is editing it.' % mode)


def _abort(shell):
    try:
        shell.run('rollback 0', PROMPT_TIMEOUT)
        leave_config(shell)
    except RestoreError:
        pass


def _statements(text):
    """Comparable lines of a display-set text (the ownership form does the same; kept local to avoid a cycle)."""
    return {l.strip() for l in (text or '').splitlines() if l.strip().startswith('set ') and not l.strip().startswith('set version ')}


def snapshot_shell(shell):
    return capture_shell(shell, display_set=True)


def render_desired_shell(shell, candidate):
    """(clean_base, rendered): the candidate alone in set form, from a private candidate that is thrown away."""
    reach_cli(shell)
    _enter(shell, 'private')
    try:
        _load(shell, 'load override terminal', candidate)
        rendered = shell.run('show | display set', LOAD_TIMEOUT)
        return '', rendered
    finally:
        _abort(shell)


def stage_shell(shell, candidate, removals, name, confirm_minutes=5, arm=False, accept=None):
    """The merge transaction on an already-open JunosShell (see the module docstring); `accept` as in
    :mod:`design_eos`: asked before `commit check`, so a refused would-be configuration is rolled back unarmed."""
    if not NAME.match(name or ''):
        raise RestoreError('The design session name is not usable.')
    reach_cli(shell)
    if pending_commit(shell):
        raise RestoreError('Another change on this node is already pending confirmation; the design was not applied.')
    before = shell.run('show configuration | display set | no-more', LOAD_TIMEOUT)
    if foreign_edits(shell):
        raise RestoreError(FOREIGN_EDITS)
    _enter(shell, 'exclusive')
    try:
        inside = shell.run('show | display set', LOAD_TIMEOUT)
        if _statements(inside) != _statements(before):
            raise RestoreError('The running configuration changed while the design was being staged; nothing was applied.')
        _delete(shell, removals or [])
        _load(shell, 'load merge terminal', candidate)
        would_be = shell.run('show | display set', LOAD_TIMEOUT)
        hierarchy = shell.run('show', LOAD_TIMEOUT)   # the device's own blocks: the containers a `delete` may name
        diff = shell.run('show | compare', LOAD_TIMEOUT)
        no_op = unchanged(diff)
        if not arm or no_op:
            _abort(shell)
            return {'before': before, 'would_be': would_be, 'diff': diff, 'no_op': no_op, 'armed': False, 'handle': {'session': name}, 'hierarchy': hierarchy}
        if accept is not None and not accept(would_be):
            raise RestoreError(NOT_REVIEWED)
        check = shell.run('commit check', COMMIT_TIMEOUT)
        if CHECK_OK not in check:
            raise RestoreError('The node failed the configuration check for the generated configuration; nothing was applied.' + _check_reasons(check))
        confirmed = shell.run('commit confirmed %d comment %s' % (int(confirm_minutes), name), COMMIT_TIMEOUT)
        if COMMIT_OK not in confirmed:
            raise RestoreError('The node did not accept the timed commit of the design; nothing was applied.')
        if COMMIT_FAILED.search(confirmed):
            raise SessionLost('The node reported both a completed and a failed commit.')
        try:
            leave_config(shell)
        except RestoreError:
            pass
        return {'before': before, 'would_be': would_be, 'diff': diff, 'no_op': False, 'armed': True,
                'handle': {'session': name}, 'confirm_minutes': int(confirm_minutes), 'hierarchy': hierarchy}
    except SessionLost:
        raise
    except RestoreError:
        _abort(shell)
        raise


def confirm_shell(shell, handle):
    name = (handle or {}).get('session') or ''
    if not NAME.match(name):
        raise RestoreError('The manager no longer knows which design change to confirm on this node.')
    result = _restore_confirm_shell(shell, {'token': name})
    return {'confirmed': bool(result.get('confirmed')), 'saved': True}


def pending_shell(shell):
    reach_cli(shell)
    return pending_commit(shell)


# --- live entry points: open a channel on a connected paramiko client -----------------------------------

def _with_shell(client, work):
    channel, shell = open_shell(client, JunosShell)
    try:
        return work(shell)
    finally:
        close_channel(channel)


def snapshot(client, **kw):
    return _with_shell(client, snapshot_shell)


def render_desired(client, candidate, **kw):
    return _with_shell(client, lambda shell: render_desired_shell(shell, candidate))


def stage(client, candidate, removals, name, confirm_minutes=5, arm=False, accept=None, **kw):
    return _with_shell(client, lambda shell: stage_shell(shell, candidate, removals, name, confirm_minutes, arm, accept))


def confirm(client, handle, **kw):
    return _with_shell(client, lambda shell: confirm_shell(shell, handle))


def pending(client, **kw):
    return _with_shell(client, pending_shell)


def cleanup(client, **kw):
    """Nothing to do: an exclusive or private candidate dies with its session."""
    return []


def persist(client, **kw):
    return True   # a Junos commit is persistent


def options(creds):
    return {}
