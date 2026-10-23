"""Node connection checks and bounded interactive SSH, separate from backups."""
import asyncio
import copy
import io
import json
import re
import secrets
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Literal
from urllib.parse import urlsplit

import paramiko
from fastapi import HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from .runner import CLI_ERROR, effective_credentials, now
from .discovery import discovery_fresh, expected_container, node_available
from .inventory import console_port
from .lab_operations import restarting_nodes
from .node_console import TelnetCodec, container_age, health_part, telnet_escape

BULK_CHECK_WORKERS = 4     # ssh-check-all never opens more SSH sessions than this at once
CHECKING_MESSAGE = 'Testing the SSH login…'
REACHABLE_MESSAGE = 'SSH login accepted and the CLI answered'
# The login was accepted but the CLI gave no real answer yet (a NOS accepts SSH while its CLI still starts).
# Never ready. In a lab linked to a VM deployment the readiness monitor asks again by itself and replaces this
# result with a real one; a lab with no deployment_name (an inventory import) is not scanned, so nothing
# re-checks and its words promise nothing but a manual Test login.
BOOTING_MESSAGE = 'SSH login accepted, but the CLI has not answered yet. The device is still starting; the manager keeps checking.'
BOOTING_UNMONITORED_MESSAGE = 'SSH login accepted, but the CLI has not answered yet. The device is still starting; Test login again in a moment.'
FAILED_MESSAGE = 'SSH login failed. Check credentials, address, port, and NOS readiness.'
CLI_COMMAND = 'show version'
# A node with no NOS platform (a plain Linux image, generic SSH profile or the
# image-based defaults in inventory.py) has no NOS CLI to answer `show version`;
# a real, harmless shell command still proves the SSH login answers a real command,
# without faking readiness for a host that was never a NOS in the first place.
GENERIC_CLI_COMMAND = 'echo readiness-check'
CLI_TIMEOUT = 25      # seconds for the whole CLI check: the exec request, the command and all of its output
# The replies that mean "the CLI is still starting": the not-ready answers of runner.CLI_ERROR and cEOS's early-boot
# agent error. For a node without a NOS platform only these (or no answer) keep it booting; a CLI that rejects the
# generic command ("% Invalid input", "error: unknown command") is a CLI that answered.
CLI_NOT_READY = re.compile(r'(?im)System is not yet ready|Waiting for editing of configuration|could not connect to agent')


def cli_answers(client, command=CLI_COMMAND, timeout=None, refused=CLI_ERROR):
    """True when the CLI returns a real answer to `command` over an exec channel before one deadline.

    SSH can accept a login while the CLI is still starting (cEOS agents, Junos
    daemons); an empty reply, or one that matches `refused` (by default any CLI error
    or not-ready reply: show version must really succeed), keeps the node in booting.
    The deadline (CLI_TIMEOUT unless given) bounds the whole check: paramiko waits for
    the exec request's reply with no timeout of its own and keeps reading while output
    trickles in, so a timer closes the transport when it passes (which ends either
    wait), and an answer that was not complete by then is no answer.
    """
    timeout = CLI_TIMEOUT if timeout is None else timeout
    expired = threading.Event()
    def expire(transport):
        expired.set()
        if transport is not None: transport.close()
    timer = None
    try:
        timer = threading.Timer(timeout, expire, (client.get_transport(),)); timer.daemon = True; timer.start()
        stdin, stdout, _ = client.exec_command(command, timeout=timeout)
        stdin.close()
        output = stdout.read(65536).decode('utf-8', 'replace')
    except Exception:
        return False
    finally:
        if timer is not None: timer.cancel()
    if expired.is_set(): return False
    return bool(output.strip()) and not refused.search(output)


def node_cli_command(node):
    return CLI_COMMAND if node.get('platform') else GENERIC_CLI_COMMAND


def node_cli_answers(client, node):
    """The one CLI check of Test login, Test logins and the readiness monitor's probe.

    A node with a NOS platform must really answer show version. A node without one is
    asked the generic shell command: a Linux shell runs it, and a NOS kind outside the
    supported ones (stored with platform '', for example cisco_iol from discovery) rejects
    it, which still proves an answering CLI; for it only no answer, the deadline or a
    not-ready reply (CLI_NOT_READY) keeps the node booting.
    """
    return cli_answers(client, node_cli_command(node), refused=CLI_ERROR if node.get('platform') else CLI_NOT_READY)


class NodeRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class TicketRequest(NodeRequest):
    """A terminal ticket: SSH unless the page asks for the serial console (the body `{name}` stays SSH)."""
    protocol: Literal['ssh', 'console'] = 'ssh'


# The serial console of the vrnetlab kinds (docs/parity-campaign/C04-DESIGN.md §1.5–1.8, §2.2–2.3): direct node access
# like SSH, no helper. The manager picks the address (discovered_address) and the kind's port; nothing of the request
# reaches the connect call. The console's cap is its own: it is not a Paramiko client and never eats the SSH limit.
CONSOLE_LIMIT = 8
CONSOLE_SETTLE = 120            # seconds a container must have run before its console is offered (the launcher takes it first)
CONSOLE_CONNECT_TIMEOUT = 5
CONSOLE_PROBE_TIMEOUT = 3       # qemu's negotiation arrives at once on a free console (verified live); silence means it is held
CONSOLE_IDLE = 900              # the SSH limits exactly: 15 minutes without browser input, 4 hours in all
CONSOLE_TOTAL = 14400
CONSOLE_CLOSED_BY_DEVICE = 'The console closed: the device stopped or restarted.'
# The gate's sentences (§2.2), one per cause, formatted with the device's short name (and the kind or port where named).
CONSOLE_KIND_UNKNOWN = ('The manager has no topology kind for {device} (it came from an inventory file), so it cannot tell whether it '
                        'has a serial console. Link the lab and use Lab actions ▾ › Sync topology from VM.')
CONSOLE_NONE = '{device} has no serial console: its kind ({kind}) does not expose one. Open CLI is the way in.'
CONSOLE_UNLINKED = ('The console needs a lab linked to the VM with this device in its topology. Link it under Advanced › Link to a '
                    'running lab…, or sync the topology from the VM.')
CONSOLE_NOT_RUNNING = '{device} is not running on the VM (or the lab status is out of date), so its console is closed. Start the lab, then try again.'
CONSOLE_NO_ADDRESS = 'The VM has not reported a management address for {device}. Refresh the lab list and try again.'
CONSOLE_RESTARTING = '{device} is restarting on the VM. Its launcher takes the console first; the console opens once the device reports healthy.'
CONSOLE_JOB_SENTENCES = {
    'start-node': '{device} has a Start device job running on the VM. Its launcher takes the console first; the console opens once the device reports healthy.',
    'stop-node': '{device} has a Stop device job running on the VM, so its console is closed. Start device brings it back; the console opens once it reports healthy.',
}
CONSOLE_STARTING = ('{device} is still starting: its launcher uses the console until the device reports healthy. Try again once it is '
                    'healthy; if the device panel has a Logs section, it shows the boot.')
CONSOLE_UNHEALTHY = ('{device} has not finished booting (its health check fails), so its launcher keeps the console. If the device panel '
                     'has a Logs section, it shows why.')
CONSOLE_YOUNG = '{device} started less than two minutes ago; its launcher takes the console first. Try again in a moment.'
# The socket's sentences (§2.3).
CONSOLE_LIMIT_SENTENCE = f'Too many consoles are open (limit {CONSOLE_LIMIT}). Close one and try again.'
CONSOLE_OPEN_HERE = ('The console of {device} is already open from this manager (since {time} UTC), in another tab or browser. Close that '
                     'tab, or wait: it closes after 15 minutes without typing.')
CONSOLE_UNREACHABLE = ('Could not reach the console of {device} (port {port} on its management address). The device may be stopping or '
                       'restarting, or its console is in use by another client; if the device panel has a Logs section, it shows what '
                       'the device prints.')
CONSOLE_HELD = ('The console of {device} is in use by its launcher (while the device boots or its boot fails) or by a client outside this '
                'manager. If the device panel has a Logs section, it shows the boot; try again once the device reports healthy.')


class ConsoleBusy(Exception):
    """A console refusal decided at socket time; its text is what the student reads."""


def device_label(node):
    return node.get('short_name') or node.get('name') or ''


def console_gate(state, lab, node):
    """The one decider of whether a device's serial console may open now: the ticket route, the socket and the public
    row (`console_hold`) all call it under the store lock, so the page and the server never disagree. None when the
    console may open; else `(status, key, sentence)` for the first cause that holds, in this order: no topology kind,
    a kind without a console, an unlinked lab or no topology node, not running (or stale discovery), no discovered
    address, a Restart device job, health starting, unhealthy, a container younger than CONSOLE_SETTLE as of now
    (its uptime plus the time since the inspection). On the three kinds the health file is written when the
    launcher's bootstrap ends, so healthy means the console is released; the young floor covers a status without a
    health part. Reads discovery's view only; never connects."""
    device = device_label(node)
    kind = node.get('kind') or ''
    if not kind: return 409, 'kind_unknown', CONSOLE_KIND_UNKNOWN.format(device=device)
    if console_port(kind) is None: return 400, 'none', CONSOLE_NONE.format(device=device, kind=kind)
    if not lab.get('deployment_name') or not expected_container(lab, node): return 409, 'unlinked', CONSOLE_UNLINKED.format(device=device)
    if not discovery_fresh(state) or not node.get('discovered') or node.get('runtime_state') != 'running':
        return 409, 'not_running', CONSOLE_NOT_RUNNING.format(device=device)
    if not node.get('discovered_address'): return 409, 'no_address', CONSOLE_NO_ADDRESS.format(device=device)
    job_action = restarting_nodes(state, lab.get('id')).get(node.get('name'))
    # One key for the page; the sentence names the job that holds the device (a restart, a start or a stop).
    if job_action: return 409, 'restarting', CONSOLE_JOB_SENTENCES.get(job_action, CONSOLE_RESTARTING).format(device=device)
    health = health_part(node.get('runtime_status'))
    if health == 'starting': return 409, 'starting', CONSOLE_STARTING.format(device=device)
    if health == 'unhealthy': return 409, 'unhealthy', CONSOLE_UNHEALTHY.format(device=device)
    age = container_age(node.get('runtime_status'), state.get('discovery', {}).get('inspected_epoch', 0), time.time())
    if age is not None and age < CONSOLE_SETTLE: return 409, 'young', CONSOLE_YOUNG.format(device=device)
    return None


def connect(client, node, creds):
    # Preserve the application's existing isolated-lab host-key policy.
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    options = dict(hostname=node['address'], port=node['port'], username=creds['username'],
                   timeout=10, auth_timeout=10, banner_timeout=10,
                   allow_agent=False, look_for_keys=False)
    if creds.get('auth') == 'key':
        for kind in (paramiko.RSAKey, paramiko.ECDSAKey, paramiko.Ed25519Key):
            try:
                options['pkey'] = kind.from_private_key(io.StringIO(creds['private_key']),
                                                       password=creds.get('passphrase') or None)
                break
            except (paramiko.SSHException, ValueError):
                continue
        if 'pkey' not in options:
            raise ValueError('Invalid SSH key')
    else:
        options['password'] = creds.get('password', '')
    client.connect(**options)
    transport = client.get_transport()
    if transport:
        transport.set_keepalive(30)


class NodeServices:
    def __init__(self, store):
        self.store = store
        self.lock = threading.RLock()
        self.checks = {}
        self.tickets = {}
        self.clients = set()
        self.checking = set()
        self.checking_all = set()      # lab ids with a lab-wide ssh-check-all in flight
        # Open serial consoles keyed by (lab_id, node name): {'opened': epoch, 'writer': StreamWriter | None, 'loop': ...}.
        # The record is inserted in the locked block that checks the cap and the key; only its own session pops it.
        self.consoles = {}
        self.bulk_pool = ThreadPoolExecutor(max_workers=BULK_CHECK_WORKERS)
        self.closed = False

    def close(self):
        with self.lock:
            self.closed = True
            self.tickets.clear()
            for client in list(self.clients):
                client.close()
            for record in list(self.consoles.values()):
                writer, loop = record.get('writer'), record.get('loop')
                if writer is None or loop is None: continue
                try: loop.call_soon_threadsafe(writer.close)
                except RuntimeError: pass    # the loop is already closed; the transport went with it
        self.bulk_pool.shutdown(wait=False, cancel_futures=True)

    def node(self, lab_id, name):
        with self.store.lock:
            lab = self.store.lab(lab_id)
            if not lab:
                raise HTTPException(404, 'Lab not found')
            node = next((n for n in lab['nodes'] if n['name'] == name), None)
            if not node:
                raise HTTPException(404, 'Node not found')
            if not node_available(self.store.state,lab,node):
                raise HTTPException(409,'Node is unavailable; refresh VM discovery before connecting.')
            return copy.deepcopy(node), copy.deepcopy(effective_credentials(lab, node))

    def reserve(self):
        with self.lock:
            if self.closed or len(self.clients) >= 32:
                raise HTTPException(429, 'SSH session limit reached; close a session and retry.')
            client = paramiko.SSHClient()
            self.clients.add(client)
            return client

    def release(self, client):
        client.close()
        with self.lock:
            self.clients.discard(client)

    def console_node(self, lab_id, name):
        """(lab, node) copies of a lab's node for the console, or 404."""
        with self.store.lock:
            lab = self.store.lab(lab_id)
            if not lab:
                raise HTTPException(404, 'Lab not found')
            node = next((n for n in lab['nodes'] if n['name'] == name), None)
            if not node:
                raise HTTPException(404, 'Node not found')
            return copy.deepcopy(lab), copy.deepcopy(node)

    def console_target(self, lab_id, name):
        """(address, port) the console of this node connects to, decided by the manager alone: the discovered address
        (what the VM's inspect reported, parsed by `ipaddress`) and the kind's constant port. Raises the gate's
        HTTPException (status, sentence) when the console may not open now; the ticket and the socket both ask."""
        with self.store.lock:
            lab, node = self.console_node(lab_id, name)
            held = console_gate(self.store.state, lab, node)
            if held:
                raise HTTPException(held[0], held[2])
            return node['discovered_address'], console_port(node.get('kind'))

    async def console_session(self, ws, lab_id, name):
        """The console branch of /api/terminal after the ticket was popped (docs/parity-campaign/C04-DESIGN.md §2.3).

        asyncio streams, no executor thread: a console is a plain TCP socket. The slot is reserved in one locked block
        (the cap and the per-device key together, no TCP connect for a refusal), the connect takes console_target's
        values only, nothing is written before the device's first byte (a silent console is held by the launcher or
        an outside client and is left within the probe timeout), the idle clock counts browser input only, and the
        events carry the lab id and the node only. Console bytes are never stored, logged or put in an event."""
        key = (lab_id, name)
        record = {'opened': time.time(), 'writer': None, 'loop': asyncio.get_running_loop()}
        reserved = opened = False
        writer = None
        device_task = browser_task = None
        try:
            address, port = self.console_target(lab_id, name)   # the device may have stopped, or started restarting, since the ticket
            device = device_label(self.console_node(lab_id, name)[1])
            with self.lock:
                if self.closed or len(self.consoles) >= CONSOLE_LIMIT:
                    raise ConsoleBusy(CONSOLE_LIMIT_SENTENCE)
                held = self.consoles.get(key)
                if held is not None:
                    raise ConsoleBusy(CONSOLE_OPEN_HERE.format(device=device, time=time.strftime('%H:%M', time.gmtime(held['opened']))))
                self.consoles[key] = record
                reserved = True
            try:
                reader, writer = await asyncio.wait_for(asyncio.open_connection(address, port), CONSOLE_CONNECT_TIMEOUT)
            except (OSError, asyncio.TimeoutError):
                raise ConsoleBusy(CONSOLE_UNREACHABLE.format(device=device, port=port))
            record['writer'] = writer
            try:
                first = await asyncio.wait_for(reader.read(16384), CONSOLE_PROBE_TIMEOUT)
            except asyncio.TimeoutError:
                first = b''
            if not first:
                raise ConsoleBusy(CONSOLE_HELD.format(device=device))
            self.store.event('console.open', 'Serial console opened', lab_id=lab_id, node=name)
            opened = True
            await ws.send_json({'type': 'status', 'message': 'Connected'})
            codec = TelnetCodec()

            async def deliver(chunk):
                output, replies = codec.feed(chunk)
                if replies:
                    writer.write(replies)
                    await writer.drain()
                if output:
                    await ws.send_bytes(output)      # awaited: socket backpressure as in the SSH loop

            await deliver(first)
            started = last_input = time.monotonic()
            device_task = asyncio.ensure_future(reader.read(16384))
            browser_task = asyncio.ensure_future(ws.receive_text())
            while True:
                current = time.monotonic()
                if current - last_input > CONSOLE_IDLE or current - started > CONSOLE_TOTAL:
                    await ws.send_json({'type': 'status', 'message': 'Session timeout. Reconnect to continue.'})
                    break
                done, _ = await asyncio.wait({device_task, browser_task}, timeout=1, return_when=asyncio.FIRST_COMPLETED)
                if device_task in done:
                    chunk = device_task.result()
                    if not chunk:
                        await ws.send_json({'type': 'status', 'message': CONSOLE_CLOSED_BY_DEVICE})
                        break
                    await deliver(chunk)
                    device_task = asyncio.ensure_future(reader.read(16384))
                if browser_task in done:
                    raw = browser_task.result()
                    browser_task = asyncio.ensure_future(ws.receive_text())
                    if len(raw) > 20000:
                        raise ValueError('Input too large')
                    event = json.loads(raw)
                    if event.get('type') == 'input':
                        value = event.get('data', '')
                        if not isinstance(value, str) or len(value.encode()) > 16384:
                            raise ValueError('Invalid input')
                        if value:
                            last_input = time.monotonic()
                            writer.write(telnet_escape(value.encode()))
                            await writer.drain()
                    elif event.get('type') == 'resize':
                        cols, rows = int(event['cols']), int(event['rows'])
                        if not (20 <= cols <= 400 and 5 <= rows <= 150):
                            raise ValueError('Invalid terminal dimensions')
                        # No NAWS: a serial console has no window size. Validated and ignored.
                    else:
                        raise ValueError('Invalid terminal message')
        except WebSocketDisconnect:
            pass
        except HTTPException as exc:
            try:
                await ws.send_json({'type': 'error', 'message': exc.detail})   # the gate's own sentence at socket time
            except Exception:
                pass
        except ConsoleBusy as exc:
            try:
                await ws.send_json({'type': 'error', 'message': str(exc)})
            except Exception:
                pass
        except Exception:
            try:
                await ws.send_json({'type': 'error', 'message': 'Session ended.'})
            except Exception:
                pass
        finally:
            # Bookkeeping first and without an await: a session cancelled from outside (the server shutting down)
            # must still free its slot and record its close before anything that could raise CancelledError.
            for task in (device_task, browser_task):
                if task is not None and not task.done():
                    task.cancel()
            if writer is not None:
                writer.close()
            with self.lock:
                if reserved and self.consoles.get(key) is record:
                    self.consoles.pop(key)
            if opened:
                self.store.event('console.close', 'Serial console closed', lab_id=lab_id, node=name)
            if writer is not None:
                try:
                    await asyncio.wait_for(writer.wait_closed(), 2)
                except Exception:
                    pass    # a half-open peer cannot pin the session
            try:
                await ws.close()
            except Exception:
                pass

    def bulk_check_targets(self, lab):
        """Split a lab's nodes into (targets, skipped) for ssh-check-all.

        Eligible: an address and effective credentials — exactly what the per-node
        ssh-check needs to attempt a login. `enabled` is the backup flag (a Linux host
        such as the multitool has no NOS platform and is never backed up) and does not
        decide whether its login can be tested. Everything else is skipped with the
        reason a student would find under Devices, not attempted.
        """
        targets, skipped = [], []
        for node in lab['nodes']:
            if not node.get('address'):
                skipped.append({'name': node['name'], 'reason': 'no address'})
                continue
            creds = effective_credentials(lab, node)
            if not creds.get('username'):
                skipped.append({'name': node['name'], 'reason': 'needs credentials'})
                continue
            targets.append((node['name'], copy.deepcopy(node), copy.deepcopy(creds)))
        return targets, skipped

    def monitored(self, lab_id):
        """True when the lab is linked to a VM deployment, the only labs ReadinessMonitor.scan() re-checks."""
        with self.store.lock:
            lab = self.store.lab(lab_id)
            return bool(lab and lab.get('deployment_name'))

    def login_result(self, client, node, creds, monitored=False):
        """The stored outcome of one Test login, shared by the per-node route and Test logins so the two
        always agree: 'reachable' only when the CLI answered a real command after the login (node_cli_answers,
        the check the readiness monitor's probe makes), 'booting' when the login was accepted but the CLI is
        silent, still starting or past CLI_TIMEOUT, 'failed' when the login itself did not work. A booting
        result promises a re-check only when `monitored` (the lab is linked to a VM deployment). Never raises."""
        try:
            connect(client, node, creds)
            answered = node_cli_answers(client, node)
        except Exception:
            return {'status': 'failed', 'at': now(), 'message': FAILED_MESSAGE}
        if answered:
            return {'status': 'reachable', 'at': now(), 'message': REACHABLE_MESSAGE}
        return {'status': 'booting', 'at': now(), 'message': BOOTING_MESSAGE if monitored else BOOTING_UNMONITORED_MESSAGE}

    def run_bulk_check(self, lab_id, name, node, creds, monitored=False):
        """One node's login test from ssh-check-all's bounded pool; stores exactly what
        the per-node route stores, and never raises (one node's failure never stops the rest)."""
        key = (lab_id, name)
        with self.lock:
            if key in self.checking:
                return      # a manual Test login is already running for this node
            self.checking.add(key)
            self.checks[key] = {'status': 'checking', 'at': now(), 'message': CHECKING_MESSAGE}
        try:
            try:
                client = self.reserve()
            except HTTPException:
                result = {'status': 'failed', 'at': now(), 'message': FAILED_MESSAGE}
            else:
                try:
                    result = self.login_result(client, node, creds, monitored)
                finally:
                    self.release(client)
        finally:
            with self.lock:
                self.checking.discard(key)
        with self.lock:
            self.checks[key] = result
        self.store.event('ssh.check', result['message'], lab_id=lab_id, node=name)

    def run_bulk_checks(self, lab_id, targets, monitored=False):
        """Run every target through the bounded pool (never more than BULK_CHECK_WORKERS
        SSH sessions from this call at once), then clear the lab-wide debounce flag."""
        futures = []
        try:
            for name, node, creds in targets:
                try:
                    futures.append(self.bulk_pool.submit(self.run_bulk_check, lab_id, name, node, creds, monitored))
                except RuntimeError:
                    break   # the pool is closing; the remaining nodes are simply not probed
            for future in futures:
                try:
                    future.result()
                except Exception:
                    pass    # one node's probe failing never stops the others
        finally:
            with self.lock:
                self.checking_all.discard(lab_id)

    def install(self, app):
        @app.get('/api/labs/{lab_id}/health')
        def health(lab_id: str):
            with self.store.lock:
                lab = copy.deepcopy(self.store.lab(lab_id))
                if not lab:
                    raise HTTPException(404, 'Lab not found')
                jobs = copy.deepcopy([j for j in self.store.state['jobs'] if j['lab_id'] == lab_id])
            with self.lock:
                rows = []
                for node in lab['nodes']:
                    backup = next(({'job_id': j['id'], 'status': n['status'],
                                    'at': n.get('captured_at') or j.get('finished') or j.get('created')}
                                   for j in jobs if j['operation'] == 'backup'
                                   for n in j['nodes'] if n['name'] == node['name']), None)
                    rows.append({'name': node['name'],
                                 'ssh': copy.deepcopy(self.checks.get((lab_id, node['name']))), 'backup': backup})
                return {'nodes': rows}

        @app.post('/api/labs/{lab_id}/ssh-check')
        def check(lab_id: str, data: NodeRequest):
            node, creds = self.node(lab_id, data.name)
            if not creds.get('username'):
                raise HTTPException(400, 'Assign SSH credentials to this node first.')
            key = (lab_id, data.name)
            with self.lock:
                if key in self.checking:
                    raise HTTPException(409, 'A login check is already running for this node.')
                client = self.reserve()
                self.checking.add(key)
            try:
                result = self.login_result(client, node, creds, self.monitored(lab_id))
            finally:
                self.release(client)
                with self.lock:
                    self.checking.discard(key)
            with self.lock:
                self.checks[key] = result
            self.store.event('ssh.check', result['message'], lab_id=lab_id, node=data.name)
            return result

        @app.post('/api/labs/{lab_id}/ssh-check-all')
        def check_all(lab_id: str):
            with self.store.lock:
                lab = self.store.lab(lab_id)
                if not lab:
                    raise HTTPException(404, 'Lab not found')
                lab = copy.deepcopy(lab)
            with self.lock:
                if lab_id in self.checking_all or any(key[0] == lab_id for key in self.checking):
                    raise HTTPException(409, 'A login check is already running for this lab.')
                self.checking_all.add(lab_id)
            at = now()
            targets, skipped = self.bulk_check_targets(lab)
            if not targets:
                with self.lock:
                    self.checking_all.discard(lab_id)
                return {'started': 0, 'skipped': skipped, 'at': at}
            # Started in the background: the route answers at once, and the browser's
            # existing 4 s poll picks up each node's result from /api/state as it lands.
            threading.Thread(target=self.run_bulk_checks, args=(lab_id, targets, bool(lab.get('deployment_name'))), daemon=True).start()
            return {'started': len(targets), 'skipped': skipped, 'at': at}

        @app.post('/api/labs/{lab_id}/terminal-ticket')
        def ticket(lab_id: str, data: TicketRequest):
            if data.protocol == 'console':
                address, port = self.console_target(lab_id, data.name)   # no credential check: a console has none
                endpoint = f'{address}:{port}'
            else:
                node, creds = self.node(lab_id, data.name)
                if not creds.get('username'):
                    raise HTTPException(400, 'Assign SSH credentials to this node first.')
                endpoint = f"{node['address']}:{node['port']}"
            with self.lock:
                self.tickets = {k: v for k, v in self.tickets.items() if v[0] > time.monotonic()}
                if len(self.tickets) >= 32:
                    raise HTTPException(429, 'Too many pending terminal sessions')
                key = secrets.token_urlsafe(32)
                self.tickets[key] = (time.monotonic() + 30, lab_id, data.name, data.protocol)
            return {'ticket': key, 'expires_in': 30, 'endpoint': endpoint, 'protocol': data.protocol}

        @app.websocket('/api/terminal')
        async def terminal(ws: WebSocket):
            origin = urlsplit(ws.headers.get('origin', ''))
            expected_scheme = 'https' if ws.url.scheme == 'wss' else 'http'
            if origin.scheme != expected_scheme or origin.netloc != ws.url.netloc:
                await ws.close(code=1008)
                return
            await ws.accept()
            client = None
            channel = None
            opened = False      # terminal.close is only audited for a session whose terminal.open was
            lab_id = name = ''
            try:
                message = await asyncio.wait_for(ws.receive_text(), 5)
                if len(message) > 512:
                    raise ValueError('Invalid authentication')
                auth = json.loads(message)
                with self.lock:
                    item = self.tickets.pop(auth.get('ticket', ''), None)
                if not item or item[0] <= time.monotonic():
                    await ws.close(code=1008)
                    return
                _, lab_id, name, protocol = item
                if protocol == 'console':
                    await self.console_session(ws, lab_id, name)
                    return
                node, creds = self.node(lab_id, name)
                if not creds.get('username'):
                    raise ValueError('Missing credentials')
                client = self.reserve()
                await asyncio.to_thread(connect, client, node, creds)
                channel = await asyncio.to_thread(client.invoke_shell, term='xterm-256color', width=100, height=30)
                channel.settimeout(5)
                self.store.event('terminal.open', 'Interactive SSH session opened', lab_id=lab_id, node=name)
                opened = True
                await ws.send_json({'type': 'status', 'message': 'Connected'})
                started = last_input = time.monotonic()
                while not channel.closed:
                    current = time.monotonic()
                    if current - last_input > 900 or current - started > 14400:
                        await ws.send_json({'type': 'status', 'message': 'Session timeout. Reconnect to continue.'})
                        break
                    if channel.recv_ready():
                        # One bounded chunk per loop; awaited sends apply socket backpressure.
                        output = await asyncio.to_thread(channel.recv, 16384)
                        if not output:
                            break
                        await ws.send_bytes(output)
                    elif channel.exit_status_ready():
                        break
                    try:
                        raw = await asyncio.wait_for(ws.receive_text(), .03)
                    except asyncio.TimeoutError:
                        continue
                    if len(raw) > 20000:
                        raise ValueError('Input too large')
                    event = json.loads(raw)
                    if event.get('type') == 'input':
                        value = event.get('data', '')
                        if not isinstance(value, str) or len(value.encode()) > 16384:
                            raise ValueError('Invalid input')
                        if value:
                            last_input = time.monotonic()
                            await asyncio.to_thread(channel.sendall, value.encode())
                    elif event.get('type') == 'resize':
                        cols, rows = int(event['cols']), int(event['rows'])
                        if not (20 <= cols <= 400 and 5 <= rows <= 150):
                            raise ValueError('Invalid terminal dimensions')
                        await asyncio.to_thread(channel.resize_pty, width=cols, height=rows)
                    else:
                        raise ValueError('Invalid terminal message')
            except WebSocketDisconnect:
                pass
            except Exception:
                try:
                    await ws.send_json({'type': 'error', 'message': 'Session ended. Check credentials, endpoint, and session limits.'})
                except Exception:
                    pass
            finally:
                if channel is not None:
                    channel.close()
                if client is not None:
                    self.release(client)
                if opened:
                    self.store.event('terminal.close', 'Interactive SSH session closed', lab_id=lab_id, node=name)
                try:
                    await ws.close()
                except Exception:
                    pass
