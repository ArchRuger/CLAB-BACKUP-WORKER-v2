"""Reviewed lab-level actions with review tokens and persistent job output."""
import copy
import difflib
import json
import re
import socket
import threading
import time
import uuid
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote

import paramiko
from fastapi import HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field

from .discovery import PinnedHostKey, vm_password, parse_definition, stamp, expected_container
from .inventory import read_data
from .topology import parse_drawing
from .drawio_export import drawio
from .layout import MAX_DOCUMENT, annotations, decorations, keep_document, map_document, revision

BUSY = ('queued', 'running')
GIT_BUSY = ('queued', 'capturing', 'exporting', 'pushing')
# A live restore holds the lab the same way a Git save does. progress_id excludes the
# restore job's own id so its pre/post backups are not blocked by itself.
RESTORE_BUSY = ('queued', 'preflight', 'backing_up', 'applying', 'confirming', 'verifying')
# A network-design apply holds the lab like a restore does (its own pre/post backups pass its id as progress_id).
DESIGN_APPLY_BUSY = ('queued', 'preflight', 'backing_up', 'applying', 'confirming', 'verifying')


def operation_busy(state, lab_id=None, progress_id=None):
    return (any(j['status'] in BUSY and (not lab_id or not j.get('lab_id') or j['lab_id'] == lab_id)
                for j in state.get('operations', [])) or
            any(j['status'] in DESIGN_APPLY_BUSY and j.get('id') != progress_id and
                (not lab_id or not j.get('lab_id') or j['lab_id'] == lab_id)
                for j in state.get('design_jobs', [])) or
            any(j['status'] in GIT_BUSY and j.get('id') != progress_id and
                (not lab_id or not j.get('lab_id') or j['lab_id'] == lab_id)
                for j in state.get('git_jobs', [])) or
            any(j['status'] in RESTORE_BUSY and j.get('id') != progress_id and
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
        client.get_transport().set_keepalive(15)
        channel = client.get_transport().open_session(timeout=8); channel.settimeout(15)
        channel.exec_command('clab-manager-operations')
        channel.sendall((json.dumps(request) + '\n').encode()); channel.shutdown_write()
        channel.settimeout(.2)
        until = time.monotonic() + (timeout if timeout is not None else 1250 if request.get('mode') == 'run' else 180)
        pending = b''; result = None; total = 0; stderr = b''; eof = False
        while True:
            if time.monotonic() > until or (stopping and stopping.is_set()):
                raise ValueError('Operation connection interrupted. Inspect the lab before retrying.')
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
                    if 'error' in item: raise ValueError(str(item['error'])[:1000])
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
LIFECYCLE_JOBS = ('deploy', 'redeploy', 'destroy', 'apply', 'start', 'stop', 'restart', 'restart-node')


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
    expected = 0; down = []
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
            if label not in down: down.append(label)
    return expected, down


def restarting_nodes(state, lab_id):
    """The manager node names of this lab with a Restart device job queued or running right now."""
    return {j.get('node') for j in state.get('operations', [])
            if j.get('lab_id') == lab_id and j.get('action') == 'restart-node' and j.get('status') in BUSY and j.get('node')}


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


class LabOperations:
    def __init__(self, store, discovery, readiness=None):
        # readiness: the ReadinessMonitor, so a Restart device job can drop the device's proven login
        # (its readiness epoch) when the restart is accepted and again when it has run.
        self.store = store; self.discovery = discovery; self.readiness = readiness; self.previews = {}; self.stopping = threading.Event()
        self.pool = ThreadPoolExecutor(max_workers=1); self.cap_cache = None; self.active = set()
        with store.lock:
            for job in store.state.setdefault('operations', []):
                if job['status'] in BUSY:
                    job.update(status='interrupted', message='Manager restarted; inspect the VM before retrying.')
            store.save()

    def close(self):
        self.stopping.set(); self.pool.shutdown(wait=False, cancel_futures=True)

    def host(self):
        with self.store.lock: return copy.deepcopy(self.store.state.get('host', {}))

    def guard(self, lab_id=''):
        if self.active or operation_busy(self.store.state): raise HTTPException(409, 'Wait for the current lab operation to finish.')
        if any(j['status'] in BUSY and (not lab_id or j['lab_id'] == lab_id) for j in self.store.state['jobs']):
            raise HTTPException(409, 'Wait for the lab backup or login job to finish.')

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

        @app.get('/api/operations/capabilities')
        def capabilities():
            host = self.host(); key = host.get('revision')
            if self.cap_cache and self.cap_cache[0] == key and self.cap_cache[1] > time.monotonic(): return self.cap_cache[2]
            result = self.invoke({'mode': 'capabilities'})
            self.cap_cache = (key, time.monotonic() + 60, result)
            return result

        @app.post('/api/operations/browse')
        def browse(data: Request): return self.invoke({'mode': 'browse', 'path': data.path})

        @app.post('/api/operations/read')
        def read(data: Request): return self.invoke({'mode': 'read', 'path': data.path})

        @app.get('/api/operations/popular')
        def popular(): return self.invoke({'mode': 'popular'})

        @app.get('/api/operations/known-images')
        def known_images():
            """Container images named by the topologies already in My labs, per kind. The lab builder
            offers them first, so a new lab starts from images this site is known to use."""
            found = {}
            with self.store.lock: texts = [l.get('definition_yaml') or '' for l in self.store.state['labs']]
            for text in texts:
                try: topology = read_data(text.encode()).get('topology') or {}
                except (ValueError, TypeError, AttributeError, RecursionError): continue
                defaults = topology.get('defaults') if isinstance(topology.get('defaults'), dict) else {}
                kinds = topology.get('kinds') if isinstance(topology.get('kinds'), dict) else {}
                for node in (topology.get('nodes') or {}).values() if isinstance(topology.get('nodes'), dict) else []:
                    node = node if isinstance(node, dict) else {}
                    kind = node.get('kind') or defaults.get('kind')
                    kind_settings = kinds.get(kind) if isinstance(kinds.get(kind), dict) else {}
                    image = node.get('image') or kind_settings.get('image') or defaults.get('image')
                    if isinstance(kind, str) and isinstance(image, str) and 0 < len(kind) <= 120 and 0 < len(image) <= 300 and '{{' not in image:
                        counts = found.setdefault(kind, {}); counts[image] = counts.get(image, 0) + 1
            return {'images': {kind: sorted(counts, key=lambda i: (-counts[i], i))[:12] for kind, counts in sorted(found.items())}}

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
            return {'name': parsed['name'], 'drawing': drawing, 'annotations_used': used}

        @app.post('/api/operations/preview')
        def preview(data: Request):
            if data.action not in ("deploy", "redeploy", "destroy", "apply", "start", "stop", "restart", "restart-node", "save", "inspect", "inspect-all", "create", "delete", "clone", "publish", "revise"):
                raise HTTPException(400, "This lab operation has been removed or is unsupported.")
            if data.node and data.action != 'restart-node': raise HTTPException(400, 'Only Restart device names a single device.')
            if 'node' in data.options or 'container' in data.options: raise HTTPException(400, 'The device selector is resolved by the manager, not sent by the page.')
            with self.store.lock:
                self.guard(data.lab_id)
                lab = copy.deepcopy(self.store.lab(data.lab_id)) if data.lab_id else None
                if data.lab_id and not lab: raise HTTPException(404, 'Lab not found.')
                host_revision = self.store.state.get('host', {}).get('revision')
                # The moment this review starts, taken while nothing else runs: any lifecycle job created at
                # or after it (even one confirmed while the helper round trips below were in flight) makes a
                # Restart device review stale at confirm time.
                review_stamp = stamp()
            if data.action == 'restart-node' and data.path: raise HTTPException(400, "Restart device uses the lab's own topology file.")
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
            if data.action == 'create':
                try:
                    parsed = parse_definition(str(options.get('text', '')).encode())
                    if not lab or data.action == 'create': name = parsed['name']
                except (ValueError, TypeError, AttributeError, RecursionError): raise HTTPException(400, 'Use valid literal Containerlab YAML for the new project.')
            diff = ''; notes = []; node_name = ''; node_label = ''; links_expected = 0; neighbours_down = []
            if data.action == 'restart-node':
                # Restart device (one node, containerlab restart --node): the page names the device by
                # the manager's own node record; the server resolves that to the literal topology node
                # name and the container containerlab gave it, and checks both against the topology file
                # on the VM as it is now. Anything that does not resolve exactly is refused here, before
                # the helper sees a request; there is no fallback to a wider scope.
                if not lab: raise HTTPException(400, 'Restart device needs a lab from My labs.')
                if options: raise HTTPException(400, 'Restart device takes no options.')
                if not data.node: raise HTTPException(400, 'Choose the device to restart.')
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
                                        'Sync the topology from the VM (Advanced › Deployment details), then review the restart again.')
                options = {'node': short, 'container': container}
                node_name = target['name']; node_label = shown
                limit = RESTART_KNOWN_LIMITS.get(target.get('kind') or target.get('platform') or '')
                if limit: notes.append(limit)
                links_expected, neighbours_down = restart_links(lab, short)
                if neighbours_down:
                    # Proven live: a neighbour stopped by containerlab keeps its link ends parked, so the link comes back;
                    # one that exited on its own or was stopped with docker stop took the link with it.
                    who = ', '.join(neighbours_down)
                    notes.append('%s is not running. If it was stopped by the manager, the VS Code extension or containerlab stop, its link to %s is parked and comes back with this restart. '
                                 'If it exited on its own or was stopped with docker stop, that link is gone: containerlab restores %s%s, and the device then waits for all its interfaces before it boots (cEOS gives up waiting after five minutes, a VM-based image waits for good) and stays at Starting until %s runs again. '
                                 'Start %s first (Restart device… on it takes the start/restore path), then this device, or redeploy the lab.'
                                 % (who, shown, 'only %d of %d links' % (links_expected - len(neighbours_down), links_expected) if links_expected > len(neighbours_down) else 'no link',
                                    ' and the job says so', who, who))
            if data.action in ('publish', 'revise'):
                # The lab builder's save. The manager checks what it will later have to read back: a
                # topology parse_definition accepts, under the name the folder and the file will carry.
                if set(options) - {'root', 'text', 'annotations', 'base'}: raise HTTPException(400, 'Unsupported save options.')
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
            if notes: result['warnings'] = notes + list(result.get('warnings', []))
            if diff: result['diff'] = diff
            if source and result.get('source_hash') != source['sha256']: raise HTTPException(409, 'Source changed during review; retry.')
            with self.store.lock:
                if self.store.state.get('host', {}).get('revision') != host_revision: raise HTTPException(409, 'VM connection changed. Preview again.')
                self.previews = {k:v for k,v in self.previews.items() if v['expires'] > time.monotonic()}
                if len(self.previews) >= 50: self.previews.pop(next(iter(self.previews)))
                token = uuid.uuid4().hex
                if node_name and any(j.get('lab_id') == data.lab_id and j.get('action') in LIFECYCLE_JOBS and j.get('created', '') >= review_stamp
                                     for j in self.store.state['operations']):
                    raise HTTPException(409, 'Another lab operation ran while this review was being prepared. Review the restart again.')
                self.previews[token] = {'request': req, 'digest': result['digest'], 'revision': host_revision,
                                        'lab_id': data.lab_id, 'expires': time.monotonic() + 300,
                                        'node': node_name, 'node_label': node_label, 'stamp': review_stamp,
                                        'links_expected': links_expected, 'neighbours_down': neighbours_down}
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
                self.guard(preview['lab_id'])
                if preview.get('node'):
                    # Restart device: the consent was for one device of one deployment. The device must
                    # still be that node of the lab, and no lifecycle operation may have run on the lab
                    # since the review (a restart keeps container ids, so the helper's digest alone
                    # would let a second tab's stale review restart the device again).
                    lab = self.store.lab(preview['lab_id']); target = next((n for n in lab['nodes'] if n['name'] == preview['node']), None)
                    if not target or expected_container(lab, target) != preview['request']['options'].get('container'):
                        raise HTTPException(409, 'The device changed after this review. Review the restart again.')
                    if any(j.get('lab_id') == preview['lab_id'] and j.get('action') in LIFECYCLE_JOBS and j.get('created', '') >= preview['stamp']
                           for j in self.store.state['operations']):
                        raise HTTPException(409, 'Another lab operation ran after this review. Review the restart again.')
                req = {**preview['request'], 'mode': 'run', 'digest': preview['digest']}
                job = {'id': uuid.uuid4().hex, 'lab_id': preview['lab_id'], 'name': req['name'], 'action': req['action'],
                       'path': req['path'], 'created': stamp(), 'status': 'queued', 'output': '', 'message': 'Queued', 'exit_code': None}
                if preview.get('node'): job.update(node=preview['node'], node_label=preview.get('node_label') or preview['node'], links_expected=preview.get('links_expected') or 0, neighbours_down=list(preview.get('neighbours_down') or []))
                previous_jobs = self.store.state['operations']
                self.store.state['operations'] = (previous_jobs + [job])[-200:]
                try: self.store.save()
                except OSError:
                    self.store.state['operations'] = previous_jobs; raise HTTPException(500, 'Could not save the operation; nothing was submitted.')
                self.previews.pop(data.token)
                try: self.pool.submit(self.execute, job['id'], self.host(), req)
                except RuntimeError:
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

        class LabSettings(BaseModel):
            model_config = ConfigDict(extra='forbid')
            favorite: bool | None = None
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
                if data.path is not None: lab['vm_project_path'] = data.path
                self.store.save()
            return {'saved': True}

        @app.get('/api/labs/{lab_id}/drawio')
        def export(lab_id: str, layout: str = 'interactive'):
            if layout != 'interactive': raise HTTPException(400, 'Choose a supported layout.')
            with self.store.lock:
                lab = self.store.lab(lab_id)
                if not lab: raise HTTPException(404, 'Lab not found.')
                content = drawio(lab, layout); filename = lab['name'] + '.drawio'
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
                previous = {k: lab.get(k) for k in ('drawing', 'annotations', 'annotations_for')}
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

    def settled_after_restart(self, key):
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
        return ('containerlab restarted the device, but its container is ' + state + (' (' + status + ')' if status else '') +
                ' right after starting. ' + why + ' Redeploy the lab to recreate the device; configuration changes that were not saved to its startup configuration are lost either way.')

    def execute(self, ident, host, req):
        with self.store.lock: self.active.add(ident)
        window = OutputWindow(); last_save = 0
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
                update(output=clean); last_save = time.monotonic()
        with self.store.lock:
            job = next((j for j in self.store.state['operations'] if j['id'] == ident), {})
            restart_key = (job.get('lab_id'), job.get('node')) if job.get('action') == 'restart-node' and job.get('node') else None
        def invalidate_readiness():
            # Restart device: the device's proven login is history from the moment the restart is
            # accepted; a probe that answered before this moment can no longer mark it ready, and it
            # is asked again after the restart. Done before the helper runs and again after, so neither
            # a probe in flight nor one that ran while the container came back counts.
            if restart_key and self.readiness: self.readiness.forget(restart_key)
        try:
            invalidate_readiness()
            update(status='running', started=stamp(), message='Executing on the VM')
            result = remote(host, req, output, self.stopping)
            invalidate_readiness()   # before the job turns terminal: no window in which an old proof reads as Ready
            add('', True); text = window.text()
            with self.store.lock: clean = scrub(text, self.store.state)
            succeeded = result.get('exit_code') == 0
            message = 'Operation completed' if succeeded else 'Host command returned an error'
            if restart_key and succeeded:
                # containerlab names each dataplane link it restores; a device stopped outside containerlab
                # has none to restore, and the student should see that rather than a bare success.
                restored = len(re.findall(r'Restored link ', text))
                expected = job.get('links_expected') or 0; down = job.get('neighbours_down') or []
                if restored and expected > restored:
                    message += ' · %d of %d links restored' % (restored, expected) + (' (no link to ' + ', '.join(down) + ': not running, its link was gone; the device waits for it before it boots)' if down else '')
                else:
                    message += ' · ' + (str(restored) + (' link' if restored == 1 else ' links') + ' restored' if restored else 'no links restored (none were parked by containerlab; redeploy the lab if this device should have links)')
                # A successful command is not a running device: the container is looked at once more.
                exited = self.settled_after_restart(restart_key)
                if exited: succeeded = False; message = exited
            finished = stamp()
            if succeeded: self.record_deployment(ident, finished)
            update(status='succeeded' if succeeded else 'failed', exit_code=result.get('exit_code'),
                   finished=finished, output=clean, result=result, message=message)
        except Exception as exc:
            message = str(exc) if type(exc) is ValueError else 'SSH connection or operation failed. Inspect the VM before retrying.'
            add('', True); text = window.text()
            with self.store.lock: clean = scrub(text, self.store.state); message = scrub(message, self.store.state)
            try:
                update(status='interrupted' if self.stopping.is_set() else 'failed', finished=stamp(), output=clean, message=message)
            except OSError:
                pass  # update retained the terminal state in memory; restart reconciles disk.
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
                with self.store.lock: self.active.discard(ident)
