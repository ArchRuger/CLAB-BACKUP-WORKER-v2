"""Node connection checks and bounded interactive SSH, separate from backups."""
import asyncio
import copy
import io
import json
import secrets
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit

import paramiko
from fastapi import HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from .runner import CLI_ERROR, effective_credentials, now
from .discovery import node_available

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
CLI_TIMEOUT = 25


def cli_answers(client, command=CLI_COMMAND, timeout=CLI_TIMEOUT):
    """True when the NOS CLI returns a real answer to show version over an exec channel.

    SSH can accept a login while the CLI is still starting (cEOS agents, Junos
    daemons); an empty or not-ready reply keeps the node in booting.
    """
    try:
        stdin, stdout, _ = client.exec_command(command, timeout=timeout)
        stdin.close()
        output = stdout.read(65536).decode('utf-8', 'replace')
    except Exception:
        return False
    return bool(output.strip()) and not CLI_ERROR.search(output)


def node_cli_command(node):
    return CLI_COMMAND if node.get('platform') else GENERIC_CLI_COMMAND


class NodeRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)


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
        self.bulk_pool = ThreadPoolExecutor(max_workers=BULK_CHECK_WORKERS)
        self.closed = False

    def close(self):
        with self.lock:
            self.closed = True
            self.tickets.clear()
            for client in list(self.clients):
                client.close()
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
        always agree: 'reachable' only when the CLI answered a real command after the login (the check the
        readiness monitor's probe makes), 'booting' when the login was accepted but the CLI is silent,
        'failed' when the login itself did not work. A booting result promises a re-check only when
        `monitored` (the lab is linked to a VM deployment). Never raises."""
        try:
            connect(client, node, creds)
            answered = cli_answers(client, node_cli_command(node))
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
        def ticket(lab_id: str, data: NodeRequest):
            node, creds = self.node(lab_id, data.name)
            if not creds.get('username'):
                raise HTTPException(400, 'Assign SSH credentials to this node first.')
            with self.lock:
                self.tickets = {k: v for k, v in self.tickets.items() if v[0] > time.monotonic()}
                if len(self.tickets) >= 32:
                    raise HTTPException(429, 'Too many pending terminal sessions')
                key = secrets.token_urlsafe(32)
                self.tickets[key] = (time.monotonic() + 30, lab_id, data.name)
            return {'ticket': key, 'expires_in': 30, 'endpoint': f"{node['address']}:{node['port']}"}

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
                _, lab_id, name = item
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
