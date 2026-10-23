"""Read-only diagnostics of one deployed device (docs/parity-campaign/C03-DESIGN.md, manager side).

Container logs, interfaces with one counter sample, impairments, the lab folder's files, the VM's images.
Everything goes through the operations helper's read-only modes over `lab_operations.remote`; nothing
here starts, stops, writes or execs anything. The browser never names a container or a lab: it sends the
manager's lab id and device name, and the manager derives the deployment name and the container.

Log text is transient: redacted line by line here, returned to the browser and never stored, logged or put
in an event (this module calls no `Store.event`, and its polled reads are GET routes, which the same-origin
guard does not audit). Public answers are field-by-field copies of what the helper said.
"""
import re
import threading
import time
from pathlib import PurePosixPath

from fastapi import HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from . import __version__, lab_operations
from .discovery import expected_container
from .host_operations import LOGS_SINCE, LOGS_TAIL_LIMIT
from .lab_operations import secret_values, topology_images
from .topology import PORT_RULES, displayed_interface

DIAGNOSTIC_SLOTS = 3
BUSY_SENTENCE = 'The manager is already asking the VM for diagnostics; try again in a moment.'
OLD_HELPER_SENTENCE = "This VM's manager tools need an update; ask your instructor or administrator."
UNLINKED_SENTENCE = ('This lab is not linked to a lab on the VM. Link it under Advanced › Link to a running lab… '
                     'to see logs and interfaces.')
NO_NODE_SENTENCE = ("The manager does not know this device's topology node. "
                    'Sync the topology from the VM (Advanced › Deployment details).')
NO_FOLDER_SENTENCE = "The manager does not know this lab's folder on the VM. Sync the topology from the VM first."
OUTSIDE_FOLDER_SENTENCE = "That file is not in this lab's folder."
UNREACHABLE_SENTENCE = 'Cannot reach the VM operations helper. Check setup and SSH settings.'
UNUSABLE_SENTENCE = 'The VM operations helper returned an answer the manager cannot use.'
# Link state on the map (C06 §2.2): every degraded case is a 200 with `available: false`, a reason and one of these.
LINK_UNLINKED_SENTENCE = ('This lab is not linked to a lab on the VM. Link it under Advanced › Link to a running lab… '
                          'to see link state.')
LINK_HELPER_SENTENCE = ('Link state needs the updated VM helper (ask your instructor or administrator). '
                        'Links are drawn from the topology file.')
LINK_CONTAINERLAB_SENTENCE = 'Link state needs containerlab 0.64 or later on the VM%s. Links are drawn from the topology file.'
LINK_NOT_RUNNING_SENTENCE = 'Links are drawn from the topology file; the lab is not running.'
# The kinds whose data ports are wired to a QEMU guest inside the container: the container veth is the VM's link to the
# device, and a port shut down inside the guest may leave it up (C06 assumption A1; the live pass settles each kind).
VM_KINDS = ('juniper_vjunosswitch', 'juniper_vjunosevolved', 'juniper_vjunosrouter', 'juniper_vqfx', 'cisco_xrv9k', 'vr-xrv9k')
LINK_CONTAINER_LIMIT = 512
TAIL_SENTENCE = 'Ask for 1 to %d log lines.' % LOGS_TAIL_LIMIT
SINCE_SENTENCE = 'The log start must be a UTC timestamp.'
DEFAULT_TAIL = 200
VIEW_LIMIT = 512 * 1024
LOG_LINE_LIMIT = 4000
INTERFACE_LIMIT = 256
IMAGE_LIMIT = 1000
IMAGE_TTL = 60

# The redaction rules of lab_operations.scrub, lifted into constants both could share. scrub() itself is
# unchanged (pinned by tests on persisted job output); a test pins that these give its answers.
SECRET_MASK = '[redacted]'
KEY_BLOCK_MASK = '[private key omitted]'
LINE_MASK = '[sensitive output omitted]'
KEY_BEGIN = re.compile(r'-----BEGIN [^-]*PRIVATE KEY-----')
KEY_END = re.compile(r'-----END [^-]*PRIVATE KEY-----')
SENSITIVE_LINE = re.compile(r'(?i)^.*(?:password|passphrase|private.key|community|secret)\s*[:= ].*$')
# View and log only (scrub() is unchanged): key-style secrets in configuration files, such as a Junos $9$ secret,
# an authentication or pre-shared key, or an EOS/IOS `key 7 ...` line.
KEY_STYLE_LINE = re.compile(r'(?i)^.*(?:\b(?:authentication-key|pre-shared-key|key\s+[0-9]\b)|\$9\$).*$')

ESCAPE_CSI = re.compile(r'\x1b\[[0-?]*[ -/]*[@-~]')
ESCAPE_OSC = re.compile(r'\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)?')
ESCAPE_TWO = re.compile(r'\x1b[@-Z\\-_]')
CONTROLS = re.compile(r'[\x00-\x08\x0b-\x1f\x7f]')   # every C0 control except \n and \t (\r included)
STAMP = re.compile(r'(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,9})?(?:Z|[+-]\d\d:\d\d)) ?(.*)', re.ASCII | re.DOTALL)
TAIL_DIGITS = re.compile(r'[0-9]{1,4}', re.ASCII)
VETH = re.compile(r'eth(\d+)', re.ASCII)
NOKIA_VETH = re.compile(r'e1-\d+', re.ASCII)
COUNTER_KEYS = ('rx_bytes', 'rx_packets', 'rx_errors', 'rx_dropped', 'tx_bytes', 'tx_packets', 'tx_errors', 'tx_dropped')
IMPAIRMENT_KEYS = ('delay', 'jitter', 'loss', 'rate', 'corruption')


def strip_escapes(text):
    """Terminal control sequences and control characters removed from a whole text: CSI, OSC, two-byte
    escapes, carriage returns and every C0 control except newline and tab."""
    for pattern in (ESCAPE_CSI, ESCAPE_OSC, ESCAPE_TWO): text = pattern.sub('', text)
    return CONTROLS.sub('', text)


def redact_lines(lines, secrets, stamped=False):
    """Each line redacted on its own, with a private-key block carried across lines. With `stamped` a line
    is first split into its `--timestamps` stamp and its body and only the body is redacted, so a redacted
    line keeps its stamp. Returns [(stamp, body)]; the stamp is '' for a line without one (or unstamped text).
    A window can start inside a block (docker --tail, the since cursor, a byte cut): an END marker seen with
    no BEGIN before it in this window masks every earlier line of the window, and after an END a further
    BEGIN on the same line opens the next block."""
    result = []; in_key = False; seen_begin = False
    for line in lines:
        stamp = ''; body = line
        if stamped:
            match = STAMP.fullmatch(line)
            if match: stamp, body = match.group(1), match.group(2)
        events = sorted([(m.start(), 'begin') for m in KEY_BEGIN.finditer(body)] + [(m.start(), 'end') for m in KEY_END.finditer(body)])
        if in_key or events:
            for _, kind in events:
                if kind == 'begin': in_key = True; seen_begin = True
                else:
                    if not in_key and not seen_begin: result = [(at, KEY_BLOCK_MASK) for at, _ in result]   # the block began before this window
                    in_key = False
            body = KEY_BLOCK_MASK
        else:
            for secret in secrets: body = body.replace(secret, SECRET_MASK)
            body = SENSITIVE_LINE.sub(LINE_MASK, body)
            body = KEY_STYLE_LINE.sub(LINE_MASK, body)
        result.append((stamp, body))
    return result


def split_lines(text):
    lines = text.split('\n')
    if lines and lines[-1] == '': lines.pop()
    return lines


def redact_text(text, secrets):
    """Unstamped text (a file) redacted line by line, newlines kept."""
    return '\n'.join(body for _, body in redact_lines(split_lines(text), secrets)) + ('\n' if text.endswith('\n') else '')


def cut_last(text, limit):
    """(text, truncated): the last `limit` bytes of a text, cut at a line boundary, when it is longer."""
    raw = text.encode('utf8', errors='replace')
    if len(raw) <= limit: return text, False
    raw = raw[-limit:]; cut = raw.find(b'\n')
    if 0 <= cut < len(raw) - 1: raw = raw[cut + 1:]
    return raw.decode('utf8', errors='ignore'), True


def image_key(reference):
    """A normal form of an image reference, so that `alpine`, `alpine:latest` and `docker.io/library/alpine:latest`
    are the same image: registry (default docker.io), path (`library/` for a one-part Docker Hub name), tag
    (default `latest`), and the digest when one is named. '' for anything that is not a string reference."""
    if not isinstance(reference, str) or not reference.strip(): return ''
    value = reference.strip(); digest = ''
    if '@' in value: value, _, digest = value.partition('@')
    first, slash, rest = value.partition('/')
    if slash and ('.' in first or ':' in first or first == 'localhost'): registry, path = first, rest
    else: registry, path = 'docker.io', value
    if registry in ('index.docker.io', 'registry-1.docker.io'): registry = 'docker.io'
    tag = ''
    head, colon, last = path.rpartition(':')
    if colon and '/' not in last: path, tag = head, last
    if registry == 'docker.io' and '/' not in path: path = 'library/' + path
    key = registry + '/' + path
    if digest: return key + ('@' + digest) + (':' + tag if tag else '')
    return key + ':' + (tag or 'latest')


def interface_role(kind, name):
    """How the drawer groups a container interface: `management` (eth0), `internal` (an ethN below the kind's
    port offset, such as cJunosEvolved's eth1-eth3, and names that are neither ethN nor e1-N, such as cEOS's
    cpu and fabric), else `data`. A display rule, not a guard for changing anything on the interface."""
    if name == 'eth0': return 'management'
    match = VETH.fullmatch(name)
    if match:
        offset = PORT_RULES.get(kind, (None, None, 0))[2]
        return 'internal' if int(match.group(1)) < offset else 'data'
    return 'data' if NOKIA_VETH.fullmatch(name) else 'internal'


def text_value(value, limit):
    return value[:limit] if isinstance(value, str) else ''


def int_value(value):
    return value if type(value) is int else 0


def public_facts(facts):
    """The container facts the browser may see, copied field by field (never the helper's raw object)."""
    if not isinstance(facts, dict) or facts.get('present') is not True: return {'present': False}
    ports = []
    for row in facts.get('ports') if isinstance(facts.get('ports'), list) else []:
        if isinstance(row, dict) and isinstance(row.get('container'), str) and isinstance(row.get('host'), str):
            ports.append({'container': row['container'][:32], 'host': row['host'][:8]})
    return {'present': True, 'id': text_value(facts.get('id'), 64), 'pid': int_value(facts.get('pid')),
            'status': text_value(facts.get('status'), 32), 'health': text_value(facts.get('health'), 32),
            'started': text_value(facts.get('started'), 64), 'ports': ports[:64]}


class ViewRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    lab_id: str = Field(max_length=64)
    path: str = Field(max_length=4096)


class BrowseRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    path: str = Field(default='', max_length=4096)
    files: bool = False
    lab_id: str = Field(default='', max_length=64)   # required with `files`: the listing is bound to the lab's folder


class DeviceDiagnostics:
    def __init__(self, store, operations, discovery):
        self.store = store; self.operations = operations; self.discovery = discovery
        self.slots = threading.BoundedSemaphore(DIAGNOSTIC_SLOTS)
        self.images_cache = None; self.images_lock = threading.Lock()

    # The transport -----------------------------------------------------------------------------------------------

    def ask(self, request, timeout):
        """One helper request through lab_operations.remote (read to stream EOF there), errors mapped as the
        operations invoke() maps them, plus the sentence for a helper that predates the mode."""
        try: result = lab_operations.remote(self.operations.host(), request, **({'timeout': timeout} if timeout else {}))
        except Exception as exc:
            message = str(exc) if type(exc) is ValueError else UNREACHABLE_SENTENCE
            if message == 'Unknown request mode.': message = OLD_HELPER_SENTENCE
            raise HTTPException(409, message)
        if not isinstance(result, dict): raise HTTPException(409, UNUSABLE_SENTENCE)
        return result

    def diagnose(self, request, timeout):
        """`ask` under the manager-wide limit of three diagnostics calls at once; the fourth is a 503."""
        if not self.slots.acquire(blocking=False): raise HTTPException(503, BUSY_SENTENCE)
        try: return self.ask(request, timeout)
        finally: self.slots.release()

    def target(self, lab_id, node_name):
        """(lab, node, deployment name, container) of a device, copied under the store lock. 404 for an unknown
        device; 409 with the way out when the manager cannot name its container."""
        with self.store.lock:
            lab = self.store.lab(lab_id)
            if not lab: raise HTTPException(404, 'Lab not found')
            node = next((n for n in lab['nodes'] if n['name'] == node_name), None)
            if not node: raise HTTPException(404, 'Device not found')
            lab = {k: lab[k] for k in ('id', 'name', 'deployment_name', 'container_prefix', 'vm_project_path', 'vm_source') if k in lab}
            node = {k: node.get(k) for k in ('name', 'short_name', 'definition_node', 'kind', 'platform')}
        container = expected_container(lab, node)
        if not container:
            raise HTTPException(409, UNLINKED_SENTENCE if not lab.get('deployment_name') else NO_NODE_SENTENCE)
        return lab, node, lab['deployment_name'], container

    def device_request(self, mode, lab_id, node_name):
        lab, node, deployment, container = self.target(lab_id, node_name)
        topo = node.get('definition_node') or node.get('short_name') or ''
        return node, container, {'mode': mode, 'name': deployment, 'options': {'node': topo, 'container': container}}

    def folder_of(self, lab_id):
        with self.store.lock:
            lab = self.store.lab(lab_id)
            if not lab: raise HTTPException(404, 'Lab not found')
            source = lab.get('vm_source') if isinstance(lab.get('vm_source'), dict) else {}
            path = lab.get('vm_project_path') or ((source.get('files') or {}).get('definition') or {}).get('path', '')
        if not isinstance(path, str) or not path.startswith('/'): raise HTTPException(409, NO_FOLDER_SENTENCE)
        folder = PurePosixPath(path).parent
        cached = self.operations.cap_cache   # the cached capabilities answer; no new helper call
        roots = cached[2].get('roots') if cached and isinstance(cached[2], dict) and isinstance(cached[2].get('roots'), list) else []
        if any(isinstance(r, str) and PurePosixPath(r) == folder for r in roots): raise HTTPException(409, NO_FOLDER_SENTENCE)
        return folder

    def secrets(self):
        with self.store.lock: return secret_values(self.store.state)

    # Link state on the map (C06 §2.2) -----------------------------------------------------------------------------

    def link_state(self, lab_id):
        """Which container interfaces of a linked lab are up, per manager device, from one lab-wide helper call (the
        `all` option of `interfaces`). Nothing is stored, logged or put in an event; a degraded case is an answer
        (`available: false`, a reason and its sentence), never an error, so a poll can tell "off here" from trouble."""
        with self.store.lock:
            lab = self.store.lab(lab_id)
            if not lab: raise HTTPException(404, 'Lab not found')
            nodes = [{k: n.get(k) for k in ('name', 'short_name', 'definition_node', 'kind', 'platform')} for n in lab.get('nodes') or [] if isinstance(n, dict)]
            lab = {k: lab[k] for k in ('id', 'name', 'deployment_name', 'container_prefix') if k in lab}
        off = lambda reason, text: {'available': False, 'reason': reason, 'text': text}
        if not lab.get('deployment_name'): return off('unlinked', LINK_UNLINKED_SENTENCE)
        cached = self.operations.cap_cache   # the cached capabilities answer while it is fresh; no new helper call
        caps = cached[2] if cached and cached[1] > time.monotonic() and isinstance(cached[2], dict) else None
        if caps is not None:
            if 'link_state' not in caps: return off('helper', LINK_HELPER_SENTENCE)
            if caps['link_state'] is not True:
                if caps.get('version') != __version__: return off('helper', LINK_HELPER_SENTENCE)
                version = caps.get('containerlab')
                return off('containerlab', LINK_CONTAINERLAB_SENTENCE % (' (it has %s)' % version[:32] if isinstance(version, str) and version else ''))
        try: result = self.diagnose({'mode': 'interfaces', 'name': lab['deployment_name'], 'options': {'all': True}}, 30)
        except HTTPException as exc:
            # A helper before C03 does not know the mode; one before C06 refuses the option. Either is the helper to update.
            if exc.status_code == 409 and exc.detail in (OLD_HELPER_SENTENCE, 'Unsupported interface options.'): return off('helper', LINK_HELPER_SENTENCE)
            raise
        if result.get('present') is not True: return off('not running', LINK_NOT_RUNNING_SENTENCE)
        listing = {}
        for entry in (result.get('nodes') if isinstance(result.get('nodes'), list) else [])[:LINK_CONTAINER_LIMIT]:
            if isinstance(entry, dict) and isinstance(entry.get('name'), str) and entry['name'] not in listing:
                listing[entry['name']] = entry.get('interfaces') if isinstance(entry.get('interfaces'), list) else []
        devices = {}
        for node in nodes:
            container = expected_container(lab, node)
            if not container or not isinstance(node.get('name'), str): continue   # unknown in the browser: never drawn down
            kind = node.get('kind') or node.get('platform') or ''
            kind = kind if isinstance(kind, str) else ''
            rows = []
            for item in listing.get(container, [])[:INTERFACE_LIMIT]:
                if not isinstance(item, dict) or not isinstance(item.get('name'), str) or not item['name']: continue
                name = item['name'][:64]; role = interface_role(kind, name)
                shown = displayed_interface(kind, name) if role == 'data' else name
                rows.append({'name': name, 'alias': text_value(item.get('alias'), 64), 'state': text_value(item.get('state'), 64),
                             'port': shown if shown != name else '', 'role': role})
            device = {'listed': container in listing, 'interfaces': rows}
            if kind in VM_KINDS: device['vm'] = True
            devices[node['name']] = device
        return {'available': True, 'devices': devices, 'listed': sum(1 for d in devices.values() if d['listed']), 'of': len(devices),
                'fetched_at': time.time()}

    # The VM's images ---------------------------------------------------------------------------------------------

    def vm_images(self):
        host = self.operations.host(); key = host.get('revision')
        with self.operations.image_flight:   # the one image question on the VM at a time, shared with image-check
            with self.images_lock:
                if self.images_cache and self.images_cache[0] == key and self.images_cache[1] > time.monotonic(): return self.images_cache[2]
            result = self.ask({'mode': 'images'}, None)
            images = [i for i in result.get('images', []) if isinstance(i, str)][:IMAGE_LIMIT] if isinstance(result.get('images'), list) else []
            details = []
            for row in result.get('details', []) if isinstance(result.get('details'), list) else []:
                if isinstance(row, dict) and isinstance(row.get('reference'), str):
                    details.append({'reference': row['reference'][:300], 'id': text_value(row.get('id'), 64),
                                    'size': text_value(row.get('size'), 32), 'created': text_value(row.get('created'), 64)})
            value = {'available': bool(result.get('available')), 'images': images, 'details': details[:IMAGE_LIMIT]}
            with self.images_lock: self.images_cache = (key, time.monotonic() + IMAGE_TTL, value)
        return value

    def image_answer(self):
        """The VM's images with `used_by` (reference -> lab names) and `missing` (references a lab names that the VM
        has none of). A lab's reference that matches a VM image by `image_key` is listed under the VM's own
        spelling; one that matches none stays under its own spelling and, unless digest-pinned, is missing."""
        value = self.vm_images()
        vm_by_key = {}
        for reference in value['images']: vm_by_key.setdefault(image_key(reference), reference)
        with self.store.lock: labs = [(l['name'], l.get('definition_yaml') or '') for l in self.store.state['labs']]
        used_by = {}; missing = []
        for name, text in labs:
            for entry in topology_images(text):
                key = image_key(entry['reference'])
                reference = vm_by_key.get(key)
                if reference is None:
                    reference = entry['reference']
                    if '@' not in reference and reference not in missing: missing.append(reference)
                names = used_by.setdefault(reference, [])
                if name not in names: names.append(name)
        return {**value, 'used_by': used_by, 'missing': missing if value['available'] else []}   # the VM said nothing when it has no Docker client

    # The routes --------------------------------------------------------------------------------------------------

    def install(self, app):
        """Installed before LabOperations.install: its `GET /api/operations/{job_id}` would otherwise take
        /logs, /interfaces and /netem, and the images and browse routes here supersede its two of the same
        path (the helper request without the new options is unchanged)."""

        @app.get('/api/operations/logs')
        def logs(lab_id: str = Query(max_length=64), node: str = Query(max_length=253), tail: str = str(DEFAULT_TAIL), since: str = ''):
            if not TAIL_DIGITS.fullmatch(tail): raise HTTPException(400, TAIL_SENTENCE)
            count = int(tail)
            if type(count) is not int or not 1 <= count <= LOGS_TAIL_LIMIT: raise HTTPException(400, TAIL_SENTENCE)
            if since and not LOGS_SINCE.fullmatch(since): raise HTTPException(400, SINCE_SENTENCE)
            _, container, request = self.device_request('logs', lab_id, node)
            request['options']['tail'] = count
            if since: request['options']['since'] = since
            result = self.diagnose(request, 30)
            facts = public_facts(result.get('facts'))
            answer = {'container': container, 'present': facts['present'], 'facts': facts, 'lines': [], 'truncated': False, 'fetched_at': time.time()}
            if not facts['present']: return answer
            text = strip_escapes(result.get('text') if isinstance(result.get('text'), str) else '')
            rows = redact_lines(split_lines(text), self.secrets(), stamped=True)[-LOG_LINE_LIMIT:]
            answer['lines'] = [{'at': at, 'text': body} for at, body in rows]
            answer['truncated'] = result.get('truncated') is True
            return answer

        @app.get('/api/operations/interfaces')
        def interfaces(lab_id: str = Query(max_length=64), node: str = Query(max_length=253)):
            row, container, request = self.device_request('interfaces', lab_id, node)
            result = self.diagnose(request, 45)
            facts = public_facts(result.get('facts'))
            raw_facts = result.get('facts') if isinstance(result.get('facts'), dict) else {}
            kind = text_value(raw_facts.get('kind'), 64) or row.get('kind') or row.get('platform') or ''
            answer = {'container': container, 'present': facts['present'], 'facts': facts, 'interfaces': [],
                      'counters': {}, 'sampled_at': None, 'counters_reason': ''}
            if not facts['present']: return answer
            for item in (result.get('interfaces') if isinstance(result.get('interfaces'), list) else [])[:INTERFACE_LIMIT]:
                if not isinstance(item, dict) or not isinstance(item.get('name'), str) or not item['name']: continue
                name = item['name'][:64]; role = interface_role(kind, name)
                shown = displayed_interface(kind, name) if role == 'data' else name
                answer['interfaces'].append({'name': name, 'alias': text_value(item.get('alias'), 64), 'state': text_value(item.get('state'), 64),
                                            'mac': text_value(item.get('mac'), 64), 'type': text_value(item.get('type'), 64),
                                            'mtu': int_value(item.get('mtu')), 'ifindex': int_value(item.get('ifindex')),
                                            'port': shown if shown != name else '', 'role': role})
            listed = {row['name'] for row in answer['interfaces']}
            counters = result.get('counters') if isinstance(result.get('counters'), dict) else None
            if counters is not None:
                for name in listed:
                    sample = counters.get(name)
                    if isinstance(sample, dict): answer['counters'][name] = {k: int_value(sample.get(k)) for k in COUNTER_KEYS}
                sampled = result.get('sampled_at')
                answer['sampled_at'] = float(sampled) if type(sampled) in (int, float) else None
            else:
                reason = result.get('counters_reason')
                answer['counters_reason'] = reason if reason in ('pid', 'host') else 'pid'
            return answer

        @app.get('/api/operations/link-state')
        def link_state(lab_id: str = Query(max_length=64)): return self.link_state(lab_id)

        @app.get('/api/operations/netem')
        def netem(lab_id: str = Query(max_length=64), node: str = Query(max_length=253)):
            _, container, request = self.device_request('netem-show', lab_id, node)
            result = self.diagnose(request, 30)
            facts = public_facts(result.get('facts'))
            answer = {'container': container, 'present': facts['present'], 'impairments': []}
            if not facts['present']: return answer
            for item in (result.get('impairments') if isinstance(result.get('impairments'), list) else [])[:INTERFACE_LIMIT]:
                if not isinstance(item, dict) or not isinstance(item.get('interface'), str) or not item['interface']: continue
                row = {'interface': item['interface'][:64]}
                for key in IMPAIRMENT_KEYS:
                    value = item.get(key)
                    if isinstance(value, str): row[key] = value[:64]
                    elif type(value) in (int, float): row[key] = value
                answer['impairments'].append(row)
            return answer

        @app.get('/api/operations/images')
        def images(): return self.image_answer()

        @app.post('/api/operations/browse')
        def browse(data: BrowseRequest):
            if not data.files: return self.ask({'mode': 'browse', 'path': data.path}, None)
            if not data.lab_id: raise HTTPException(400, OUTSIDE_FOLDER_SENTENCE)
            folder = self.folder_of(data.lab_id)   # Lab files mode is bound to the lab's folder here, as view() binds a file
            if any(ord(c) < 32 for c in data.path): raise HTTPException(400, OUTSIDE_FOLDER_SENTENCE)
            given = PurePosixPath(data.path) if data.path else folder
            if '..' in given.parts or not given.is_absolute() or (given != folder and folder not in given.parents): raise HTTPException(400, OUTSIDE_FOLDER_SENTENCE)
            result = self.ask({'mode': 'browse', 'path': str(given), 'options': {'files': True}}, None)
            entries = []
            for entry in result.get('entries') if isinstance(result.get('entries'), list) else []:
                if not isinstance(entry, dict) or not isinstance(entry.get('name'), str) or not isinstance(entry.get('path'), str): continue
                kind = entry.get('kind') if entry.get('kind') in ('directory', 'topology', 'file') else ('directory' if entry.get('directory') else 'topology')
                row = {'name': entry['name'], 'path': entry['path'], 'directory': kind == 'directory', 'kind': kind}
                if kind != 'directory' and type(entry.get('size')) is int: row['size'] = entry['size']
                entries.append(row)
            return {'path': text_value(result.get('path'), 4096), 'parent': text_value(result.get('parent'), 4096), 'entries': entries}

        @app.post('/api/operations/view')
        def view(data: ViewRequest):
            folder = self.folder_of(data.lab_id)
            if not data.path or any(ord(c) < 32 for c in data.path): raise HTTPException(400, OUTSIDE_FOLDER_SENTENCE)
            path = PurePosixPath(data.path)
            if '..' in path.parts: raise HTTPException(400, OUTSIDE_FOLDER_SENTENCE)
            full = path if path.is_absolute() else folder / path
            if full == folder or folder not in full.parents: raise HTTPException(400, OUTSIDE_FOLDER_SENTENCE)
            result = self.ask({'mode': 'read', 'path': str(full)}, None)
            text = strip_escapes(result.get('text') if isinstance(result.get('text'), str) else '')
            text, truncated = cut_last(redact_text(text, self.secrets()), VIEW_LIMIT)   # redact the whole text, then cut
            return {'name': full.name, 'text': text, 'truncated': truncated}
