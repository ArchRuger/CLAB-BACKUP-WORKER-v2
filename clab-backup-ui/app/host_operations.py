"""Installed host operations service. Structured stdin, fixed argv, no shell.

Stdlib only. Deployment is privileged and restricted to explicitly trusted roots.
Topology hooks and mounts retain Containerlab semantics; this is not a sandbox.
"""
import errno
import hashlib
import json
import os
from pathlib import Path
import queue
import re
import signal
import stat
import subprocess
import sys
import threading
import time
import uuid
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

PROTOCOL = 'clab-manager-operations-v1'
VERSION = '1.31.6'
LIMIT = 1024 * 1024
# `containerlab inspect --all` runs a Docker inspection per container: several labs or a busy daemon take
# well over the short bound of the other commands. The same bounds as discovery's copy of this command
# (host_files.INSPECT_TIMEOUT, COMMAND_LIMIT); the manager waits 180 s for a review, 1250 s for a run.
INSPECT_TIMEOUT = 25
INSPECT_LIMIT = 4 * LIMIT
# Read-only image questions for the lab builder and the deploy review: which images this VM already
# has, and whether a named image is on the VM or can be pulled from its registry. Both run the Docker
# client with fixed argv; the only client input is an image reference checked against Docker's own
# reference grammar and passed as one argv element. No image is pulled, run or removed here.
DOCKER = '/usr/bin/docker'
IMAGE_CHECK_LIMIT = 16
IMAGE_PROBE_TIMEOUT = 12
# github.com/distribution/reference: optional registry host (with port), lower-case path components
# joined by separators, an optional tag, an optional digest. Nothing else reaches argv.
IMAGE_REFERENCE = re.compile(
    r'^(?:(?:[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)(?:\.(?:[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?))*(?::[0-9]{1,5})?/)?'
    r'[a-z0-9]+(?:(?:[._]|__|-+)[a-z0-9]+)*(?:/[a-z0-9]+(?:(?:[._]|__|-+)[a-z0-9]+)*)*'
    r'(?::[A-Za-z0-9_][A-Za-z0-9_.-]{0,127})?(?:@[A-Za-z][A-Za-z0-9]*(?:[-_+.][A-Za-z][A-Za-z0-9]*)*:[0-9a-fA-F]{32,})?$')
# Read-only diagnostics of one deployed device: its container log, its interfaces with one counter
# sample, and its impairments. They run outside the host lock (they change nothing, and their value is
# highest while a deploy holds it). The variable argv elements are the validated lab name, the
# container name node_selector() bound, a tail count, a `since` stamp of this exact shape, and the
# 64-hex Id that `docker inspect --type container` returned after its labels named this lab and node.
LOGS_TAIL_LIMIT = 2000
LOGS_TIMEOUT = 15
LOGS_LIMIT = 512 * 1024
LOGS_SINCE = re.compile(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d{1,9})?Z', re.ASCII)
CONTAINER_ID = re.compile(r'[0-9a-f]{64}')
# Health is an optional key: a container without a HEALTHCHECK has no `State.Health` at all, and Docker
# 27 evaluates a template with `index .Config.Labels` against the raw JSON map, where `.State.Health`
# then fails the whole inspect ("map has no entry for key Health"). `index .State "Health"` is nil there
# and `with` skips it; every optional map key in this format is read with `index` for that reason.
INSPECT_FORMAT = '\t'.join(('{{.Id}}', '{{.State.Pid}}', '{{.State.Status}}', '{{.State.StartedAt}}', '{{with index .State "Health"}}{{.Status}}{{end}}',
                            '{{index .Config.Labels "containerlab"}}', '{{index .Config.Labels "clab-node-name"}}', '{{index .Config.Labels "clab-node-kind"}}',
                            '{{index .Config.Labels "clab-topo-file"}}', '{{json .NetworkSettings.Ports}}', '{{.HostConfig.NetworkMode}}'))
CGROUP_LINE = r'(?:^|/)(?:docker-)?%s(?:\.scope)?(?:$|/)'
PROC_LIMIT = 64 * 1024
INTERFACE_LIMIT = 256
# The `all` option of `interfaces` (C06 link state): at most this many containers of one lab are answered.
LINK_CONTAINER_LIMIT = 512
TRUSTED_ROOTS_SENTENCE = 'This lab was deployed from outside the trusted lab roots. Add its project root during operations setup.'
BINDING_FAILED_SENTENCE = 'Containerlab on the VM did not list this lab.'
# lab_links: a containerlab before 0.64 has no `inspect interfaces`; it answers the plain `inspect` JSON (an object), not a list.
INTERFACES_LISTING_SENTENCE = 'Containerlab on the VM cannot list interfaces (0.64 or later is needed).'
# The text files the lab browser lists beside the topologies (`files` option) and the viewer reads:
# what containerlab and its users write into a lab folder. Keys, certificates, `.env`, binaries and
# hooks are never listed or read.
READABLE = ('.yaml', '.yml', '.json', '.drawio', '.txt', '.cfg', '.conf', '.set', '.md')
READABLE_NAMES = ('startup-config', 'juniper.conf')
LIFECYCLE = ('deploy', 'redeploy', 'destroy', 'apply', 'start', 'stop', 'restart', 'save', 'inspect')
# One device at a time: containerlab's node-scoped restart, start and stop (the action without `-node` is the command).
NODE_ACTIONS = ('restart-node', 'start-node', 'stop-node')
# Run options beyond cleanup and graceful, each allowed only for the actions named here (C05 design section 2.8) and
# appended only when the installed command's help lists its flag. A partial deploy is only for a lab that is not deployed.
OPTION_ACTIONS = {'nodes': ('deploy', 'destroy', 'save'), 'max_workers': ('deploy', 'redeploy', 'destroy'),
                  'skip_post_deploy': ('deploy', 'redeploy'), 'keep_mgmt_net': ('redeploy', 'destroy')}
NODE_NAME = re.compile(r'[A-Za-z0-9_][A-Za-z0-9_.-]{0,119}')
NODE_FILTER_LIMIT = 64
MAX_WORKERS_LIMIT = 64
# The dry run (`deploy --dry-run --format json`): read-only, pulls nothing, creates nothing (facts F8, F12); it is the
# plan inside the apply review and the pending-changes check `apply-plan`.
APPLY_PLAN_TIMEOUT = 60
PLAN_LIST_LIMIT = 256
PLAN_KEYS = (('added-nodes', 'added'), ('deleted-nodes', 'removed'), ('recreated-nodes', 'recreated'), ('started-nodes', 'started'),
             ('restarted-nodes', 'restarted'), ('added-links', 'links_added'), ('deleted-endpoints', 'endpoints_removed'))
# Link impairments (`tools netem set` / `reset`): one interface of one running container of this lab, bound by
# container_of() and the container id the drawer showed; never the management interface, never a host-network task.
NETEM_TIMEOUT = 15
SHOW_ALL_DEADLINE = 60
IMPAIRMENT_INTERFACE = re.compile(r'[A-Za-z0-9_][A-Za-z0-9_.-]{0,14}', re.ASCII)   # Linux IFNAMSIZ; never a leading dash (an option-like argv element)
IMPAIRMENT_TIME = re.compile(r'(0|[1-9][0-9]{0,5})(ms|s)', re.ASCII)
DELAY_LIMIT_MS = 60000
RATE_LIMIT_KBIT = 10_000_000
MANAGEMENT_INTERFACES = ('eth0', 'lo')
IMPAIRMENT_SET_KEYS = ('node', 'container', 'interface', 'delay', 'jitter', 'loss', 'rate', 'corruption')
IMPAIRMENT_RESET_KEYS = ('node', 'container', 'interface')
TIME_SENTENCE = 'Delay and jitter are a number with ms or s, up to 60s.'
PERCENT_SENTENCE = 'Loss and corruption are a percentage from 0 to 100.'
RATE_SENTENCE = 'Rate is a whole number of kbit/s.'
CHANGED_SENTENCE = "The device's container changed since you opened this section; reopen it and apply again."
HOST_NETWORK_SENTENCE = "This device shares the VM's own network; its interfaces are the VM's and cannot be impaired."
# The one host lock. main() takes it, non-blocking, for exactly preview, run, netem-set and netem-reset; held elsewhere
# answers LOCK_SENTENCE and runs nothing. lab_operations.LOCK_SENTENCE is pinned equal to it.
LOCK_PATH = '/run/clab-manager-operations.lock'
LOCK_SENTENCE = 'Another host lab operation is running.'
# The lab builder publishes a new lab folder (publish) and saves again over a lab that is not
# deployed (revise). Both texts travel in one request line, so each stays well inside it.
BUILDER_LIMIT = 512 * 1024
ANNOTATIONS_SUFFIX = '.annotations.json'
ENV = {'PATH': '/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin', 'HOME': '/root',
       'GIT_TERMINAL_PROMPT': '0', 'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': '/dev/null', 'NO_COLOR': '1'}


def identity(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]{0,119}', value):
        raise ValueError('Choose a literal lab/project name.')
    return value


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def container_matches(container, lab, node):
    """Whether `container` is what containerlab names node `node` of lab `lab`: <prefix>-<lab>-<node> for any
    prefix, <lab>-<node> for the `__lab-name` prefix, or the bare node name for an empty prefix. The one rule
    node_selector() and the `nodes` membership check apply; a bare suffix match would let `switch` bind
    `…-vjunos-switch`."""
    return container == node or container == lab + '-' + node or container.endswith('-' + lab + '-' + node)


def node_selector(options, lab):
    """The one topology node of a single-device action, and the container it must be on the VM.

    Fails closed: each must be one plain literal string (the node as containerlab names it in the
    topology, the container as `inspect` lists it). A list, a comma-separated pair, an option-like
    value, an empty or absent selector is refused here, so a request without a valid selector can
    never continue into the lab-wide restart. The container must be exactly what containerlab names
    that node of this lab: <prefix>-<lab>-<node> for any prefix, <lab>-<node> for the `__lab-name`
    prefix, or the bare node name for an empty prefix; a bare suffix match would let `switch` bind
    `…-vjunos-switch`."""
    node = options.get('node'); container = options.get('container')
    if not isinstance(node, str) or not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]{0,119}', node):
        raise ValueError('Choose one device by its literal topology node name.')
    if not isinstance(container, str) or not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]{0,252}', container):
        raise ValueError('The device has no valid container name.')
    if not container_matches(container, lab, node): raise ValueError('The container name does not belong to this topology node.')
    return node, container


def image_reference(value):
    """A Docker image reference as the helper will pass it (one argv element), or ValueError."""
    if not isinstance(value, str) or not 1 <= len(value) <= 255 or value[0] == '-' or not IMAGE_REFERENCE.fullmatch(value):
        raise ValueError('Not a usable image reference.')
    return value


def probe(argv, timeout=IMAGE_PROBE_TIMEOUT):
    """Run a bounded read-only command and keep its stderr: a registry answer is told apart from an
    unreachable registry by the Docker client's own message. (code, stdout, stderr), killed on timeout."""
    try:
        done = subprocess.run(argv, cwd='/', env=ENV, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return 124, '', 'timed out after %ds' % timeout
    return done.returncode, done.stdout[:LIMIT].decode('utf8', errors='replace'), done.stderr[:4096].decode('utf8', errors='replace')


def registry_answer(code, stderr):
    """What `docker manifest inspect` said about a reference that is not on the VM."""
    if code == 0: return 'found'
    text = (stderr or '').lower()
    # The Docker client could not even ask (its credential helper is broken): no verdict about the image.
    if 'error getting credentials' in text or 'credential' in text and 'executable file not found' in text: return 'unknown'
    if any(w in text for w in ('manifest unknown', 'no such manifest', 'not found', 'requested access to the resource is denied',
                               'authentication required', 'name unknown', 'repository does not exist')): return 'not-found'
    if any(w in text for w in ('no such host', 'timed out', 'timeout', 'connection refused', 'error pinging', 'network is unreachable',
                               'tls handshake', 'certificate', 'eof', 'dial tcp', 'temporary failure')): return 'unreachable'
    return 'unknown'


def capture(argv, cwd='/', timeout=15, limit=LIMIT):
    # JSON inspection must not be contaminated by Containerlab's stderr log lines.
    process = subprocess.Popen(argv, cwd=cwd, env=ENV, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    timer = threading.Timer(timeout, process.kill); timer.start()
    try:
        output = process.stdout.read(limit + 1)
        if len(output) > limit: raise ValueError('Command output exceeded %d MiB.' % (limit // LIMIT))
        code = process.wait(timeout=2)
        return code, output.decode('utf8', errors='replace')
    finally:
        timer.cancel()
        if process.poll() is None: process.kill()
        process.wait(); process.stdout.close()


def capture_merged(argv, cwd='/', timeout=15, limit=LIMIT):
    """`capture` for the one command whose stderr is part of the answer (`docker logs`: a container's
    two streams). Unlike `capture` it keeps the newest bytes: the stream is read to its end (or the
    timeout) and only the last limit + 1 bytes are returned, raw, so the caller can tell that it was
    longer and cut at a line before decoding. Memory stays within twice the limit."""
    process = subprocess.Popen(argv, cwd=cwd, env=ENV, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
    timer = threading.Timer(timeout, process.kill); timer.start()
    try:
        output = bytearray()
        while True:
            chunk = process.stdout.read1(65536)
            if not chunk: break
            output += chunk
            if len(output) > 2 * limit + 2: del output[:len(output) - limit - 1]
        return process.wait(timeout=2), bytes(output[-(limit + 1):])
    finally:
        timer.cancel()
        if process.poll() is None: process.kill()
        process.wait(); process.stdout.close()


def read_fd(fd, limit):
    """At most limit bytes from an open descriptor (one more than the caller allows, so it can tell)."""
    data = b''
    while len(data) <= limit:
        chunk = os.read(fd, limit + 1 - len(data))
        if not chunk: break
        data += chunk
    return data


def bounded_text(value, limit=64):
    return value[:limit] if isinstance(value, str) else ''


def bounded_int(value):
    return value if type(value) is int else 0


def readable_name(name):
    return name in READABLE_NAMES or Path(name).suffix.lower() in READABLE


def port_bindings(text):
    """Docker's `NetworkSettings.Ports` reduced to [{container: '22/tcp', host: '2201'}], digits only."""
    try: value = json.loads(text)
    except ValueError: return []
    if not isinstance(value, dict): return []
    found = []
    for key in sorted((k for k in value if isinstance(k, str) and re.fullmatch(r'[0-9]{1,5}/(tcp|udp|sctp)', k)), key=lambda k: (int(k.split('/')[0]), k)):
        rows = value[key] if isinstance(value[key], list) else []
        hosts = sorted({r['HostPort'] for r in rows if isinstance(r, dict) and isinstance(r.get('HostPort'), str) and re.fullmatch(r'[0-9]{1,5}', r['HostPort'])}, key=int)
        found.extend({'container': key, 'host': host} for host in hosts)
    return found[:64]


def interface_rows(rows):
    """`containerlab inspect interfaces` entries of one container, reduced to bounded plain values."""
    found = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict) or not isinstance(row.get('name'), str) or not row['name']: continue
        found.append({'name': row['name'][:64], 'alias': bounded_text(row.get('alias')), 'state': bounded_text(row.get('state')), 'mac': bounded_text(row.get('mac')),
                      'type': bounded_text(row.get('type')), 'mtu': bounded_int(row.get('mtu')), 'ifindex': bounded_int(row.get('ifindex'))})
        if len(found) >= INTERFACE_LIMIT: break
    return found


def link_rows(rows):
    """`containerlab inspect interfaces` entries of one container reduced to what a link colour needs: the name,
    alias, state and type, each cut at 64 characters. No MAC, MTU or ifindex (the device drawer has its own call)."""
    found = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict) or not isinstance(row.get('name'), str) or not row['name']: continue
        found.append({'name': row['name'][:64], 'alias': bounded_text(row.get('alias')), 'state': bounded_text(row.get('state')), 'type': bounded_text(row.get('type'))})
        if len(found) >= INTERFACE_LIMIT: break
    return found


def impairment_rows(rows):
    """`containerlab tools netem show` entries of one container, reduced to the keys `netem set` names
    (`packet_loss`, containerlab's JSON key for `--loss`, is read as `loss`); unknown keys are dropped; an
    interface printed as `eth1 (ge-0/0/0)` is split into `interface` and `alias`."""
    found = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict): continue
        item = {}
        for key in ('interface', 'delay', 'jitter', 'loss', 'rate', 'corruption'):
            value = row.get(key, row.get('packet_loss') if key == 'loss' else None)
            if isinstance(value, str): item[key] = value[:64]
            elif type(value) in (int, float): item[key] = value
        # containerlab prints a VM-in-container interface as 'eth1 (ge-0/0/0)': the Linux name is what `netem set`
        # and `reset` take, the NOS name is kept as `alias` (verified live on vJunos-switch, 2026-10-23).
        name = item.get('interface')
        if isinstance(name, str) and ' (' in name and name.endswith(')'):
            item['interface'], alias = name.split(' (', 1)[0], name.split(' (', 1)[1][:-1]
            if alias: item['alias'] = alias[:64]
        if isinstance(item.get('interface'), str) and item['interface']: found.append(item)
        if len(found) >= INTERFACE_LIMIT: break
    return found


def duration_ms(value):
    """A netem delay or jitter as the request spells it (`<n>ms` or `<n>s`, no leading zero), in milliseconds."""
    match = IMPAIRMENT_TIME.fullmatch(value) if isinstance(value, str) else None
    if not match: raise ValueError(TIME_SENTENCE)
    ms = int(match.group(1)) * (1000 if match.group(2) == 's' else 1)
    if ms > DELAY_LIMIT_MS: raise ValueError(TIME_SENTENCE)
    return ms


def percentage(value):
    """A loss or corruption percentage: an int or float (never a bool) in 0..100, `-0.0` normalised to 0."""
    if type(value) not in (int, float) or not 0 <= value <= 100: raise ValueError(PERCENT_SENTENCE)
    return 0 if value == 0 else value


def impairment_values(options):
    """The five values of a `netem-set` row, validated (C05 design section 2.2, the table shared with the manager and
    the UI), rendered as the argv text containerlab receives: durations as sent, percentages with `%g` (at most six
    significant digits, `0` for zero), the rate as a whole number. Jitter needs a delay; an all-zero row is a Reset."""
    delay = duration_ms(options['delay']); jitter = duration_ms(options['jitter'])
    loss = percentage(options['loss']); corruption = percentage(options['corruption']); rate = options['rate']
    if type(rate) is not int or not 0 <= rate <= RATE_LIMIT_KBIT: raise ValueError(RATE_SENTENCE)
    if jitter and not delay: raise ValueError('Set a delay before adding jitter.')
    if not (delay or jitter or loss or corruption or rate): raise ValueError('Set at least one impairment, or use Reset to remove them.')
    return {'delay': options['delay'], 'jitter': options['jitter'], 'loss': '%g' % loss, 'rate': str(rate), 'corruption': '%g' % corruption}


def apply_plan(value):
    """The dry run's JSON (fact F8) reduced to bounded, sorted lists and reasons, so the same plan always hashes the
    same whatever order containerlab printed it in; `null` lists are empty, unknown keys are dropped."""
    value = value if isinstance(value, dict) else {}
    plan = {'deploys_lab': value.get('deployed-lab') is True}
    for key, out in PLAN_KEYS:
        rows = value.get(key)
        plan[out] = sorted(r[:120] for r in rows if isinstance(r, str) and r)[:PLAN_LIST_LIMIT] if isinstance(rows, list) else []
    reasons = value.get('node-change-reasons')
    reasons = reasons if isinstance(reasons, dict) else {}
    plan['reasons'] = {k[:120]: v[:200] for k, v in sorted((k, v) for k, v in reasons.items() if isinstance(k, str) and k and isinstance(v, str))[:PLAN_LIST_LIMIT]}
    return plan


def plan_changes(plan):
    return bool(plan) and (plan['deploys_lab'] or any(plan[out] for _, out in PLAN_KEYS))


def error_line(text, limit=300):
    """The sentence of a failed containerlab command from its stderr (fact F13): the first non-empty line after a
    line reading `ERROR` (its box stripped), else the first line containing `Failed` or `ERRO`, else the last
    non-empty line that is not the INFO banner; the generic `Consult…` line only when nothing better exists."""
    lines = [line.strip() for line in (text or '').splitlines() if line.strip()]
    for index, line in enumerate(lines[:-1]):
        if re.sub(r'[^A-Za-z]', '', line) == 'ERROR': return lines[index + 1][:limit]
    for line in lines:
        if 'Failed' in line or 'ERRO' in line: return line[:limit]
    rest = [line for line in lines[1:] if not line.startswith('Consult with release notes')] or lines[1:] or lines
    return rest[-1][:limit] if rest else ''


def net_dev(text, names):
    """/proc/<pid>/net/dev parsed for the named interfaces only: the eight counters the device drawer shows."""
    wanted = set(names); found = {}
    for line in text.splitlines():
        name, colon, rest = line.partition(':')
        name = name.strip()
        if not colon or name not in wanted: continue
        fields = rest.split()
        if len(fields) < 12 or not all(re.fullmatch(r'[0-9]+', f) for f in fields[:12]): continue
        value = [int(f) for f in fields[:12]]
        found[name] = {'rx_bytes': value[0], 'rx_packets': value[1], 'rx_errors': value[2], 'rx_dropped': value[3],
                       'tx_bytes': value[8], 'tx_packets': value[9], 'tx_errors': value[10], 'tx_dropped': value[11]}
    return found


def stream(argv, cwd, emit, timeout=1200):
    process = subprocess.Popen(argv, cwd=cwd, env=ENV, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               start_new_session=True)
    chunks = queue.Queue(maxsize=32)
    def reader():
        try:
            while True:
                raw = process.stdout.read1(4096)
                if not raw: break
                chunks.put(raw)
        finally: chunks.put(None)
    threading.Thread(target=reader, daemon=True).start()
    until = time.monotonic() + timeout; count = 0; finished = False; last_ping = time.monotonic()
    try:
        while not finished:
            if time.monotonic() > until: raise ValueError('Operation timed out. Inspect the lab before retrying.')
            if time.monotonic() - last_ping > 1:
                emit({'heartbeat': True}); last_ping = time.monotonic()
            try: chunk = chunks.get(timeout=1)
            except queue.Empty:
                emit({'heartbeat': True}); continue
            if chunk is None: finished = True; continue
            count += len(chunk)
            if count <= LIMIT: emit({'output': chunk.decode('utf8', errors='replace')})
            elif count - len(chunk) <= LIMIT: emit({'output': '\n[Further output omitted after 1 MiB.]\n'})
        return process.wait(timeout=5)
    finally:
        if process.poll() is None:
            if os.name == 'posix': os.killpg(process.pid, signal.SIGTERM)
            else: process.terminate()
            try: process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                if os.name == 'posix': os.killpg(process.pid, signal.SIGKILL)
                else: process.kill()
                process.wait()
        process.stdout.close()


class HostOperations:
    def __init__(self, config, run=capture, probe=probe, run_merged=capture_merged):
        self.config = config; self.run = run; self.probe = probe; self.run_merged = run_merged
        self.proc = '/proc'  # a test points the counter sample at a temporary tree
        # Older operations.json files still carry a 'docker' path (the retired Grafana mode used it); it is ignored.
        self.clab = config['clab']
        self.roots = [Path(p) for p in config['roots']]

    def path(self, value, exists=True):
        if not isinstance(value, str) or len(value) > 4096 or any(ord(c) < 32 for c in value):
            raise ValueError('Invalid project path.')
        path = Path(value)
        if not path.is_absolute() or '..' in path.parts: raise ValueError('Use an absolute project path without traversal.')
        if any(p.is_symlink() for p in (path, *path.parents)): raise ValueError('Symlink paths are not supported.')
        if not any(path == root or root in path.parents for root in self.roots):
            raise ValueError('This path is outside the trusted lab roots. Add its project root during operations setup.')
        if exists and not path.exists(): raise ValueError('The selected VM path no longer exists.')
        return path

    def read(self, value):
        path = self.path(value)
        if not path.is_file() or path.stat().st_size > LIMIT: raise ValueError('Select a regular file smaller than 1 MiB.')
        if not readable_name(path.name): raise ValueError('This file type cannot be viewed in the manager.')
        # The bytes come from a descriptor opened through the parent directory with O_NOFOLLOW (a symlink
        # planted at this name or at its parent after the checks above is refused, never followed; a
        # directory higher up is covered by path() only) and O_NONBLOCK (a FIFO cannot make the helper
        # wait for a writer); fstat on that descriptor, not a fresh path stat, must show a regular file
        # within the limit. The same shape as owned_bytes_any().
        try:
            folder_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        except OSError as exc:
            raise ValueError('Symlink paths are not supported.' if exc.errno == errno.ELOOP else 'The selected VM path no longer exists.') from None
        try:
            try: fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=folder_fd)
            except OSError as exc:
                raise ValueError('Symlink paths are not supported.' if exc.errno == errno.ELOOP else 'The selected VM path no longer exists.') from None
            try:
                info = os.fstat(fd)
                if not stat.S_ISREG(info.st_mode) or info.st_size > LIMIT: raise ValueError('Select a regular file smaller than 1 MiB.')
                raw = read_fd(fd, LIMIT)
            finally: os.close(fd)
        finally: os.close(folder_fd)
        if len(raw) > LIMIT: raise ValueError('File exceeded the read limit.')
        return {'path': str(path), 'text': raw.decode('utf-8-sig'), 'sha256': hashlib.sha256(raw).hexdigest()}

    def browse(self, value='', options=None):
        """The folders and topologies under a trusted root; with the one option `files`, also the readable
        text files (READABLE suffixes and containerlab's two configuration names) with their sizes."""
        options = options or {}
        if not isinstance(options, dict) or set(options) - {'files'} or type(options.get('files', False)) is not bool: raise ValueError('Unsupported browse options.')
        files = options.get('files', False)
        if not value: return {'path': '', 'entries': [{'name': str(p), 'path': str(p), 'directory': True} for p in self.roots]}
        path = self.path(value)
        if not path.is_dir(): raise ValueError('Choose a project directory.')
        entries = []
        for p in sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
            if p.name.startswith('.') or p.is_symlink(): continue
            if p.is_dir(): kind = 'directory'
            elif not p.is_file(): continue
            elif p.name.lower().endswith(('.clab.yaml', '.clab.yml')): kind = 'topology'
            elif files and readable_name(p.name): kind = 'file'
            else: continue
            entry = {'name': p.name, 'path': str(p), 'directory': kind == 'directory'}
            if files:
                entry['kind'] = kind
                if kind != 'directory':
                    try: entry['size'] = p.lstat().st_size
                    except OSError: continue
            entries.append(entry)
            if len(entries) >= 500: break
        return {'path': str(path), 'parent': str(path.parent) if path not in self.roots else '', 'entries': entries}

    def help(self, *parts):
        code, out = self.run([self.clab, *parts, '--help'])
        return out if code == 0 and 'unknown command' not in out.lower() else ''

    def docker_available(self):
        return os.access(DOCKER, os.X_OK)

    def images(self):
        """The image references this VM already has (`repository:tag`, dangling images left out), as
        `images` (the list the lab builder reads, unchanged) and `details` (Docker's own id, size and
        creation strings per reference; the manager normalises them)."""
        if not self.docker_available(): return {'available': False, 'images': []}
        code, out = self.run([DOCKER, 'image', 'ls', '--format', '{{.Repository}}:{{.Tag}}\t{{.ID}}\t{{.Size}}\t{{.CreatedAt}}'])
        if code: raise ValueError('Docker on the VM did not list its images.')
        details = {}
        for line in out.splitlines():
            fields = [f.strip() for f in line.split('\t')] + ['', '', '']
            ref = fields[0]
            if not ref or '<none>' in ref or not IMAGE_REFERENCE.match(ref) or ref in details: continue
            details[ref] = {'reference': ref, 'id': fields[1][:64], 'size': fields[2][:32], 'created': fields[3][:64]}
        found = sorted(details)[:1000]
        return {'available': True, 'images': found, 'details': [details[r] for r in found]}

    def container_of(self, options, lab):
        """The container of `lab`'s node `options['node']` as Docker binds it: `{'present': False}` when
        there is none, else its facts. `docker inspect --type container` never resolves an image, a volume
        or a network of that name (it may still resolve a container Id prefix, which the labels then
        refuse); the answer counts only with a 64-hex Id, the labels `containerlab` == lab and
        `clab-node-name` == node, and a `clab-topo-file` inside the trusted roots (the same binding of a
        lab name to a trusted topology path that every lifecycle action has), and that Id (never the
        name) is what the other modes hand to Docker."""
        node, container = node_selector(options, lab)
        if not self.docker_available(): raise ValueError('No Docker client on the VM.')
        code, out, err = self.probe([DOCKER, 'inspect', '--type', 'container', '--format', INSPECT_FORMAT, container], IMAGE_PROBE_TIMEOUT)
        if code:
            if 'no such container' in (err or '').lower(): return {'present': False}
            raise ValueError('Docker on the VM did not answer about this container.')
        fields = out.rstrip('\r\n').split('\t')
        if len(fields) != 11 or not CONTAINER_ID.fullmatch(fields[0]): raise ValueError('Docker on the VM returned an unusable container identity.')
        if fields[5] != lab or fields[6] != node: raise ValueError('This container does not belong to lab ' + lab + '.')
        if not self.trusted(fields[8]): raise ValueError('This lab was deployed from outside the trusted lab roots. Add its project root during operations setup.')
        pid = int(fields[1]) if re.fullmatch(r'[0-9]{1,10}', fields[1]) else 0
        return {'present': True, 'id': fields[0], 'pid': pid, 'status': fields[2][:32], 'health': fields[4][:32], 'started': fields[3][:64],
                'kind': fields[7][:64], 'ports': port_bindings(fields[9]), 'network_mode': fields[10][:64]}

    def trusted(self, value):
        """Whether a topology path a label names lies under a trusted root: the lexical half of path()
        (absolute, no traversal, a root among its parents), without touching the file system."""
        if not isinstance(value, str) or not value or len(value) > 4096 or any(ord(c) < 32 for c in value): return False
        path = Path(value)
        return path.is_absolute() and '..' not in path.parts and any(root in path.parents for root in self.roots)

    def logs(self, name, options):
        """The last `tail` lines of one container's log, stamped, optionally from `since`: raw text (the
        manager redacts), the last 512 KiB cut at a line when longer. Docker's own message never becomes log text."""
        lab = identity(name)
        if not isinstance(options, dict) or set(options) - {'node', 'container', 'tail', 'since'}: raise ValueError('Unsupported log options.')
        tail = options.get('tail')
        if type(tail) is not int or not 1 <= tail <= LOGS_TAIL_LIMIT: raise ValueError('Ask for 1 to %d log lines.' % LOGS_TAIL_LIMIT)
        since = options.get('since')
        if since is not None and (not isinstance(since, str) or not LOGS_SINCE.fullmatch(since)): raise ValueError('The log start must be a UTC timestamp.')
        facts = self.container_of(options, lab)
        if not facts['present']: return {'facts': facts, 'text': '', 'truncated': False}
        argv = [DOCKER, 'logs', '--tail', str(tail), '--timestamps', *(['--since', since] if since else []), facts['id']]
        code, raw = self.run_merged(argv, timeout=LOGS_TIMEOUT, limit=LOGS_LIMIT)
        if code: raise ValueError("Docker on the VM did not return this container's log.")
        truncated = len(raw) > LOGS_LIMIT
        if truncated:
            raw = raw[-LOGS_LIMIT:]; cut = raw.find(b'\n')
            if 0 <= cut < len(raw) - 1: raw = raw[cut + 1:]
        return {'facts': facts, 'text': raw.decode('utf8', errors='replace'), 'truncated': truncated}

    def interfaces(self, name, options):
        """One container's interfaces from the lab-wide `containerlab inspect interfaces`, with one counter
        sample from its own /proc/<pid>/net/dev when the task can be bound to it. With exactly `{'all': True}`
        instead, every running container of the lab with four fields per interface (lab_links)."""
        lab = identity(name)
        if isinstance(options, dict) and 'all' in options:
            if set(options) != {'all'} or options['all'] is not True: raise ValueError('Unsupported interface options.')
            return self.lab_links(lab)
        if not isinstance(options, dict) or set(options) - {'node', 'container'}: raise ValueError('Unsupported interface options.')
        facts = self.container_of(options, lab)
        result = {'facts': facts, 'interfaces': []}
        if not facts['present']: return result
        code, out = self.run([self.clab, 'inspect', 'interfaces', '--name', lab, '-f', 'json'], timeout=INSPECT_TIMEOUT, limit=INSPECT_LIMIT)
        if code: raise ValueError('Containerlab on the VM did not list the interfaces of this lab.')
        try: listing = json.loads(out)
        except ValueError: listing = None  # "no containers found" is text with exit 0
        for entry in listing if isinstance(listing, list) else []:
            if isinstance(entry, dict) and entry.get('name') == options['container']:
                result['interfaces'] = interface_rows(entry.get('interfaces')); break
        counters = self.counters(facts, [row['name'] for row in result['interfaces']])
        if counters is None or counters == 'host': result['counters_reason'] = counters or 'pid'
        else: result['counters'] = counters; result['sampled_at'] = time.time()
        return result

    def lab_links(self, lab):
        """The `all` option of `interfaces` (C06 link state): every running container of `lab` with the name, alias,
        state and type of each interface. Read-only and outside the host lock like the per-device form.

        The lab is bound first, once per call: one fixed `containerlab inspect --name <lab> -f json`, whose every
        row must name a topology inside the trusted roots (container_of's binding of a lab name to a trusted
        topology path, for the whole lab), else nothing is listed. No row (no lab of that name runs) is
        `present: False`, not an error. Then the same lab-wide listing the per-device form reads, kept to the
        containers the binding listed and reduced by link_rows. No Docker command, no counters, no facts; binding
        a container to a manager device is the manager's job."""
        # The binding keeps stderr (probe): containerlab 0.79 answers a lab with no container with exit 1 and
        # "Lab 'x' not found - no running containers." (checked live 2026-10-27), the one failure that means
        # "not running". Every other failure (Docker unreachable, a killed command) is an error, so the manager
        # answers 409 and the browser keeps its colours and retries, instead of showing a running lab as stopped
        # for good (the independent risk review of 1.31.6, docs/parity-campaign/C06-DESIGN.md section 13).
        code, out, err = self.probe([self.clab, 'inspect', '--name', lab, '-f', 'json'], INSPECT_TIMEOUT)
        if code:
            if 'not found' in (err or '').lower(): return {'nodes': [], 'present': False}
            raise ValueError(BINDING_FAILED_SENTENCE)
        try: listing = json.loads(out)
        except ValueError: listing = None
        if isinstance(listing, dict): rows = [row for group in listing.values() for row in (group if isinstance(group, list) else [group])]
        else: rows = listing if isinstance(listing, list) else []
        if not rows: return {'nodes': [], 'present': False}
        if not all(isinstance(row, dict) and self.trusted(row.get('absLabPath') or row.get('labPath')) for row in rows):
            raise ValueError(TRUSTED_ROOTS_SENTENCE)
        bound = {row['name'] for row in rows if isinstance(row.get('name'), str)}
        code, out = self.run([self.clab, 'inspect', 'interfaces', '--name', lab, '-f', 'json'], timeout=INSPECT_TIMEOUT, limit=INSPECT_LIMIT)
        if code: raise ValueError('Containerlab on the VM did not list the interfaces of this lab.')
        try: listing = json.loads(out)
        except ValueError: return {'nodes': [], 'present': False}   # "no containers found" is text with exit 0
        if not isinstance(listing, list): raise ValueError(INTERFACES_LISTING_SENTENCE)
        nodes = []
        for entry in listing:
            if not isinstance(entry, dict) or not isinstance(entry.get('name'), str) or len(entry['name']) > 253 or entry['name'] not in bound: continue
            nodes.append({'name': entry['name'], 'interfaces': link_rows(entry.get('interfaces'))})
            if len(nodes) >= LINK_CONTAINER_LIMIT: break
        return {'nodes': nodes, 'present': True}

    def counters(self, facts, names):
        """The named interfaces' counters from /proc/<pid>/net/dev, read through one directory descriptor of
        /proc/<pid> that is bound to that task (a reused pid answers ESRCH through it, never another
        process's files) and only after its cgroup named this container. None when it cannot be had,
        'host' when the task shares the VM's network namespace; no exec, no shell, nothing enters the container."""
        dir_fd = self.bound_task(facts)
        if dir_fd is None: return None
        try:
            if self.in_host_network(dir_fd): return 'host'
            return net_dev(self.proc_text(dir_fd, 'net/dev'), names)
        except OSError: return None
        finally: os.close(dir_fd)

    def bound_task(self, facts):
        """An open directory descriptor of /proc/<pid> whose cgroup names this container's Id (a whole path
        segment, `/docker/<id>` or `/docker-<id>.scope`, never a substring), or None when the task cannot be bound."""
        pid = facts.get('pid')
        if type(pid) is not int or pid <= 0: return None
        try: dir_fd = os.open('%s/%d' % (self.proc, pid), os.O_RDONLY | os.O_DIRECTORY)
        except OSError: return None
        try:
            if re.search(CGROUP_LINE % facts['id'], self.proc_text(dir_fd, 'cgroup'), re.MULTILINE): return dir_fd
        except OSError: pass
        os.close(dir_fd); return None

    def in_host_network(self, dir_fd):
        """Whether the task's network namespace is the VM's own (a `network-mode: host` node): its
        net/dev would be the VM's interfaces, which the manager never receives. None when it cannot be told."""
        try: own = os.stat('%s/1/ns/net' % self.proc); task = os.stat('ns/net', dir_fd=dir_fd)
        except OSError: return None
        return (own.st_dev, own.st_ino) == (task.st_dev, task.st_ino)

    def network_separate(self, facts):
        """Tri-state: True when the bound task's network namespace is proven separate from the VM's, False when it
        is the VM's own, None when it cannot be bound or told (no task, a cgroup mismatch, an OSError)."""
        dir_fd = self.bound_task(facts)
        if dir_fd is None: return None
        try:
            shared = self.in_host_network(dir_fd)
            return None if shared is None else not shared
        finally: os.close(dir_fd)

    def proc_text(self, dir_fd, name):
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=dir_fd)
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode): raise OSError(errno.EINVAL, 'not a regular file')
            return read_fd(fd, PROC_LIMIT)[:PROC_LIMIT].decode('utf8', errors='replace')
        finally: os.close(fd)

    def netem_show(self, name, options):
        """One container's impairments as `containerlab tools netem show` reports them (read-only; the
        command takes a container name, shown beside the bound facts)."""
        lab = identity(name)
        if not isinstance(options, dict) or set(options) - {'node', 'container'}: raise ValueError('Unsupported impairment options.')
        facts = self.container_of(options, lab)
        if not facts['present']: return {'facts': facts, 'impairments': []}
        return {'facts': facts, 'impairments': self.netem_rows(options['container'])}

    def netem_rows(self, container):
        """`containerlab tools netem show -n <container> -f json`, reduced by impairment_rows()."""
        code, out = self.run([self.clab, 'tools', 'netem', 'show', '-n', container, '-f', 'json'], timeout=NETEM_TIMEOUT)
        try: value = json.loads(out) if not code else None
        except ValueError: value = None
        if value is None: raise ValueError('Containerlab on the VM did not show the impairments of this device.')
        return impairment_rows(value.get(container) if isinstance(value, dict) else None)

    def impairment_request(self, req, keys):
        """The shape and the binding of a mutating netem request `{mode, name, options, expected_id, digest}`: the
        option keys exactly `keys`, `expected_id` a 64-hex container id, and `digest` the helper's own digest over
        `{mode, name, options, expected_id}`, recomputed here. The digest is an integrity check of the manager's own
        request (the options the student confirmed are the options that run); the binding to the live container is
        `expected_id` compared with `container_of()` at execution, not the digest. Returns (options, expected_id)."""
        options = req.get('options')
        if not isinstance(options, dict) or set(options) != set(keys): raise ValueError('Unsupported impairment options.')
        expected_id = req.get('expected_id')
        if not isinstance(expected_id, str) or not CONTAINER_ID.fullmatch(expected_id): raise ValueError(CHANGED_SENTENCE)
        if set(req) - {'mode', 'name', 'options', 'expected_id', 'digest'}: raise ValueError('Review the impairment again.')
        bound = {'mode': req.get('mode'), 'name': req.get('name'), 'options': options, 'expected_id': expected_id}
        if req.get('digest') != digest(bound): raise ValueError('Review the impairment again.')
        return options, expected_id

    def impairment_target(self, name, options, expected_id):
        """The one interface of the one running container an impairment may touch (C05 design section 2.1). The
        interface name is checked first (a literal name, never eth0 or lo: the manager reaches the device through
        eth0); then container_of() binds the container (labels, trusted topology, 64-hex Id), which must be running,
        be the container the drawer showed (`expected_id`), run in its own Docker network (not `host`, not another
        container's), and have a task whose network namespace is proven separate from the VM's (tri-state: shared
        and unknown both refuse). Returns (lab, facts, interface)."""
        lab = identity(name)
        interface = options.get('interface')
        if not isinstance(interface, str) or not IMPAIRMENT_INTERFACE.fullmatch(interface): raise ValueError('Choose an interface by its literal name.')
        if interface == 'eth0': raise ValueError('The management interface eth0 cannot be impaired: the manager reaches the device through it.')
        if interface in MANAGEMENT_INTERFACES: raise ValueError(interface + ' cannot be impaired.')
        facts = self.container_of(options, lab)
        if not facts['present'] or facts['status'] != 'running':
            raise ValueError('Device ' + options['container'] + ' is not running; impairments exist only on a running device.')
        if facts['id'] != expected_id: raise ValueError(CHANGED_SENTENCE)
        mode = facts['network_mode']
        if not mode: raise ValueError("The manager could not read this device's network mode; try again in a moment.")
        if mode == 'host': raise ValueError(HOST_NETWORK_SENTENCE)
        if mode.startswith('container:'): raise ValueError("This device shares another container's network; its interfaces are not its own and cannot be impaired.")
        separate = self.network_separate(facts)
        if separate is False: raise ValueError(HOST_NETWORK_SENTENCE)
        if separate is None: raise ValueError("The manager could not bind this device's network namespace; try again in a moment.")
        return lab, facts, interface

    def netem_set(self, req):
        """`netem-set`: replace the impairments of one interface with the row's five values (containerlab replaces the
        whole qdisc, fact F4, so all five flags always travel). Argv: the fixed command, then the bound container name,
        the validated interface and the five validated values; none of them at argv[0..4]. Runs under the host lock."""
        options, expected_id = self.impairment_request(req, IMPAIRMENT_SET_KEYS)
        lab, facts, interface = self.impairment_target(req.get('name'), options, expected_id)
        values = impairment_values(options)
        container = options['container']
        argv = [self.clab, 'tools', 'netem', 'set', '-n', container, '-i', interface, '--delay', values['delay'], '--jitter', values['jitter'],
                '--loss', values['loss'], '--rate', values['rate'], '--corruption', values['corruption']]
        code, out, err = self.probe(argv, NETEM_TIMEOUT)
        if code:
            if 'Link not found' in (err or ''): raise ValueError(interface + ' is not an interface of this device right now.')
            raise ValueError('Containerlab on the VM refused the impairment: ' + error_line(err, 200))
        return {'facts': facts, 'impairments': self.netem_rows(container)}

    def netem_reset(self, req):
        """`netem-reset`: remove the impairments of one interface. Nothing runs when the interface has no row
        (containerlab fails on a clean interface, fact F7). Runs under the host lock."""
        options, expected_id = self.impairment_request(req, IMPAIRMENT_RESET_KEYS)
        lab, facts, interface = self.impairment_target(req.get('name'), options, expected_id)
        container = options['container']
        rows = self.netem_rows(container)
        if not any(row['interface'] == interface for row in rows): return {'facts': facts, 'changed': False, 'impairments': rows}
        code, out, err = self.probe([self.clab, 'tools', 'netem', 'reset', '-n', container, '-i', interface], NETEM_TIMEOUT)
        if code: raise ValueError('Containerlab on the VM could not reset the impairment on ' + interface + '.')
        return {'facts': facts, 'changed': True, 'impairments': self.netem_rows(container)}

    def netem_show_all(self, name, options):
        """`netem-show-all` (read-only, outside the lock): the impairments of 1..64 devices of one lab in one call,
        each pair bound like the single read and carrying the bound container `id` (64 hex, '' when absent) so the
        manager's impairment calls can send it back as `expected_id`; a stopped or absent device answers `[]`. Pairs not
        reached within SHOW_ALL_DEADLINE, or whose own `netem show` failed, come back as `unread` and the answer says
        `complete: False`."""
        lab = identity(name)
        if not isinstance(options, dict) or set(options) != {'nodes'}: raise ValueError('Unsupported impairment options.')
        pairs = options['nodes']
        if not isinstance(pairs, list) or not 1 <= len(pairs) <= NODE_FILTER_LIMIT: raise ValueError('Name 1 to %d devices.' % NODE_FILTER_LIMIT)
        selected = []
        for pair in pairs:
            if not isinstance(pair, dict) or set(pair) != {'node', 'container'}: raise ValueError('Unsupported impairment options.')
            selected.append(node_selector(pair, lab))
        started = time.monotonic(); devices = []; complete = True
        for node, container in selected:
            if time.monotonic() - started >= SHOW_ALL_DEADLINE:
                devices.append({'node': node, 'container': container, 'unread': True}); complete = False; continue
            facts = self.container_of({'node': node, 'container': container}, lab)   # a binding failure stays fatal
            try:
                rows = self.netem_rows(container) if facts['present'] and facts['status'] == 'running' else []
            except ValueError:
                # One device's failed `netem show` (a container stopping mid-call, an odd answer) must not fail the
                # lab-wide read: it comes back unread, like a pair the deadline did not reach.
                devices.append({'node': node, 'container': container, 'present': True, 'unread': True}); complete = False; continue
            devices.append({'node': node, 'container': container, 'present': facts['present'], 'id': facts.get('id', ''), 'impairments': rows})
        return {'devices': devices, 'complete': complete}

    def dry_run_argv(self, path, name, help_text):
        """The one builder of every dry-run argv: `deploy --dry-run --format json -t <path> [--name <lab>]`. `apply`
        is deploy's alias (fact F8), so the dry run is spelled `deploy`, the command whose help was probed."""
        return [self.clab, 'deploy', '--dry-run', '--format', 'json', '-t', str(path)] + (['--name', name] if '--name' in help_text else [])

    def dry_run(self, path, name):
        """The plan a deploy of `path` would carry out against the live lab: (plan, failed, error) where failed is
        '' (plan is the reduced JSON), 'unsupported' (no --dry-run on this containerlab) or 'error' (error is the
        sentence from stderr). Read-only: writes nothing, pulls nothing (facts F8, F12)."""
        help_text = self.help('deploy')
        if '--dry-run' not in help_text: return None, 'unsupported', ''
        code, out, err = self.probe(self.dry_run_argv(path, name, help_text), APPLY_PLAN_TIMEOUT)
        if code == 0:
            try: value = json.loads(out)
            except ValueError: value = None
            if isinstance(value, dict): return apply_plan(value), '', ''
        return None, 'error', error_line(err)

    def pending_plan(self, name, value):
        """`apply-plan` (read-only, outside the lock): the pending-changes check of one lab from its topology path."""
        lab = identity(name)
        path = self.path(value)
        if path.suffix.lower() not in ('.yaml', '.yml'): raise ValueError('Select the original lab YAML.')
        plan, failed, error = self.dry_run(path, lab)
        return {'plan': plan, 'failed': failed, 'error': error}

    def image_check(self, options):
        """For each reference (at most IMAGE_CHECK_LIMIT, each validated): is it on the VM (`docker image
        inspect`), and if not, does its registry know it (`docker manifest inspect`, bounded, read-only)?
        Answers are `local` (bool) and `registry`: found, not-found, unreachable, unknown, or skipped (local
        images are not asked for; without a Docker client nothing is)."""
        if not isinstance(options, dict) or set(options) - {'references'}: raise ValueError('Unsupported image check options.')
        refs = options.get('references')
        if not isinstance(refs, list) or not 1 <= len(refs) <= IMAGE_CHECK_LIMIT: raise ValueError('Name 1 to %d images per check.' % IMAGE_CHECK_LIMIT)
        refs = [image_reference(r) for r in refs]
        if len(set(refs)) != len(refs): raise ValueError('Name each image once.')
        if not self.docker_available(): return {'available': False, 'images': [{'reference': r, 'local': None, 'registry': 'skipped', 'detail': 'No Docker client on the VM.'} for r in refs]}
        def one(ref):
            code, out, err = self.probe([DOCKER, 'image', 'inspect', '--format', '{{.Id}}', ref], IMAGE_PROBE_TIMEOUT)
            if code == 0 and out.strip(): return {'reference': ref, 'local': True, 'registry': 'skipped', 'detail': ''}
            code, out, err = self.probe([DOCKER, 'manifest', 'inspect', ref], IMAGE_PROBE_TIMEOUT)
            answer = registry_answer(code, err); detail = (err or '').strip().splitlines()
            # The Docker client's last line travels only when the answer itself says nothing (unknown).
            return {'reference': ref, 'local': False, 'registry': answer, 'detail': (detail[-1] if detail and answer == 'unknown' else '')[:200]}
        from concurrent.futures import ThreadPoolExecutor
        pool = ThreadPoolExecutor(max_workers=4)
        try: results = list(pool.map(one, refs))
        finally: pool.shutdown(wait=False, cancel_futures=True)  # a signal stops the queue, not only the main thread
        return {'available': True, 'images': results}

    def capabilities(self):
        actions = {}
        for action in LIFECYCLE:
            help_text = self.help(action)
            actions[action] = {'available': bool(help_text), 'cleanup': '--cleanup' in help_text, 'graceful': '--graceful' in help_text,
                               'node_filter': '--node-filter' in help_text, 'max_workers': '--max-workers' in help_text,
                               'skip_post_deploy': '--skip-post-deploy' in help_text, 'keep_mgmt_net': '--keep-mgmt-net' in help_text,
                               'dry_run': '--dry-run' in help_text}
            # One device (restart-node, start-node, stop-node): containerlab's own node selector on that command.
            if action in ('restart', 'start', 'stop'): actions[action + '-node'] = {'available': bool(help_text) and '--node' in help_text}
        if not actions['redeploy']['available'] and actions['deploy']['available'] and actions['destroy']['available']:
            # The destroy step takes cleanup, graceful, keep_mgmt_net and max_workers; the deploy step skip_post_deploy; no filter, no plan.
            actions['redeploy'] = {**actions['destroy'], 'node_filter': False, 'skip_post_deploy': actions['deploy']['skip_post_deploy'], 'dry_run': False, 'fallback': True}
        actions['impairments'] = {'available': bool(self.help('tools', 'netem', 'set'))}
        actions['clone'] = {'available': bool(self.config.get('network')) and os.access(self.config.get('git', '/usr/bin/git'), os.X_OK)}
        actions['publish'] = {'available': True}; actions['revise'] = {'available': True}
        # `link_state`: `interfaces` with {'all': true} (C06) needs containerlab's own `inspect interfaces` (0.64 or later).
        # A containerlab without it prints the help of `inspect` itself for this argv, so its usage line must name it.
        result = {'protocol': PROTOCOL, 'version': VERSION, 'actions': actions, 'roots': [str(p) for p in self.roots],
                  'network': bool(self.config.get('network')), 'images': self.docker_available(), 'diagnostics': True, 'lifecycle_options': True,
                  'link_state': 'inspect interfaces' in self.help('inspect', 'interfaces')}
        # The installed containerlab's release, for the footer and the debug page; kept only when it reads as one.
        code, out = self.run([self.clab, 'version', '--short'])
        version = out.strip().splitlines()[0].strip() if code == 0 and out.strip() else ''
        if re.match(r'\d+\.\d+\.\d+', version): result['containerlab'] = version[:32]
        return result

    def popular(self):
        if not self.config.get('network'): raise ValueError('Enable --allow-downloads on the VM to browse the online popular-lab catalog.')
        request = Request('https://api.github.com/search/repositories?q=topic:clab-topo+org:srl-labs+fork:true&sort=stars&order=desc', headers={'User-Agent': 'Containerlab-Node-Manager', 'Accept': 'application/vnd.github+json'})
        try:
            with urlopen(request, timeout=12) as response: raw = response.read(LIMIT + 1)
            if len(raw) > LIMIT: raise ValueError()
            items = json.loads(raw).get('items', [])
            return {'items': [{'name': str(i['name'])[:120], 'url': i['html_url'], 'description': str(i.get('description') or '')[:300]} for i in items[:30] if str(i.get('html_url', '')).startswith('https://github.com/srl-labs/')]}
        except Exception: raise ValueError('The GitHub catalog is unavailable. Retry when online or select an existing VM project.')

    def deployed(self):
        code, out = self.run([self.clab, 'inspect', '--all', '--format', 'json'], timeout=INSPECT_TIMEOUT, limit=INSPECT_LIMIT)
        if code: raise ValueError('Could not inspect deployed labs before the operation.')
        value = json.loads(out)
        groups = {}
        if not isinstance(value, (dict, list)): raise ValueError('Unsupported Containerlab inspection response.')
        iterable = [(None, value)] if isinstance(value, list) else value.items()
        for group, rows in iterable:
            if not isinstance(rows, list): raise ValueError('Unsupported Containerlab inspection response.')
            for row in rows:
                if not isinstance(row, dict): raise ValueError('Unsupported Containerlab inspection response.')
                name = row.get('lab_name') or group
                groups.setdefault(name, []).append(row)
        return groups

    def builder_texts(self, options):
        """The YAML and the optional annotations of a builder request; None means no annotations."""
        text = options.get('text'); annotations = options.get('annotations')
        if not isinstance(text, str) or not text.strip() or len(text.encode()) > BUILDER_LIMIT: raise ValueError('The topology must be text smaller than 512 KiB.')
        if annotations is not None and (not isinstance(annotations, str) or len(annotations.encode()) > BUILDER_LIMIT):
            raise ValueError('The map layout must be text smaller than 512 KiB.')
        return text, annotations

    def owned_bytes(self, path):
        """Bytes of a regular, single-link file of this account, read without following a symlink."""
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.geteuid() or info.st_size > BUILDER_LIMIT: return None
            return os.read(fd, BUILDER_LIMIT + 1)
        finally: os.close(fd)

    def publish_state(self, folder, wanted):
        """new, reuse, resume or published. A folder is only ours to continue when everything in it is what
        this request would have written, in the order it writes: the annotations first, the YAML last."""
        if not folder.exists(): return 'new'
        if folder.is_symlink() or not folder.is_dir(): raise ValueError('The lab folder name is taken by something that is not a folder.')
        present = {}
        with os.scandir(folder) as listing: entries = list(listing)
        for entry in entries:
            # Left by this helper: temporaries of an interrupted run, and the recovery copies of a deleted lab.
            if entry.name.startswith('.clab-manager-') and not entry.is_symlink() and entry.stat(follow_symlinks=False).st_uid == os.geteuid() and (entry.is_file(follow_symlinks=False) or entry.name == '.clab-manager-history'): continue
            if entry.name not in wanted: raise ValueError('A lab folder with this name already exists on the VM: ' + str(folder) + '. Choose another lab name.')
            try: present[entry.name] = self.owned_bytes(entry.path)
            except OSError: present[entry.name] = None
            if present[entry.name] != wanted[entry.name]: raise ValueError('A lab folder with this name already exists on the VM: ' + str(folder) + '. Choose another lab name.')
        yaml_name = next(n for n in wanted if not n.endswith(ANNOTATIONS_SUFFIX))
        if yaml_name in present: 
            if len(present) != len(wanted): raise ValueError('A lab folder with this name already exists on the VM: ' + str(folder) + '. Choose another lab name.')
            return 'published'
        return 'resume' if present else 'reuse'  # reuse: only this helper's recovery copies are left in it

    def plan(self, req):
        action = req.get('action')
        if action not in (*LIFECYCLE, *NODE_ACTIONS, 'inspect-all', 'create', 'delete', 'clone', 'publish', 'revise'): raise ValueError('Unsupported lab operation.')
        options = req.get('options') or {}
        # A node action takes its two selector keys and nothing else; no other action accepts a selector. The run
        # options beyond the old union (nodes, max_workers, skip_post_deploy, keep_mgmt_net) are allowed per action
        # by OPTION_ACTIONS; a key outside that is refused before anything runs.
        if action in NODE_ACTIONS: allowed = {'node', 'container'}
        else: allowed = {'cleanup', 'graceful', 'url', 'project', 'text', 'annotations', 'root', 'base'} | {k for k, actions in OPTION_ACTIONS.items() if action in actions}
        if not isinstance(options, dict) or set(options) - allowed:
            raise ValueError('Unsupported operation options.')
        for key in ('cleanup', 'graceful', 'skip_post_deploy', 'keep_mgmt_net'):
            if key in options and type(options[key]) is not bool: raise ValueError('Invalid boolean option.')
        if 'max_workers' in options and (type(options['max_workers']) is not int or not 1 <= options['max_workers'] <= MAX_WORKERS_LIMIT):
            raise ValueError('Max workers must be a whole number from 1 to %d.' % MAX_WORKERS_LIMIT)
        nodes = options.get('nodes')
        if 'nodes' in options and (not isinstance(nodes, list) or not 1 <= len(nodes) <= NODE_FILTER_LIMIT or len(set(map(str, nodes))) != len(nodes)
                                   or not all(isinstance(n, str) and NODE_NAME.fullmatch(n) for n in nodes)):
            raise ValueError('Choose devices by their literal topology node names.')
        name = identity(req.get('name', 'manager'))
        path = None; source_hash = ''; affected = []; argv = []; steps = []; warnings = []; extra = {}
        if action == 'clone':
            if not self.config.get('network'): raise ValueError('Repository downloads are disabled in host operations setup.')
            url = options.get('url', '')
            if not isinstance(url, str) or len(url) > 2000 or any(ord(c) < 33 for c in url): raise ValueError('Invalid repository URL.')
            parsed = urlsplit(url)
            if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
                raise ValueError('Use a plain HTTPS repository URL without embedded credentials.')
            project = identity(options.get('project'))
            path = self.path(str(Path(self.config['projects']) / project), exists=False)
            if path.exists(): raise ValueError('Choose a new project directory; existing projects are never overwritten.')
            argv = [self.config.get('git', '/usr/bin/git'), '-c', 'protocol.file.allow=never', '-c', 'protocol.ext.allow=never',
                    'clone', '--depth', '1', '--', url, str(path)]
            warnings.append('Downloads a repository into the trusted project area. Review its YAML, hooks and mounts before deployment.')
        elif action == 'create':
            path = self.path(req.get('path'), exists=False)
            if path.exists() or path.suffix not in ('.yaml', '.yml'): raise ValueError('Choose a new YAML filename in a trusted project directory.')
            self.path(str(path.parent))
            source_hash = 'new'
        elif action == 'publish':
            # Every path is derived here from the lab name; the request only names a trusted root.
            root = options.get('root')
            if not isinstance(root, str) or Path(root) not in self.roots: raise ValueError('Choose one of the trusted lab folders for the new lab.')
            text, annotations = self.builder_texts(options)
            folder = self.path(str(Path(root) / name), exists=False); self.path(root)
            path = folder / (name + '.clab.yml')
            wanted = {path.name: text.encode()}
            if annotations is not None: wanted[path.name + ANNOTATIONS_SUFFIX] = annotations.encode()
            state = self.publish_state(folder, wanted)
            source_hash = 'new'
            extra = {'folder': str(folder), 'files': sorted(wanted), 'folder_mode': 0o2775 if Path(root).stat().st_mode & stat.S_ISGID else 0o755}
            if state in ('published', 'resume'): warnings.append('This lab is already saved on the VM with the same content; nothing will be written.' if state == 'published' else 'An earlier save of this lab stopped half way; this run completes it.')
        elif action == 'inspect-all':
            argv = [self.clab, 'inspect', '--all', '--format', 'json']
        else:
            path = self.path(req.get('path'))
            if path.suffix.lower() not in ('.yaml', '.yml'): raise ValueError('Select the original lab YAML.')
            source_hash = self.read(str(path))['sha256']
            groups = self.deployed(); rows = groups.get(name, [])
            affected = [{'name': r.get('name'), 'id': r.get('container_id'), 'state': r.get('state')} for r in rows]
            for row in rows:
                original = row.get('absLabPath') or row.get('labPath')
                if original and Path(original).is_absolute() and Path(original) != path:
                    raise ValueError('The deployed lab name belongs to a different topology path.')
            if action in NODE_ACTIONS:
                # Restart, start or stop one device: containerlab's node-scoped command (the operation the
                # VS Code extension runs as `containerlab restart -r docker --node <node> -t <topology>`;
                # start and stop park and restore the node's dataplane interfaces the same way, fact F1).
                # Exactly one node, named literally, bound to the one deployed container it must be (its
                # id and state are in the digest, so a redeploy, a start or a stop between review and run
                # is caught at run time). Stop of a stopped device and start of a running one are refused
                # here: containerlab would exit 0 silently (fact F2) and a no-op must never read as a success.
                command = action[:-5]
                node, container = node_selector(options, name)
                help_text = self.help(command)
                if not help_text: raise ValueError('This Containerlab version does not support ' + command + '.')
                if '--node' not in help_text:
                    raise ValueError('The installed Containerlab cannot ' + command + ' one device: its ' + command + ' command has no --node option. Upgrade containerlab on the VM.')
                targets = [r for r in rows if r.get('name') == container]
                if len(targets) != 1:
                    raise ValueError('Device ' + container + ' is not deployed in lab ' + name + '. Refresh the lab list and review again.')
                target = targets[0]
                affected = [{'name': target.get('name'), 'id': target.get('container_id'), 'state': target.get('state')}]
                state = str(target.get('state') or '')
                if action == 'stop-node' and state != 'running': raise ValueError('Device ' + container + ' is ' + (state or 'not running') + '; there is nothing to stop.')
                if action == 'start-node' and state == 'running': raise ValueError('Device ' + container + ' is already running.')
                argv = [self.clab, command, '-t', str(path)]
                if '--name' in help_text: argv.extend(['--name', name])
                elif req.get('source_name', name) != name: raise ValueError('This version cannot target the overridden lab name.')
                argv.extend(['--node', node])
                if argv.count('--node') != 1 or argv[-1] != node or ',' in node:
                    raise ValueError('The ' + command + ' command must name exactly one device.')
                if action == 'restart-node' and state != 'running':
                    warnings.append('This device is ' + (state or 'not running') + ', so containerlab takes its start/restore path: it starts the container and restores its links instead of stopping it first. '
                                    'Links are restored only if containerlab parked them (a stop from the manager, the VS Code extension or containerlab stop); a device stopped with docker stop has already lost its links, and redeploying the lab is the way to get them back.')
                extra = {'node': node, 'container': container}
            elif action in ('delete',):
                # Found by its topology path too, as revise does: a lab deployed under another name (containerlab
                # --name, or the YAML's name edited and redeployed on the VM) is not listed under this one.
                if rows or [r for g in groups.values() for r in g if (r.get('absLabPath') or r.get('labPath')) == str(path)]:
                    raise ValueError('Destroy the deployment before deleting its source YAML.')
                side = Path(str(path) + ANNOTATIONS_SUFFIX)
                if side.is_file() and not side.is_symlink():
                    extra = {'layout': str(side)}; warnings.append('The map layout file beside it is deleted as well. A recovery copy of both is kept.')
            elif action == 'revise':
                # Saving again is only for a lab that is not running: the running lab was built from the
                # file on disk, and the request must come from exactly the versions it names.
                running = rows or [r for g in groups.values() for r in g if (r.get('absLabPath') or r.get('labPath')) == str(path)]
                if running: raise ValueError('This lab is deployed. Destroy it before saving topology changes.')
                text, annotations = self.builder_texts(options)
                opened = options.get('base') or {}
                if not isinstance(opened, dict) or set(opened) - {'yaml', 'annotations'}: raise ValueError('Invalid saved-version reference.')
                side_name = path.name + ANNOTATIONS_SUFFIX
                current = ''
                folder_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
                try:
                    try:
                        if stat.S_ISLNK(os.stat(side_name, dir_fd=folder_fd, follow_symlinks=False).st_mode):
                            raise ValueError('Symlink paths are not supported.')
                    except FileNotFoundError: pass
                    try: existing = self.owned_bytes_any(folder_fd, side_name)
                    except FileNotFoundError: existing = None
                finally: os.close(folder_fd)
                if existing is not None: current = hashlib.sha256(existing).hexdigest()
                if opened.get('yaml') != source_hash or (annotations is not None and opened.get('annotations', '') != current):
                    raise ValueError('The topology changed on the VM after it was opened. Open it again before saving.')
                extra = {'annotations_hash': current}
            elif action in LIFECYCLE:
                help_text = self.help(action)
                if not help_text and action == 'redeploy':
                    if not self.help('destroy') or not self.help('deploy'): raise ValueError('Deploy and destroy are required for redeploy.')
                    steps = [[self.clab, 'destroy', '-t', str(path)], [self.clab, 'deploy', '-t', str(path)]]
                elif not help_text: raise ValueError('This Containerlab version does not support ' + action + '.')
                else: argv = [self.clab, action, '-t', str(path)]
                for command in steps or [argv]:
                    if '--name' in self.help(command[1]): command.extend(['--name', name])
                    elif req.get('source_name', name) != name: raise ValueError('This version cannot target the overridden lab name.')
                # Chosen devices (`nodes`, section 2.8): on destroy and save every name must be exactly one deployed
                # container of this lab (the rule node_selector applies); on deploy only while nothing is deployed
                # (containerlab would delete the devices left out, fact F9); never with cleanup (it would delete the
                # whole lab folder the kept devices use, fact F10). The review names the devices kept.
                if nodes is not None:
                    if action == 'deploy' and rows:
                        raise ValueError('This lab is already deployed, so a deploy limited to chosen devices is not possible (containerlab would remove the devices left out). Use Apply topology changes to add the missing devices.')
                    if options.get('cleanup'):
                        raise ValueError('Clean up cannot be combined with chosen devices: containerlab would delete the whole lab folder, which the devices left running still use.')
                    if action in ('destroy', 'save'):
                        chosen = []
                        for node in nodes:
                            matched = [r for r in rows if container_matches(str(r.get('name') or ''), name, node)]
                            if len(matched) != 1: raise ValueError('Device ' + node + ' is not deployed in lab ' + name + '. Refresh the lab list and review again.')
                            chosen.append(matched[0])
                        affected = [{'name': r.get('name'), 'id': r.get('container_id'), 'state': r.get('state')} for r in chosen]
                        extra['kept'] = [r.get('name') for r in rows if not any(r is c for c in chosen)]
                    if '--node-filter' not in help_text: raise ValueError('Installed command lacks --node-filter.')
                    argv.extend(['--node-filter', ','.join(nodes)])
                # Flags in one fixed order after the filter: --max-workers N, --skip-post-deploy, --cleanup, --graceful,
                # --keep-mgmt-net; each only when the installed command (or, in the redeploy fallback, the step that
                # takes it) lists it. The review shows the argv verbatim.
                if 'max_workers' in options:
                    for command in steps or [argv]:
                        if '--max-workers' not in self.help(command[1]): raise ValueError('Installed ' + command[1] + ' command lacks this option.' if steps else 'Installed command lacks --max-workers.')
                        command.extend(['--max-workers', str(options['max_workers'])])
                for flag in ('skip_post_deploy', 'cleanup', 'graceful', 'keep_mgmt_net'):
                    if options.get(flag):
                        if flag == 'cleanup' and action not in ('deploy', 'redeploy', 'destroy'): raise ValueError('Cleanup is only available for lifecycle recreation/removal.')
                        dashed = '--' + flag.replace('_', '-')
                        if steps:
                            step = steps[1] if flag == 'skip_post_deploy' else steps[0]
                            if dashed not in self.help(step[1]): raise ValueError('Installed ' + step[1] + ' command lacks this option.')
                            step.append(dashed)
                        else:
                            if dashed not in help_text: raise ValueError('Installed command lacks ' + dashed + '.')
                            argv.append(dashed)
                if action == 'inspect': argv += ['--format', 'json']
                if action == 'apply':
                    # The plan inside the apply review (section 2.6): the dry run reads the live lab, so its result
                    # is part of the digest; a device that stops, a link that disappears or a file edit between the
                    # review and the run changes the plan and the run is refused with the existing sentence.
                    plan, failed, error = self.dry_run(path, name)
                    extra['plan'] = plan; extra['plan_failed'] = failed
                    if failed == 'error': warnings.append('containerlab could not plan this change: ' + error)
                if action in ('redeploy', 'apply'):
                    # The deploy review's own body text now names the same trust plainly (hooks, mounts,
                    # image pulls) as ordinary description text, not a warning box; repeating it here as
                    # a warning would only duplicate that for the one action (deploy) that never reaches
                    # this branch. redeploy/apply act on an already-running lab, so they keep the warning.
                    warnings.append('Runs this trusted topology with host privileges, including its configured hooks, mounts and image pulls.')
                if options.get('cleanup'):
                    directories = sorted({str(r.get('labdir') or (r.get('labels') or {}).get('clab-node-lab-dir') or path.parent / ('clab-' + name)) for r in rows}) or [str(path.parent / ('clab-' + name))]
                    warnings.append('Cleanup removes generated lab artifacts. Expected lab directory: ' + ', '.join(directories) + '. Check any custom lab directory configured on the VM.')
            else: raise ValueError('Unknown lab operation.')
        if action == 'create':
            text = options.get('text')
            if not isinstance(text, str) or len(text.encode()) > LIMIT: raise ValueError('YAML must be smaller than 1 MiB.')
            # A saved map file (from a copied lab, or drawn elsewhere) is optional and travels with the
            # upload; it is written next to the topology under the same name the VS Code extension and
            # the builder use, so the existing importer picks it up without knowing this is a new file.
            # Its state is bound into the digest exactly like revise's opened['annotations']: a change
            # to this file between review and confirm must be caught, not silently overwritten.
            annotations = options.get('annotations')
            if annotations is not None:
                if not isinstance(annotations, str) or len(annotations.encode()) > LIMIT: raise ValueError('The map layout must be text smaller than 1 MiB.')
                try:
                    if not isinstance(json.loads(annotations), dict): raise ValueError()
                except (ValueError, TypeError, RecursionError): raise ValueError('The map layout is not valid JSON.')
                side_name = path.name + ANNOTATIONS_SUFFIX
                current = ''
                folder_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
                try:
                    try:
                        if stat.S_ISLNK(os.stat(side_name, dir_fd=folder_fd, follow_symlinks=False).st_mode):
                            raise ValueError('Symlink paths are not supported.')
                    except FileNotFoundError: existing = None
                    else:
                        try: existing = self.owned_bytes_any(folder_fd, side_name)
                        except FileNotFoundError: existing = None
                        except (OSError, ValueError):
                            # The recovery-copy promise holds only for a plain, bounded file; anything
                            # else (a directory, a device file, something oversized) is refused here,
                            # before the topology itself is written, so a retry never lands on a
                            # half-finished create.
                            raise ValueError('The existing ' + side_name + ' next to this topology is not a plain file within 1 MiB and cannot be replaced safely; move or remove it on the VM first.') from None
                finally: os.close(folder_fd)
                if existing is not None:
                    current = hashlib.sha256(existing).hexdigest()
                    warnings.append('Replaces the existing map file next to this topology; a recovery copy of it is kept.')
                extra['annotations_hash'] = current
        base = {'action': action, 'name': name, 'source_name': req.get('source_name', name), 'path': str(path) if path else '', 'options': options,
                'source_hash': source_hash, 'affected': affected, 'argv': argv, 'steps': steps, **extra}
        return {**base, 'digest': digest(base), 'warnings': warnings}

    def place(self, folder_fd, name, data, mode, replace=False):
        """Write one file inside an open folder: private temporary, flushed to disk, then published
        under its name. A new file is linked (fails if the name exists); a revision replaces."""
        temp = '.clab-manager-' + uuid.uuid4().hex
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=folder_fd)
        try:
            with os.fdopen(fd, 'wb') as handle:
                handle.write(data); handle.flush(); os.fsync(handle.fileno()); os.fchmod(handle.fileno(), mode)
                inode = os.fstat(handle.fileno()).st_ino
            if replace: os.replace(temp, name, src_dir_fd=folder_fd, dst_dir_fd=folder_fd); temp = None
            else:
                try: os.link(temp, name, src_dir_fd=folder_fd, dst_dir_fd=folder_fd)
                except FileExistsError: raise ValueError('The lab file now exists on the VM. Nothing was overwritten; review the save again.') from None
            os.fsync(folder_fd)
            return inode
        finally:
            if temp:
                try: os.unlink(temp, dir_fd=folder_fd)
                except FileNotFoundError: pass

    def publish(self, plan, emit):
        """Create the lab folder with its map layout first and its topology last, so the lab only
        becomes visible to the file browser (which lists *.clab.yml) once it is complete."""
        folder = Path(plan['folder']); text, annotations = self.builder_texts(plan['options'])
        wanted = {n: (text if not n.endswith(ANNOTATIONS_SUFFIX) else annotations).encode() for n in plan['files']}
        state = self.publish_state(folder, wanted)
        if state == 'published':
            emit({'output': 'This lab is already saved on the VM. Nothing was written.\n'}); return {'already_published': True}
        made_folder = False; placed = {}
        mode = 0o664 if plan['folder_mode'] & stat.S_ISGID else 0o644
        try:
            if state == 'new':
                os.mkdir(folder, 0o700); made_folder = True
            folder_fd = os.open(folder, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                if made_folder:
                    os.fchmod(folder_fd, plan['folder_mode'])
                    root_fd = os.open(folder.parent, os.O_RDONLY | os.O_DIRECTORY)
                    try: os.fsync(root_fd)
                    finally: os.close(root_fd)
                existing = set(os.listdir(folder))
                for name in [n for n in existing if n.startswith('.clab-manager-') and n != '.clab-manager-history']:  # temporaries of an interrupted run
                    os.unlink(name, dir_fd=folder_fd)
                for name in sorted(wanted, key=lambda n: not n.endswith(ANNOTATIONS_SUFFIX)):
                    if name in existing: continue
                    placed[name] = self.place(folder_fd, name, wanted[name], mode)
            except BaseException:
                # Take back only what this run published, and only while it is still that file.
                for name, inode in placed.items():
                    try:
                        if os.stat(name, dir_fd=folder_fd, follow_symlinks=False).st_ino == inode: os.unlink(name, dir_fd=folder_fd)
                    except OSError: pass
                raise
            finally: os.close(folder_fd)
        except BaseException:
            if made_folder:
                try: os.rmdir(folder)
                except OSError: pass
            raise
        emit({'output': 'Lab folder saved on the VM: ' + str(folder) + '\n'})
        return {'published_path': plan['path'], 'resumed': state == 'resume'}

    def revise(self, plan, emit):
        path = Path(plan['path']); text, annotations = self.builder_texts(plan['options'])
        side = path.name + ANNOTATIONS_SUFFIX
        folder_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            recovery = {}; contents = {}
            for name in (path.name, side) if annotations is not None else (path.name,):
                try: previous = self.owned_bytes_any(folder_fd, name)
                except FileNotFoundError: continue
                contents[name] = previous
                recovery[name] = self.history_backup(folder_fd, path.parent, name, previous)
            # The bytes just backed up, not a second by-path read: one fewer place a race could slip in.
            if hashlib.sha256(contents.get(path.name, b'')).hexdigest() != plan['source_hash']: raise ValueError('The topology changed on the VM. Review the save again.')
            keep = stat.S_IMODE(os.stat(path.name, dir_fd=folder_fd, follow_symlinks=False).st_mode)
            if annotations is not None: self.place(folder_fd, side, annotations.encode(), keep, replace=True)
            self.place(folder_fd, path.name, text.encode(), keep, replace=True)
        finally: os.close(folder_fd)
        emit({'output': 'Topology saved on the VM. The previous version was kept.\n'})
        return {'published_path': str(path), 'recovery_path': recovery.get(path.name, ''), 'recovery_paths': recovery}

    def owned_bytes_any(self, folder_fd, name):
        # O_NONBLOCK: a FIFO planted at this name must never make the helper hang waiting for a
        # writer; fstat below then refuses it (not a regular file) exactly like any other special file.
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=folder_fd)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_size > LIMIT: raise ValueError('The saved lab files cannot be replaced safely.')
            return os.read(fd, LIMIT + 1)
        finally: os.close(fd)

    def history_backup(self, folder_fd, parent, name, data):
        """Write one recovery copy of `data` under an unpredictable name, private (0600), through an
        open '.clab-manager-history' directory beside the file it protects -- never opened, chmoded
        or read by a bare path. Created if absent; refused (never used) if it is a symlink or is not
        owned by this process, so a directory an attacker pre-planted in a shared folder is never
        written into."""
        history_name = '.clab-manager-history'
        try: os.mkdir(history_name, 0o700, dir_fd=folder_fd)
        except FileExistsError: pass
        history_fd = os.open(history_name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=folder_fd)
        try:
            if os.fstat(history_fd).st_uid != os.geteuid():
                raise ValueError('The recovery folder next to this file is not safe to use.')
            backup_name = name + '.' + uuid.uuid4().hex
            fd = os.open(backup_name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=history_fd)
            try:
                with os.fdopen(fd, 'wb') as handle:
                    handle.write(data); handle.flush(); os.fsync(handle.fileno())
            except BaseException:
                try: os.unlink(backup_name, dir_fd=history_fd)
                except OSError: pass
                raise
            os.fsync(history_fd)
            return str(parent / history_name / backup_name)
        finally: os.close(history_fd)

    def execute(self, req, emit):
        plan = self.plan(req)
        if req.get('digest') != plan['digest']: raise ValueError('The topology or deployment changed. Preview the operation again.')
        action = plan['action']; path = Path(plan['path']) if plan['path'] else None
        result = {}; code = 0
        if action == 'publish': result = self.publish(plan, emit)
        elif action == 'revise': result = self.revise(plan, emit)
        elif action in ('create', 'delete'):
            # Every write below goes through this one open directory descriptor (O_NOFOLLOW), the same
            # shape place()/owned_bytes_any()/history_backup() give publish() and revise(): a mode is
            # set with os.fchmod on the still-open file, before it gets its name, so nothing that later
            # appears at that name (an attacker's symlink, in a group-writable engineer folder) is ever
            # chmod-by-path, and the final folder mode itself comes from this fd, not a fresh path stat.
            # A symlink at the topology path itself was already refused when plan() resolved it with
            # self.path().
            folder_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                mode = 0o664 if os.fstat(folder_fd).st_mode & stat.S_ISGID else 0o644
                if action != 'create':
                    content = self.owned_bytes_any(folder_fd, path.name)
                    result['recovery_path'] = self.history_backup(folder_fd, path.parent, path.name, content)
                if action == 'delete' and plan.get('layout'):
                    side_name = Path(plan['layout']).name
                    try: side_content = self.owned_bytes_any(folder_fd, side_name)
                    except FileNotFoundError: side_content = None
                    if side_content is not None:
                        result['layout_recovery_path'] = self.history_backup(folder_fd, path.parent, side_name, side_content)
                        os.unlink(side_name, dir_fd=folder_fd)
                if action == 'delete':
                    os.unlink(path.name, dir_fd=folder_fd)
                else:
                    annotations = plan['options'].get('annotations')
                    side = path.name + ANNOTATIONS_SUFFIX
                    if annotations is not None:
                        # Re-read the map file exactly as reviewed: a symlink now at its name is refused
                        # by owned_bytes_any's O_NOFOLLOW open, never followed; any other change (edited,
                        # replaced, removed) fails the hash bound into the digest above. Checked before
                        # the topology itself is written, so a rejected save leaves nothing behind.
                        try: previous = self.owned_bytes_any(folder_fd, side)
                        except FileNotFoundError: previous = None
                        current = hashlib.sha256(previous).hexdigest() if previous is not None else ''
                        if current != plan.get('annotations_hash', ''):
                            raise ValueError('The map file next to this topology changed after the review; review again.')
                    # Atomically publish only if the destination is still absent. Editors outside our
                    # flock may create it after plan(); place() never overwrites in that case.
                    self.place(folder_fd, path.name, plan['options']['text'].encode(), mode)
                    if annotations is not None:
                        if previous is not None:
                            result['layout_recovery_path'] = self.history_backup(folder_fd, path.parent, side, previous)
                        self.place(folder_fd, side, annotations.encode(), mode, replace=True)
            finally:
                os.close(folder_fd)
            emit({'output': 'VM source ' + ('removed' if action == 'delete' else 'saved') + '.\n'})
        else:
            cwd = str(path.parent) if path else '/'
            for argv in plan['steps'] or [plan['argv']]:
                code = stream(argv, cwd, emit)
                if code: break
            if action == 'clone' and code == 0: result['project_path'] = str(path)
        return {'exit_code': code, **result}


def main():
    def interrupted(signum, frame): raise KeyboardInterrupt()
    for name in ('SIGTERM', 'SIGINT', 'SIGHUP'):
        if hasattr(signal, name): signal.signal(getattr(signal, name), interrupted)
    def emit(value):
        print(json.dumps(value, separators=(',', ':')), flush=True)
    def locked(work):
        """The one host lock, non-blocking: held by another process answers LOCK_SENTENCE and nothing runs."""
        import fcntl
        with open(LOCK_PATH, 'a') as lock:
            try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError: raise ValueError('Another host lab operation is running.') from None   # == LOCK_SENTENCE (the C02 test pins the literal)
            return work()
    try:
        config = json.loads(Path('/etc/clab-manager/operations.json').read_text())
        raw = sys.stdin.buffer.readline(2 * LIMIT + 1)
        if len(raw) > 2 * LIMIT: raise ValueError('Request is too large.')
        req = json.loads(raw)
        if not isinstance(req, dict): raise ValueError('Invalid operation request.')
        host = HostOperations(config)
        mode = req.get('mode')
        if mode == 'capabilities': result = host.capabilities()
        elif mode == 'read': result = host.read(req.get('path'))
        elif mode == 'browse': result = host.browse(req.get('path', ''), req.get('options') or {})
        elif mode == 'popular': result = host.popular()
        elif mode == 'images': result = host.images()
        elif mode == 'image-check': result = host.image_check(req.get('options') or {})
        elif mode == 'logs': result = host.logs(req.get('name'), req.get('options') or {})
        elif mode == 'interfaces': result = host.interfaces(req.get('name'), req.get('options') or {})
        elif mode == 'netem-show': result = host.netem_show(req.get('name'), req.get('options') or {})
        elif mode == 'netem-show-all': result = host.netem_show_all(req.get('name'), req.get('options') or {})
        elif mode == 'apply-plan': result = host.pending_plan(req.get('name'), req.get('path'))
        elif mode == 'netem-set': result = locked(lambda: host.netem_set(req))
        elif mode == 'netem-reset': result = locked(lambda: host.netem_reset(req))
        elif mode == 'preview': result = locked(lambda: host.plan(req)); result.pop('options', None)
        elif mode == 'run': result = locked(lambda: host.execute(req, emit))
        else: raise ValueError('Unknown request mode.')
        emit({'result': result}); return 0
    except (BrokenPipeError, KeyboardInterrupt): return 1
    except Exception as exc:
        message = str(exc) if type(exc) is ValueError and not isinstance(exc, json.JSONDecodeError) else 'Host operation failed. Check setup, paths and installed tools.'
        emit({'error': message}); return 1


if __name__ == '__main__': raise SystemExit(main())
