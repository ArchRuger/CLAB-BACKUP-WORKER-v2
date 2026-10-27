"""Reviewed lab-level actions with review tokens and persistent job output."""
import copy
import difflib
import json
import re
import socket
import threading
import time
import uuid
from contextlib import contextmanager
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote

import paramiko
from fastapi import HTTPException
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field

from .discovery import PinnedHostKey, vm_password, parse_definition, register_definition, stamp, expected_container, lab_status, discovery_fresh
from .host_operations import IMAGE_CHECK_LIMIT, LOCK_SENTENCE, NODE_ACTIONS, OPTION_ACTIONS, container_matches, image_reference
from .inventory import ALIASES, read_data
from .topology import parse_drawing
from .drawio_export import drawio
from .layout import MAX_DOCUMENT, annotations, decorations, keep_document, map_document, revision

BUSY = ('queued', 'running')
# The actions that run through the helper's stream() and so die with the SSH channel: the only ones a person can stop.
# create, delete, publish and revise write first and answer once at the end; inspect is one short read.
# status.js STATUS_STOPPABLE is the same list (a test pins the two equal).
STOPPABLE = ('deploy', 'redeploy', 'destroy', 'apply', 'start', 'stop', 'restart', 'restart-node', 'start-node', 'stop-node', 'save', 'clone', 'inspect-all')
# action -> (how far the lab may have got, what repairs it); status.js STATUS_STOP_AFTERMATH holds the same words.
STOP_AFTERMATH = {
    'deploy': ('started', 'Redeploy lab'), 'redeploy': ('started', 'Redeploy lab'), 'apply': ('started', 'Redeploy lab'),
    'start': ('started', 'Redeploy lab'), 'restart': ('started', 'Redeploy lab'),
    'destroy': ('removed', 'run Destroy lab again'), 'stop': ('stopped', 'run Stop devices again'),
    'restart-node': ('started', 'Restart device again (Redeploy lab also works but clears unsaved configuration on every device)'),
    'start-node': ('started', 'Start device again'), 'stop-node': ('stopped', 'Stop device again (or Start device if it should run)'),
    'save': ('', 'run Save device configurations again'), 'clone': ('', 'run Download lab again'), 'inspect-all': ('', 'run it again'),
}
STOP_LABELS = {'deploy': 'Start lab', 'redeploy': 'Redeploy lab', 'destroy': 'Destroy lab', 'apply': 'Apply topology changes', 'start': 'Start devices',
               'stop': 'Stop devices', 'restart': 'Restart all devices', 'restart-node': 'Restart device', 'start-node': 'Start device', 'stop-node': 'Stop device', 'save': 'Save device configurations',
               'clone': 'Download lab', 'inspect-all': 'Running labs on the VM'}
STOP_ASKED = 'Stopping… the manager has asked the lab VM to end the command'
STOP_UNPROVEN = 'The lab VM is still ending the command; wait a moment before the next operation.'
# What host_operations.main() answers for any error it did not word itself (a missing config, a bad request, a crash):
# it can come from before the host lock was taken, so it proves nothing about the command having ended.
GENERIC_HELPER_ERROR = 'Host operation failed. Check setup, paths and installed tools.'
FOLLOW_UP_LIMIT = 20


class OperationStopped(ValueError):
    """A person (or the shutdown) ended the operation while the helper had not yet answered: the outcome is not known.
    `sent` is False when the stop came before the request was handed to the VM (nothing can have run)."""
    sent = True


def stop_message(action):
    verb, repair = STOP_AFTERMATH.get(action, ('', 'run it again'))
    label = STOP_LABELS.get(action, action)
    return 'You stopped ' + label + '. ' + ('The lab may be only partly ' + verb + ': ' + repair + '.' if verb else 'Afterwards: ' + repair + '.')


class StopCondition:
    """What remote() polls: the manager's shutdown or this one job's stop request."""
    def __init__(self, stopping, event): self.stopping = stopping; self.event = event
    def is_set(self): return self.stopping.is_set() or bool(self.event and self.event.is_set())
GIT_BUSY = ('queued', 'capturing', 'exporting', 'pushing')
# A live restore holds the lab the same way a Git save does. progress_id excludes the
# restore job's own id so its pre/post backups are not blocked by itself.
RESTORE_BUSY = ('queued', 'preflight', 'backing_up', 'applying', 'confirming', 'verifying')
# A network-design apply holds the lab like a restore does (its own pre/post backups pass its id as progress_id).
DESIGN_APPLY_BUSY = ('queued', 'preflight', 'backing_up', 'applying', 'confirming', 'verifying')


def restore_awaits_recheck(target):
    """A restore target a manager restart caught mid-change and nobody has read back yet: 'interrupted' with the
    token its change was armed under (or the restart's own mark) and no final outcome. A target interrupted before
    it was changed carries neither; jobs stored before stages existed have no timeline."""
    return (isinstance(target, dict) and target.get('status') == 'interrupted' and
            bool(target.get('_token') or target.get('_recheck')) and 'settled' not in (target.get('timeline') or {}))


def restore_holds_lab(job):
    """A restore holds its lab while it runs and, after a restart, until every node it was changing has been read
    back: such a node may still run an unconfirmed change that the device is about to undo."""
    return job.get('status') in RESTORE_BUSY or (job.get('status') == 'interrupted' and
                                                 any(restore_awaits_recheck(t) for t in job.get('targets') or []))


def design_rechecking(state, lab_id=None):
    """A network-design apply whose devices are still being read back after a manager restart (`rechecking`): of this lab,
    or of any lab when none is named. `operation_busy` holds only the lab it is asked about with it; a caller that acts
    on one lab but asks `operation_busy` without one asks this as well."""
    return any(j.get('rechecking') and (not lab_id or j.get('lab_id') == lab_id) for j in state.get('design_jobs', []))


def operation_busy(state, lab_id=None, progress_id=None):
    return (any(j['status'] in BUSY and (not lab_id or not j.get('lab_id') or j['lab_id'] == lab_id)
                for j in state.get('operations', [])) or
            any(j['status'] in DESIGN_APPLY_BUSY and j.get('id') != progress_id and
                (not lab_id or not j.get('lab_id') or j['lab_id'] == lab_id)
                for j in state.get('design_jobs', [])) or
            # The read-back after a restart (`rechecking`, up to the device's own timer) holds its own lab only:
            # a check that names no lab (background discovery, Git's idle check) is not held by it (audit L-15).
            bool(lab_id and design_rechecking(state, lab_id)) or
            any(j['status'] in GIT_BUSY and j.get('id') != progress_id and
                (not lab_id or not j.get('lab_id') or j['lab_id'] == lab_id)
                for j in state.get('git_jobs', [])) or
            any(restore_holds_lab(j) and j.get('id') != progress_id and
                (not lab_id or not j.get('lab_id') or j['lab_id'] == lab_id)
                for j in state.get('restore_jobs', [])) or
            # Removing the lines the retired telemetry feature added holds the lab while it configures its devices.
            any(isinstance(l.get('telemetry_retired'), dict) and l['telemetry_retired'].get('removing') and
                (not lab_id or l.get('id') == lab_id) for l in state.get('labs', [])))


def operation_connection_error(status, stderr):
    """Explain known gateway failures without exposing remote stderr or secrets."""
    diagnostic = stderr.decode('utf-8', errors='replace').lower()
    if 'sudo:' in diagnostic and any(value in diagnostic for value in (
            'a password is required', 'not allowed', 'not in the sudoers', 'no tty present')):
        return ('Operations gateway could not obtain its restricted sudo permission. '
                'Run sudo bash deploy/start-manager.sh --enable-operations on the VM.')
    if 'clab-manager-operations' in diagnostic and any(value in diagnostic for value in (
            'not found', 'no such file', 'unknown command')):
        return ('The clab-discovery SSH session did not run the operations gateway '
                '(its operations command was not found). On the VM, run '
                'sudo bash deploy/start-manager.sh --enable-operations from the matching '
                'source, then reconnect. This does not indicate a wrong password; discovery '
                'uses the same clab-discovery account.')
    detail = 'no SSH exit status' if status == -1 else 'SSH exit ' + str(status)
    return ('Operations helper did not return a complete successful response (' + detail + '). '
            'Run sudo bash deploy/check-install.sh on the VM and review the operations checks.')


def unsent_stop():
    failure = OperationStopped('Operation stopped. Inspect the lab before retrying.'); failure.sent = False
    return failure


def remote(host, request, output=None, stopping=None, timeout=None):
    if not host or not host.get('enabled'): raise ValueError('Configure and enable the VM connection first.')
    if not host.get('fingerprint'): raise ValueError('Refresh discovery to establish the VM fingerprint first.')
    password = vm_password(host)
    client = paramiko.SSHClient(); client.set_missing_host_key_policy(PinnedHostKey(host['fingerprint']))
    opts = dict(hostname=host['address'], port=host['port'], username=host['username'], timeout=8,
                auth_timeout=8, banner_timeout=8, allow_agent=False, look_for_keys=False)
    opts['password'] = password
    try:
        client.connect(**opts)
        if stopping and stopping.is_set(): raise unsent_stop()
        client.get_transport().set_keepalive(15)
        channel = client.get_transport().open_session(timeout=8); channel.settimeout(15)
        if stopping and stopping.is_set(): raise unsent_stop()
        channel.exec_command('clab-manager-operations')
        channel.sendall((json.dumps(request) + '\n').encode()); channel.shutdown_write()
        channel.settimeout(.2)
        until = time.monotonic() + (timeout if timeout is not None else 1250 if request.get('mode') == 'run' else 180)
        pending = b''; result = None; total = 0; stderr = b''; eof = False
        while True:
            if time.monotonic() > until: raise ValueError('Operation connection interrupted. Inspect the lab before retrying.')
            # Only while the helper has said nothing final: once its result line is in, the loop runs to EOF and
            # exit status, and a command that completed is never relabelled as stopped.
            # What has already arrived is read first: a result or error line waiting in the channel is the answer, not a stop.
            if result is None and stopping and stopping.is_set() and not channel.recv_ready(): raise OperationStopped('Operation stopped. Inspect the lab before retrying.')
            if channel.recv_stderr_ready():
                chunk = channel.recv_stderr(65536)
                stderr = (stderr + chunk)[:8192]
                total += len(chunk)
                if total > 5 * 1024 * 1024: raise ValueError('Host operation response exceeded its limit.')
            if not eof:
                try: chunk = channel.recv(65536)
                except socket.timeout: continue
                eof = not chunk
                pending += chunk; total += len(chunk)
                if len(pending) > 3 * 1024 * 1024 or total > 5 * 1024 * 1024: raise ValueError('Host operation response exceeded its limit.')
                while b'\n' in pending:
                    line, pending = pending.split(b'\n', 1)
                    try: item = json.loads(line)
                    except ValueError: raise ValueError('Operations helper is unavailable or outdated. Run start-manager.sh --enable-operations on the VM.')
                    if not isinstance(item, dict): raise ValueError('Invalid operations helper response.')
                    if 'error' in item:
                        failure = ValueError(str(item['error'])[:1000]); failure.from_helper = True
                        raise failure
                    if output and 'output' in item: output(str(item['output']))
                    if 'result' in item: result = item['result']
            # Exit status is metadata, not EOF. Some servers deliver it before
            # the last stdout packets; recv_ready() only describes the current buffer.
            if eof and not channel.recv_stderr_ready() and channel.exit_status_ready(): break
            if eof: time.sleep(.03)
        status = channel.recv_exit_status()
        if status != 0 or pending or not isinstance(result, dict):
            raise ValueError(operation_connection_error(status, stderr))
        return result
    finally: client.close()


DEPLOY_ACTIONS = ('deploy', 'redeploy')
# The operations that change which containers a lab has, or their state: a Restart device review made
# before one of them ran is stale, whatever the helper's digest still says (a lab-wide restart keeps every
# container id and state, so only the manager can tell that the device was already restarted since).
LIFECYCLE_JOBS = ('deploy', 'redeploy', 'destroy', 'apply', 'start', 'stop', 'restart', 'restart-node', 'start-node', 'stop-node')


# Images whose container cannot be started a second time, proven live on the development VM: the restart
# command succeeds, the container exits at once, and only a redeploy recreates the device. Named in the
# review so the student decides knowingly; the job itself reports the exit afterwards (settled_after_restart).
RESTART_KNOWN_LIMITS = {
    'juniper_vjunosswitch': 'Known limit of the vJunos-switch image: its container cannot be started a second time (the launcher renames '
                            'its init.conf on the first start and fails without it), so this restart leaves the device stopped until '
                            'you redeploy the lab. Proven on vjunos-switch 23.2R1.14 with containerlab 0.79.0.',
    'cisco_xrv9k': 'Known limit of the XRv9k image: its launcher picks the VM disk by file name at every start, and after '
                   'the first start a second copy of the pristine image sorts first, so the first restart after a deploy boots '
                   'the device from a fresh disk: it comes back Ready with its factory configuration and everything configured '
                   'since the deploy is gone (proven on cisco_xrv9k 24.3.1 with containerlab 0.79.0). Back up the configuration '
                   'first and use Replace running configuration afterwards.',
}


# The same images when the device is stopped rather than restarted (Stop device's review).
STOP_KNOWN_LIMITS = {
    'juniper_vjunosswitch': 'Known limit of the vJunos-switch image: its container cannot be started a second time, so after this stop only '
                            'Redeploy lab brings the device back (Start device and Restart device leave it stopped).',
    'cisco_xrv9k': 'Known limit of the XRv9k image: the next start boots the device from a fresh disk, so it comes back with its factory '
                   'configuration and everything configured since the deploy is gone. Back up the configuration first.',
}
# The run options as a person names them, for the refusal of an option an action does not take.
OPTION_LABELS = {'nodes': 'Choose devices', 'max_workers': 'Max workers', 'skip_post_deploy': 'Skip post-deploy', 'keep_mgmt_net': 'Keep the management network',
                 'deployed': 'Save while deployed'}
# The node actions and what a device shows while one of them is queued or running: (nos_login status, message).
NODE_ACTION_STATUS = {
    'restart-node': ('restarting', 'Restarting on the VM (containerlab restart --node); its login is checked again afterwards.'),
    'start-node': ('starting', 'Starting on the VM (containerlab start --node); its login is checked again afterwards.'),
    'stop-node': ('stopping', 'Stopping on the VM (containerlab stop --node).'),
}


def restart_links(lab, short):
    """What containerlab will have to restore for a node's restart, as the lab's drawing (parsed from the
    topology file) knows it: the number of dataplane links the node has, and the neighbours whose container is
    not running. containerlab restores a parked link only while its other end exists; a link to a neighbour that
    exited on its own stays missing, and the device then waits for the interface before it boots: cEOS for the five
    minutes containerlab's CLAB_INTFS gives it, a vrnetlab VM for good (QA-018)."""
    by_short = {}
    for n in lab.get('nodes') or []:
        for key in (n.get('definition_node'), n.get('short_name')):
            if key and key not in by_short: by_short[key] = n
    expected = 0; down = []; absent = []
    for pair in (lab.get('drawing') or {}).get('links') or []:
        if not isinstance(pair, list) or len(pair) != 2: continue
        ends = [str((ep or {}).get('node') or '') if isinstance(ep, dict) else '' for ep in pair]
        if short not in ends: continue
        expected += 1
        other = ends[1] if ends[0] == short else ends[0]
        peer = by_short.get(other) if other and other != short else None
        state = (peer or {}).get('runtime_state') or ''
        if peer is not None and state and state not in ('running', 'unknown'):
            label = peer.get('short_name') or peer.get('definition_node') or peer['name']
            # `absent`: the container is gone (destroyed, a filtered destroy included), not merely stopped.
            target = absent if state == 'absent' else down
            if label not in target: target.append(label)
    return expected, down, absent


def neighbour_note(action, shown, expected, down, absent):
    """The review notes about the neighbours of a device a node action touches (pure). Restart and Start: a neighbour that is
    stopped (its link may be parked or gone) and one that was destroyed (its link is gone until Apply recreates it) are two
    different sentences. Stop: the links are parked, not removed. Returns a list of sentences."""
    if action == 'stop-node':
        return ['Its links are parked, not removed: Start device or Restart device brings them back; a neighbour that restarts meanwhile keeps waiting for this link.']
    verb = 'start' if action == 'start-node' else 'restart'
    notes = []
    if down:
        who = ', '.join(down)
        notes.append('%s is not running. If it was stopped by the manager, the VS Code extension or containerlab stop, its link to %s is parked and comes back with this %s. '
                     'If it exited on its own or was stopped with docker stop, that link is gone: containerlab restores %s%s, and the device then waits for all its interfaces before it boots (cEOS gives up waiting after five minutes, a VM-based image waits for good) and stays at Starting until %s runs again. '
                     'Start %s first (%s on it takes the start/restore path), then this device, or redeploy the lab.'
                     % (who, shown, verb, 'only %d of %d links' % (expected - len(down) - len(absent), expected) if expected > len(down) + len(absent) else 'no link',
                        ' and the job says so', who, who, 'Start device' if action == 'start-node' else 'Restart device…'))
    if absent:
        who = ', '.join(absent)
        notes.append('%s %s removed from the VM (destroyed, not stopped): its link to %s is gone until Apply topology changes recreates %s; %s may wait for that interface before it boots. '
                     'Apply topology changes first (Lab actions ▾), then %s this device.'
                     % (who, 'was' if len(absent) == 1 else 'were', shown, who if len(absent) == 1 else 'them', shown, verb))
    return notes


def restarting_nodes(state, lab_id):
    """{manager node name: action} of this lab's devices with a Restart, Start or Stop device job queued or running right now."""
    return {j['node']: j['action'] for j in state.get('operations', [])
            if j.get('lab_id') == lab_id and j.get('action') in NODE_ACTIONS and j.get('status') in BUSY and j.get('node')}


def last_deployed(state, lab):
    """When this manager last deployed the lab, or ''. The lab's own record first; for a lab deployed before
    that record existed, the newest succeeded deploy in the (capped) operation history. A lab that was
    deployed from a terminal, or whose history is gone, has none: the page must not invent one."""
    known = lab.get('last_deployed') or ''
    if known: return known
    stamps = [j.get('finished') or '' for j in state.get('operations', [])
              if j.get('lab_id') == lab.get('id') and j.get('action') in DEPLOY_ACTIONS and j.get('status') == 'succeeded']
    return max(stamps, default='')


OUTPUT_LIMIT = 512 * 1024


def secret_values(state):
    """The stored credentials scrub() replaces, each once, longest first."""
    host = state.get('host', {}); secrets = [host.get(k, '') for k in ('password', 'passphrase', 'private_key')]
    for lab in state['labs']:
        for item in lab.get('nodes', []) + lab.get('profiles', []):
            secrets += [item.get(k, '') for k in ('password', 'passphrase', 'private_key', 'enable_password')]
    return sorted(dict.fromkeys(filter(None, secrets)), key=len, reverse=True)


def scrub(text, state):
    for secret in secret_values(state): text = text.replace(secret, '[redacted]')
    text = re.sub(r'\x1b\[[0-9;]*[A-Za-z]', '', text)
    text = re.sub(r'(?s)-----BEGIN [^-]*PRIVATE KEY-----.*?(?:-----END [^-]*PRIVATE KEY-----|$)', '[private key omitted]', text)
    text = re.sub(r'(?im)^.*(?:password|passphrase|private.key|community|secret)\s*[:= ].*$', '[sensitive output omitted]', text)
    return text[-OUTPUT_LIMIT:]


class OutputWindow:
    """The last 512 KiB of an operation's streamed output, its stored secrets (secret_values(), longest first)
    replaced before the window cuts anything. Only the longest tail of the received text that is a proper prefix of
    a secret (at most max(len(secret)) - 1 characters, usually none after a line break) waits unscrubbed for the
    next chunk or the final flush, so a secret split between chunks is still matched whole, only redacted text is
    ever cut, and every line that cannot begin a secret is published at once. Adding a chunk costs its own length
    plus that tail (and at most one 4 KiB part), never the window; scrub() still runs on the whole window before it
    is published."""
    def __init__(self): self.carry = ''; self.covered = 0; self.parts = deque(); self.size = 0; self.cut = False; self.whole = False

    def add(self, chunk, secrets, final=False):
        text = self.carry + chunk; cut = len(text)
        # The tail held back: the leftmost start from which the rest of the text is a proper prefix of some secret. Each
        # secret is looked for only in its own last len(secret) - 1 characters and only left of the tail found so far:
        # by its first 16 characters where that much text is left, by its first character in the shorter remainder.
        for secret in () if final else secrets:
            low = max(len(text) - len(secret) + 1, 0); head = secret[:min(len(secret) - 1, 16)]
            if not head: continue  # a one-character secret has no proper prefix to wait for
            at = text.find(head, low, cut + len(head) - 1)
            while at >= 0 and not secret.startswith(text[at:]): at = text.find(head, at + 1, cut + len(head) - 1)
            if at < 0: at = text.find(secret[0], max(low, len(text) - len(head) + 1), cut)
            while at >= 0 and not secret.startswith(text[at:]): at = text.find(secret[0], at + 1, cut)
            if at >= 0: cut = at
        if not cut: self.carry = text; return
        # Every occurrence of every secret, overlapping ones too. One that starts before the cut ends inside this
        # text, so everything before the cut is decided; the head of the carry an earlier one covered stays covered.
        spans = [(0, self.covered)] if self.covered else []
        for secret in secrets:
            at = text.find(secret)
            while 0 <= at < cut: spans.append((at, at + len(secret))); at = text.find(secret, at + 1)
        runs = []
        for begin, end in sorted(spans):
            if runs and begin < runs[-1][1]: runs[-1][1] = max(runs[-1][1], end)
            else: runs.append([begin, end])
        done = 0
        for begin, end in runs:  # a run that continues one of the previous chunk already has its marker
            self.keep(text[done:begin] + ('' if begin == 0 and self.covered else '[redacted]')); done = end
        self.keep(text[done:cut]); self.covered = max(done - cut, 0); self.carry = text[cut:]

    def keep(self, text):
        if not text: return
        if self.parts and len(self.parts[-1]) < 4096: self.size -= len(self.parts[-1]); text = self.parts.pop() + text
        self.parts.append(text); self.size += len(text)
        while self.size - len(self.parts[0]) >= OUTPUT_LIMIT:
            dropped = self.parts.popleft(); self.size -= len(dropped); self.cut = True; self.whole = dropped.endswith('\n')

    def text(self):
        text = ''.join(self.parts); longer = len(text) > OUTPUT_LIMIT
        if not (longer or self.cut): return text
        # A window that lost its beginning starts at a whole line, so scrub()'s line rules see every line it keeps,
        # and a private key whose BEGIN line was cut off is omitted up to its END line.
        whole = text[-OUTPUT_LIMIT - 1] == '\n' if longer else self.whole; text = text[-OUTPUT_LIMIT:]
        if not whole and '\n' in text: text = text.partition('\n')[2]
        marker = re.search(r'-----(BEGIN|END) [^-]*PRIVATE KEY-----', text)
        return '[private key omitted]' + text[marker.end():] if marker and marker.group(1) == 'END' else text


def topology_images(text):
    """The container images a topology names, in the order of its nodes: [{reference, kind, nodes}], one entry
    per image (node image, else the kind's image, else the default; templated values are left out)."""
    try: topology = read_data(text.encode() if isinstance(text, str) else text).get('topology') or {}
    except (ValueError, TypeError, AttributeError, RecursionError): return []
    defaults = topology.get('defaults') if isinstance(topology.get('defaults'), dict) else {}
    kinds = topology.get('kinds') if isinstance(topology.get('kinds'), dict) else {}
    found = {}
    for node_name, node in (topology.get('nodes') or {}).items() if isinstance(topology.get('nodes'), dict) else []:
        node = node if isinstance(node, dict) else {}
        kind = node.get('kind') or defaults.get('kind')
        if not isinstance(kind, str): continue
        kind_settings = kinds.get(kind) if isinstance(kinds.get(kind), dict) else {}
        image = node.get('image') or kind_settings.get('image') or defaults.get('image')
        if not (isinstance(kind, str) and isinstance(image, str) and 0 < len(kind) <= 120 and 0 < len(image) <= 300 and '{{' not in image): continue
        entry = found.setdefault(image, {'reference': image, 'kind': kind, 'nodes': []})
        if isinstance(node_name, str) and len(entry['nodes']) < 50: entry['nodes'].append(node_name)
    return list(found.values())


CPTX_KIND = 'juniper_cjunosevolved'


def cptx_startup_warnings(text):
    """Review warnings for cJunosEvolved nodes that carry both env CPTX_AUTO_CONFIG and a startup-config: Juniper's
    entrypoint checks CPTX_AUTO_CONFIG first, so the startup-config is silently ignored on first boot. Settings are
    resolved the way containerlab does (node, then its group, then its kind, then the defaults; `env` maps merged
    across those levels). Read-only and silent on anything it cannot read: never refuses a topology."""
    try: topology = read_data(text.encode() if isinstance(text, str) else text).get('topology') or {}
    except (ValueError, TypeError, AttributeError, RecursionError): return []
    if not isinstance(topology, dict) or not isinstance(topology.get('nodes'), dict): return []
    def mapping(value): return value if isinstance(value, dict) else {}
    defaults = mapping(topology.get('defaults')); kinds = mapping(topology.get('kinds')); groups = mapping(topology.get('groups'))
    warnings = []
    for name, node in topology['nodes'].items():
        node = mapping(node)
        group = mapping(groups.get(node.get('group'))) if isinstance(node.get('group'), str) else {}
        kind = node.get('kind', group.get('kind', defaults.get('kind')))
        if kind != CPTX_KIND: continue
        levels = (defaults, mapping(kinds.get(kind)), group, node)
        env = {}
        for level in levels: env.update(mapping(level.get('env')))
        startup = next((level['startup-config'] for level in reversed(levels) if 'startup-config' in level), None)
        auto = env.get('CPTX_AUTO_CONFIG')
        if auto is None or auto is False or (isinstance(auto, str) and not auto.strip()): continue
        if not (isinstance(startup, str) and startup.strip()): continue
        label = name if isinstance(name, str) and len(name) <= 120 else 'A cJunosEvolved node'
        warnings.append(label + ': CPTX_AUTO_CONFIG is set, so cJunosEvolved ignores its startup-config on first boot. Remove one of them.')
        if len(warnings) >= 50: break
    return warnings


# The vrnetlab kinds (a VM inside the container, its disk inside the container too) and cJunosEvolved: a recreate boots them
# from their image again. A restart's effect is proven only where RESTART_KNOWN_LIMITS says so (TOPOLOGY-EDIT-DESIGN A10).
VRNETLAB_KINDS = ('juniper_vjunosswitch', 'juniper_vjunosrouter', 'juniper_vsrx', 'juniper_vqfx', 'cisco_xrv9k')
RECREATE_LOSES_CONFIGURATION = VRNETLAB_KINDS + (CPTX_KIND,)
RECREATE_LIMIT = 'A recreated device boots from its image again: configuration not saved is lost.'
RESTART_UNVERIFIED = "The effect of this restart on the device's configuration is not verified on this kind; back it up first."
# What a changed definition is named by in the deployed-save review, in this order.
DEFINITION_FIELDS = (('kind', 'kind'), ('image', 'image'), ('env', 'environment'), ('startup-config', 'startup configuration'))
MAP_CHANGED_SENTENCE = 'The map changed in the manager since you opened Edit topology. Reopen it; your topology changes stay in this browser.'
REGISTER_ACTIONS = ('apply', 'deploy', 'redeploy')


def canonical_kind(kind):
    return ALIASES.get(kind, kind) if isinstance(kind, str) else ''


def plan_limits(text, plan):
    """{device: sentence} for the plan's `restarted` and `recreated` devices whose kind (from the topology text the plan was
    made from) has a known or unverified configuration effect; {} when the text cannot be read. Pure."""
    if not isinstance(plan, dict): return {}
    try: kinds = {n['definition_node']: canonical_kind(n.get('kind')) for n in parse_definition(text.encode() if isinstance(text, str) else text)['nodes']}
    except (ValueError, TypeError, AttributeError, KeyError, RecursionError): return {}
    limits = {}
    for name in plan.get('recreated') or []:
        if isinstance(name, str) and kinds.get(name) in RECREATE_LOSES_CONFIGURATION: limits[name] = RECREATE_LIMIT
    for name in plan.get('restarted') or []:
        if not isinstance(name, str) or name in limits: continue
        kind = kinds.get(name, '')
        sentence = RESTART_KNOWN_LIMITS.get(kind) or (RESTART_UNVERIFIED if kind in VRNETLAB_KINDS else '')
        if sentence: limits[name] = sentence
    return dict(sorted(limits.items()))


def annotate_plan(text, plan):
    """The plan with its `limits` (plan_limits) added, and the devices to back up first: every sentence in `limits` says the
    device's configuration is lost or may be lost. Returns (plan, backup_first); the plan is a new dict."""
    if not isinstance(plan, dict): return plan, []
    limits = plan_limits(text, plan)
    return {**plan, 'limits': limits}, sorted(limits)


def definition_settings(text):
    """{node: {kind, image, env, startup-config}} as containerlab resolves them (node, then its group, then its kind, then
    the defaults; `env` merged across those levels), for the comparison of two versions of one topology. {} when unreadable."""
    try: topology = read_data(text.encode() if isinstance(text, str) else text).get('topology') or {}
    except (ValueError, TypeError, AttributeError, RecursionError): return {}
    if not isinstance(topology, dict) or not isinstance(topology.get('nodes'), dict): return {}
    def mapping(value): return value if isinstance(value, dict) else {}
    defaults = mapping(topology.get('defaults')); kinds = mapping(topology.get('kinds')); groups = mapping(topology.get('groups'))
    found = {}
    for name, node in topology['nodes'].items():
        if not isinstance(name, str): continue
        node = mapping(node)
        group = mapping(groups.get(node.get('group'))) if isinstance(node.get('group'), str) else {}
        kind = node.get('kind', group.get('kind', defaults.get('kind')))
        levels = (defaults, mapping(kinds.get(kind)) if isinstance(kind, str) else {}, group, node)
        env = {}
        for level in levels: env.update(mapping(level.get('env')))
        found[name] = {'kind': kind, 'image': next((l['image'] for l in reversed(levels) if 'image' in l), None), 'env': env,
                       'startup-config': next((l['startup-config'] for l in reversed(levels) if 'startup-config' in l), None)}
    return found


def deployed_save_warnings(old_text, new_text, affected, lab_names, dry_run):
    """The manager's sentences of a deployed save (TOPOLOGY-EDIT-DESIGN A8, A13, R11), from digested inputs only: the helper's
    `affected` containers, the VM file the review read and the text being saved; never from discovery. `lab_names` are the
    names the containers may carry (the deployment, the topology). `dry_run` False adds that Apply cannot be planned."""
    try:
        old = parse_definition(old_text.encode() if isinstance(old_text, str) else old_text)
        new = parse_definition(new_text.encode() if isinstance(new_text, str) else new_text)
    except (ValueError, TypeError, AttributeError, KeyError, RecursionError): old = new = None
    warnings = []
    if old and new:
        containers = [str(a.get('name') or '') for a in affected if isinstance(a, dict)]
        names = [n for n in dict.fromkeys(lab_names) if n]
        def on_vm(short): return any(container_matches(c, lab, short) for c in containers for lab in names)
        old_names = [n['definition_node'] for n in old['nodes']]; new_names = {n['definition_node'] for n in new['nodes']}
        removed = [n for n in old_names if n not in new_names and on_vm(n)]
        before = definition_settings(old_text); after = definition_settings(new_text)
        def key(short, settings): return json.dumps(settings.get(short) or {}, sort_keys=True, default=str)
        # A rename is a device the new file no longer defines whose definition reappears, unchanged, under exactly one new
        # name nobody else shares: applying removes the old device and creates the new one (a new device to its history).
        added = [n['definition_node'] for n in new['nodes'] if n['definition_node'] not in set(old_names)]
        renamed = {}
        for short in removed:
            twins = [a for a in added if key(a, after) == key(short, before)]
            others = [r for r in removed if key(r, before) == key(short, before)]
            if len(twins) == 1 and len(others) == 1: renamed[short] = twins[0]
        changed = []
        for short in old_names:
            if short in renamed: changed.append(short + ' (renamed to ' + renamed[short] + ')'); continue
            if short not in new_names or not on_vm(short): continue
            fields = [label for field, label in DEFINITION_FIELDS if (before.get(short) or {}).get(field) != (after.get(short) or {}).get(field)]
            if fields: changed.append(short + ' (' + ', '.join(fields) + ')')
        gone = [n for n in removed if n not in renamed]
        if gone:
            warnings.append('Running devices the new file does not define: ' + ', '.join(gone) + '. They keep running until the changes are applied; '
                            'applying removes them and their unsaved configuration.')
        if changed:
            warnings.append('Devices whose definition changed: ' + ', '.join(changed) + '. Applying recreates them; configuration not saved is lost then. '
                            'Use Save in the lab header first to keep it.')
    if dry_run is False: warnings.append('The installed containerlab cannot show what applying will change.')
    return warnings


class LabOperations:
    def __init__(self, store, discovery, readiness=None):
        # readiness: the ReadinessMonitor, so a Restart device job can drop the device's proven login
        # (its readiness epoch) when the restart is accepted and again when it has run.
        self.store = store; self.discovery = discovery; self.readiness = readiness; self.previews = {}; self.stopping = threading.Event()
        self.cancels = {}   # operation id -> threading.Event, set by the stop route and by close()
        self.pool = ThreadPoolExecutor(max_workers=1); self.cap_cache = None; self.active = set()
        # Impairment calls in flight (impairments.py registers them through impairing()): guard() refuses a preview or confirm
        # while one holds the host lock, so a job is never created only to meet the helper's lock sentence.
        self.in_flight_impairments = set()
        # The pending-changes plan per lab (impairments.py serves it): lab id -> (expires, answer). A generation per lab keeps an
        # answer that was being computed while the lab changed from being stored after forget_plan().
        self.plan_cache = {}; self.plan_gen = {}; self.plan_lock = threading.Lock()
        # Image questions are read-only and repeat (every builder edit, every review): the VM's image list is kept for
        # a minute and each reference's answer for a while, so the helper is asked once per question, not per page.
        self.images_cache = None; self.image_cache = {}; self.image_lock = threading.Lock()
        # One image question on the VM at a time: tabs and reviews that miss the cache together queue here
        # instead of each opening an SSH session and four Docker processes.
        self.image_flight = threading.Lock()
        # Undo of Arrange devices (C06): lab id -> (the arranged drawing's revision, the lab's map keys before it, a digest
        # of the map keys right after it). Process memory only, never persisted: one entry per lab, read and written under
        # the store lock, gone on restart.
        self.arrange_undo = {}
        with store.lock:
            for job in store.state.setdefault('operations', []):
                if job['status'] in BUSY:
                    job.update(status='interrupted', message='Manager restarted; inspect the VM before retrying.')
            store.save()

    def close(self):
        # The manager-wide flag first: execute() reads it before it classifies a stop, so a shutdown racing a stop is `interrupted`.
        self.stopping.set()
        with self.store.lock:
            for event in list(self.cancels.values()): event.set()
        self.pool.shutdown(wait=False, cancel_futures=True)

    def host(self):
        with self.store.lock: return copy.deepcopy(self.store.state.get('host', {}))

    def guard(self, lab_id=''):
        # operation_busy without a lab holds every lab for the others' work; a design apply's read-back after a restart
        # holds only its own lab, so a named lab asks for it too (a Restart device under it would decide its outcome).
        if self.active or self.in_flight_impairments or operation_busy(self.store.state) or (lab_id and design_rechecking(self.store.state, lab_id)):
            raise HTTPException(409, 'Wait for the current lab operation to finish.')
        if any(j['status'] in BUSY and (not lab_id or j['lab_id'] == lab_id) for j in self.store.state['jobs']):
            raise HTTPException(409, 'Wait for the lab backup or login job to finish.')

    @contextmanager
    def impairing(self, lab_id):
        """An impairment call in flight: refused (guard's two sentences) while any job, restore, Git save or design apply holds
        the lab, and visible to guard() for as long as the call runs."""
        token = object()
        with self.store.lock:
            self.guard(lab_id)
            self.in_flight_impairments.add(token)
        try: yield
        finally:
            with self.store.lock: self.in_flight_impairments.discard(token)

    def forget_plan(self, lab_id):
        """Drop the lab's cached pending-changes plan (and make any answer still being computed unstorable)."""
        with self.plan_lock:
            self.plan_cache.pop(lab_id, None); self.plan_gen[lab_id] = self.plan_gen.get(lab_id, 0) + 1

    def capabilities(self):
        """The helper's capabilities, kept for a minute per VM connection revision."""
        host = self.host(); key = host.get('revision')
        if self.cap_cache and self.cap_cache[0] == key and self.cap_cache[1] > time.monotonic(): return self.cap_cache[2]
        result = self.invoke({'mode': 'capabilities'})
        self.cap_cache = (key, time.monotonic() + 60, result)
        return result

    def invoke(self, req):
        try: return remote(self.host(), req)
        except Exception as exc:
            message = str(exc) if type(exc) is ValueError else 'Cannot reach the VM operations helper. Check setup and SSH settings.'
            raise HTTPException(409, message)

    def install(self, app):
        class Request(BaseModel):
            model_config = ConfigDict(extra='forbid')
            action: str = Field(default='', max_length=60)
            lab_id: str = Field(default='', max_length=64)
            path: str = Field(default='', max_length=4096)
            name: str = Field(default='', max_length=120)
            options: dict = Field(default_factory=dict)
            # Restart device: the manager's own name of the device (its node record), never a command,
            # path or container id. The server resolves it to the topology node and its container.
            node: str = Field(default='', max_length=253)
            # Save changes to the VM (`revise`) from Edit topology: the revision of the lab's map document the page opened
            # (GET /api/labs/<id>/map-document). With lab_id, a map changed in the manager since then refuses the review.
            map_revision: str | None = Field(default=None, max_length=64)

        @app.get('/api/operations/capabilities')
        def capabilities(): return self.capabilities()

        # /api/operations/browse and /api/operations/images are owned by device_diagnostics.py (installed first):
        # browse gained a files mode and images its details there; the helper modes behind them are unchanged.

        @app.post('/api/operations/read')
        def read(data: Request):
            # The helper also reads configuration names and .md for the redacted viewer (device_diagnostics /view);
            # this raw route keeps the file types it always served.
            if not data.path.lower().endswith(('.yaml', '.yml', '.json', '.drawio', '.txt', '.cfg', '.conf', '.set')): raise HTTPException(409, 'This file type cannot be viewed in the manager.')
            return self.invoke({'mode': 'read', 'path': data.path})

        @app.get('/api/operations/popular')
        def popular(): return self.invoke({'mode': 'popular'})

        @app.get('/api/operations/known-images')
        def known_images():
            """Container images named by the topologies already in My labs, per kind. The lab builder
            offers them first, so a new lab starts from images this site is known to use."""
            found = {}
            with self.store.lock: texts = [l.get('definition_yaml') or '' for l in self.store.state['labs']]
            for text in texts:
                for entry in topology_images(text):
                    counts = found.setdefault(entry['kind'], {}); counts[entry['reference']] = counts.get(entry['reference'], 0) + len(entry['nodes'])
            return {'images': {kind: sorted(counts, key=lambda i: (-counts[i], i))[:12] for kind, counts in sorted(found.items())}}

        class ImageCheck(BaseModel):
            model_config = ConfigDict(extra='forbid')
            references: list[str] = Field(min_length=1, max_length=IMAGE_CHECK_LIMIT)

        @app.post('/api/operations/image-check')
        def image_check(data: ImageCheck):
            """Is each image on the VM, and if not, does its registry know it? Read-only; answers are cached
            (a found or local image an hour, an absent one half an hour, an unreachable registry two minutes)
            so the builder's background check and the reviews ask the VM once per image, and a registry's
            pull allowance is not spent on repeats. A name that is not an image reference is answered as
            `invalid` and never sent anywhere."""
            answers = {}; refs = []
            for raw in dict.fromkeys(data.references):
                try: refs.append(image_reference(raw))
                except ValueError: answers[raw] = {'reference': raw[:300], 'local': False, 'registry': 'invalid', 'detail': '', 'available': True}
            order = list(dict.fromkeys(data.references))
            host = self.host(); key = host.get('revision'); now = time.monotonic()
            with self.image_lock:
                self.image_cache = {k: v for k, v in self.image_cache.items() if v[1] > now and v[0] == key}
                answers.update({r: self.image_cache[r][2] for r in refs if r in self.image_cache})
            missing = [r for r in refs if r not in answers]
            if missing:
                with self.image_flight:
                    with self.image_lock: answers.update({r: self.image_cache[r][2] for r in missing if r in self.image_cache and self.image_cache[r][1] > time.monotonic()})
                    missing = [r for r in missing if r not in answers]
                    result = self.invoke({'mode': 'image-check', 'options': {'references': missing}}) if missing else {'images': []}
                    available = bool(result.get('available'))
                    for item in result.get('images', []):
                        if not isinstance(item, dict) or item.get('reference') not in missing: continue
                        local = item.get('local'); registry = str(item.get('registry', 'unknown'))
                        if registry not in ('found', 'not-found', 'unreachable', 'unknown', 'skipped'): registry = 'unknown'
                        answer = {'reference': item['reference'], 'local': local if isinstance(local, bool) else None, 'registry': registry,
                                  'detail': str(item.get('detail', ''))[:200] if registry == 'unknown' else '', 'available': available}
                        answers[item['reference']] = answer
                        ttl = 3600 if local or registry == 'found' else 1800 if registry == 'not-found' else 120
                        with self.image_lock: self.image_cache[item['reference']] = (key, time.monotonic() + ttl, answer)
            return {'images': [answers[r] for r in order if r in answers]}

        @app.post('/api/operations/parse-yaml')
        def parse_yaml(data: Request):
            invalid = (ValueError, TypeError, AttributeError, RecursionError)
            try:
                raw = str(data.options.get('text', '')).encode()
                parsed = parse_definition(raw)
            except invalid: raise HTTPException(400, 'Enter a valid literal Containerlab topology.')
            # The annotations file the VS Code extension keeps beside a topology carries the drawn node
            # positions and styling. When the browser found one it comes along here, so the preview and the
            # saved workspace start from that layout instead of the default grid; a
            # file that cannot be read falls back to the grid without failing the topology.
            annotations = data.options.get('annotations', '')
            drawing = None; used = False
            if isinstance(annotations, str) and annotations.strip():
                try: drawing = parse_drawing(annotations.encode(), raw); used = True
                except invalid: drawing = None
            if drawing is None:
                try: drawing = parse_drawing(b'{"nodeAnnotations":[]}', raw)
                except invalid: raise HTTPException(400, 'Enter a valid literal Containerlab topology.')
            # A preview has no lab to match devices against: the renderer needs to know which drawn devices
            # the topology file names (the rest come from the map file alone). Not stored anywhere.
            names = {n.get('definition_node') or n['name'] for n in parsed['nodes']}
            for node in drawing['nodes']: node['in_topology'] = node.get('alias') in names or node['id'] in names
            return {'name': parsed['name'], 'drawing': drawing, 'annotations_used': used}

        @app.post('/api/operations/preview')
        def preview(data: Request):
            if data.action not in ("deploy", "redeploy", "destroy", "apply", "start", "stop", "restart", "restart-node", "start-node", "stop-node", "save", "inspect", "inspect-all", "create", "delete", "clone", "publish", "revise"):
                raise HTTPException(400, "This lab operation has been removed or is unsupported.")
            if data.node and data.action not in NODE_ACTIONS: raise HTTPException(400, 'Only Restart device, Start device and Stop device name a single device.')
            if 'node' in data.options or 'container' in data.options: raise HTTPException(400, 'The device selector is resolved by the manager, not sent by the page.')
            with self.store.lock:
                self.guard(data.lab_id)
                lab = copy.deepcopy(self.store.lab(data.lab_id)) if data.lab_id else None
                if data.lab_id and not lab: raise HTTPException(404, 'Lab not found.')
                if data.map_revision is not None and data.action != 'revise': raise HTTPException(400, 'Only Save changes to the VM names a map revision.')
                # Edit topology saves the lab's map document beside the file (TOPOLOGY-EDIT-DESIGN A2, R4): a map that changed in
                # the manager since the page opened it is refused before the helper is asked, so the save never carries an old map.
                if lab and data.map_revision is not None and data.map_revision != (revision(lab['drawing']) if lab.get('drawing') else ''):
                    raise HTTPException(409, MAP_CHANGED_SENTENCE)
                host_revision = self.store.state.get('host', {}).get('revision')
                # The moment this review starts, taken while nothing else runs: any lifecycle job created at
                # or after it (even one confirmed while the helper round trips below were in flight) makes a
                # Restart device review stale at confirm time.
                review_stamp = stamp()
            if data.action in NODE_ACTIONS and data.path: raise HTTPException(400, STOP_LABELS[data.action] + " uses the lab's own topology file.")
            run_options = [k for k in OPTION_ACTIONS if k in data.options]
            # `deployed` is named by its label for every action but revise (the next line), never as "no run options".
            if [k for k in run_options if k != 'deployed'] and not any(data.action in actions for actions in OPTION_ACTIONS.values()): raise HTTPException(400, 'This action takes no run options.')
            refused_options = [OPTION_LABELS[k] for k in run_options if data.action not in OPTION_ACTIONS[k]]
            if refused_options: raise HTTPException(400, 'This action does not take: ' + ', '.join(refused_options) + '.')
            path = data.path or (lab.get('vm_project_path') or lab.get('vm_source', {}).get('files', {}).get('definition', {}).get('path', '') if lab else '')
            name = (lab.get('deployment_name') or lab['name']) if lab else data.name or 'manager'
            options = copy.deepcopy(data.options)
            source_name = name
            source = None
            if data.action == 'publish': path = ''
            if data.action not in ('create', 'clone', 'inspect-all', 'publish'):
                source = self.invoke({'mode': 'read', 'path': path})
                try: source_name = parse_definition(source['text'].encode())['name']
                except (ValueError, TypeError, AttributeError, RecursionError): raise HTTPException(400, 'The VM file must contain a valid literal Containerlab topology.')
                if not lab: name = source_name
            chosen_nodes = None
            if run_options:
                # Run options (docs/parity-campaign/C05-DESIGN.md 3.2). The helper validates them again; the manager says first, and names
                # devices from the topology file it parsed, so a review never shows a command that cannot run.
                if 'max_workers' in options:
                    value = options['max_workers']
                    if type(value) is not int or not 1 <= value <= 64: raise HTTPException(400, 'Max workers must be a whole number from 1 to 64.')
                for flag in ('skip_post_deploy', 'keep_mgmt_net', 'deployed'):
                    if flag in options and type(options[flag]) is not bool: raise HTTPException(400, 'Invalid boolean option.')
                if 'nodes' in options:
                    names = options['nodes']
                    if not isinstance(names, list) or not 1 <= len(names) <= 64 or not all(isinstance(n, str) for n in names) or len(set(names)) != len(names):
                        raise HTTPException(400, 'Choose devices by their literal topology node names.')
                    try: known = {n['definition_node'] for n in parse_definition(source['text'].encode())['nodes']}
                    except (ValueError, TypeError, AttributeError, KeyError, RecursionError): raise HTTPException(400, 'The VM file must contain a valid literal Containerlab topology.')
                    unknown = [n for n in names if n not in known]
                    if unknown: raise HTTPException(400, "Choose devices from this lab's topology file: " + ', '.join(unknown) + (' is' if len(unknown) == 1 else ' are') + ' not in it.')
                    if options.get('cleanup'): raise HTTPException(400, 'Clean up cannot be combined with chosen devices: containerlab would delete the whole lab folder, which the devices left running still use.')
                    if data.action == 'deploy' and lab:
                        with self.store.lock: deployment = lab_status(self.store.state, lab)['status']
                        if deployment in ('Unknown', 'Unlinked'):
                            raise HTTPException(409, 'The manager cannot tell whether this lab is deployed (the VM was not reached recently, or the lab is not linked). Refresh the lab list, then try again.')
                        if deployment != 'Not deployed':
                            raise HTTPException(409, 'This lab is already deployed, so a deploy limited to chosen devices is not possible (containerlab would remove the devices left out). Use Apply topology changes to add the missing devices.')
                    chosen_nodes = list(names)
            if data.action == 'create':
                try:
                    parsed = parse_definition(str(options.get('text', '')).encode())
                    if not lab or data.action == 'create': name = parsed['name']
                except (ValueError, TypeError, AttributeError, RecursionError): raise HTTPException(400, 'Use valid literal Containerlab YAML for the new project.')
            diff = ''; notes = []; node_name = ''; node_label = ''; links_expected = 0; neighbours_down = []; neighbours_absent = []
            if data.action in NODE_ACTIONS:
                # Restart, Start and Stop device (one node, containerlab <command> --node): the page names the device by
                # the manager's own node record; the server resolves that to the literal topology node
                # name and the container containerlab gave it, and checks both against the topology file
                # on the VM as it is now. Anything that does not resolve exactly is refused here, before
                # the helper sees a request; there is no fallback to a wider scope.
                label = STOP_LABELS[data.action]; verb = data.action[:-5]
                if not lab: raise HTTPException(400, label + ' needs a lab from My labs.')
                if options: raise HTTPException(400, label + ' takes no options.')
                if not data.node: raise HTTPException(400, 'Choose the device to ' + verb + '.')
                target = next((n for n in lab['nodes'] if n['name'] == data.node), None)
                if not target: raise HTTPException(404, 'This device is not in the lab.')
                shown = target.get('short_name') or target.get('definition_node') or target['name']
                short = target.get('definition_node') or target.get('short_name') or ''
                container = expected_container(lab, target)
                try: parsed = parse_definition(source['text'].encode(), lab.get('deployment_name') or '')
                except (ValueError, TypeError, AttributeError, RecursionError): raise HTTPException(400, 'The VM file must contain a valid literal Containerlab topology.')
                defined = next((n for n in parsed['nodes'] if n['definition_node'] == short), None) if short else None
                if not container or not defined or defined['name'] != container or target['name'] != container:
                    raise HTTPException(409, 'The manager cannot match ' + shown + ' to a device of the topology file on the VM. '
                                        'Sync the topology from the VM (Advanced › Deployment details), then review the ' + verb + ' again.')
                # What discovery last saw of the device: Stop device and Start device are refused here, before the helper is asked,
                # when the answer is already known (the helper checks the live container again).
                with self.store.lock: fresh = discovery_fresh(self.store.state)   # a stale or absent discovery proves nothing about the device
                state = (target.get('runtime_state') or '') if fresh else ''
                if data.action in ('start-node', 'stop-node') and target.get('discovered') is False and state == 'absent':
                    raise HTTPException(409, shown + ' is not deployed on the VM, so there is nothing to ' + verb + '.' +
                                        (' Apply topology changes (Lab actions ▾) recreates it.' if data.action == 'start-node' else ''))
                if data.action == 'stop-node' and state and state not in ('running', 'unknown'):
                    raise HTTPException(409, 'Device ' + container + ' is ' + state + '; there is nothing to stop.')
                if data.action == 'start-node' and state == 'running':
                    raise HTTPException(409, 'Device ' + container + ' is already running.')
                options = {'node': short, 'container': container}
                node_name = target['name']; node_label = shown
                limit = (STOP_KNOWN_LIMITS if data.action == 'stop-node' else RESTART_KNOWN_LIMITS).get(target.get('kind') or target.get('platform') or '')
                if limit: notes.append(limit)
                links_expected, neighbours_down, neighbours_absent = restart_links(lab, short)
                notes.extend(neighbour_note(data.action, shown, links_expected, neighbours_down, neighbours_absent))
            if data.action in ('publish', 'revise'):
                # The lab builder's save. The manager checks what it will later have to read back: a
                # topology parse_definition accepts, under the name the folder and the file will carry.
                if set(options) - {'root', 'text', 'annotations', 'base'} - ({'deployed'} if data.action == 'revise' else set()): raise HTTPException(400, 'Unsupported save options.')
                try: parsed = parse_definition(str(options.get('text', '')).encode())
                except (ValueError, TypeError, AttributeError, RecursionError) as exc:
                    if 'topology.nodes' in str(exc): raise HTTPException(400, 'Add at least one device before saving: a lab without devices cannot be deployed.')
                    raise HTTPException(400, 'The manager cannot read this topology: ' + (str(exc) if type(exc) is ValueError else 'it is not a literal Containerlab topology.'))
                if data.action == 'revise' and parsed['name'] != source_name: raise HTTPException(400, 'The lab name cannot change when saving again. It is ' + source_name + ' on the VM.')
                name = source_name = parsed['name']
                layout = options.get('annotations')
                if layout is not None:
                    try:
                        if not isinstance(json.loads(layout), dict): raise ValueError()
                    except (ValueError, TypeError, RecursionError): raise HTTPException(400, 'The map layout is not valid JSON.')
                    try: parse_drawing(layout.encode(), str(options['text']).encode())
                    except (ValueError, TypeError, AttributeError, KeyError, RecursionError):
                        notes.append('The manager cannot read this map layout, so its own map will start from the default grid. The layout file is still saved for the editor.')
                if len(json.dumps(options)) > 1536 * 1024: raise HTTPException(400, 'This lab is too large to save in one step (topology and map layout together must stay under 1.5 MiB).')
                if source: diff = ''.join(difflib.unified_diff(source['text'].splitlines(True), str(options['text']).splitlines(True), 'on the VM', 'your changes', n=2))
                if len(diff) > 200000: diff = diff[:200000] + '\n… the rest of the differences is not shown (the list is long).\n'
            req = dict(mode='preview', action=data.action, path=path, name=name, source_name=source_name, options=options)
            result = self.invoke(req)
            if data.action == 'publish':
                with self.store.lock:
                    taken = next((l for l in self.store.state['labs'] if (l.get('deployment_name') or l['name']) == name and
                                  (l.get('vm_project_path') or l.get('vm_source', {}).get('files', {}).get('definition', {}).get('path', '')) not in ('', result.get('path'))), None)
                if taken: raise HTTPException(409, 'A lab named ' + name + ' is already in My labs with a different topology file. Choose another lab name.')
                req['path'] = result.get('path', '')
            if data.action in ('deploy', 'redeploy', 'publish', 'revise', 'create'):
                # Manager-side only (the helper's plan and its digest are untouched): shown with the review's warnings.
                notes.extend(cptx_startup_warnings(str(options.get('text', '')) if data.action in ('publish', 'revise', 'create') else (source or {}).get('text', '')))
            if data.action == 'revise':
                # A save of a lab with containers on the VM (the helper binds them into `affected` only with `deployed`): the
                # manager's own sentences follow the helper's, built from the two texts and those containers (A13).
                containers = [a for a in result.get('affected') or [] if isinstance(a, dict)]
                result['deployed'] = bool(containers)
                if containers:
                    try: dry = ((self.capabilities().get('actions') or {}).get('deploy') or {}).get('dry_run')
                    except HTTPException: dry = None   # not known: no sentence either way
                    later = deployed_save_warnings(source['text'], str(options.get('text', '')), containers,
                                                   [req['name'], source_name, (lab or {}).get('deployment_name') or ''], dry if isinstance(dry, bool) else None)
                    result['warnings'] = list(result.get('warnings', [])) + later
            if data.action == 'apply' and isinstance(result.get('plan'), dict):
                # The device limits of the plan (A10), by the kind the VM file gives each device.
                result['plan'], backup = annotate_plan((source or {}).get('text', ''), result['plan'])
                if backup: result['backup_first'] = backup
            if notes: result['warnings'] = notes + list(result.get('warnings', []))
            if diff: result['diff'] = diff
            # The images the reviewed topology names, so the page can ask whether each is usable on this VM
            # (POST /api/operations/image-check) while the review is on the screen: the answer never delays it.
            if data.action in ('deploy', 'redeploy', 'publish', 'revise', 'create'):
                result['images'] = topology_images(str(options.get('text', '')) if data.action in ('publish', 'revise', 'create') else (source or {}).get('text', ''))
            if source and result.get('source_hash') != source['sha256']: raise HTTPException(409, 'Source changed during review; retry.')
            with self.store.lock:
                if self.store.state.get('host', {}).get('revision') != host_revision: raise HTTPException(409, 'VM connection changed. Preview again.')
                self.previews = {k:v for k,v in self.previews.items() if v['expires'] > time.monotonic()}
                if len(self.previews) >= 50: self.previews.pop(next(iter(self.previews)))
                token = uuid.uuid4().hex
                if node_name and any(j.get('lab_id') == data.lab_id and j.get('action') in LIFECYCLE_JOBS and j.get('created', '') >= review_stamp
                                     for j in self.store.state['operations']):
                    raise HTTPException(409, 'Another lab operation ran while this review was being prepared. Review the ' + data.action[:-5] + ' again.')
                self.previews[token] = {'request': req, 'digest': result['digest'], 'revision': host_revision,
                                        'lab_id': data.lab_id, 'expires': time.monotonic() + 300,
                                        # A revise on a lab with containers (the deployed save): the job carries the flag so the
                                        # page's output dialog never offers a deploy of a lab that runs (TOPOLOGY-EDIT-DESIGN A16).
                                        'deployed': result.get('deployed') is True,
                                        'node': node_name, 'node_label': node_label, 'stamp': review_stamp,
                                        'links_expected': links_expected, 'neighbours_down': neighbours_down, 'neighbours_absent': neighbours_absent,
                                        'nodes': chosen_nodes,
                                        # The map revision the page opened (A19): checked again at confirm, so a map changed
                                        # in the manager between this review and the confirmation is never saved over.
                                        'map_revision': data.map_revision if lab else None}
            if node_name:
                if len(result.get('affected', [])) != 1 or result['affected'][0].get('name') != options['container']:
                    raise HTTPException(409, 'The helper did not bind the restart to exactly this device. Review again.')
                return {**result, 'token': token, 'node': node_name, 'node_label': node_label}
            return {**result, 'token': token}

        class Confirmation(BaseModel):
            model_config = ConfigDict(extra='forbid')
            token: str = Field(min_length=32, max_length=32)

        @app.post('/api/operations/confirm')
        def confirm(data: Confirmation):
            with self.store.lock:
                preview = self.previews.get(data.token)
                if not preview or preview['expires'] < time.monotonic(): raise HTTPException(409, 'Review expired; preview the operation again.')
                if preview['revision'] != self.store.state.get('host', {}).get('revision'): raise HTTPException(409, 'VM changed. Preview again.')
                if preview['lab_id'] and not self.store.lab(preview['lab_id']): raise HTTPException(409, 'Saved lab was removed. Preview again.')
                if preview.get('map_revision') is not None:
                    # Edit topology's save (A19): the map the review carried must still be the lab's map now, under the same
                    # lock every map writer takes; otherwise the same refusal as the preview's, and no job.
                    drawing = self.store.lab(preview['lab_id']).get('drawing')
                    if preview['map_revision'] != (revision(drawing) if drawing else ''): raise HTTPException(409, MAP_CHANGED_SENTENCE)
                if preview.get('node'):
                    # Restart device: the consent was for one device of one deployment. The device must
                    # still be that node of the lab, and no lifecycle operation may have run on the lab
                    # since the review (a restart keeps container ids, so the helper's digest alone
                    # would let a second tab's stale review restart the device again). These checks come
                    # before the busy guard: the executor keeps that guard raised for its follow-up
                    # discovery refresh after the job already reads succeeded, and a stale review can
                    # never be confirmed, so its tab must hear the reason at once, not "wait" and then,
                    # on its retry, "review again" (QA-020).
                    lab = self.store.lab(preview['lab_id']); target = next((n for n in lab['nodes'] if n['name'] == preview['node']), None)
                    again = 'Review the ' + preview['request']['action'][:-5] + ' again.'
                    if not target or expected_container(lab, target) != preview['request']['options'].get('container'):
                        raise HTTPException(409, 'The device changed after this review. ' + again)
                    if any(j.get('lab_id') == preview['lab_id'] and j.get('action') in LIFECYCLE_JOBS and j.get('created', '') >= preview['stamp']
                           for j in self.store.state['operations']):
                        raise HTTPException(409, 'Another lab operation ran after this review. ' + again)
                self.guard(preview['lab_id'])
                req = {**preview['request'], 'mode': 'run', 'digest': preview['digest']}
                job = {'id': uuid.uuid4().hex, 'lab_id': preview['lab_id'], 'name': req['name'], 'action': req['action'],
                       'path': req['path'], 'created': stamp(), 'status': 'queued', 'output': '', 'message': 'Queued', 'exit_code': None}
                if preview.get('node'): job.update(node=preview['node'], node_label=preview.get('node_label') or preview['node'], links_expected=preview.get('links_expected') or 0, neighbours_down=list(preview.get('neighbours_down') or []),
                                                 neighbours_absent=list(preview.get('neighbours_absent') or []))
                if preview.get('nodes'): job['nodes'] = list(preview['nodes'])   # the devices a filtered job names: topology node names the review showed
                if preview.get('deployed'): job['deployed'] = True   # a deployed save (revise on a lab with containers)
                previous_jobs = self.store.state['operations']
                self.store.state['operations'] = (previous_jobs + [job])[-200:]
                try: self.store.save()
                except OSError:
                    self.store.state['operations'] = previous_jobs; raise HTTPException(500, 'Could not save the operation; nothing was submitted.')
                self.previews.pop(data.token)
                self.cancels[job['id']] = threading.Event()   # before submit: execute() and the stop route both find it
                try: self.pool.submit(self.execute, job['id'], self.host(), req)
                except RuntimeError:
                    self.cancels.pop(job['id'], None)
                    job.update(status='interrupted', message='Manager is shutting down. Preview again after restart.'); self.store.save()
                    raise HTTPException(409, job['message'])
                return copy.deepcopy(job)

        @app.get('/api/operations')
        def history():
            with self.store.lock: return [{k:v for k,v in j.items() if k != 'output'} for j in reversed(self.store.state['operations'][-200:])]

        @app.get('/api/operations/{job_id}')
        def job(job_id: str):
            with self.store.lock:
                found = next((j for j in self.store.state['operations'] if j['id'] == job_id), None)
                if not found: raise HTTPException(404, 'Operation not found.')
                return copy.deepcopy(found)

        @app.post('/api/operations/{job_id}/cancel', status_code=202)
        def cancel(job_id: str):
            with self.store.lock:
                found = next((j for j in self.store.state['operations'] if j['id'] == job_id), None)
                if not found: raise HTTPException(404, 'Operation not found.')
                if found.get('action') not in STOPPABLE: raise HTTPException(409, 'This step finishes on its own in a moment and cannot be stopped.')
                if found['status'] not in BUSY: raise HTTPException(409, 'This operation has already finished.')
                if not found.get('cancel_requested'):
                    found['cancel_requested'] = stamp()
                    try: self.store.save()
                    except OSError: pass   # the memory record and the event carry the request; the job's own saves write it
                event = self.cancels.get(job_id)
                if event: event.set()
                return {'id': job_id, 'status': found['status'], 'cancel_requested': found['cancel_requested'], 'message': STOP_ASKED}

        class LabSettings(BaseModel):
            model_config = ConfigDict(extra='forbid')
            favorite: bool | None = None
            # Hide from Home: a flag on the lab record and nothing else. The lab, its devices, backups,
            # history and Git binding stay; nothing on the VM changes; background discovery keeps
            # updating the lab without ever clearing the flag. Adding the lab again through the
            # topology browser (POST /api/lab-definitions) or Show on Home clears it.
            hidden: bool | None = None
            path: str | None = Field(default=None, max_length=4096)

        @app.put('/api/labs/{lab_id}/operations-settings')
        def settings(lab_id: str, data: LabSettings):
            with self.store.lock:
                lab = self.store.lab(lab_id)
                if not lab: raise HTTPException(404, 'Lab not found.')
                self.guard(lab_id)
                name = parse_definition(lab['definition_yaml'].encode())['name'] if lab.get('definition_yaml') else lab['name']
                revision = self.store.state.get('host', {}).get('revision')
            if data.path:
                self.forget_plan(lab_id)   # and again after the new path is stored: an answer computed meanwhile read the old file
                value = self.invoke({'mode': 'read', 'path': data.path})
                try:
                    parsed = parse_definition(value['text'].encode())
                    if parsed['name'] != name: raise ValueError()
                except (ValueError, TypeError): raise HTTPException(400, 'The selected VM YAML does not match this lab name.')
            with self.store.lock:
                self.guard(lab_id); lab = self.store.lab(lab_id)
                if not lab: raise HTTPException(404, 'Lab was removed.')
                if revision != self.store.state.get('host', {}).get('revision'): raise HTTPException(409, 'VM connection changed. Select the project again.')
                if data.favorite is not None: lab['favorite'] = data.favorite
                if data.hidden is not None:
                    if data.hidden: lab['hidden'] = True
                    else: lab.pop('hidden', None)
                if data.path is not None: lab['vm_project_path'] = data.path
                self.store.save()
                if data.path: self.forget_plan(lab_id)
                if data.hidden is not None:
                    self.store.event('lab.hide' if data.hidden else 'lab.show', 'Hidden from Home' if data.hidden else 'Shown on Home again', lab_id=lab_id)
            return {'saved': True}

        @app.get('/api/labs/{lab_id}/drawio')
        def export(lab_id: str, layout: str = 'map', theme: str = 'manager'):
            if layout not in ('map', 'interactive', 'rows', 'columns'): raise HTTPException(400, 'Choose a supported layout.')
            if theme not in ('manager', 'print'): raise HTTPException(400, 'Choose a supported theme.')
            with self.store.lock:
                lab = self.store.lab(lab_id)
                if not lab: raise HTTPException(404, 'Lab not found.')
                content = drawio(lab, layout, theme); filename = lab['name'] + ('' if layout in ('map', 'interactive') else '-' + layout) + '.drawio'
            return Response(content, media_type='application/xml', headers={'Content-Disposition': "attachment; filename=topology.drawio; filename*=UTF-8''" + quote(filename, safe='')})

        class Layout(BaseModel):
            model_config = ConfigDict(extra="forbid")
            positions: dict = Field(default_factory=dict, max_length=2000)
            decorations: list[dict] | None = Field(default=None, max_length=2000)
            revision: str | None = Field(default=None, max_length=64)

        def positioned(lab, data):
            if not lab or not lab.get('drawing'): raise HTTPException(404, 'Import a topology map first.')
            if data.revision and data.revision != revision(lab['drawing']): raise HTTPException(409, 'The map changed. Reopen the editor before saving or exporting.')
            drawing = copy.deepcopy(lab['drawing'])
            positions = data.positions
            if data.decorations is not None:
                try: drawing['decorations'] = decorations(data.decorations)
                except ValueError as exc: raise HTTPException(400, str(exc))
            aliases = {n['id']: n for n in drawing['nodes']}
            if set(positions) - set(aliases): raise HTTPException(400, 'Unknown map nodes.')
            for alias, point in positions.items():
                if not isinstance(point, list) or len(point) != 2 or any(type(v) not in (int, float) or not -100000 <= v <= 100000 for v in point): raise HTTPException(400, 'Invalid node coordinates.')
                aliases[alias].update(x=point[0], y=point[1])
            # A layout saved by a person is theirs: discovery never replaces it with the VM annotations.
            drawing['placed'] = True
            return drawing

        @app.put('/api/labs/{lab_id}/layout')
        def layout(lab_id: str, data: Layout):
            with self.store.lock:
                self.guard(lab_id); lab = self.store.lab(lab_id)
                drawing = positioned(lab, data)
                previous = lab['drawing']; lab['drawing'] = drawing
                try: self.store.save()
                except OSError:
                    lab['drawing'] = previous
                    raise HTTPException(500, 'Could not save the layout. Try again.')
            self.store.event('topology.layout', 'Diagram layout and annotations saved', lab_id=lab_id)
            return {'saved': True}

        # The map editor (the lab builder in map mode) works on the full annotations document. Reading it
        # changes nothing. Saving it is a map edit and nothing else: the topology text is only read, to
        # derive the drawing again; no helper is called, nothing is deployed and nothing on the VM changes.
        class MapDocument(BaseModel):
            model_config = ConfigDict(extra="forbid")
            annotations: str = Field(max_length=MAX_DOCUMENT)
            revision: str = Field(min_length=1, max_length=64)

        def map_lab(lab_id):
            lab = self.store.lab(lab_id)
            if not lab: raise HTTPException(404, 'Lab not found.')
            if not lab.get('definition_yaml'):
                raise HTTPException(409, 'This lab has no topology file in the manager, so its map opens in the simple editor. Add the topology under Advanced › Update topology file… to use the full map editor.')
            if not lab.get('drawing'): raise HTTPException(404, 'Import a topology map first.')
            return lab

        @app.get('/api/labs/{lab_id}/map-document')
        def read_map_document(lab_id: str):
            with self.store.lock:
                lab = map_lab(lab_id)
                return dict(name=lab['name'], yaml=lab['definition_yaml'], annotations=map_document(lab), revision=revision(lab['drawing']))

        @app.put('/api/labs/{lab_id}/map-document')
        def save_map_document(lab_id: str, data: MapDocument):
            if len(data.annotations.encode()) > MAX_DOCUMENT: raise HTTPException(400, 'The map is larger than 1 MiB.')
            with self.store.lock:
                self.guard(lab_id); lab = map_lab(lab_id)
                if data.revision != revision(lab['drawing']): raise HTTPException(409, 'The map changed since it was opened. Reopen the map editor; your other changes were not saved.')
                try:
                    if not isinstance(json.loads(data.annotations), dict): raise ValueError('not an object')
                    drawing = parse_drawing(data.annotations.encode(), lab['definition_yaml'].encode())
                except (ValueError, TypeError, AttributeError, RecursionError) as exc:
                    raise HTTPException(400, 'The manager cannot read this map: ' + str(exc)[:200])
                # A map a person saved is theirs: discovery never replaces it with the VM's annotations file.
                drawing['placed'] = True
                previous = {k: lab.get(k) for k in ('drawing', 'annotations', 'annotations_for', 'map_written_at')}
                lab['drawing'] = drawing; keep_document(lab, data.annotations)
                try: self.store.save()
                except OSError:
                    for key, value in previous.items():
                        if value is None: lab.pop(key, None)
                        else: lab[key] = value
                    raise HTTPException(500, 'Could not save the map. Try again.')
                saved = revision(drawing)
            self.store.event('topology.layout', 'Map saved from the map editor', lab_id=lab_id)
            return {'saved': True, 'revision': saved}

        # Arrange devices (C06 §2.6): one explicit, saved map change outside Edit map, with one exact Undo kept on the server.
        # The drawing and the stored document move together and the document is kept through keep_document, as the
        # map-document save does; the map state before it stays in process memory (arrange_undo), never in the Store.
        class Arrange(BaseModel):
            model_config = ConfigDict(extra="forbid")
            mode: str | None = Field(default=None, max_length=20)
            undo: bool = False
            revision: str = Field(min_length=1, max_length=64)

        arranged_messages = {'rows': 'Devices arranged in rows', 'columns': 'Devices arranged in columns', 'ring': 'Devices arranged in a ring'}
        map_keys = ('drawing', 'annotations', 'annotations_for', 'map_written_at')
        not_saved = 'Could not save the map. Try again.'

        def map_state(lab):
            """The lab's map keys as they are, deep-copied; a key the lab does not have is left out (and so removed on restore)."""
            return {k: copy.deepcopy(lab[k]) for k in map_keys if k in lab}

        def map_digest(lab):
            """One digest of every map key as it is now: a later save that keeps the drawing's revision (a document change
            parse_drawing does not carry into the drawing: a groupId, geo coordinates, an unknown key) still changes it."""
            return revision({k: lab[k] for k in map_keys if k in lab})

        def put_back(lab, state):
            for key in map_keys: lab.pop(key, None)
            lab.update(state)

        def fitting(document):
            """The document's text: indented like the map-document answers, compact when only that fits the 1 MiB a stored
            document may have (keep_document would drop a larger one, and the map would then lose what it kept)."""
            for options in ({'indent': 2}, {'separators': (',', ':')}):
                text = json.dumps(document, ensure_ascii=False, **options)
                if len(text.encode()) <= MAX_DOCUMENT: return text
            raise HTTPException(400, 'The map is larger than 1 MiB.')

        def arranged_document(lab, old, new):
            """The stored document with the arranged positions, every other key as it was, when it belongs to the drawing
            being arranged; else the document the map editor would open for the arranged drawing."""
            if not (lab.get('annotations') and lab.get('annotations_for') == revision(old)): return fitting(annotations(new))
            try: document = json.loads(lab['annotations'])
            except ValueError: document = None
            if not isinstance(document, dict): raise HTTPException(500, not_saved)   # it parsed when it was kept; nothing is changed
            where = {n['id']: (n['x'], n['y']) for n in new['nodes']}; placed = set()
            for key in ('nodeAnnotations', 'networkNodeAnnotations'):
                for entry in document.get(key) if isinstance(document.get(key), list) else []:
                    ident = entry.get('id') if isinstance(entry, dict) else None
                    if not isinstance(ident, str) or ident not in where: continue
                    x, y = where[ident]
                    if isinstance(entry.get('position'), dict): entry['position'].update(x=x, y=y)
                    else: entry['position'] = {'x': x, 'y': y}
                    placed.add(ident)
            missing = [{'id': n['id'], 'position': {'x': n['x'], 'y': n['y']}} for n in new['nodes'] if n['id'] not in placed]
            if missing:
                if not isinstance(document.get('nodeAnnotations'), list): document['nodeAnnotations'] = []
                document['nodeAnnotations'].extend(missing)
            return fitting(document)

        def stale():
            return JSONResponse({'detail': 'The map changed since you looked at it. The map was reloaded; try again.', 'reason': 'stale'}, status_code=412)

        @app.post('/api/labs/{lab_id}/arrange')
        def arrange_map(lab_id: str, data: Arrange):
            if (data.mode is not None) == data.undo: raise HTTPException(400, 'Choose an arrangement or undo, not both.')
            if data.mode is not None and data.mode not in arranged_messages: raise HTTPException(400, 'Choose rows, columns or a ring.')
            from .layout import arrange   # C06 S1a: the pure, deterministic arrangement of a drawing's nodes
            with self.store.lock:
                self.guard(lab_id); lab = self.store.lab(lab_id)
                if not lab:
                    self.arrange_undo.pop(lab_id, None); raise HTTPException(404, 'Lab not found.')
                if not lab.get('drawing'): raise HTTPException(404, 'Import a topology map first.')
                current = revision(lab['drawing'])
                if data.undo:
                    entry = self.arrange_undo.get(lab_id)
                    if not entry or entry[0] != data.revision or entry[0] != current or entry[2] != map_digest(lab):
                        self.arrange_undo.pop(lab_id, None); return stale()
                    now = map_state(lab)
                    put_back(lab, copy.deepcopy(entry[1]))
                    try: self.store.save()
                    except OSError:
                        put_back(lab, now)   # nothing changed: the Undo stays offered
                        raise HTTPException(500, not_saved)
                    self.arrange_undo.pop(lab_id, None)
                    answer = {'saved': True, 'revision': revision(lab['drawing']), 'undo': False}; message = 'Device positions restored'
                else:
                    if data.revision != current: return stale()
                    old = lab['drawing']
                    if len(old.get('nodes') or []) < 2: raise HTTPException(400, 'Nothing to arrange: this map has one device.')
                    try: positions = arrange(copy.deepcopy(old), data.mode)
                    except ValueError as exc: raise HTTPException(400, str(exc)[:200])
                    new = copy.deepcopy(old)
                    for node in new['nodes']:
                        point = positions.get(node['id']) if isinstance(positions, dict) else None
                        if not isinstance(point, (list, tuple)) or len(point) != 2 or any(type(v) is not int or not -100000 <= v <= 100000 for v in point):
                            raise HTTPException(500, not_saved)
                        node['x'], node['y'] = point
                    # An arrangement a person chose is theirs: discovery never replaces it with the VM annotations.
                    new['placed'] = True
                    text = arranged_document(lab, old, new)
                    previous = map_state(lab)
                    lab['drawing'] = new; keep_document(lab, text)
                    try: self.store.save()
                    except OSError:
                        put_back(lab, previous)
                        raise HTTPException(500, not_saved)
                    saved = revision(new)
                    self.arrange_undo[lab_id] = (saved, previous, map_digest(lab))   # Undo only while the map is exactly this
                    answer = {'saved': True, 'revision': saved, 'undo': True}; message = arranged_messages[data.mode]
            self.store.event('topology.layout', message, lab_id=lab_id)
            return answer

        @app.post('/api/labs/{lab_id}/annotations')
        def export_annotations(lab_id: str, data: Layout):
            with self.store.lock:
                lab = self.store.lab(lab_id)
                drawing = positioned(lab, data)
                content = json.dumps(annotations(drawing), ensure_ascii=False, indent=2).encode()
                filename = lab['name'] + '.clab.yaml.annotations.json'
            return Response(content, media_type='application/json', headers={'Content-Disposition': "attachment; filename=topology.annotations.json; filename*=UTF-8''" + quote(filename, safe='')})

        @app.post('/api/labs/{lab_id}/drawio')
        def export_current(lab_id: str, data: Layout):
            with self.store.lock:
                lab = copy.deepcopy(self.store.lab(lab_id))
                drawing = positioned(lab, data)
                lab['drawing'] = drawing
                content = drawio(lab)
            return Response(content, media_type='application/xml', headers={'Content-Disposition': "attachment; filename=topology.drawio; filename*=UTF-8''" + quote(lab['name']+'.drawio', safe='')})

    def record_deployment(self, ident, finished):
        """A deploy or redeploy that succeeded is when the lab was last deployed: kept on the lab, because
        the operation history is capped. Written with the job's own save; nothing else sets this field."""
        with self.store.lock:
            job = next((j for j in self.store.state['operations'] if j['id'] == ident), None)
            lab = self.store.lab(job['lab_id']) if job and job.get('action') in DEPLOY_ACTIONS and job.get('lab_id') else None
            if lab: lab['last_deployed'] = finished

    def reregister(self, lab_id, host, path, name=''):
        """After a successful apply, deploy or redeploy: register the lab's definition again from the topology file the job
        ran and the map file beside it, read through the helper's read mode (TOPOLOGY-EDIT-DESIGN A1, R2, R12, R20). The nodes
        follow the file; `deployment_name` (else `name`, the one the job deployed under), Hide from Home and the saved node settings are kept. The map: the VM's map file
        when it has one, unless a person changed the map in the manager since the last sync (then the manager's own map
        document is read against the new file, so positions placed here are kept and the file's devices still appear;
        a device the manager's document lacks takes its entry from the VM's map file, where the builder's save placed it:
        discovery.merge_map, A18). Returns '' or the job's note; never raises, never fails the job."""
        from .runner import Runner
        from .topology import unplaced
        unread = ('The lab ran, but the manager could not read its topology file on the VM afterwards, so My labs still shows the '
                  'previous definition. Use Sync from VM (Advanced › Deployment details) to refresh it.')
        try:
            text = remote(host, {'mode': 'read', 'path': path}, None, self.stopping, timeout=30)['text']
            if not isinstance(text, str): raise ValueError('not text')
        except Exception: return unread
        note = ''; vm_map = None
        try:
            vm_map = remote(host, {'mode': 'read', 'path': path + '.annotations.json'}, None, self.stopping, timeout=30)['text']
            if not isinstance(vm_map, str): raise ValueError('not text')
        except ValueError as exc:
            vm_map = None
            if 'no longer exists' not in str(exc): note = 'The manager could not read the map file beside the topology on the VM; the map in the manager was kept.'
        except Exception:
            vm_map = None; note = 'The manager could not read the map file beside the topology on the VM; the map in the manager was kept.'
        with self.store.lock:
            lab = self.store.lab(lab_id)
            if not lab: return ''
            drawn = isinstance(lab.get('drawing'), dict) and bool(lab['drawing'].get('nodes'))
            # The VM's map file wins unless a person changed the map here since the last sync; without either, the manager's
            # own map is read against the new file, so the file's devices appear and every position stays where it was.
            use_ours = drawn and (vm_map is None or Runner.map_changed_in_manager(lab))
            ours = map_document(lab) if use_ours else None
            document = ours if use_ours else vm_map
            was_unplaced = use_ours and unplaced(lab['drawing'])
            deployment = lab.get('deployment_name') or name
            before = copy.deepcopy(lab)
            try:
                try:
                    if use_ours and ours: register_definition(self.store.state, lab, text.encode(), vm_map.encode() if vm_map else None, deployment, kept=ours.encode())
                    else: register_definition(self.store.state, lab, text.encode(), document.encode() if document else None, deployment)
                except (ValueError, TypeError, AttributeError, KeyError, RecursionError):
                    if not document: raise
                    # The map did not fit the new file: the nodes alone, the map kept as it was.
                    register_definition(self.store.state, lab, text.encode(), None, deployment)
                    note = 'The map could not be matched to the new topology file; the map in the manager was kept.'; was_unplaced = False
            except (ValueError, TypeError, AttributeError, KeyError, RecursionError):
                lab.clear(); lab.update(before)
                return ('The lab ran, but My labs could not take its topology file from the VM (not a literal topology the manager '
                        'reads, or its deployment belongs to another lab), so My labs still shows the previous definition. '
                        'Use Sync from VM (Advanced › Deployment details) once that is corrected.')
            if was_unplaced:
                # Still on the default grid: discovery may place it from the VM's map file later (topology.unplaced).
                lab['drawing']['placed'] = False; keep_document(lab, document)
            try: self.store.save()
            except OSError: pass   # the record is in memory; the job's own save writes it
        self.forget_plan(lab_id)
        self.store.event('topology.registered', 'Lab definition refreshed after apply', lab_id=lab_id)
        return note

    def settled_after_restart(self, key, action='restart-node'):
        """After a successful node restart: '' when the container is running, else the reason the job failed.

        Some images cannot start a second time (vJunos-switch renames its init.conf on the first start): the
        restart command exits 0 and the container dies right after. Discovery is asked again a moment later,
        and what it lists for the device (state and the runtime's status line) is the job's outcome."""
        lab_id, name = key
        time.sleep(2)
        try: self.discovery.refresh(wait=True)
        except Exception: return ''
        with self.store.lock:
            lab = self.store.lab(lab_id); node = next((n for n in (lab or {}).get('nodes', []) if n['name'] == name), None)
            if not node or not node.get('discovered'): return ''
            state = node.get('runtime_state') or ''; status = node.get('runtime_status') or ''
            kind = node.get('kind') or node.get('platform') or ''
        if state in ('', 'running'): return ''
        why = RESTART_KNOWN_LIMITS.get(kind, 'The image could not start again from its current state.')
        return ('containerlab ' + ('started' if action == 'start-node' else 'restarted') + ' the device, but its container is ' + state + (' (' + status + ')' if status else '') +
                ' right after starting. ' + why + ' Redeploy the lab to recreate the device; configuration changes that were not saved to its startup configuration are lost either way.')

    def finish_stopped(self, ident, host, req, ran, clean):
        """A person stopped the job: keep it busy until the VM proves it ended the command, then record `cancelled`.

        The stop closed the SSH channel; the helper's next heartbeat fails and it ends containerlab's process group.
        Until its host lock is free the lab may still be written to, so the job stays `running` (and every guard keeps
        refusing) while a read-only preview, which needs that same lock, is asked once a second for up to 20 s."""
        def update(**fields):
            with self.store.lock:
                job = next(j for j in self.store.state['operations'] if j['id'] == ident)
                job.update(fields); self.store.save()
        with self.store.lock:
            job = next(j for j in self.store.state['operations'] if j['id'] == ident)
            action = job.get('action', ''); asked = job.get('cancel_requested') or stamp()
        if not ran:
            self.forget_plan(job.get('lab_id'))
            update(status='cancelled', cancel_requested=asked, finished=stamp(), exit_code=None, output=clean,
                   message='You stopped ' + STOP_LABELS.get(action, action) + ' before it started. Nothing was changed on the VM.')
            return
        try: update(status='running', cancel_requested=asked, output=clean, message=STOP_ASKED)
        except OSError: pass   # the memory record holds it
        probe = {k: v for k, v in req.items() if k != 'digest'}; probe['mode'] = 'preview'
        deadline = time.monotonic() + FOLLOW_UP_LIMIT; proven = False
        while True:
            if self.stopping.is_set():
                self.forget_plan(job.get('lab_id'))
                update(status='interrupted', finished=stamp(), output=clean, message='Operation connection interrupted. Inspect the lab before retrying.')
                return
            try:
                remote(host, probe, None, self.stopping, timeout=8)
                proven = True
            except OperationStopped: continue   # the shutdown flag: the next pass ends the job as interrupted
            except ValueError as exc:
                # The helper's own answer other than the lock sentence or its generic failure (which can predate the lock) means it took the lock: the command is gone.
                # A connection failure (ours or the gateway's) proves nothing.
                proven = bool(getattr(exc, 'from_helper', False)) and str(exc) not in (LOCK_SENTENCE, GENERIC_HELPER_ERROR)
            except Exception: proven = False
            if proven or time.monotonic() >= deadline: break
            time.sleep(1)
        self.forget_plan(job.get('lab_id'))
        update(status='cancelled', finished=stamp(), exit_code=None, output=clean, message=stop_message(action) if proven else STOP_UNPROVEN)

    def execute(self, ident, host, req):
        with self.store.lock: self.active.add(ident); event = self.cancels.get(ident)
        stop = StopCondition(self.stopping, event)
        window = OutputWindow(); last_save = 0; ran = False; note = ''   # ran: the request was handed to the VM; note: the re-registration's
        def update(**fields):
            with self.store.lock:
                job = next(j for j in self.store.state['operations'] if j['id'] == ident)
                job.update(fields); self.store.save()
        def add(chunk, final=False):
            # Secrets are replaced as the output arrives, before the 512 KiB window can cut one.
            with self.store.lock: secrets = secret_values(self.store.state)
            window.add(chunk, secrets, final)
        def output(chunk):
            nonlocal last_save
            add(chunk)
            if time.monotonic() - last_save > .25:
                # Publish complete lines so split credential values cannot leak mid-chunk.
                text = window.text().rpartition('\n')[0]
                with self.store.lock: clean = scrub(text, self.store.state)
                # A storage error must not cut off the running operation: the job keeps the text in memory
                # and the next publication (or the final save) writes it.
                try: update(output=clean)
                except OSError: pass
                last_save = time.monotonic()
        with self.store.lock:
            job = next((j for j in self.store.state['operations'] if j['id'] == ident), {})
            restart_key = (job.get('lab_id'), job.get('node')) if job.get('action') in ('restart-node', 'start-node') and job.get('node') else None
            # Stop device: the device will not answer, so its proven login is forgotten once (no settle check follows).
            stop_key = (job.get('lab_id'), job.get('node')) if job.get('action') == 'stop-node' and job.get('node') else None
            lab_of_job = job.get('lab_id') or ''; action_of_job = job.get('action') or ''; forgot_stop = []
            # A lab-wide lifecycle job (deploy, redeploy, start, restart) boots every device of the lab: each one's proven
            # login is history too, and each gets the same login grace window as a single restarted device (QA-019).
            lab_keys = []
            if job.get('action') in ('deploy', 'redeploy', 'start', 'restart') and job.get('lab_id'):
                lab_row = next((l for l in self.store.state.get('labs', []) if l.get('id') == job['lab_id']), None)
                lab_keys = [(job['lab_id'], n['name']) for n in (lab_row or {}).get('nodes', []) if n.get('name')]
        def invalidate_readiness():
            # Restart device: the device's proven login is history from the moment the restart is
            # accepted; a probe that answered before this moment can no longer mark it ready, and it
            # is asked again after the restart. Done before the helper runs and again after, so neither
            # a probe in flight nor one that ran while the container came back counts.
            if not self.readiness: return
            if restart_key: self.readiness.forget(restart_key)
            if stop_key and not forgot_stop: self.readiness.forget(stop_key); forgot_stop.append(True)
            for key in lab_keys: self.readiness.forget(key)
        try:
            # A shutdown, or a stop asked while the job was queued, ends it before the VM is touched.
            if stop.is_set(): raise OperationStopped('Operation stopped. Inspect the lab before retrying.')
            invalidate_readiness()
            try: update(status='running', started=stamp(), message='Executing on the VM')
            except OSError: raise ValueError("The manager could not save the operation record, so nothing was run on the VM. Check the manager's disk and try again.") from None
            ran = True
            result = remote(host, req, output, stop)
            invalidate_readiness()   # before the job turns terminal: no window in which an old proof reads as Ready
            add('', True); text = window.text()
            with self.store.lock: clean = scrub(text, self.store.state)
            succeeded = result.get('exit_code') == 0
            message = 'Operation completed' if succeeded else 'Host command returned an error'
            if restart_key and succeeded:
                # containerlab names each dataplane link it restores; a device stopped outside containerlab
                # has none to restore, and the student should see that rather than a bare success.
                restored = len(re.findall(r'Restored link ', text))
                expected = job.get('links_expected') or 0; down = job.get('neighbours_down') or []; gone = job.get('neighbours_absent') or []
                if restored and expected > restored:
                    reason = 'not running' if not gone else 'removed' if not down else 'not running or removed'
                    message += ' · %d of %d links restored' % (restored, expected) + (' (no link to ' + ', '.join(down + gone) + ': ' + reason + ', its link was gone; the device waits for it before it boots)' if down or gone else '')
                else:
                    message += ' · ' + (str(restored) + (' link' if restored == 1 else ' links') + ' restored' if restored else 'no links restored (none were parked by containerlab; redeploy the lab if this device should have links)')
                # A successful command is not a running device: the container is looked at once more.
                exited = self.settled_after_restart(restart_key, action_of_job)
                if exited: succeeded = False; message = exited
            finished = stamp()
            if succeeded: self.record_deployment(ident, finished)
            # The lab now runs what its file says: My labs follows the file (A1). A deployed save (revise) never does this.
            if succeeded and action_of_job in REGISTER_ACTIONS and lab_of_job and req.get('path'): note = self.reregister(lab_of_job, host, req['path'], req.get('name') or '')
        except Exception as exc:
            stopped = isinstance(exc, OperationStopped)
            if stopped and self.stopping.is_set(): message = 'Operation connection interrupted. Inspect the lab before retrying.'
            else: message = str(exc) if type(exc) is ValueError else 'SSH connection or operation failed. Inspect the VM before retrying.'
            add('', True); text = window.text()
            with self.store.lock: clean = scrub(text, self.store.state); message = scrub(message, self.store.state)
            self.forget_plan(lab_of_job)   # before any terminal write: a browser that sees the job end can never be handed the pre-operation plan
            try:
                if stopped and not self.stopping.is_set(): self.finish_stopped(ident, host, req, ran and getattr(exc, 'sent', True), clean)
                else: update(status='interrupted' if self.stopping.is_set() else 'failed', finished=stamp(), output=clean, message=message)
            except OSError:
                pass  # update retained the terminal state in memory; restart reconciles disk.
        else:
            # Outside the try of the remote call: the operation ran, so a storage error here is not an SSH failure.
            self.forget_plan(lab_of_job)   # before the terminal write (see the except branch)
            try:
                update(status='succeeded' if succeeded else 'failed', exit_code=result.get('exit_code'),
                       finished=finished, output=clean, result=result, message=message, **({'note': note} if note else {}))
            except OSError:
                pass  # update retained the outcome in memory; restart reconciles disk.
        finally:
            try:
                invalidate_readiness()
                try:
                    with self.store.lock: lab_id = next((j.get('lab_id', '') for j in self.store.state['operations'] if j['id'] == ident), '')
                    self.store.event('lab.operation', 'Lab operation finished; review its operation record', lab_id=lab_id)
                except OSError:
                    pass  # Logging cannot retain the active guard after execution ends.
                if not self.stopping.is_set(): self.discovery.refresh()
            except OSError:
                pass  # The discovery loop retries storage failures independently.
            finally:
                with self.store.lock: self.active.discard(ident); self.cancels.pop(ident, None)
