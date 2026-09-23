"""Replace a whole-device Cisco IOS XR running-configuration over the interactive CLI.

The manager restores a saved *desired state* onto a running IOS XR node without a reboot or a
containerlab redeploy. IOS XR's own ``commit replace confirmed`` gives, in one native command,
both true whole-configuration replacement (unlike a plain ``commit``, which only merges) and a
timed automatic rollback if nobody confirms it -- the same "load, review, activate, auto-revert"
shape the Junos and EOS drivers use, with platform-specific twists proven live against a real
XRv9k 24.3.1 (see docs/multi-platform-restore/evidence/xr-live-facts.md for the commands that
proved each one):

1. Whole-device replacement is one command: ``configure exclusive`` (locks the whole
   configuration namespace against any other session -- ``show configuration sessions`` shows the
   lock, and a second session cannot enter exclusive mode either) then a line-by-line paste of the
   candidate, then ``commit replace confirmed minutes <N>``. Pasting a hierarchical
   ``show running-config`` back in is *not* a matter of typing every line: IOS XR's ``!`` markers
   are comments, not an "exit one level" signal, so this module tracks the real prompt after every
   line and issues an explicit ``exit`` only when the next line's indentation needs one level (or
   more) popped -- never ``root``, which this NOS refuses inside a prefix-set/route-policy/if-block.
   Those three "policy object" constructs must be closed with their own literal token
   (``end-set``, ``end-policy``, ``endif``) sent *while still inside* the block, not by exiting
   first and sending it afterwards (that produces a real rejection). The paste self-corrects: any
   time the observed prompt is the bare ``(config)#`` the tracked submode stack is reset to match,
   and ``exit`` is never sent while that stack is already empty (never dropping to EXEC mid-paste);
   a stray "Uncommitted changes...exit?" prompt (seen live leaving a route-policy) is answered
   ``cancel`` and raised as a controlled failure rather than answered blind.
2. The replace warning ("This commit will replace or remove the entire running configuration...
   Do you wish to proceed? [no]:") is not a CLI prompt Shell.run's prompt regex ever matches, so
   it is answered with a dedicated ``expect``/raw write, not folded into the normal command dialog.
3. **The confirming commit is scoped to the CLI session that armed it.** A bare ``commit`` (or
   ``commit confirmed`` again) issued from a genuinely different, reconnected SSH session never
   confirms someone else's pending replace: IOS XR answers "No configuration changes to commit."
   (indistinguishable by wording from a real no-op) and, while that trial is outstanding, refuses
   *any* other session's commit outright ("Cannot commit because there is an unexpired
   trial/rollback session") and refuses a second ``configure exclusive`` too.

   Because of this, :data:`HOLDS_SESSION` is set: :func:`apply_candidate` never confirms inline.
   It arms the trial, checks for positive evidence it took (the target configuration buffer -- and
   therefore ``show configuration changes diff`` -- is reset the moment a commit is accepted, so a
   diff that still shows the *entire* running configuration as removable proves the commit was
   consumed; proven live, see the module evidence), and then stops, leaving the channel open and in
   configuration mode. The manager keeps that connection (keyed by the job's token, together with
   the node's address) in ``_HELD`` until :func:`confirm` or :func:`release` is called; the service
   never closes it in between. A fresh connection is only ever released once its own confirming
   attempt has actually been made, success or failure: one that never reaches its CLI leaves the
   held session untouched, so a later retry can still confirm it (proven live, see the module
   evidence). :func:`confirm` receives a **fresh** connection -- proof management survived --
   reaches its CLI first, then sends the confirming ``commit`` on the *held* channel: only that
   channel's identity can make it stick. :func:`release` leaves configuration mode on the held
   channel first, best-effort, before closing it: a session with nothing outstanding is simply gone
   from ``show configuration sessions`` at once, and a session whose trial is still outstanding is
   answered with an immediate rollback rather than left open for the several minutes a
   merely-dropped connection leaves its row for -- proven live, see the module evidence and
   :func:`release`'s own docstring.

IOS XR persists a confirmed commit immediately (no EOS-style separate "write memory"): once the
confirming ``commit`` succeeds the configuration survives a reload by itself.

Device output never leaves this module unscrubbed: callers get controlled messages and the
``show configuration changes diff`` diff, which they redact before display or logging.
"""
import re
import threading

from .restore_compare import compare_indented, ordered_blocks_differ
from .restore_shell import PROMPT_TIMEOUT, RestoreError, SessionLost, Shell, close_channel, open_shell

PROMPT = re.compile(r'^RP/\d+/\w+/CPU\d+:[\w.\-]+(?:\([\w.\-]+\))?#\s*$', re.M)
CONFIG_PROMPT = re.compile(r'^RP/\d+/\w+/CPU\d+:[\w.\-]+\([\w.\-]+\)#\s*$', re.M)
BARE_CONFIG_PROMPT = re.compile(r'^RP/\d+/\w+/CPU\d+:[\w.\-]+\(config\)#\s*$')
REPLACE_WARNING = re.compile(r'Do you wish to proceed\?\s*\[no\]:\s*$')
UNCOMMITTED_EXIT = re.compile(r'Uncommitted changes found, commit them before '
                              r'exiting\(yes/no/cancel\)\?\s*\[cancel\]:\s*$')
# The raw, non-CLI prompt IOS XR raises on 'end' (or 'exit') while a commit-confirmed trial armed
# by THIS session is still outstanding (proven live: docs/multi-platform-restore/evidence/
# xr-live-facts.md, the release()/end section). Answering 'yes' rolls the change back immediately;
# 'no' leaves it exactly as an unanswered raw prompt would -- see release()/_leave_held_configuration.
EXIT_ROLLBACK_WARNING = re.compile(r"Do you wish to exit\?\s*\[no\]:\s*$")
REJECTED_LINE = re.compile(r'^%\s')
SESSION_ENTRY = re.compile(r'^\s*\d+\)\s+Session:', re.M)
TRIAL_CLIENT = re.compile(r'Client:\s*commit-confirm')
LOCK_RESERVED = re.compile(r'Lock:\s*Reserved')
COMMIT_ROW = re.compile(r'^\d+\s+\d+\s')
TIMESTAMP_LINE = re.compile(r'^\w{3}\s+\w{3}\s+\d{1,2}\s+\d\d:\d\d:\d\d(?:\.\d+)?\s+\S+\s*$')
BUILDING_LINE = re.compile(r'^!!\s*Building configuration')
DIFF_CHANGE = re.compile(r'^[+#-]\s')
BANNER_LINE = re.compile(r'^banner\b', re.M)

CLOSERS = {'end-set', 'end-policy', 'endif'}

LOAD_TIMEOUT = 90
COMMIT_TIMEOUT = 180
# How much of the caller's own confirm_minutes window apply_shell() reserves for the round trip
# back to the caller and its reconnect, when bounding how long it will wait for the arming commit
# to answer (see _arm_timeout / F7): a commit that took nearly the whole window to answer would
# otherwise report "armed" with the trial already expired or about to expire.
ARM_MARGIN = 30
SUPPORTED_KINDS = ('cisco_xrv9k',)
RESTORE_FORMAT = 'iosxr-running-config'
HOLDS_SESSION = True

REQUIRED_BANNER = '!! IOS XR Configuration'
HEADER_SCAN_LINES = 6

# An order-sensitive block: same lines, different order, still a real difference. Mirrors
# restore_eos.EOS_ORDERED / restore_compare.EOS_ORDERED for the IOS XR statement families that are
# evaluated top-to-bottom (a route-policy's clauses, an ACL's entries).
IOSXR_ORDERED = re.compile(r'^route-policy |^ipv4 access-list |^ipv6 access-list ')

# Sessions this process is holding open past a successful apply_candidate(), keyed by the job
# token: {'client': paramiko.SSHClient, 'channel': ..., 'shell': IosXrShell, 'peer': (ip, port)}.
# A manager restart loses this table; the node's own timer then rolls back an unconfirmed change.
# Several nodes are restored at the same time, so every read or change of the table itself happens under
# _HELD_LOCK; no device I/O ever runs while it is held.
_HELD = {}
_HELD_LOCK = threading.Lock()


def supports_restore(platform):
    return platform in SUPPORTED_KINDS


class IosXrShell(Shell):
    any_prompt = PROMPT


def validate_candidate(text):
    """Refuse an obviously wrong, truncated or unsupported candidate before touching the device."""
    if not text.strip():
        raise RestoreError('The saved configuration is empty.')
    header_lines = text.splitlines()[:HEADER_SCAN_LINES]
    if not any(REQUIRED_BANNER in line for line in header_lines):
        raise RestoreError('The saved configuration does not look like an IOS XR running-configuration.')
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines or lines[-1].strip() != 'end':
        raise RestoreError('The saved configuration looks truncated; it does not end with "end".')
    if BANNER_LINE.search(text):
        raise RestoreError('The saved configuration defines a banner; this restore driver cannot '
                           'paste banner delimiter text safely yet.')


def reach_cli(shell):
    """Land on the exec prompt (the containerlab login is already privileged) and disable paging."""
    shell.expect([PROMPT], PROMPT_TIMEOUT)
    shell.run('terminal length 0', PROMPT_TIMEOUT)
    shell.run('terminal width 512', PROMPT_TIMEOUT)


def session_conflict(shell):
    """What, if anything, another session already holds: 'trial' (a commit-confirmed trial is
    outstanding -- 'show configuration sessions detail' lists an extra 'Client: commit-confirm'
    entry while its rollback timer runs), 'lock' (a plain 'Lock: Reserved' exclusive session, no
    trial), 'plain' (an ordinary open configuration session, no lock, no trial) or '' (nothing).
    Must be called from the operational (EXEC) prompt -- this command is invalid in configuration
    mode. Proven live: docs/multi-platform-restore/evidence/xr-live-facts.md.
    """
    detail = shell.run('show configuration sessions detail', PROMPT_TIMEOUT)
    if not SESSION_ENTRY.search(detail):
        return ''
    if TRIAL_CLIENT.search(detail):
        return 'trial'
    if LOCK_RESERVED.search(detail):
        return 'lock'
    return 'plain'


def strip_generated_header(text):
    """Drop the leading timestamp line and 'Building configuration...' banner IOS XR always prints
    above 'show running-config' output; every other '!' banner line is left for validate_candidate
    and for the paste step (which already skips every '!' line as a comment)."""
    out, dropped_timestamp = [], False
    for line in (text or '').splitlines():
        stripped = line.strip()
        if not dropped_timestamp and TIMESTAMP_LINE.match(stripped):
            dropped_timestamp = True
            continue
        if BUILDING_LINE.match(stripped):
            continue
        out.append(line)
    return '\n'.join(out)


def _body_lines(candidate):
    """The candidate as pasteable lines: generated header dropped, trailing 'end' excluded (the
    driver leaves and closes the exclusive session itself, it never types 'end')."""
    lines = strip_generated_header(candidate).splitlines()
    while lines and not lines[-1].strip():
        lines.pop()
    if lines and lines[-1].strip() == 'end':
        lines.pop()
    return lines


def _is_rejected(text):
    """A real CLI rejection, judged per physical line: a line starting '% ' that does not itself
    contain 'WARNING' is a rejection, even when another line in the same output is a harmless
    '% WARNING: ... Use abort to cancel' overwrite notice (expected when the candidate redefines an
    existing prefix-set or route-policy)."""
    return any(REJECTED_LINE.match(line) and 'WARNING' not in line for line in text.splitlines())


def _depth_of(line):
    return len(line) - len(line.lstrip(' '))


def _send(shell, line, timeout):
    """Send one command and return (full echo+output+prompt text, the real device prompt).

    Unlike Shell.run(), which trims the echo and the trailing prompt for callers that only want
    the output, the paste needs the *actual* prompt after every line to know whether it just
    entered a new submode (only 'entered a submode' pushes the exit stack; a leaf statement never
    changes the prompt) -- trimming it away silently broke that detection.
    """
    shell.send(line)
    _, text = shell.expect([shell.any_prompt], timeout)
    lines = [l for l in text.splitlines() if l.strip()]
    return text, (lines[-1] if lines else '')


def _send_exit(shell, timeout):
    """Send 'exit' watching for the raw, non-CLI "Uncommitted changes...exit?" prompt a route-policy
    can raise (proven live, evidence Fact in section 2). Answered 'cancel' -- never blind 'yes' --
    and raised as a controlled failure: something tracked incorrectly if a plain 'exit' pop hits it,
    since this driver closes prefix-set/route-policy/if-block constructs with their own CLOSERS token.
    """
    shell.send('exit')
    index, text = shell.expect([shell.any_prompt, UNCOMMITTED_EXIT], timeout)
    if index == 1:
        shell.send('cancel')
        shell.expect([shell.any_prompt], timeout)
        raise RestoreError('The node asked whether to discard uncommitted changes while leaving a '
                           'submode; the candidate was not applied.')
    lines = [l for l in text.splitlines() if l.strip()]
    return text, (lines[-1] if lines else '')


def _paste(shell, lines, initial_prompt, timeout=LOAD_TIMEOUT):
    """Replay an indented IOS XR configuration body.

    IOS XR's own '!' markers are comments, not a submode exit, so this tracks the *real* prompt
    after every line and pops exactly the submodes that need it with plain 'exit' (never 'root',
    which a prefix-set/route-policy/if-block refuses). Those three constructs close with their own
    literal token (CLOSERS) sent while still inside them, matching how 'show running-config' writes
    them and avoiding the "Uncommitted changes... exit?" prompt a bare 'exit' can raise there.
    Whenever the observed prompt is the bare '(config)#' the tracked submode stack is reset to
    match reality, so a drifted stack can never later send a stray 'exit' past top-level into EXEC.

    Returns (rejections, mode_stack, final_prompt): rejections is a list of (line, output) for
    every real '%' rejection (the caller aborts on any); mode_stack is the depth stack left open
    (normal: the paste does not close its own last construct, 'commit replace' does not require it
    to); final_prompt is the real prompt text after the last line, for the caller's own sanity check
    before committing.
    """
    mode_stack = []
    prev_prompt = initial_prompt
    rejections = []
    if BARE_CONFIG_PROMPT.match(prev_prompt):
        mode_stack = []
    for raw in lines:
        stripped = raw.strip()
        if not stripped or stripped.startswith('!'):
            continue
        if stripped in CLOSERS:
            out, prompt = _send(shell, stripped, timeout)
            if _is_rejected(out):
                rejections.append((stripped, out))
            if mode_stack:
                mode_stack.pop()
            prev_prompt = prompt
            if BARE_CONFIG_PROMPT.match(prev_prompt):
                mode_stack = []
            continue
        depth = _depth_of(raw)
        while mode_stack and mode_stack[-1] >= depth:
            mode_stack.pop()
            _exited, prev_prompt = _send_exit(shell, timeout)
            if BARE_CONFIG_PROMPT.match(prev_prompt):
                mode_stack = []
        out, new_prompt = _send(shell, stripped, timeout)
        if _is_rejected(out):
            rejections.append((stripped, out))
        if new_prompt != prev_prompt:
            mode_stack.append(depth)
        prev_prompt = new_prompt
        if BARE_CONFIG_PROMPT.match(prev_prompt):
            mode_stack = []
    return rejections, mode_stack, prev_prompt


def _diff_has_changes(diff_text):
    return any(DIFF_CHANGE.match(line) for line in diff_text.splitlines())


def _last_commit_was_rollback(shell):
    """True when the most recent entry of 'show configuration commit list' is an automatic
    rollback (the node reverted on its own). A real entry row looks like '1    1000000035 ... ',
    i.e. two whitespace-separated numbers at the start of the (stripped) line -- not merely "the
    first line starting with a digit", which also matches header/separator text on some renders."""
    text = shell.run('show configuration commit list', PROMPT_TIMEOUT)
    for line in text.splitlines():
        stripped = line.strip()
        if COMMIT_ROW.match(stripped):
            return 'Rollback' in stripped
    return False


def _safe_abort(shell):
    """Best-effort discard of an uncommitted candidate on a failure path: never raises, whatever
    goes wrong (a dead channel is exactly as harmless to swallow here as a rejected 'abort')."""
    try:
        shell.run('abort', PROMPT_TIMEOUT)
    except Exception:
        pass


def _peer(client):
    try:
        return client.get_transport().getpeername()
    except Exception:
        return None


def _arm_timeout(confirm_minutes):
    """How long apply_shell() is willing to wait for the arming 'commit replace confirmed' to
    answer (see F7 / ARM_MARGIN): never more than COMMIT_TIMEOUT, and never so much of the caller's
    own recovery window that a slow answer could report "armed" with the trial already expired, or
    about to expire before the caller can even attempt to reconnect. A commit slower than this
    raises SessionLost (Shell.expect's own timeout), which is correct: whether the node actually
    armed the trial in time is genuinely unknown at that point.
    """
    window = max(1, int(confirm_minutes) * 60)
    return max(1, min(COMMIT_TIMEOUT, window - ARM_MARGIN))


def _leave_held_configuration(shell):
    """Best-effort: leave configuration mode on a held channel without confirming whatever it may
    still have armed. Never raises. Four shapes, (a)-(c) proven live (see the module evidence, the
    release() section); (d) is a defensive case, not live-observed from this path:

    (a) nothing outstanding (already confirmed, or a true no-op that never created a trial, see
        §13) -- a plain 'end' returns straight to the operational prompt and the session row is
        gone from 'show configuration sessions' at once.
    (b) a commit-confirmed trial armed by this session is still outstanding -- 'end' raises IOS
        XR's own raw, non-CLI warning that leaving now rolls the change back immediately; this
        answers 'yes' on purpose (see release()'s docstring for why).
    (c) the channel is already dead -- swallowed here; close_channel() below still runs.
    (d) 'end' instead raises the raw "Uncommitted changes...exiting(yes/no/cancel)?" prompt (not
        expected on a session that only ever reaches _HELD after a successful commit replace, but
        recognised rather than left to stall): never answered 'yes' (that would commit whatever is
        staged) and never 'no' either -- it is left exactly as an unanswered prompt, which lands on
        the node's own safe '[cancel]' default, so the channel below closes at once instead of
        waiting out PROMPT_TIMEOUT for nothing.
    """
    try:
        shell.send('end')
        index, _text = shell.expect([shell.any_prompt, EXIT_ROLLBACK_WARNING, UNCOMMITTED_EXIT],
                                     PROMPT_TIMEOUT)
        if index == 1:
            shell.send('yes')
            shell.expect([shell.any_prompt], PROMPT_TIMEOUT)
        # index == 2 (UNCOMMITTED_EXIT): see (d) above -- deliberately left unanswered.
    except Exception:
        pass


def apply_shell(shell, candidate, confirm_minutes=5, token=None):
    """Replace the running-configuration on an already-open IosXrShell, arm its timed recovery and
    stop -- this never confirms. Returns a dict: diff (show configuration changes diff, taken
    before the commit, for the review), no_op, confirm_minutes, handle. Raises RestoreError on any
    load/commit failure or when another session's lock or trial is already outstanding; the
    candidate is aborted (best-effort) before any failure raised while nothing has been committed
    yet, so nothing is left half-applied. Once the replace has been accepted (no rejection after
    answering the warning) a failure raises SessionLost instead: the node may already have armed
    the change, so the caller must read it back rather than assume nothing happened.
    """
    validate_candidate(candidate)
    reach_cli(shell)
    conflict = session_conflict(shell)
    if conflict == 'trial':
        raise RestoreError('Another change on this node is already pending confirmation; '
                            'this restore was not started.')
    if conflict == 'lock':
        raise RestoreError('Another session holds an exclusive configuration lock on this node; '
                            'this restore was not started.')
    body = _body_lines(candidate)
    entered = False
    try:
        opened, prompt = _send(shell, 'configure exclusive', LOAD_TIMEOUT)
        if _is_rejected(opened):
            raise RestoreError('The node did not open an exclusive configuration session for the restore.')
        entered = True
        rejections, _mode_stack, prompt = _paste(shell, body, prompt)
        if rejections:
            raise RestoreError('The node rejected the saved configuration while loading it.')
        if not CONFIG_PROMPT.match(prompt):
            raise RestoreError('Lost track of the configuration session while loading the candidate.')
        diff = shell.run('show configuration changes diff', LOAD_TIMEOUT)
        no_op = not _diff_has_changes(diff)
    except RestoreError:
        if entered:
            _safe_abort(shell)
        raise
    # Bounded by the caller's own recovery window (F7 / ARM_MARGIN), not just COMMIT_TIMEOUT: a
    # commit slow enough to eat most of a short window must not be waited out to where "armed"
    # would be reported with the trial already expired or about to.
    arm_timeout = _arm_timeout(confirm_minutes)
    shell.send('commit replace confirmed minutes %d' % int(confirm_minutes))
    index, text = shell.expect([REPLACE_WARNING, PROMPT], arm_timeout)
    if index == 0:
        shell.send('yes')
        _, text = shell.expect([PROMPT], arm_timeout)
    if _is_rejected(text):
        _safe_abort(shell)
        raise RestoreError('The node did not accept the timed replacement of the saved configuration.')
    # Positive evidence the trial is armed, without confirming it: a successful commit always
    # resets the target configuration buffer, so comparing it (now empty) against the just-applied
    # running configuration always shows the whole thing as removable -- proven live (see the
    # module evidence) for both a real change and a no-op replace. A diff that still looks like the
    # *pre-commit* one (or none at all) means the replace was never actually consumed.
    armed_evidence = shell.run('show configuration changes diff', arm_timeout)
    if not _diff_has_changes(armed_evidence):
        raise SessionLost('The node did not show the replace as armed after answering the prompt; '
                          'reading the node back.')
    return {'diff': diff, 'no_op': no_op, 'confirm_minutes': int(confirm_minutes), 'handle': {'token': token}}


def confirm(client, handle, **_kw):
    """Confirm a pending timed replace. `client` is a fresh connection: reaching its CLI is the
    proof management survived the replace. Only then is the confirming 'commit' sent, on the HELD
    channel that originally armed it (see the module docstring) -- never fabricated. Raises
    RestoreError, never confirming, when the held session is gone (a manager restart, or the
    channel died) or when the held channel's own confirming commit does not show the node's own
    positive evidence ('% Confirming commit for trial session.').

    The held session is released (F2) only once its own confirming commit has actually been
    attempted, success or failure -- never merely because the fresh connection was opened. A fresh
    connection that fails before that point (`reach_cli` stalls or drops) leaves the held session
    untouched and re-raises: it is still the only session that can confirm this change, so a
    later retry with another fresh connection must still find it in `_HELD`. Proven live, see the
    module evidence.
    """
    handle = handle or {}
    token = handle.get('token')
    channel, shell = _open(client)
    try:
        reach_cli(shell)
        with _HELD_LOCK:
            held = _HELD.get(token)
        if not held:
            if _last_commit_was_rollback(shell):
                raise RestoreError('The session that armed this change is gone, and the node has '
                                   'already rolled the change back on its own.')
            raise RestoreError('The session that armed this change is gone; if it was never '
                               'confirmed the node undoes the change by itself.')
        hshell = held['shell']
        try:
            result = hshell.run('commit', COMMIT_TIMEOUT)
        except Exception:
            # The confirming commit was attempted (a fresh confirm() call proved management
            # survived and reached this point): whatever the held channel's own state is now, a
            # second confirm() must not find it still in `_HELD` and resend 'commit' onto it.
            _release_held(token)
            raise
        if 'Confirming commit for trial session' not in result:
            _release_held(token)
            raise RestoreError('The node did not confirm the change from the session that armed '
                               'it, and closing that session has already undone it.')
        # Leaving configuration mode is safe here (proven live): nothing is uncommitted any more,
        # so 'end' does not raise the "Uncommitted changes...?" prompt the way it can before a
        # replace is confirmed (see _send_exit / evidence section 5), nor release()'s own
        # immediate-rollback prompt (see _leave_held_configuration): the trial this session armed
        # was just confirmed, so none is outstanding any more.
        try:
            hshell.run('end', PROMPT_TIMEOUT)
        finally:
            _release_held(token, already_left=True)
        if session_conflict(shell) == 'trial':
            raise RestoreError('The node still shows a change waiting for confirmation after '
                               'confirming; it may be undone automatically.')
        return {'confirmed': True}
    finally:
        _close(channel)


def release(token):
    """Close a held session (if any) without confirming; never raises.

    Leaves configuration mode on the held channel first, best-effort (see
    :func:`_leave_held_configuration`): proven live in three shapes (see the module evidence).
    (a) Nothing outstanding (already confirmed, or a true no-op that never armed a trial, see
    §13) -- 'end' returns directly to the operational prompt and the session row is gone from
    'show configuration sessions' immediately. (b) A trial armed by this session is still
    outstanding -- IOS XR raises its own raw "leaving now rolls the change back immediately"
    warning on 'end', and this answers it 'yes' on purpose: the previous configuration is active
    again, and the session row gone, as soon as release() returns, rather than left open for the
    several minutes a merely-dropped connection's row lingers for (a real device quirk, proven
    live and not something a driver can shorten once the connection is simply dropped instead).
    (c) The channel is already dead -- swallowed; never raised.

    Contract note: see restore_drivers.py's "``HOLDS_SESSION`` and ``release(token)``" section for
    the general contract this follows, including the immediate-rollback behaviour it already
    documents for IOS XR specifically.
    """
    try:
        _release_held(token)
    except Exception:
        pass


def _release_held(token, already_left=False):
    """Pop and close a held session. `already_left` skips leaving configuration mode again when
    the caller (confirm(), after a successful confirming commit) already did it on the same
    channel -- sending 'end' twice would just draw a harmless but pointless second round trip."""
    with _HELD_LOCK:
        held = _HELD.pop(token, None)
    if not held:
        return
    if not already_left:
        _leave_held_configuration(held['shell'])
    _close(held['channel'])
    try:
        held['client'].close()
    except Exception:
        pass


def pending(client, **_kw):
    """'' when no trial is outstanding; the held token when one is outstanding AND this process
    holds the arming session for the same node (matched by peer address, since a fresh connection
    used only to probe carries no token); True when a trial is outstanding that this process does
    not hold (a foreign restore, or a change armed directly on the device)."""
    channel, shell = _open(client)
    try:
        reach_cli(shell)
        if session_conflict(shell) != 'trial':
            return ''
        peer = _peer(client)
        with _HELD_LOCK:
            entries = list(_HELD.items())
        for token, held in entries:
            if peer is not None and held.get('peer') == peer:
                return token
        return True
    finally:
        _close(channel)


def blocked(client, **_kw):
    """A student-readable reason why a restore must not start now, or ''. An ordinary open
    configuration session or an exclusive lock without a trial is not "pending confirmation"
    (see :func:`pending`), but it still must not be paved over."""
    channel, shell = _open(client)
    try:
        reach_cli(shell)
        if session_conflict(shell) in ('lock', 'plain'):
            return ("A configuration session is open on this node; the restore was not started "
                    "so that nobody's work is lost.")
        return ''
    finally:
        _close(channel)


def compare(desired, actual):
    """(missing, extra) between two `show running-config` texts, hierarchy kept.

    No IOS XR-specific generated line needs excluding beyond what compare_indented already drops
    (every `!` comment/banner line and the closing `end`): a pre-hashed `secret 10 $6$...` line is
    stored and echoed back verbatim (proven: re-pasting an unchanged capture produces an empty
    diff), so, unlike EOS's session diff, there is no extra per-run text to skip here. An
    order-sensitive block (a route-policy, an ACL) whose lines only changed order is reported as
    missing, mirroring restore_eos.compare.
    """
    missing, extra = compare_indented(desired, actual)
    missing += ['(order) ' + name for name in ordered_blocks_differ(desired, actual, IOSXR_ORDERED)]
    return missing, extra


def capture_shell(shell):
    """Capture the running configuration for verification, with the generated header removed."""
    reach_cli(shell)
    text = shell.run('show running-config', LOAD_TIMEOUT)
    return strip_generated_header(text)


# --- live entry points: open a channel on a connected paramiko client ---------------

def _open(client):
    return open_shell(client, IosXrShell)


def apply_candidate(client, candidate, confirm_minutes=5, token=None, **_kw):
    channel, shell = _open(client)
    try:
        result = apply_shell(shell, candidate, confirm_minutes, token)
    except Exception:
        _close(channel)
        raise
    with _HELD_LOCK:
        reused = token in _HELD
    if reused:
        # Never expected from the service (its tokens are per-attempt uuids), but a reused token
        # must not silently leak the older held session's channel and client (F6).
        _release_held(token)
    entry = {'client': client, 'channel': channel, 'shell': shell, 'peer': _peer(client)}
    with _HELD_LOCK:
        _HELD[token] = entry
    return result


def capture(client, **_kw):
    channel, shell = _open(client)
    try:
        return capture_shell(shell)
    finally:
        _close(channel)


_close = close_channel
