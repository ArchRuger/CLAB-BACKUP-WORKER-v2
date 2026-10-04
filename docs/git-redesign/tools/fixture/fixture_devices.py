"""Scripted devices and the scripted restore seam.

The real restore service runs unchanged: its preflight, the mandatory pre-restore backup, the per-device transaction with
its timed recovery, the confirmation on a fresh connection and the read-back verification are all `app/restore.py`. What the
fixture replaces is the device edge, at two seams the service already has:

* `RestoreService.connect` (the connector `_open` calls) hands each client its scripted device, or raises the error of an
  unreachable one, and
* `restore_drivers.for_platform` returns a scripted driver that wraps the real one (same kinds, format check and `compare`)
  and answers `pending`, `blocked`, `capture`, `apply_candidate`, `confirm` from the device model.

The pre- and post-restore backups and every Save capture read the same device model (see `backup_files`), so a load that
changes a device is visible to the next save, and a save with nothing changed is `unchanged`.
"""
import threading
import time

import paramiko

from app import restore_drivers
from app.restore_junos import FOREIGN_EDITS
from app.restore_shell import RestoreError

import fixture_content as content

ONE = {'one-failed': 'failed', 'one-rolled-back': 'rolled_back', 'one-uncertain': 'uncertain', 'one-unreachable': 'unreachable',
       'one-blocked': 'blocked', 'one-editing': 'blocked-editing', 'one-bad-login': 'bad-login'}
REJECTED = {'junos': 'error: syntax error near "protocols ospf"; the candidate configuration was not loaded.',
            'eos': "% Invalid input detected at '^' marker; the session was aborted.",
            'xr': "% Failed to commit one or more configuration items; the candidate was discarded."}


def copy_list(value):
    return list(value) if value is not None else None


class Device:
    def __init__(self, name, platform, label, config=None, statements=None):
        self.name, self.platform, self.label = name, platform, label
        self.family = content.family(platform)
        self.statements = statements
        self.config = config
        self.armed = None            # {'token', 'previous'} while a timed change awaits confirmation
        self.rank = 1
        self.down = False            # a device that never answers a connection (the first fixture's third Junos node)
        self.volatile = False        # the first fixture's behaviour: every capture differs (a comment line with the job), so every Save is a change

    def candidate(self):
        if self.family != 'junos':
            return self.config
        statements = self.statements if self.statements is not None else \
            [tuple(line[4:].split()) for line in self.config.splitlines() if line.startswith('set ')]
        return content.junos_hier(statements)

    def load_candidate(self, candidate):
        if self.family == 'junos':
            self.statements = content.junos_parse(candidate)
            self.config = content.junos_set(self.statements)
        else:
            self.config = candidate

    def replace_capture(self, text):
        self.config = text
        if self.family == 'junos':
            self.statements = [tuple(line[4:].split()) for line in text.splitlines() if line.startswith('set ')]


class Devices:
    def __init__(self, control):
        self.control = control
        self.lock = threading.RLock()
        self.nodes = {}
        self.steady = set()          # lab names whose captures are deterministic; the other labs keep the first fixture's drifting captures

    # --- the model -------------------------------------------------------------------------------------------------------

    def add(self, name, platform, label, tag='running', text=None):
        """A device running the configuration of `tag` (or `text`, a ready capture)."""
        if text is not None:
            device = Device(name, platform, label, config=text)
        elif content.family(platform) == 'junos':
            statements = content.junos_statements(label, platform, tag)
            device = Device(name, platform, label, config=content.junos_set(statements), statements=statements)
        else:
            device = Device(name, platform, label, config=content.indented_text(label, platform, tag))
        self.nodes[name] = device
        return device

    def add_for(self, lab_name, name, platform, label, tag='running'):
        device = self.add(name, platform, label, tag)
        device.volatile = lab_name not in self.steady
        return device

    def register_lab(self, lab, tag='running'):
        rank = 0
        for node in lab['nodes']:
            if node.get('platform') in content.PLATFORMS:
                rank += 1
                device = self.nodes.get(node['name']) or self.add_for(lab['name'], node['name'], node['platform'], content.short_name(node, lab['name']), tag)
                device.rank = rank

    def find(self, key):
        key = str(key)
        return next((d for d in self.nodes.values() if key in (d.name, d.label)), None)

    # --- what the controls say about a device ------------------------------------------------------------------------

    def outcome(self, device):
        """ok | failed | rolled_back | uncertain | unreachable | blocked | blocked-editing | bad-login | slow"""
        script = self.control.get('load_script') or {}
        for key in (device.name, device.label, '*'):
            if key in script:
                return script[key]
        preset = self.control.get('load_preset')
        if preset == 'slow':
            return 'slow'
        if preset in ONE:
            target = self.control.get('load_device') or 'xrv9k'
            if target in (device.name, device.label):
                return ONE[preset]
        return 'ok'

    def unreadable(self, device):
        listed = self.control.get('device_unreadable') or []
        return device.name in listed or device.label in listed or self.outcome(device) in ('unreachable', 'bad-login')

    # --- backups and saves read the device model -------------------------------------------------------------------

    def backup_files(self, node, job_id=''):
        """(capture text, restore candidate) of a node for a backup job, or None for a device the fixture does not model.
        Raises OSError for a device that cannot be read (the capture of that node fails)."""
        device = self.nodes.get(node['name'])
        if device is None:
            return None
        with self.lock:
            if self.unreadable(device):
                raise OSError('SSH login failed')
            capture, candidate = device.config, device.candidate()
            if device.volatile:
                mark = ('# ' if device.family == 'junos' else '! ') + 'saved as backup ' + job_id[:6] + '\n'
                capture += mark
            return capture, candidate

    def edit(self, device, add=(), remove=()):
        """Add and remove configuration lines on a device, so the next Save reports exactly this change."""
        found = self.find(device)
        if not found:
            raise ValueError('No such device: ' + str(device))
        with self.lock:
            lines = [line for line in found.config.splitlines() if line.strip() not in {r.strip() for r in remove}]
            tail = [lines.pop()] if found.family != 'junos' and lines and lines[-1].strip() == 'end' else []
            lines += list(add) + tail
            found.replace_capture('\n'.join(lines) + '\n')
        return {'device': found.name, 'lines': len(lines)}

    def set_tag(self, device, tag):
        """Replace what a device runs with the configuration of a tag (action `device_config`)."""
        found = self.find(device)
        if not found:
            raise ValueError('No such device: ' + str(device))
        if tag not in content.LAYERS and tag != 'final':
            raise ValueError('Unknown configuration tag ' + str(tag) + '. Known: ' + ', '.join(sorted(set(content.LAYERS) | {'final'})))
        with self.lock:
            found.armed = None
            if found.family == 'junos':
                found.statements = content.junos_statements(found.label, found.platform, tag)
                found.config = content.junos_set(found.statements)
            else:
                found.config = content.indented_text(found.label, found.platform, tag)
        return {'device': found.name, 'tag': tag}

    def snapshot_initial(self):
        with self.lock:
            self.initial = {n: (d.config, copy_list(d.statements)) for n, d in self.nodes.items()}

    def reset(self):
        with self.lock:
            for name, (config, statements) in getattr(self, 'initial', {}).items():
                device = self.nodes[name]
                device.config, device.statements, device.armed = config, copy_list(statements), None

    # --- the connector -----------------------------------------------------------------------------------------------

    def connector(self, client, node, creds):
        device = self.nodes.get(node['name'])
        if device is None:
            raise OSError('fixture: no device answers here')
        outcome = self.outcome(device)
        if outcome == 'unreachable' or device.down:
            raise ConnectionError('fixture: no device here')
        if outcome == 'bad-login':
            raise paramiko.AuthenticationException('fixture: rejected')
        client._fixture_device = device


class ScriptedDriver:
    """The real driver's contract over the device model. Kinds, candidate validation and the comparison are the real driver's."""
    HOLDS_SESSION = False

    def __init__(self, real, devices):
        self.real, self.devices = real, devices
        self.SUPPORTED_KINDS, self.RESTORE_FORMAT = real.SUPPORTED_KINDS, real.RESTORE_FORMAT
        self.validate_candidate, self.compare = real.validate_candidate, real.compare

    @staticmethod
    def device(client):
        return client._fixture_device

    def pending(self, client, **_kw):
        device = self.device(client)
        with self.devices.lock:
            outcome = self.devices.outcome(device)
            if outcome == 'blocked':
                return 'clabmgr-somebody-elses-change'
            if device.armed and outcome == 'rolled_back':
                # The timer ran out before anything confirmed: the node undid the change by itself.
                device.replace_capture(device.armed['previous'])
                device.armed = None
            return device.armed['token'] if device.armed else ''

    def blocked(self, client, **_kw):
        device = self.device(client)
        return FOREIGN_EDITS if self.devices.outcome(device) == 'blocked-editing' else ''

    def capture(self, client, **_kw):
        return self.device(client).config

    def apply_candidate(self, client, candidate, confirm_minutes, token=None, **_kw):
        device = self.device(client)
        outcome = self.devices.outcome(device)
        if outcome == 'failed':
            raise RestoreError(REJECTED[device.family])
        if outcome == 'slow':
            time.sleep(device.rank * float(self.devices.control.get('load_seconds') or 5))
        with self.devices.lock:
            wanted = content.candidate_to_capture(device.platform, candidate)
            previous = device.config
            if self.compare(wanted, previous) == ([], []):
                return {'diff': '', 'no_op': True, 'handle': {}}
            old, new = set(previous.splitlines()), set(wanted.splitlines())
            diff = '\n'.join(['[edit]'] + ['- ' + l for l in previous.splitlines() if l not in new and l.strip()] +
                             ['+ ' + l for l in wanted.splitlines() if l not in old and l.strip()])
            if outcome == 'uncertain':
                device.replace_capture(content.odd_capture(device.platform, device.label, wanted))
                return {'diff': diff, 'no_op': False, 'handle': {'token': token}}
            device.armed = {'token': token, 'previous': previous}
            device.load_candidate(candidate)
            return {'diff': diff, 'no_op': False, 'handle': {'token': token}}

    def confirm(self, client, handle, **_kw):
        device = self.device(client)
        with self.devices.lock:
            if not device.armed or device.armed['token'] != (handle or {}).get('token'):
                raise RestoreError('The node did not confirm the commit; it will revert on its own.')
            device.armed = None
        return {'confirmed': True, 'saved': True}

    def persist(self, client, **_kw):
        return True

    def cleanup(self, client, **_kw):
        return []


def install(app, devices):
    """Point the real restore service at the scripted devices."""
    restore = app.state.restore
    restore.connect = devices.connector
    restore.connect_pause = 0.1      # an unreachable device is retried three times: do not wait 3 s between tries
    restore.retry_interval = 1
    restore.recovery_grace = 3
    real_for_platform = restore_drivers.for_platform
    wrappers = {}

    def for_platform(platform):
        real = real_for_platform(platform)
        if real is None:
            return None
        return wrappers.setdefault(id(real), ScriptedDriver(real, devices))
    restore_drivers.for_platform = for_platform
