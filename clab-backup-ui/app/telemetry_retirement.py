"""What is left of the removed network telemetry feature: the record of the device lines it added.

Releases that shipped automatic telemetry could add a few gRPC/gNMI service lines to a device (EOS
``management api gnmi``, IOS XR ``grpc``, Junos Evolved ``extension-service request-response grpc``)
and recorded every such line verbatim per lab, under ``lab['telemetry']['applied']``. The feature is
gone, but those lines can still be on the devices, so the record is never thrown away silently:

* :func:`migrate_retired_telemetry` runs at every start (idempotent). It drops the old setting and
  moves a non-empty ledger to ``lab['telemetry_retired']``; a stored value that is not in the expected
  shape is kept as it was under ``malformed``, never replaced by a default.
* :func:`public_retired_telemetry` is what ``/api/state`` shows: node names and line counts only.
* :class:`TelemetryRetirement` serves the lab page: the recorded lines on request, an explicit removal
  over direct node SSH that deletes only what the ledger proves the manager added, and forgetting an
  entry the manager can never act on (the device left the lab, its kind is not supported or changed,
  its lines are not a recognised form, or the lab was redeployed after they were recorded) or the
  malformed copy. A malformed copy is bounded to 4 KiB.

Removal, per node, from the operational prompt: read the service block; nothing recorded is left there
-> ``absent`` (the record is cleared); a block the manager created now also holds statements it did not
add -> ``failed`` and nothing is changed; otherwise the exact inverse is sent inside the NOS's own
configuration mode (EOS configure terminal, IOS XR commit, Junos ``configure private`` + commit) and
the block is read back. A whole block is deleted only when it holds nothing but the manager's lines;
gRPC/gNMI is never disabled wholesale. A change that another session left waiting for confirmation is
never committed over. Identical text is no proof of authorship: once this manager redeployed the lab
after the lines were recorded, the record is cleared without touching the device. While a removal runs
the lab is busy for every other operation (``removing`` in the record, read by ``operation_busy``).
Events and messages carry node names, counts and fixed text, never configuration or device output.
"""
import copy
import json
import math
import re
import threading
import time
from collections import namedtuple
from concurrent.futures import CancelledError, ThreadPoolExecutor, wait
from datetime import datetime, timezone

import paramiko
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field

from . import restore_eos, restore_iosxr, restore_junos
from .discovery import discovery_fresh, node_available
from .lab_operations import RESTORE_BUSY, last_deployed, operation_busy
from .node_services import connect
from .restore import IN_FLIGHT
from .restore_shell import ANSI, RestoreError, SessionLost, close_channel
from .runner import effective_credentials, now

NODE_SECONDS = 120          # wall time for one node: login, reads, change and read-back
STEP_TIMEOUT = 30
COMMIT_TIMEOUT = 90
ABORT_GRACE = 10            # leaving configuration mode may still run this long after the node's deadline
WORKERS = 4
MALFORMED_LIMIT = 4096

ABSENT = 'None of the recorded lines is on the device any more (it was redeployed or they were removed); the record was cleared.'
LEFT_IN_PLACE = ('The lines the manager added are gone; the service block it created now holds only settings the manager '
                 'did not add and was left in place. The record was cleared.')
REMOVED = 'Removed the lines the manager had added and read the device back: they are gone.'
FOREIGN = ("The device's gRPC service now carries settings the manager did not add, so nothing was changed. "
           'Remove the recorded lines by hand if you no longer need them.')
INVALID = 'The recorded lines are not in a form the manager can remove safely; remove them by hand.'
STILL = 'The removal was sent, but the device still shows lines the manager added; check the device before you retry.'
UNVERIFIED = 'The removal was sent, but the device could not be read back; run the removal again to check it.'
UNCONFIRMED = 'The device did not confirm the removal in time; run the removal again to check it.'
REJECTED = 'The device refused the removal, so the manager discarded its change; nothing was changed.'
REJECTED_EOS = 'The device refused the removal and the manager stopped; check the device before you retry.'
LOST_EOS = 'The device stopped answering during the removal; check the device before you retry.'
PENDING = ('Another configuration change is waiting for confirmation on the device, so nothing was changed. '
           'Retry after it is confirmed or rolled back.')
LOCKED = 'Someone holds an exclusive configuration session on the device, so nothing was changed.'
READ_FAILED = 'The device did not show its gRPC configuration, so nothing was changed.'
ENABLE = 'The login did not reach privileged mode (check the enable password of the login), so nothing was changed.'
NO_ANSWER = 'The device did not answer in time, so nothing was changed.'
LOGIN = 'The device refused the saved login, so nothing was changed.'
SSH_FAILED = 'The SSH session to the device failed, so nothing was changed.'
SLOT = 'No SSH session slot was free; close a terminal and retry.'
STOPPING = 'The manager is stopping; retry after it has restarted.'
TOO_LONG = 'The device did not finish within the time allowed; run the removal again to check it.'
REDEPLOYED = ("The lab was redeployed after these lines were recorded, so the device's configuration comes from its startup "
              "files and the manager's record no longer applies; the record was cleared.")
REDEPLOYED_REASON = 'The lab was redeployed after these lines were recorded; nothing to remove.'
NO_RECORD = 'No configuration lines of the removed telemetry feature are recorded for this lab.'


class Refused(Exception):
    """A controlled, student-facing reason a node's lines were not removed; never device output."""


Decision = namedtuple('Decision', 'outcome commands message')


# ---- the stored record ---------------------------------------------------------------------------

def _text(value, limit=64):
    return value[:limit] if isinstance(value, str) else ''


def _entry(value):
    """A clean ledger entry, None when it holds no line, or False when it is not in the expected shape."""
    if not isinstance(value, dict):
        return False
    lines = value.get('lines')
    if lines is None:
        return None
    if not isinstance(lines, list) or not all(isinstance(line, str) for line in lines):
        return False
    kept = [line for line in lines if line.strip()]
    return {'lines': kept, 'at': _text(value.get('at')), 'kind': _text(value.get('kind'))} if kept else None


def _split(old):
    """(clean ledger {node: entry}, reason it is malformed or '') of a lab's old telemetry value."""
    if not isinstance(old, dict):
        return {}, 'the stored telemetry setting is not an object'
    applied = old.get('applied')
    if applied is None:
        return {}, ''
    if not isinstance(applied, dict):
        return {}, 'its record of added lines is not an object'
    ledger, bad = {}, []
    for name, value in applied.items():
        entry = _entry(value)
        if entry is False:
            bad.append(str(name))
        elif entry:
            ledger[name] = entry
    if not bad:
        return ledger, ''
    names = ', '.join(sorted(bad)[:5]) + (' and others' if len(bad) > 5 else '')
    return ledger, 'the recorded lines of ' + names + ' are not in the expected shape'


def _raw(value):
    """The value as it was, or, when its JSON is longer than MALFORMED_LIMIT (4 KiB), its first 4096
    characters as a string: the malformed copy kept in the state is bounded."""
    try:
        text = json.dumps(value)
    except (TypeError, ValueError):
        text = repr(value)
        return text[:MALFORMED_LIMIT] + ('…(truncated)' if len(text) > MALFORMED_LIMIT else '')
    return value if len(text) <= MALFORMED_LIMIT else text[:MALFORMED_LIMIT] + '…(truncated)'


def _newer(candidate, existing):
    new, old = _moment(candidate.get('at')), _moment(existing.get('at'))
    return bool(new and old and new > old)


def _applied(record):
    """The usable ledger entries of a retired record: {node: {'lines', 'at', 'kind'}}."""
    applied = record.get('applied') if isinstance(record, dict) else None
    if not isinstance(applied, dict):
        return {}
    return {name: entry for name, entry in applied.items()
            if isinstance(entry, dict) and isinstance(entry.get('lines'), list) and entry['lines']
            and all(isinstance(line, str) for line in entry['lines'])}


def _order(lab, applied):
    """Ledger node names in the lab's node order, then any the lab no longer has."""
    known = [n.get('name') for n in lab.get('nodes', []) if n.get('name') in applied]
    return known + sorted(name for name in applied if name not in known)


def _short(node, name):
    node = node or {}
    return node.get('short_name') or node.get('definition_node') or name


def _devices(lab, applied):
    nodes = {n.get('name'): n for n in lab.get('nodes', [])}
    names = _order(lab, applied)
    parts = ', '.join(f"{_short(nodes.get(name), name)} ({len(applied[name]['lines'])})" for name in names)
    return f"{len(names)} device{'' if len(names) == 1 else 's'}: {parts}"


def _record(lab, stamp):
    """The lab's retired record to merge into; an existing one is kept, never replaced wholesale."""
    record = lab.get('telemetry_retired')
    if record is None:
        return {'applied': {}, 'retired_at': stamp}
    if not isinstance(record, dict):
        return {'applied': {}, 'retired_at': stamp,
                'malformed': [{'reason': 'the retired record is not an object', 'value': _raw(record), 'at': stamp}]}
    if not isinstance(record.get('applied'), dict):
        if record.get('applied') is not None:
            record['malformed'] = _malformed(record) + [{'reason': 'the retired record of added lines is not an object',
                                                         'value': _raw(record['applied']), 'at': stamp}]
        record['applied'] = {}
    if 'malformed' in record and not isinstance(record['malformed'], list):
        record['malformed'] = [{'reason': 'the kept malformed value is not a list', 'value': _raw(record['malformed']), 'at': stamp}]
    return record


def _malformed(record):
    value = record.get('malformed') if isinstance(record, dict) else None
    return value if isinstance(value, list) else ([] if value is None else [value])


def migrate_retired_telemetry(store):
    """Move each lab's old telemetry ledger to ``telemetry_retired`` and drop the old setting.

    Also clears the ``removing`` flag a restart left behind. Idempotent; saves once, and only when a lab
    changed. Returns ``{'labs': changed, 'kept': {lab id: [node names]}, 'malformed': [lab ids]}``. No
    other key of any lab is touched.
    """
    summary = {'labs': 0, 'kept': {}, 'malformed': []}
    events = []
    with store.lock:
        for lab in store.state.get('labs', []):
            if not isinstance(lab, dict):
                continue
            retired = lab.get('telemetry_retired')
            stale = isinstance(retired, dict) and 'removing' in retired
            if stale:
                # A removal a restart interrupted: its device sessions are gone with the old process.
                retired.pop('removing')
                _tidy(lab)
            if 'telemetry' not in lab:
                summary['labs'] += stale
                continue
            old = lab.pop('telemetry')
            summary['labs'] += 1
            ledger, reason = _split(old) if old is not None else ({}, '')
            if not ledger and not reason:
                continue
            stamp = now()
            record = _record(lab, stamp)
            for name, entry in ledger.items():
                current = record['applied'].get(name)
                if _entry(current) in (None, False) or _newer(entry, current):
                    record['applied'][name] = entry
            if reason:
                record['malformed'] = _malformed(record) + [{'reason': reason, 'value': _raw(old), 'at': stamp}]
                summary['malformed'].append(lab.get('id', ''))
                events.append(('telemetry.retired.malformed', 'warning', lab.get('id', ''),
                               f"Telemetry retired; the stored telemetry record of lab {lab.get('name', '')!r} is not in the "
                               f"expected shape ({reason}). It was kept unchanged for inspection and nothing was removed."))
            lab['telemetry_retired'] = record
            applied = _applied(record)
            if applied:
                summary['kept'][lab.get('id', '')] = _order(lab, applied)
                events.append(('telemetry.retired', 'info', lab.get('id', ''),
                               'Telemetry retired; configuration lines the removed feature added remain recorded for '
                               + _devices(lab, applied) + '. Remove them from the lab page.'))
        if summary['labs']:
            store.save()
    for action, level, lab_id, message in events:
        store.event(action, message, level=level, lab_id=lab_id)
    return summary


def public_retired_telemetry(lab):
    """The /api/state summary: node names and line counts, never the lines; None when nothing is kept."""
    record = lab.get('telemetry_retired')
    if not isinstance(record, dict):
        return None
    applied = _applied(record)
    malformed = bool(record.get('malformed'))
    if not applied and not malformed:
        return None
    nodes = {n.get('name'): n for n in lab.get('nodes', [])}
    rows = [{'name': name, 'short_name': _short(nodes.get(name), name), 'lines': len(applied[name]['lines'])}
            for name in _order(lab, applied)]
    return {'nodes': rows, 'total': sum(row['lines'] for row in rows), 'malformed': malformed}


# ---- reading a service block and planning the inverse ----------------------------------------------

def _block(text, header):
    """(present, statements) of the top-level ``header`` block of an indented configuration excerpt.
    A statement is the tuple of its stripped ancestors below the header and itself."""
    present, inside, stack, paths = False, False, [], []
    for raw in (text or '').split('\n'):
        line = ANSI.sub('', raw).replace('\r', '').rstrip()
        body = line.strip()
        if not body:
            continue
        depth = len(line) - len(line.lstrip(' '))
        if depth == 0:
            inside = body == header
            present = present or inside
            stack = []
            continue
        if not inside or body == '!':
            continue
        while stack and stack[-1][0] >= depth:
            stack.pop()
        paths.append(tuple(item for _, item in stack) + (body,))
        stack.append((depth, body))
    return present, paths


def _owned_block(lines, header):
    """(header recorded, statements) the ledger holds under ``header``, or None when the lines are not
    one block of it (nothing is then removed automatically)."""
    rows = [line.rstrip() for line in lines if line.strip()]
    tops = [index for index, line in enumerate(rows) if not line.startswith(' ')]
    if tops not in ([], [0]) or any(rows[index].strip() != header for index in tops):
        return None
    header_owned = tops == [0]
    _, paths = _block('\n'.join(rows if header_owned else [header] + rows), header)
    if len(paths) != len(rows) - (1 if header_owned else 0):
        return None
    return header_owned, set(paths)


def plan_block(header, lines, text):
    """What to do about the recorded lines of one indented block (EOS, IOS XR).

    The ledger records the header when the manager created the block: then the whole block goes, but
    only when it holds nothing the manager did not add. Lines the manager added to an existing block
    are removed one by one and the block itself stays.
    """
    owned = _owned_block(lines, header)
    if owned is None:
        return Decision('invalid', [], INVALID)
    header_owned, mine = owned
    present, current = _block(text, header)
    current = set(current)
    if not present:
        return Decision('absent', [], ABSENT)
    found = mine & current
    if header_owned:
        foreign = current - mine
        if foreign and not found:
            return Decision('absent', [], LEFT_IN_PLACE)
        if foreign:
            return Decision('foreign', [], FOREIGN)
        return Decision('remove', ['no ' + header], REMOVED)
    if not found:
        return Decision('absent', [], ABSENT)
    roots = sorted(path for path in found if not any(path[:size] in found for size in range(1, len(path))))
    if any(path[:len(root)] == root and path not in mine for root in roots for path in current):
        return Decision('foreign', [], FOREIGN)
    commands = []
    for index, root in enumerate(roots):
        if index:
            commands += ['exit'] * len(roots[index - 1])
        commands += [header, *root[:-1], 'no ' + root[-1]]
    return Decision('remove', commands, REMOVED)


def left_block(header, lines, text):
    """True while anything the ledger recorded under ``header`` is still configured."""
    owned = _owned_block(lines, header)
    present, current = _block(text, header)
    if owned is None:
        return present
    header_owned, mine = owned
    return present and (header_owned or bool(mine & set(current)))


def _top_lines(text):
    return [line.strip() for line in (text or '').replace('\r', '').split('\n') if line.strip() and not line.startswith(' ')]


JUNOS_GRPC = 'system services extension-service request-response grpc'
JUNOS_OWNED = re.compile(r'^set ' + re.escape(JUNOS_GRPC) + r' (clear-text(?: port \d+)?|routing-instance \S+)$')


def _junos_owned(lines):
    owned = set()
    for line in lines:
        if not line.strip():
            continue
        match = JUNOS_OWNED.match(' '.join(line.split()))
        if not match:
            return None
        owned.add(tuple(match[1].split()))
    return owned


def _junos_current(text):
    """(verb, statement below the grpc service) of every display-set line about the service."""
    rows = []
    for raw in (text or '').split('\n'):
        words = ANSI.sub('', raw).split()
        rest = ' '.join(words[1:])
        if len(words) > 1 and (rest == JUNOS_GRPC or rest.startswith(JUNOS_GRPC + ' ')):
            rows.append((words[0], tuple(rest[len(JUNOS_GRPC):].split())))
    return rows


def plan_junos(lines, text):
    """What to do about the recorded Junos Evolved lines (``| display set`` form).

    A recorded ``clear-text`` line means the manager created that stanza, a ``routing-instance`` line
    that leaf. Each goes only when it holds nothing the manager did not add. The routing instance binds
    the whole service, so it goes only when nothing else under the service is someone else's (deleting
    it would move their gRPC out of the management instance). When the manager's lines are all the grpc
    service holds, the service container goes with them, so no empty service is left behind.
    """
    mine = _junos_owned(lines)
    if mine is None:
        return Decision('invalid', [], INVALID)
    current = _junos_current(text)
    found = {path for verb, path in current if verb == 'set' and path in mine}
    if not found:
        return Decision('absent', [], ABSENT)
    roots = sorted({path[:1] for path in found})

    def inside(path):
        return any(path[:len(root)] == root for root in roots)
    foreign = [path for verb, path in current if not (verb == 'set' and path in mine)]
    if any(inside(path) for path in foreign) or (('routing-instance',) in roots and foreign):
        return Decision('foreign', [], FOREIGN)
    if all(verb == 'set' and inside(path) for verb, path in current):
        return Decision('remove', ['delete ' + JUNOS_GRPC], REMOVED)
    return Decision('remove', ['delete ' + JUNOS_GRPC + ' ' + root[0] for root in roots], REMOVED)


def left_junos(lines, text):
    mine = _junos_owned(lines) or set()
    return any(verb == 'set' and path in mine for verb, path in _junos_current(text))


# ---- per-NOS drivers ------------------------------------------------------------------------------

class _Bounded:
    """Every wait of one node's removal shares one wall-clock deadline."""
    deadline = None

    def expect(self, patterns, timeout=None):
        left = (self.deadline if self.deadline is not None else math.inf) - time.monotonic()
        if left <= 0:
            raise SessionLost('The node did not finish in time.')
        return super().expect(patterns, min(timeout or self.timeout, left))


class EosSession(_Bounded, restore_eos.EosShell):
    pass


class IosXrSession(_Bounded, restore_iosxr.IosXrShell):
    pass


class JunosSession(_Bounded, restore_junos.JunosShell):
    pass


def _rejected_lines(text):
    return any(re.match(r'^\s*%', line) and 'WARNING' not in line for line in text.split('\n'))


class Eos:
    platform = 'arista_ceos'
    shell = EosSession
    header = 'management api gnmi'
    read = 'show running-config | section management api gnmi'
    commits = ()
    transactional = False       # configure terminal applies each line at once
    question = None             # a raw (non-CLI) question a configuration command can raise
    decline = ''

    def reach(self, shell, creds):
        restore_eos.reach_cli(shell, (creds or {}).get('enable_password') or '')

    def in_config(self, prompt):
        return '(config' in prompt

    def read_failed(self, output):
        return bool(re.search(r'(?m)^\s*% ', output))

    def recognised(self, output):
        """Only the block itself: anything else is never taken as "the lines are gone"."""
        return all(line == self.header for line in _top_lines(output))

    def rejected(self, output):
        return _rejected_lines(output)

    def blocked(self, shell):
        return PENDING if restore_eos.pending_shell(shell) else ''

    def plan(self, lines, text):
        return plan_block(self.header, lines, text)

    def left(self, lines, text):
        return left_block(self.header, lines, text)

    def valid(self, lines):
        return _owned_block(lines, self.header) is not None

    def wrap(self, commands):
        return ['configure terminal', *commands, 'end']

    def abort(self, shell):
        _exchange(shell, 'end', STEP_TIMEOUT)


class IosXr(Eos):
    platform = 'cisco_xrv9k'
    shell = IosXrSession
    header = 'grpc'
    read = 'show running-config grpc'
    commits = ('commit',)
    transactional = True
    question = restore_iosxr.UNCOMMITTED_EXIT
    decline = 'cancel'

    def reach(self, shell, creds):
        restore_iosxr.reach_cli(shell)

    def read_failed(self, output):
        return bool(re.search(r'(?m)^\s*%(?!\s*No such configuration item)', output))

    def recognised(self, output):
        """The block, the generated timestamp and banner lines, or IOS XR's "nothing configured" answer."""
        return all(line in (self.header, '!', 'end') or line.startswith('!!') or line.startswith('% No such configuration item')
                   or restore_iosxr.TIMESTAMP_LINE.match(line) or restore_iosxr.BUILDING_LINE.match(line)
                   for line in _top_lines(output))

    def rejected(self, output):
        return _rejected_lines(output) or '!! SEMANTIC ERRORS' in output or '!! SYNTAX' in output

    def blocked(self, shell):
        conflict = restore_iosxr.session_conflict(shell)
        return PENDING if conflict == 'trial' else LOCKED if conflict == 'lock' else ''

    def wrap(self, commands):
        return ['configure terminal', *commands, 'commit', 'end']

    def abort(self, shell):
        _exchange(shell, 'abort', STEP_TIMEOUT)


JUNOS_ERROR = re.compile(r'(?im)^\s*(?:error:|syntax error|unknown command|missing\b)|commit failed')
JUNOS_STATEMENT = re.compile(r'^\s*(?:(?:set|deactivate|activate|protect|annotate|insert) \S|\{.*\}\s*$|#)')


class JunosEvolved(Eos):
    platform = 'juniper_cjunosevolved'
    shell = JunosSession
    read = 'show configuration system services extension-service | display set'
    commits = ('commit and-quit',)
    transactional = True
    question = restore_junos.EXIT_QUESTION
    decline = 'no'

    def reach(self, shell, creds):
        restore_junos.reach_cli(shell)

    def in_config(self, prompt):
        return prompt.endswith('#')

    def read_failed(self, output):
        return bool(JUNOS_ERROR.search(output))

    def recognised(self, output):
        """Only ``display set`` statements (and the braces or comments Junos may print around them)."""
        return all(JUNOS_STATEMENT.match(line) for line in (output or '').replace('\r', '').split('\n') if line.strip())

    def rejected(self, output):
        return bool(JUNOS_ERROR.search(output))

    def blocked(self, shell):
        return PENDING if restore_junos.pending_commit(shell) else ''

    def plan(self, lines, text):
        return plan_junos(lines, text)

    def left(self, lines, text):
        return left_junos(lines, text)

    def valid(self, lines):
        return _junos_owned(lines) is not None

    def wrap(self, commands):
        return ['configure private', *commands, 'commit and-quit']

    def abort(self, shell):
        _exchange(shell, 'rollback 0', STEP_TIMEOUT)
        _, _, index = _exchange(shell, 'exit configuration-mode', STEP_TIMEOUT, self.question)
        if index:
            _exchange(shell, 'yes', STEP_TIMEOUT)


DRIVERS = {driver.platform: driver for driver in (Eos(), IosXr(), JunosEvolved())}
SUPPORTED = tuple(DRIVERS)


def _exchange(shell, command, timeout, question=None):
    """Send one command: (output without echo and prompt, the prompt, index of the matched pattern)."""
    shell.send(command)
    index, text = shell.expect([shell.any_prompt] + ([question] if question is not None else []), timeout)
    lines = text.replace('\r', '').split('\n')
    while lines and not lines[0].strip():
        lines.pop(0)
    if lines and command.strip() and lines[0].strip().endswith(command.strip()):
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    prompt = lines.pop().strip() if lines else ''
    return '\n'.join(lines), prompt, index


def _read(shell, driver):
    output, prompt, _ = _exchange(shell, driver.read, STEP_TIMEOUT)
    if driver.platform == 'arista_ceos' and prompt.endswith('>'):
        raise Refused(ENABLE)
    if driver.in_config(prompt) or driver.read_failed(output) or not driver.recognised(output):
        raise Refused(READ_FAILED)
    return output


def _abort(shell, driver, prompt):
    """Leave configuration mode without keeping anything; skipped when the device is known to be out of it."""
    if prompt is not None and not driver.in_config(prompt):
        return
    if getattr(shell, 'deadline', None) is not None:
        shell.deadline = max(shell.deadline, time.monotonic() + ABORT_GRACE)
    try:
        driver.abort(shell)
    except (RestoreError, OSError, EOFError, paramiko.SSHException):
        pass


def _change(shell, driver, commands):
    """Send the removal; on any refusal leave configuration mode without keeping it (raises Refused)."""
    committing = False
    prompt = None
    try:
        for command in commands:
            committing = committing or command in driver.commits
            output, prompt, index = _exchange(shell, command, COMMIT_TIMEOUT if command in driver.commits else STEP_TIMEOUT,
                                              driver.question)
            if index:
                prompt = None
                shell.send(driver.decline)
                shell.expect([shell.any_prompt], STEP_TIMEOUT)
                raise Refused('question')
            if driver.rejected(output):
                raise Refused('rejected')
    except Refused:
        _abort(shell, driver, prompt)
        raise Refused(REJECTED if driver.transactional else REJECTED_EOS)
    except (RestoreError, OSError, EOFError, paramiko.SSHException):
        if committing:
            raise Refused(UNCONFIRMED)
        _abort(shell, driver, None)
        raise Refused(NO_ANSWER if driver.transactional else LOST_EOS)
    if prompt is None or driver.in_config(prompt):
        _abort(shell, driver, prompt)
        raise Refused(REJECTED if driver.transactional else REJECTED_EOS)


def retire(shell, driver, lines):
    """Remove one node's recorded lines on a shell at the operational prompt: (outcome, message)."""
    try:
        decision = driver.plan(lines, _read(shell, driver))
        if decision.outcome == 'absent':
            return 'absent', decision.message
        if decision.outcome != 'remove':
            return 'failed', decision.message
        blocked = driver.blocked(shell)
    except (RestoreError, OSError, EOFError, paramiko.SSHException):
        return 'failed', NO_ANSWER
    if blocked:
        return 'failed', blocked
    _change(shell, driver, driver.wrap(decision.commands))
    try:
        after = _read(shell, driver)
    except (Refused, RestoreError, OSError, EOFError, paramiko.SSHException):
        return 'failed', UNVERIFIED
    if driver.left(lines, after):
        return 'failed', STILL
    return 'removed', REMOVED


def open_channel(services, node, creds):
    """Log in over direct node SSH (host keys are not pinned, like every lab-device session) and open
    an interactive shell. Returns (channel, close); the client counts against the SSH session limit."""
    client = services.reserve()
    try:
        connect(client, node, creds)
        channel = client.invoke_shell(term='vt100', width=240, height=100000)
        channel.settimeout(1.0)
    except BaseException:
        services.release(client)
        raise

    def close():
        close_channel(channel)
        services.release(client)
    return channel, close


def _restore_active(state, lab_id, restore):
    rechecks = getattr(restore, 'rechecks', None) or {}
    for job in state.get('restore_jobs', []):
        if job.get('lab_id') != lab_id:
            continue
        if job.get('status') in RESTORE_BUSY or rechecks.get(job.get('id'), 0) > 0:
            return True
        if any(target.get('status') in IN_FLIGHT for target in job.get('targets', []) if isinstance(target, dict)):
            return True
    return False


def _moment(text):
    """An ISO time as an aware datetime (a time without a zone is UTC), or None when unreadable."""
    try:
        value = datetime.fromisoformat(text)
    except (TypeError, ValueError):
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def redeployed_since(state, lab, entry):
    """True when this manager deployed the lab after the entry's lines were recorded.

    Identical text on the device is no proof that the manager wrote it: containerlab's own cEOS template
    carries the same ``management api gnmi`` block the provisioner used to add. After a redeploy the
    configuration comes from the startup files, so the record no longer applies. A record time that is
    missing or unreadable counts as older; an unreadable deployment time proves nothing.
    """
    deployed = _moment(last_deployed(state, lab))
    if deployed is None:
        return False
    recorded = _moment(entry.get('at'))
    return recorded is None or deployed > recorded


def _tidy(lab):
    """Drop the retired record once nothing is left in it."""
    record = lab.get('telemetry_retired')
    if isinstance(record, dict) and not record.get('applied') and not record.get('malformed') and not record.get('removing'):
        lab.pop('telemetry_retired')


class TelemetryRetirement:
    """The lab page's view of the retired record, the explicit removal of the recorded lines and
    forgetting a record the manager can never act on.

    While a removal runs, ``lab['telemetry_retired']['removing']`` holds its start time in the store:
    :func:`lab_operations.operation_busy`, the guard that backups, Git saves, restores, imports and lab
    operations consult, treats the lab as busy until the request and every device session of it ended.
    """

    def __init__(self, store, services):
        self.store = store
        self.services = services
        self.lock = threading.Lock()
        self.running = set()        # lab ids with a removal request in progress
        self.inflight = set()       # (lab id, node name) with a device session in progress
        self.closed = False
        self.pool = ThreadPoolExecutor(max_workers=WORKERS, thread_name_prefix='telemetry-retired')

    def close(self):
        with self.lock:
            self.closed = True
        self.pool.shutdown(wait=False, cancel_futures=True)

    def reason(self, state, lab, name, entry, checks):
        """('', False) when the manager may remove this node's lines now; else one student-facing sentence and
        whether it is permanent (the entry can then only be forgotten) or passes (the device, the VM or a login)."""
        if redeployed_since(state, lab, entry):
            return REDEPLOYED_REASON, True
        node = next((n for n in lab['nodes'] if n.get('name') == name), None)
        if node is None:
            return 'This device is no longer part of the lab.', True
        platform = node.get('platform') or ''
        driver = DRIVERS.get(platform)
        if driver is None:
            return 'The manager cannot remove lines from this kind of device; remove them by hand.', True
        if entry.get('kind') and entry['kind'] != platform:
            return 'The device kind changed since the lines were recorded; remove them by hand.', True
        if not driver.valid(entry['lines']):
            return INVALID, True
        if not discovery_fresh(state):
            return 'The VM has not been checked recently; check the VM connection first.', False
        if not node_available(state, lab, node):
            return 'The device is not running.', False
        if not effective_credentials(lab, node).get('username'):
            return 'Give the device a login first.', False
        if checks.get((lab['id'], name)) != 'reachable':
            return 'Log in to the device first (Test logins).', False
        with self.lock:
            if (lab['id'], name) in self.inflight:
                return 'A removal is already running for this device.', False
        return '', False

    def checks(self, lab_id):
        with self.services.lock:
            return {key: (value or {}).get('status') for key, value in self.services.checks.items() if key[0] == lab_id}

    def lab(self, lab_id):
        """The lab with a retired record (call under the store lock), or 404."""
        lab = self.store.lab(lab_id)
        if not lab:
            raise HTTPException(404, 'Lab not found')
        if not public_retired_telemetry(lab):
            raise HTTPException(404, NO_RECORD)
        return lab

    def guard(self, state, lab, restore):
        """409 while anything else holds the lab: a removal, a lab operation, a restore or a backup."""
        lab_id = lab['id']
        with self.lock:
            if self.closed:
                raise HTTPException(503, STOPPING)
            running = lab_id in self.running or any(key[0] == lab_id for key in self.inflight)
        if running or lab['telemetry_retired'].get('removing'):
            raise HTTPException(409, 'A removal is already running for this lab.')
        if operation_busy(state, lab_id):
            raise HTTPException(409, 'Wait for the lab operation to finish.')
        if _restore_active(state, lab_id, restore):
            raise HTTPException(409, 'Wait for the configuration restore to finish.')
        if any(job.get('lab_id') == lab_id and job.get('status') in ('queued', 'running') for job in state.get('jobs', [])):
            raise HTTPException(409, 'Wait for the backup to finish.')

    def view(self, lab_id):
        checks = self.checks(lab_id)
        with self.store.lock:
            lab = self.lab(lab_id)
            record = lab['telemetry_retired']
            applied = _applied(record)
            nodes = {n.get('name'): n for n in lab['nodes']}
            rows = []
            for name in _order(lab, applied):
                entry = applied[name]
                reason, permanent = self.reason(self.store.state, lab, name, entry, checks)
                rows.append({'name': name, 'short_name': _short(nodes.get(name), name),
                             'kind': entry.get('kind') or (nodes.get(name) or {}).get('platform', '') or '',
                             'lines': list(entry['lines']), 'at': entry.get('at', ''), 'removable': not reason,
                             'permanent': permanent, 'reason': reason})
            return {'lab_id': lab_id, 'lab_name': lab.get('name', ''), 'nodes': rows, 'malformed': bool(record.get('malformed'))}

    def save(self, lab_id, name=''):
        try:
            self.store.save()
        except OSError:
            self.store.event('telemetry.retired.save_failed', 'The retired record could not be saved; check manager storage.',
                             level='warning', lab_id=lab_id, node=name)

    def clear(self, lab_id, name, lines):
        """Drop a node's ledger entry (only if it still records the lines acted on), then save."""
        with self.store.lock:
            lab = self.store.lab(lab_id)
            record = (lab or {}).get('telemetry_retired')
            if not isinstance(record, dict) or not isinstance(record.get('applied'), dict):
                return
            entry = record['applied'].get(name)
            if not isinstance(entry, dict) or entry.get('lines') != lines:
                return
            record['applied'].pop(name)
            _tidy(lab)
            self.save(lab_id, name)

    def release(self, lab_id):
        """Drop the lab's ``removing`` flag once neither the request nor any device session of it still runs."""
        with self.lock:
            if lab_id in self.running or any(key[0] == lab_id for key in self.inflight):
                return
        with self.store.lock:
            lab = self.store.lab(lab_id)
            record = (lab or {}).get('telemetry_retired')
            if not isinstance(record, dict) or 'removing' not in record:
                return
            record.pop('removing')
            _tidy(lab)
            self.save(lab_id)

    def remove_node(self, lab_id, name, node, creds, platform, lines):
        """One node's removal in the pool; never raises. Returns the result row."""
        driver = DRIVERS[platform]
        deadline = time.monotonic() + NODE_SECONDS
        try:
            try:
                channel, close = open_channel(self.services, node, creds)
            except HTTPException:
                outcome, message = 'failed', SLOT
            except paramiko.AuthenticationException:
                outcome, message = 'failed', LOGIN
            except Exception:
                outcome, message = 'failed', SSH_FAILED
            else:
                try:
                    shell = driver.shell(channel)
                    shell.deadline = deadline
                    try:
                        driver.reach(shell, creds)
                    except (RestoreError, OSError, EOFError, paramiko.SSHException):
                        raise Refused(NO_ANSWER)
                    outcome, message = retire(shell, driver, lines)
                except Refused as refused:
                    outcome, message = 'failed', str(refused)
                except Exception:
                    outcome, message = 'failed', SSH_FAILED
                finally:
                    close()
            if outcome in ('removed', 'absent'):
                self.clear(lab_id, name, lines)
                self.store.event('telemetry.retired.' + outcome, message, lab_id=lab_id, node=name)
            else:
                self.store.event('telemetry.retired.failed', message, level='warning', lab_id=lab_id, node=name)
            return {'name': name, 'outcome': outcome, 'message': message}
        finally:
            with self.lock:
                self.inflight.discard((lab_id, name))
            self.release(lab_id)

    def remove(self, lab_id, choice, restore=None):
        checks = self.checks(lab_id)
        results, tasks, cleared = {}, [], []
        with self.store.lock:
            state = self.store.state
            lab = self.lab(lab_id)
            applied = _applied(lab['telemetry_retired'])
            if choice and choice not in applied:
                raise HTTPException(404, 'No lines are recorded for this device.')
            self.guard(state, lab, restore)
            order = [name for name in _order(lab, applied) if not choice or name == choice]
            nodes = {n.get('name'): n for n in lab['nodes']}
            for name in order:
                entry = applied[name]
                if redeployed_since(state, lab, entry):
                    cleared.append(name)
                    results[name] = {'name': name, 'outcome': 'absent', 'message': REDEPLOYED}
                    continue
                why, _ = self.reason(state, lab, name, entry, checks)
                if why:
                    results[name] = {'name': name, 'outcome': 'skipped', 'message': why}
                    continue
                node = nodes[name]
                tasks.append((name, copy.deepcopy(node), copy.deepcopy(effective_credentials(lab, node)), node['platform'],
                              list(entry['lines'])))
            if cleared or tasks:
                before = copy.deepcopy(lab['telemetry_retired'])
                record = lab['telemetry_retired']
                for name in cleared:
                    record['applied'].pop(name, None)
                if tasks:
                    record['removing'] = now()
                _tidy(lab)
                try:
                    self.store.save()
                except OSError:
                    lab['telemetry_retired'] = before
                    raise HTTPException(500, 'Could not save the change; nothing was removed.')
                if tasks:
                    with self.lock:
                        self.running.add(lab_id)
        for name in cleared:
            self.store.event('telemetry.retired.absent', REDEPLOYED, lab_id=lab_id, node=name)
        if tasks:
            try:
                futures = {}
                for name, node, creds, platform, lines in tasks:
                    with self.lock:
                        self.inflight.add((lab_id, name))
                    try:
                        futures[name] = self.pool.submit(self.remove_node, lab_id, name, node, creds, platform, lines)
                    except RuntimeError:
                        with self.lock:
                            self.inflight.discard((lab_id, name))
                        results[name] = {'name': name, 'outcome': 'failed', 'message': STOPPING}
                budget = (NODE_SECONDS + ABORT_GRACE + 30) * math.ceil(len(futures) / WORKERS) + 30 if futures else 0
                done, _ = wait(list(futures.values()), timeout=budget)
                for name, future in futures.items():
                    if future not in done:
                        results[name] = {'name': name, 'outcome': 'failed', 'message': TOO_LONG}
                        continue
                    try:
                        results[name] = future.result()
                    except CancelledError:
                        with self.lock:
                            self.inflight.discard((lab_id, name))
                        results[name] = {'name': name, 'outcome': 'failed', 'message': STOPPING}
                    except Exception:
                        results[name] = {'name': name, 'outcome': 'failed', 'message': SSH_FAILED}
            finally:
                with self.lock:
                    self.running.discard(lab_id)
                self.release(lab_id)
        with self.store.lock:
            lab = self.store.lab(lab_id) or {'nodes': []}
            remaining = _order(lab, _applied(lab.get('telemetry_retired')))
        return {'results': [results[name] for name in order if name in results], 'remaining': remaining}

    def forget(self, lab_id, node='', malformed=False, restore=None):
        """Drop a record the manager can never act on, without touching any device."""
        if bool(node) == bool(malformed):
            raise HTTPException(400, 'Choose one device or the malformed record to forget.')
        checks = self.checks(lab_id)
        with self.store.lock:
            state = self.store.state
            lab = self.lab(lab_id)
            record = lab['telemetry_retired']
            if node:
                applied = _applied(record)
                if node not in applied:
                    raise HTTPException(404, 'No lines are recorded for this device.')
            elif not record.get('malformed'):
                raise HTTPException(404, 'No malformed record is kept for this lab.')
            self.guard(state, lab, restore)
            before = copy.deepcopy(record)
            if node:
                reason, permanent = self.reason(state, lab, node, applied[node], checks)
                if not permanent:
                    raise HTTPException(409, 'Remove the lines from the device instead.')
                count = len(applied[node]['lines'])
                record['applied'].pop(node)
                message = (f"Forgot the record of {count} line{'' if count == 1 else 's'} the removed telemetry feature added, "
                           f'without changing the device: {reason}')
                forgotten = node
            else:
                reasons = sorted({item['reason'] for item in _malformed(record) if isinstance(item, dict) and isinstance(item.get('reason'), str)})
                record.pop('malformed')
                message = 'Forgot the malformed record of the removed telemetry feature' + (f" ({'; '.join(reasons)})" if reasons else '') + '.'
                forgotten = 'malformed'
            _tidy(lab)
            try:
                self.store.save()
            except OSError:
                lab['telemetry_retired'] = before
                raise HTTPException(500, 'Could not save the change; the record was kept.')
            remaining = _order(lab, _applied(lab.get('telemetry_retired')))
        self.store.event('telemetry.retired.forgotten', message, lab_id=lab_id, node=node)
        return {'forgotten': forgotten, 'remaining': remaining}

    def install(self, app):
        retirement = self

        class NodeChoice(BaseModel):
            model_config = ConfigDict(extra='forbid')
            node: str = Field(default='', max_length=200)

        class ForgetChoice(BaseModel):
            model_config = ConfigDict(extra='forbid')
            node: str = Field(default='', max_length=200)
            malformed: bool = False

        @app.get('/api/labs/{lab_id}/telemetry-retired')
        def retired(lab_id: str):
            return retirement.view(lab_id)

        @app.post('/api/labs/{lab_id}/telemetry-retired/remove')
        def remove(lab_id: str, data: NodeChoice):
            return retirement.remove(lab_id, data.node, getattr(app.state, 'restore', None))

        @app.post('/api/labs/{lab_id}/telemetry-retired/forget')
        def forget(lab_id: str, data: ForgetChoice):
            return retirement.forget(lab_id, data.node, data.malformed, getattr(app.state, 'restore', None))
