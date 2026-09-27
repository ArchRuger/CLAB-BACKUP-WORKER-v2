"""Stage, arm and confirm a network-design candidate on Cisco IOS XR (XRv9k): the merge transaction of
PROVISIONING.md §2, with the provisioning driver contract documented in :mod:`design_eos`.

What differs, following the restore driver's live-proven facts (:mod:`restore_iosxr`, the module docstring and
docs/multi-platform-restore/evidence/xr-live-facts.md):

* the transaction is `configure exclusive`; refused while another session holds a lock, an ordinary configuration
  session is open, or a commit-confirmed trial is outstanding;
* removals (indented `no …` lines under their parents) and the candidate are entered line by line with
  :func:`restore_iosxr._paste`, which tracks the real prompt; any `% ` rejection aborts;
* the would-be configuration is `show configuration merge` (running-config form); the display diff is the target
  buffer (`show configuration`): `show configuration changes diff` misleads for a merge;
* the desired set is the candidate alone in a plain `configure` session: the target buffer holds exactly the
  entered lines, then `abort`;
* arming is `commit confirmed minutes <N>` on a session that is **kept open**: IOS XR confirms a trial only from
  the session that armed it. The client entry point registers the connection in ``_HELD`` under the design's
  session name and returns ``held: True`` so the service does not close it; :func:`confirm` reaches a fresh
  connection's CLI first (management proven) and then sends `commit` on the held channel; a trial nobody can
  confirm any more (a manager restart) is undone by the device itself at the timer, and the service waits for
  that before reading the node back. The commit is persistent.
"""
import re
import secrets
import threading

from .restore_iosxr import (COMMIT_TIMEOUT, CONFIG_PROMPT, LOAD_TIMEOUT, PROMPT, TRIAL_CLIENT, IosXrShell, _body_lines,
                            _is_rejected, _last_commit_was_rollback, _leave_held_configuration, _paste, _safe_abort,
                            _send, capture_shell, reach_cli, session_conflict, strip_generated_header)
from .restore_shell import PROMPT_TIMEOUT, RestoreError, SessionLost, close_channel, open_shell

SUPPORTED_KINDS = ('cisco_xrv9k',)
NAME = re.compile(r'^clabdsg-[0-9a-f]{8}$')
HOLDS_SESSION = True
NO_CHANGES = 'No configuration changes to commit'
_HELD = {}
_HELD_LOCK = threading.Lock()


def session_name():
    return 'clabdsg-' + secrets.token_hex(4)


def _peer(client):
    try:
        return client.get_transport().getpeername()
    except Exception:
        return None


def _comparable(text):
    return [l.rstrip() for l in strip_generated_header(text or '').splitlines() if l.strip() and not l.lstrip().startswith('!') and l.strip() != 'end']


def _enter(shell, mode):
    opened, prompt = _send(shell, 'configure' + (' ' + mode if mode else ''), LOAD_TIMEOUT)
    if _is_rejected(opened) or not CONFIG_PROMPT.match(prompt):
        raise RestoreError('The node did not open %sconfiguration session for the design.' % ('an exclusive ' if mode else 'a '))
    return prompt


def _enter_lines(shell, lines, prompt, what):
    rejections, _stack, prompt = _paste(shell, lines, prompt)
    if rejections:
        raise RestoreError('The node rejected %s while loading it (%d line(s)).' % (what, len(rejections)))
    if not CONFIG_PROMPT.match(prompt):
        raise RestoreError('Lost track of the configuration session while loading the design.')
    return prompt


FAILED_REASON = re.compile(r'^!!%\s*(.+)$')
# The device's `!!%` reasons (`show configuration failed`) mapped to fixed words: a job message never carries device or
# configuration text (CLAUDE.md, persistent logs and job messages), so the reason is classified, never quoted.
FAILURE_PHRASES = (
    (re.compile(r'BGP is still in process of unconfiguration', re.I), 'BGP was still being removed: change the AS in two applies (drop BGP first, then add it with the new AS)'),
    (re.compile(r'not defined|does not exist|has not been configured|undefined', re.I), 'it refers to an object the device does not have yet'),
    (re.compile(r'in use|cannot be (?:deleted|removed)|still referenced', re.I), 'something it removes is still in use'),
)
GENERIC_FAILURE = 'the device refused the commit on semantic grounds'


def _failure_reasons(shell):
    """Why the device refused the commit, in the manager's fixed words (at most three), or ''."""
    try:
        text = shell.run('show configuration failed', PROMPT_TIMEOUT)
    except Exception:
        return ''
    phrases = []
    for line in text.splitlines():
        match = FAILED_REASON.match(line.strip())
        if not match: continue
        phrase = next((words for pattern, words in FAILURE_PHRASES if pattern.search(match.group(1))), GENERIC_FAILURE)
        if phrase not in phrases: phrases.append(phrase)
    return (' The device said, in the manager\'s words: ' + '; '.join(phrases[:3]) + '.') if phrases else ''


def snapshot_shell(shell):
    return capture_shell(shell)


def render_desired_shell(shell, candidate):
    """(clean_base, rendered): the candidate alone as the target buffer of a plain session renders it."""
    reach_cli(shell)
    if session_conflict(shell) == 'lock':
        raise RestoreError('Another session holds an exclusive configuration lock on this node; the design was not reviewed.')
    prompt = _enter(shell, '')
    try:
        _enter_lines(shell, _body_lines(candidate), prompt, 'the generated configuration')
        rendered = shell.run('show configuration', LOAD_TIMEOUT)
        return '', strip_generated_header(rendered)
    finally:
        _safe_abort(shell)


def stage_shell(shell, candidate, removals, name, confirm_minutes=5, arm=False):
    """The merge transaction on an already-open IosXrShell (see the module docstring). With `arm` the session is
    left open in configuration mode and the caller keeps it (``held``)."""
    if not NAME.match(name or ''):
        raise RestoreError('The design session name is not usable.')
    reach_cli(shell)
    conflict = session_conflict(shell)
    if conflict == 'trial':
        raise RestoreError('Another change on this node is already pending confirmation; the design was not applied.')
    if conflict == 'lock':
        raise RestoreError('Another session holds an exclusive configuration lock on this node; the design was not applied.')
    if conflict == 'plain':
        raise RestoreError("A configuration session is open on this node; the design was not applied so that nobody's work is lost.")
    before = strip_generated_header(shell.run('show running-config', LOAD_TIMEOUT))   # the CLI is reached already: no second reach_cli
    prompt = _enter(shell, 'exclusive')
    try:
        # One paste for the removals and the candidate: the depth tracking of `_paste` must see both, or a
        # candidate line typed after a removal that ended inside a submode would land in that submode.
        removal_lines = [line.strip() for line in (removals or [])]
        rejections, _stack, prompt = _paste(shell, list(removals or []) + _body_lines(candidate), prompt)
        if rejections:
            what = 'the removals' if any(line in removal_lines for line, _ in rejections) else 'the generated configuration'
            raise RestoreError('The node rejected %s while loading it (%d line(s)).' % (what, len(rejections)))
        if not CONFIG_PROMPT.match(prompt):
            raise RestoreError('Lost track of the configuration session while loading the design.')
        would_be = strip_generated_header(shell.run('show configuration merge', LOAD_TIMEOUT))
        diff = strip_generated_header(shell.run('show configuration', LOAD_TIMEOUT))
        no_op = _comparable(would_be) == _comparable(before)
        if not arm or no_op:
            _safe_abort(shell)
            return {'before': before, 'would_be': would_be, 'diff': diff, 'no_op': no_op, 'armed': False, 'handle': {'session': name}}
        out = shell.run('commit confirmed minutes %d' % int(confirm_minutes), COMMIT_TIMEOUT)
        if NO_CHANGES in out:
            _safe_abort(shell)
            return {'before': before, 'would_be': would_be, 'diff': diff, 'no_op': True, 'armed': False, 'handle': {'session': name}}
        if _is_rejected(out):
            raise RestoreError('The node did not accept the timed commit of the design; nothing was applied.' + _failure_reasons(shell))
    except RestoreError:
        _safe_abort(shell)
        raise
    # Positive evidence the trial is armed, from this session: the sessions table lists the commit-confirm client.
    evidence = shell.run('do show configuration sessions detail', PROMPT_TIMEOUT)
    if not TRIAL_CLIENT.search(evidence):
        raise SessionLost('The node did not show the design as armed after the commit; reading the node back.')
    return {'before': before, 'would_be': would_be, 'diff': diff, 'no_op': False, 'armed': True, 'held': True,
            'handle': {'session': name}, 'confirm_minutes': int(confirm_minutes)}


# --- live entry points: open a channel on a connected paramiko client -----------------------------------

def _with_shell(client, work):
    channel, shell = open_shell(client, IosXrShell)
    try:
        return work(shell)
    finally:
        close_channel(channel)


def snapshot(client, **kw):
    return _with_shell(client, snapshot_shell)


def render_desired(client, candidate, **kw):
    return _with_shell(client, lambda shell: render_desired_shell(shell, candidate))


def stage(client, candidate, removals, name, confirm_minutes=5, arm=False, **kw):
    channel, shell = open_shell(client, IosXrShell)
    try:
        result = stage_shell(shell, candidate, removals, name, confirm_minutes, arm)
    except Exception:
        close_channel(channel)
        raise
    if not result.get('held'):
        close_channel(channel)
        return result
    with _HELD_LOCK:
        stale = _HELD.pop(name, None)
    if stale: _drop(stale)
    with _HELD_LOCK:
        _HELD[name] = {'client': client, 'channel': channel, 'shell': shell, 'peer': _peer(client)}
    return result


def _drop(held, already_left=False):
    if not already_left:
        _leave_held_configuration(held['shell'])
    close_channel(held['channel'])
    try:
        held['client'].close()
    except Exception:
        pass


def release(name):
    """Close a held session without confirming; the device undoes its trial at once. Never raises."""
    with _HELD_LOCK:
        held = _HELD.pop(name, None)
    if held:
        try: _drop(held)
        except Exception: pass


def confirm(client, handle, **kw):
    """`client` is a fresh connection (management proven); the confirming `commit` goes on the held channel."""
    name = (handle or {}).get('session') or ''
    if not NAME.match(name):
        raise RestoreError('The manager no longer knows which design change to confirm on this node.')
    channel, shell = open_shell(client, IosXrShell)
    try:
        reach_cli(shell)
        with _HELD_LOCK:
            held = _HELD.get(name)
        if not held:
            if _last_commit_was_rollback(shell):
                raise RestoreError('The session that armed this change is gone, and the node has already undone the change on its own.')
            raise RestoreError('The session that armed this change is gone; if it was never confirmed the node undoes the change by itself.')
        try:
            result = held['shell'].run('commit', COMMIT_TIMEOUT)
        except Exception:
            release(name)
            raise
        if 'Confirming commit for trial session' not in result:
            release(name)
            raise RestoreError('The node did not confirm the change from the session that armed it, and closing that session has undone it.')
        try:
            held['shell'].run('end', PROMPT_TIMEOUT)
        finally:
            with _HELD_LOCK: _HELD.pop(name, None)
            _drop(held, already_left=True)
        if session_conflict(shell) == 'trial':
            raise RestoreError('The node still shows a change waiting for confirmation after confirming; it may be undone automatically.')
        return {'confirmed': True, 'saved': True}
    finally:
        close_channel(channel)


def pending(client, session=None, **kw):
    """'' when no trial is outstanding; this driver's session name when the trial is one this process holds for
    the same node (the caller's own `session` first, so a stale entry for the node cannot shadow it); True when a
    trial is outstanding that this process cannot confirm."""
    def work(shell):
        reach_cli(shell)
        if session_conflict(shell) != 'trial':
            return ''
        peer = _peer(client)
        with _HELD_LOCK:
            entries = list(_HELD.items())
        for name, held in entries:
            if name == session and peer is not None and held.get('peer') == peer:
                return name
        for name, held in entries:
            if peer is not None and held.get('peer') == peer:
                return name
        return True
    return _with_shell(client, work)


def cleanup(client, **kw):
    """Nothing to clean from a fresh connection: a dropped session's row disappears by itself."""
    return []


def persist(client, **kw):
    return True   # an IOS XR commit is persistent


def options(creds):
    return {}
