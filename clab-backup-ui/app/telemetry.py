"""Automatic, session-only network telemetry for deployed labs.

A separate state machine per node (disabled, waiting, configuring, connecting,
streaming, stale, unsupported, failed) sits beside the readiness monitor. Once the
monitor has recorded a real ``show version`` answer for a running node of a lab whose
automatic-telemetry setting is on, this manager configures the node's gNMI service
over SSH (only the lines that are missing, with the NOS's own scoped commit), opens
a gNMI dial-in subscription to the node's management address with the same password
login, and keeps the last hour of samples in memory. Streaming means usable samples
arrived, never merely that the login or the configuration succeeded.

Telemetry never blocks terminals, captures, backups or deployments: it defers while
a lab operation or a backup job runs, it forgets a node whose runtime signature
changes (stop, restart, redeploy) and clears the lab when a lifecycle operation is
submitted, so an earlier deployment's samples cannot appear under a new one. Nothing
it observes is persisted; only the lab's setting and the record of the lines the
manager added live in the encrypted state, so an explicit removal only removes those.
"""
import copy
import logging
import os
import queue
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import paramiko
from fastapi import HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from .discovery import discovery_fresh, node_available
from .node_services import connect
from .runner import effective_credentials, now
from .telemetry_adapters import adapter_for, SUPPORTED
from .telemetry_collector import AVAILABLE, NodeCollector
from .telemetry_names import endpoint_candidates, interface_role
from .telemetry_provision import ProvisionError, provision
from .telemetry_settings import default_settings, settings_of
from .telemetry_store import INTERVAL, STALE_AFTER, WINDOWS, TelemetryStore
from .topology import bind_drawing

SCAN_INTERVAL = 5
QUEUE_SIZE = 5000               # records waiting between the collectors and the store
MAX_PROVISIONING = 4            # concurrent SSH provisioning sessions
MAX_COLLECTORS = 64             # concurrent gNMI sessions per manager
RETRY_MIN = 15                  # seconds before the first retry after a failure
RETRY_MAX = 300                 # backoff ceiling
LIFECYCLE = ('deploy', 'redeploy', 'destroy', 'start', 'stop', 'restart', 'apply')
STATES = ('disabled', 'waiting', 'configuring', 'connecting', 'streaming', 'stale', 'unsupported', 'failed')
DOWN_STATES = ('DOWN', 'LOWER_LAYER_DOWN', 'NOT_PRESENT', 'TESTING', 'DORMANT')
MISSING = object()
METHOD = 'gNMI dial-in: counters sampled every 10 s'


def summarize(states):
    """Lab-level verdict for the deployment bar and the Telemetry view header."""
    counted = [s for s in states if s in STATES and s != 'disabled']
    counts = {name: sum(s == name for s in states) for name in STATES}
    supported = [s for s in counted if s != 'unsupported']
    if not states or all(s == 'disabled' for s in states):
        status = 'disabled'
    elif not supported:
        status = 'unsupported'
    elif all(s == 'streaming' for s in supported):
        status = 'streaming'
    elif counts['failed']:
        status = 'failed'
    elif counts['streaming'] or counts['stale']:
        status = 'partial'
    else:
        status = 'waiting'
    return {'status': status, 'total': len(supported), **counts}


def end_status(row, node_state):
    """One end of a link as the map shows it: up, down, stale, unknown or unsupported."""
    if node_state in ('unsupported', 'disabled'):
        return 'unsupported'
    if row is None:
        return 'unknown'
    if not row.get('fresh'):
        return 'stale' if row.get('oper') else 'unknown'
    oper = row.get('oper', '')
    if oper == 'UP':
        return 'up'
    if oper in DOWN_STATES:
        return 'down'
    return 'unknown'


def link_status(a, z):
    """Both ends count. A fresh DOWN on either end wins; UP needs both ends fresh and up;
    one observed UP end with an unobserved other end is 'up-partial'; stale beats unknown."""
    states = (a, z)
    if 'down' in states:
        return 'down', 'up' in states
    if states == ('up', 'up'):
        return 'up', False
    if 'up' in states and all(s in ('up', 'unknown', 'unsupported') for s in states):
        return 'up-partial', False
    if 'stale' in states:
        return 'stale', False
    return 'unknown', False


class TelemetryManager:
    def __init__(self, store, services, environ=None):
        self.store = store
        self.services = services
        config = os.environ if environ is None else environ
        mode = (config.get('TELEMETRY_COLLECTOR', 'gnmi') or 'gnmi').strip().lower()
        self.enabled = mode == 'gnmi' and AVAILABLE
        if mode not in ('gnmi', 'disabled'):
            self.enabled = False
            self.unavailable = 'Unknown TELEMETRY_COLLECTOR value; supported values are gnmi and disabled.'
        elif mode == 'disabled':
            self.unavailable = 'Telemetry is disabled by TELEMETRY_COLLECTOR=disabled in the manager environment.'
        elif not AVAILABLE:
            self.unavailable = 'The gNMI client library (pygnmi) is not installed in this image; rebuild the manager.'
        else:
            self.unavailable = ''
        # The optional Grafana stack (deploy/setup-telemetry.sh) is announced to the UI
        # by port only; the browser opens it on the manager's own host name.
        stack = (config.get('TELEMETRY_STACK', '') or '').strip().lower()
        try: port = int(config.get('TELEMETRY_GRAFANA_PORT', '3000') or 3000)
        except ValueError: port = 0
        try: prometheus = int(config.get('TELEMETRY_PROMETHEUS_PORT', '9090') or 9090)
        except ValueError: prometheus = 0
        self.grafana = {'enabled': stack == 'grafana' and 1 <= port <= 65535, 'port': port if 1 <= port <= 65535 else 0,
                        'prometheus_port': prometheus if 1 <= prometheus <= 65535 else 0}
        self.data = TelemetryStore()
        self.queue = queue.Queue(maxsize=QUEUE_SIZE)
        self.lock = threading.RLock()
        self.status = {}          # (lab id, node) -> status dict
        self.collectors = {}      # (lab id, node) -> NodeCollector
        self.observed = {}        # (lab id, node) -> runtime signature or None
        self.inflight = set()     # nodes with an SSH provisioning session running
        self.operations_seen = set()
        with store.lock:
            self.operations_seen = {j.get('id') for j in store.state.get('operations', [])}
        self.pool = ThreadPoolExecutor(max_workers=MAX_PROVISIONING)
        self.stopping = threading.Event()
        self.wake = threading.Event()
        self.threads = []
        self.dropped_queue = 0

    # ---- lifecycle ----------------------------------------------------------
    def start(self):
        for target in (self.loop, self.ingest):
            thread = threading.Thread(target=target, daemon=True)
            thread.start()
            self.threads.append(thread)

    def close(self):
        self.stopping.set(); self.wake.set()
        with self.lock:
            collectors = list(self.collectors.values())
            self.collectors.clear()
        for collector in collectors:
            collector.stop()
        self.pool.shutdown(wait=False, cancel_futures=True)
        for thread in self.threads:
            thread.join(timeout=2)

    def reset(self):
        """Manager reset: everything observed is dropped; nothing here is persistent."""
        with self.lock:
            keys = list(self.status) + list(self.collectors)
        for key in set(keys):
            self.stop_collector(key)
        with self.lock:
            self.status.clear(); self.observed.clear()
        self.data.clear_all()

    def forget_lab(self, lab_id):
        """Removal of a saved lab: stop its collectors and drop its buffers."""
        self.clear_lab(lab_id, log=False)
        with self.lock:
            for key in [k for k in self.status if k[0] == lab_id]:
                self.status.pop(key, None); self.observed.pop(key, None)

    def clear_lab(self, lab_id, reason='', log=True):
        with self.lock:
            keys = [k for k in set(self.status) | set(self.collectors) if k[0] == lab_id]
        for key in keys:
            self.stop_collector(key)
            with self.lock:
                self.status.pop(key, None)
        self.data.clear_lab(lab_id)
        if log and reason:
            self.event('telemetry.clear', 'Telemetry session cleared: ' + reason, lab_id)

    # ---- helpers ------------------------------------------------------------
    def event(self, action, message, lab_id, node='', level='info'):
        try: self.store.event(action, message, level=level, lab_id=lab_id, node=node)
        except OSError: pass

    def get(self, key):
        with self.lock:
            return self.status.setdefault(key, {'state': 'waiting', 'message': '', 'at': now(), 'generation': '',
                                                'groups': {}, 'attempts': 0, 'retry_at': 0.0, 'provisioned': None,
                                                'endpoint': '', 'transport': '', 'applied': 0, 'first_sample': ''})

    def set(self, key, state, message, log=False, level='info', **fields):
        """Record a state; audit-log the transition when asked and when the state changed."""
        with self.lock:
            status = self.get(key)
            changed = status['state'] != state or status['message'] != message
            status.update(state=state, message=message, **fields)
            if changed:
                status['at'] = now()
        if changed and log:
            self.event('telemetry.' + state, message, key[0], key[1], level)
        return changed

    @staticmethod
    def signature(lab, node):
        return (lab.get('deployment_name'), node.get('runtime_state'), node.get('discovered_address'), node.get('address'), node.get('port'))

    @staticmethod
    def new_generation():
        """Unique per boot cycle and per provisioning attempt: two deployments of the same lab and
        node name, even at the same management address, never share a generation."""
        return uuid.uuid4().hex[:16]

    def gnmi_credentials(self, lab, node, settings):
        """(credentials for gNMI, problem) — gNMI needs a password login; SSH keys do not carry over."""
        if settings.get('profile_id'):
            profile = next((p for p in lab['profiles'] if p['id'] == settings['profile_id']), None)
            if not profile:
                return None, 'The telemetry credential profile was removed. Choose another one in Telemetry settings.'
            if profile.get('auth') != 'password':
                return None, 'The telemetry credential profile uses an SSH key; gNMI needs a username and password.'
            return {'username': profile['username'], 'password': profile.get('password', '')}, ''
        creds = effective_credentials(lab, node)
        if not creds.get('username'):
            return None, 'Assign NOS credentials to this node first.'
        if creds.get('auth') != 'password':
            return None, 'This node logs in with an SSH key, which gNMI cannot use. Choose a password profile in Telemetry settings.'
        return {'username': creds['username'], 'password': creds.get('password', '')}, ''

    # ---- scanning -----------------------------------------------------------
    def loop(self):
        while not self.stopping.is_set():
            try: self.scan()
            except Exception:
                logging.getLogger(__name__).warning('Telemetry scan failed; retrying on the next pass.')
            self.wake.wait(SCAN_INTERVAL); self.wake.clear()

    def review_operations(self, state):
        """A lifecycle operation submitted for a lab ends that lab's telemetry session."""
        for job in state.get('operations', []):
            ident = job.get('id')
            if not ident or ident in self.operations_seen:
                continue
            self.operations_seen.add(ident)
            if job.get('lab_id') and job.get('action') in LIFECYCLE:
                self.clear_lab(job['lab_id'], f"lab operation {job['action']} submitted")
        self.operations_seen &= {j.get('id') for j in state.get('operations', [])} or set()

    def scan(self):
        from .lab_operations import operation_busy
        if self.store.reset_pending: return
        state = self.store.snapshot()
        fresh = discovery_fresh(state)
        self.review_operations(state)
        present = set()
        with self.services.lock: checks = {k: v.get('status') for k, v in self.services.checks.items()}
        for lab in state['labs']:
            if not lab.get('deployment_name'): continue
            lab_id = lab['id']
            settings = settings_of(lab)
            busy = operation_busy(state, lab_id) or any(j['status'] in ('queued', 'running') and j.get('lab_id') == lab_id for j in state['jobs'])
            for node in lab['nodes']:
                key = (lab_id, node['name']); present.add(key)
                running = fresh and node_available(state, lab, node)
                signature = self.signature(lab, node) if running else None
                previous = self.observed.get(key, MISSING)
                if previous is not MISSING and previous != signature:
                    self.restart_node(key)
                self.observed[key] = signature
                if not self.enabled:
                    self.set(key, 'disabled', self.unavailable); continue
                if not settings['auto']:
                    self.stop_collector(key)
                    self.set(key, 'disabled', 'Automatic telemetry is off for this lab.' if settings['decided']
                             else 'Automatic telemetry has not been enabled for this lab yet. Open Telemetry to enable it.')
                    continue
                adapter = adapter_for(node.get('platform'))
                if adapter is None:
                    self.set(key, 'unsupported', 'No telemetry adapter for this node kind; supported kinds: cEOS, XRv9k, cJunosEvolved.')
                    continue
                if not running:
                    self.stop_collector(key)
                    self.set(key, 'waiting', 'Node is not running, or VM discovery is stale.')
                    continue
                status = self.get(key)
                if status['state'] in ('connecting', 'streaming', 'stale'):
                    self.check_stream(key, status)
                    continue
                if status['state'] == 'configuring' or key in self.inflight:
                    continue
                creds, problem = self.gnmi_credentials(lab, node, settings)
                ssh = effective_credentials(lab, node)
                if problem or not ssh.get('username'):
                    self.set(key, 'failed', problem or 'Assign NOS credentials to this node first.', log=True, level='warning')
                    continue
                if checks.get(key) != 'reachable':
                    self.set(key, 'waiting', 'Waiting for the NOS: the automatic SSH login and show version check has not answered yet.')
                    continue
                if busy:
                    self.set(key, 'waiting', 'Waiting for the lab operation or backup job to finish before touching the node.')
                    continue
                if status['retry_at'] > time.monotonic():
                    continue
                with self.lock:
                    collectors = len(self.collectors)
                if collectors >= MAX_COLLECTORS:
                    self.set(key, 'waiting', f'Collector limit of {MAX_COLLECTORS} concurrent gNMI sessions reached.')
                    continue
                if status.get('provisioned') == signature and status.get('endpoint') and status.get('generation'):
                    self.start_collector(key, node, creds, adapter, status['generation'], status['endpoint'], status['transport'])
                    continue
                generation = self.new_generation()
                with self.lock:
                    self.inflight.add(key)
                self.set(key, 'configuring', 'Checking the NOS telemetry service over SSH and adding the missing lines.',
                         generation=generation)
                try:
                    self.pool.submit(self.provision_node, key, copy.deepcopy(node), copy.deepcopy(ssh), creds, adapter, signature, generation)
                except RuntimeError:
                    with self.lock: self.inflight.discard(key)
        with self.lock:
            gone = [k for k in set(self.status) | set(self.observed) | set(self.collectors) if k not in present]
        for key in gone:
            self.stop_collector(key)
            with self.lock:
                self.status.pop(key, None); self.observed.pop(key, None)
            self.data.clear_node(*key)

    def restart_node(self, key):
        """Stop, restarted or redeployed node: new generation, empty buffers, provisioning again."""
        self.stop_collector(key)
        with self.lock:
            self.status.pop(key, None)
        self.data.clear_node(*key)

    def check_stream(self, key, status):
        with self.lock:
            collector = self.collectors.get(key)
        alive = collector is not None and collector.is_alive()
        snapshot = self.data.snapshot(*key)
        last = snapshot['last_sample'] if snapshot else 0
        if not alive:
            self.schedule_retry(key, 'The gNMI session ended; reconnecting.')
            return
        if status['state'] == 'streaming' and last and time.time() - last > STALE_AFTER:
            self.set(key, 'stale', f'No samples for more than {STALE_AFTER} s; the session is open and recent history is kept.', log=True, level='warning')
        elif status['state'] == 'stale' and last and time.time() - last <= STALE_AFTER:
            self.set(key, 'streaming', 'Usable samples are arriving again.', log=True)

    def schedule_retry(self, key, message, level='warning', reason=''):
        self.stop_collector(key)
        with self.lock:
            status = self.get(key)
            status['attempts'] += 1
            delay = min(RETRY_MAX, RETRY_MIN * 2 ** (status['attempts'] - 1))
            if reason == 'auth':
                delay = RETRY_MAX
            status['retry_at'] = time.monotonic() + delay
        self.set(key, 'failed', f'{message} Next attempt in {int(delay)} s.', log=True, level=level)

    # ---- provisioning -------------------------------------------------------
    def provision_node(self, key, node, ssh, gnmi, adapter, signature, generation, mode='apply'):
        lab_id, name = key
        client = None
        result = None
        message = ''
        try:
            client = self.services.reserve()
            connect(client, node, ssh)
            owned = self.owned_lines(lab_id, name)
            result = provision(client, adapter, ssh, mode=mode, owned=owned)
        except paramiko.AuthenticationException:
            message = 'SSH login for telemetry configuration was refused with the saved credentials.'
        except ProvisionError as error:
            message = str(error)
        except HTTPException as error:
            message = 'No SSH session slot was free (' + str(error.detail) + ').'
        except Exception:
            message = 'The SSH session for telemetry configuration failed; the node may still be booting.'
        finally:
            if client is not None:
                try: self.services.release(client)
                except Exception: pass
            with self.lock:
                self.inflight.discard(key)
        with self.lock:
            current = self.status.get(key)
        if not current or current.get('generation') != generation:
            return   # the node changed meanwhile; the next scan starts over
        if mode == 'remove':
            if message:
                self.set(key, 'disabled', 'Removal failed: ' + message, log=True, level='warning')
            else:
                self.record_applied(lab_id, name, [], removed=result['removed'])
                self.set(key, 'disabled', result['message'], log=True)
                self.event('telemetry.remove', result['message'] + ' Lines: ' + '; '.join(result['removed']), lab_id, name)
            return
        if message:
            self.schedule_retry(key, message)
            return
        if result['applied']:
            self.record_applied(lab_id, name, result['applied'])
            self.event('telemetry.configure', result['message'] + ' Lines: ' + '; '.join(l.strip() for l in result['applied']), lab_id, name)
        elif result.get('missing'):
            self.schedule_retry(key, 'The telemetry service still needs configuration: ' + ' '.join(result['blockers'] or result['missing']))
            return
        endpoint = f"{node['address']}:{result['port']}"
        with self.lock:
            status = self.get(key)
            status.update(provisioned=signature, endpoint=endpoint, transport=result['transport'], applied=len(result['applied']))
        self.start_collector(key, node, gnmi, adapter, generation, endpoint, result['transport'])

    def owned_lines(self, lab_id, name):
        with self.store.lock:
            lab = self.store.lab(lab_id)
            applied = ((lab or {}).get('telemetry') or {}).get('applied', {}) if lab else {}
            return list(applied.get(name, {}).get('lines', []))

    def record_applied(self, lab_id, name, lines, removed=None):
        with self.store.lock:
            lab = self.store.lab(lab_id)
            if not lab: return
            settings = lab.setdefault('telemetry', default_settings())
            applied = settings.setdefault('applied', {})
            if lines:
                applied[name] = {'lines': list(lines), 'at': now(), 'kind': next((n.get('platform') for n in lab['nodes'] if n['name'] == name), '')}
            elif removed is not None:
                applied.pop(name, None)
            try: self.store.save()
            except OSError: pass

    # ---- collection ---------------------------------------------------------
    def start_collector(self, key, node, gnmi, adapter, generation, endpoint, transport):
        address, _, port = endpoint.rpartition(':')
        try: port = int(port)
        except ValueError:
            self.schedule_retry(key, 'The telemetry endpoint is invalid.'); return
        if not self.data.begin(key[0], key[1], generation):
            self.set(key, 'waiting', 'The session store has reached its node limit.'); return
        collector = NodeCollector(key, generation, (address, port), gnmi, adapter, transport or 'plaintext',
                                  self.queue, self.on_event)
        with self.lock:
            old = self.collectors.pop(key, None)
            self.collectors[key] = collector
        if old is not None:
            old.stop()
        self.set(key, 'connecting', f'Connecting to gNMI at {endpoint}.', generation=generation, endpoint=endpoint, transport=transport, groups={})
        collector.start()

    def stop_collector(self, key):
        with self.lock:
            collector = self.collectors.pop(key, None)
        if collector is not None:
            collector.stop()

    def on_event(self, event):
        key = event['key']
        with self.lock:
            status = self.status.get(key)
            if not status or status.get('generation') != event.get('generation'):
                return
        kind = event['event']
        if kind == 'connected':
            self.set(key, 'connecting', f"gNMI connected over {'TLS' if event['transport'] == 'tls' else 'plain text'}; subscribing.",
                     transport=event['transport'])
        elif kind == 'group':
            with self.lock:
                status['groups'][event['group']] = {'status': event['status'], 'message': event['message'], 'encoding': event.get('encoding', '')}
                groups = dict(status['groups'])
            if event['status'] == 'streaming' and status['state'] != 'streaming':
                self.set(key, 'streaming', 'Usable samples are arriving.', log=True, first_sample=now())
            elif event['status'] == 'unsupported':
                self.event('telemetry.unsupported', f"{event['group']}: {event['message']}", key[0], key[1], 'warning')
            elif event['status'] == 'failed' and status['state'] == 'streaming' and all(g['status'] != 'streaming' for g in groups.values()):
                pass   # the collector ends its session; check_stream schedules the reconnect
        elif kind == 'failed':
            if event.get('reason') == 'auth':
                self.schedule_retry(key, event['message'], reason='auth')
            else:
                self.schedule_retry(key, event['message'])

    def ingest(self):
        while not self.stopping.is_set():
            self.ingest_one(1)

    def ingest_one(self, timeout=0):
        """Move one record from the collectors' queue into the store; True when one was taken."""
        try: record = self.queue.get(timeout=timeout) if timeout else self.queue.get_nowait()
        except queue.Empty: return False
        if self.data.ingest(record):
                key = (record['lab_id'], record['node'])
                with self.lock:
                    status = self.status.get(key)
                if status and status['state'] in ('connecting', 'stale'):
                    self.set(key, 'streaming', 'Usable samples are arriving.', log=status['state'] == 'stale', first_sample=status.get('first_sample') or now())
        return True

    # ---- public views -------------------------------------------------------
    def node_status(self, lab, node):
        if not lab.get('deployment_name'):
            return {'state': 'unmonitored', 'message': 'Telemetry is only collected for labs linked to a VM deployment.'}
        with self.lock:
            status = self.status.get((lab['id'], node['name']))
            if not status:
                settings = settings_of(lab)
                if not self.enabled:
                    return {'state': 'disabled', 'message': self.unavailable}
                if not settings['auto']:
                    return {'state': 'disabled', 'message': 'Automatic telemetry is off for this lab.' if settings['decided'] else 'Automatic telemetry has not been enabled for this lab yet.'}
                return {'state': 'waiting', 'message': 'Waiting for the next telemetry check.'}
            return {'state': status['state'], 'message': status['message'], 'at': status['at']}

    def lab_summary(self, lab):
        if not lab.get('deployment_name'):
            return {'status': 'unmonitored', 'total': 0}
        states = [self.node_status(lab, n)['state'] for n in lab['nodes']]
        result = summarize(states)
        result.update(settings_of(lab))
        return result

    def health(self):
        with self.lock:
            collectors = sum(1 for c in self.collectors.values() if c.is_alive())
            states = {}
            for status in self.status.values():
                states[status['state']] = states.get(status['state'], 0) + 1
        return {'enabled': self.enabled, 'collector': 'gnmi' if self.enabled else 'disabled', 'message': self.unavailable or 'gNMI dial-in collector ready.',
                'library': 'pygnmi' if AVAILABLE else 'missing', 'method': METHOD, 'sample_interval': INTERVAL,
                'sessions': collectors, 'states': states, 'queue': self.queue.qsize(), 'queue_dropped': self.dropped_queue,
                'bounds': {'collectors': MAX_COLLECTORS, 'provisioning': MAX_PROVISIONING, 'queue': QUEUE_SIZE},
                'store': self.data.stats(), 'supported_kinds': list(SUPPORTED), 'grafana': self.grafana,
                'metrics_path': '/api/telemetry/metrics'}

    def lab_view(self, lab):
        """Everything the Telemetry view and the map overlay need for one lab; bounded."""
        settings = settings_of(lab)
        profile = next((p for p in lab['profiles'] if p['id'] == settings['profile_id']), None)
        drawing = bind_drawing(lab)
        wired = {}   # inventory name -> {nos interface name: {'peer': ..., 'drawn': ...}}
        if drawing:
            by_id = {n['id']: n for n in drawing['nodes']}
            kinds = {n['name']: n.get('platform') for n in lab['nodes']}
            for pair in drawing['links']:
                ends = [(by_id.get(ep['node'], {}).get('inventory_name'), ep['interface']) for ep in pair]
                for (node, interface), (peer_node, peer_interface) in ((ends[0], ends[1]), (ends[1], ends[0])):
                    if not node: continue
                    for candidate in endpoint_candidates(kinds.get(node), interface):
                        wired.setdefault(node, {}).setdefault(candidate, {'peer': peer_node or '', 'peer_interface': peer_interface, 'drawn': interface})
        nodes = []
        snapshots = {}
        for node in lab['nodes']:
            status = self.node_status(lab, node)
            with self.lock:
                detail = copy.deepcopy(self.status.get((lab['id'], node['name']), {}))
            snapshot = self.data.snapshot(lab['id'], node['name']) if lab.get('deployment_name') else None
            snapshots[node['name']] = snapshot
            adapter = adapter_for(node.get('platform'))
            interfaces = []
            for row in (snapshot or {}).get('interfaces', []):
                physical = adapter.physical(row['name']) if adapter else row['name']
                link = (wired.get(node['name'], {}).get(row['name']) or wired.get(node['name'], {}).get(physical))
                row = dict(row, role=interface_role(node.get('platform'), row['name']), wired=bool(link),
                           peer=link['peer'] if link else '', peer_interface=link['peer_interface'] if link else '',
                           drawn=link['drawn'] if link else '')
                interfaces.append(row)
            order = {'physical': 0, 'management': 1, 'other': 2}
            interfaces.sort(key=lambda r: (not r['wired'], order.get(r['role'], 3), r['name']))
            nodes.append({'name': node['name'], 'short_name': node.get('short_name') or node['name'], 'platform': node.get('platform', ''),
                          'label': adapter.label if adapter else '', 'supported': adapter is not None,
                          **status, 'endpoint': detail.get('endpoint', ''), 'transport': detail.get('transport', ''),
                          'groups': detail.get('groups', {}), 'attempts': detail.get('attempts', 0), 'applied': detail.get('applied', 0),
                          'first_sample': detail.get('first_sample', ''), 'method': METHOD if detail.get('endpoint') else '',
                          'last_sample': (snapshot or {}).get('last_sample', 0), 'fresh': (snapshot or {}).get('fresh', False),
                          'samples': (snapshot or {}).get('samples', 0), 'dropped': (snapshot or {}).get('dropped', 0),
                          'overflow': (snapshot or {}).get('overflow', 0),
                          'interfaces': interfaces, 'peers': (snapshot or {}).get('peers', [])})
        links = []
        if drawing:
            by_id = {n['id']: n for n in drawing['nodes']}
            by_name = {n['name']: n for n in nodes}
            for index, pair in enumerate(drawing['links']):
                ends = []
                for ep in pair:
                    inventory = by_id.get(ep['node'], {}).get('inventory_name')
                    view = by_name.get(inventory) if inventory else None
                    row = None
                    if view:
                        for candidate in endpoint_candidates(view['platform'], ep['interface']):
                            row = next((r for r in view['interfaces'] if r['name'] == candidate or (adapter_for(view['platform']) and adapter_for(view['platform']).physical(r['name']) == candidate)), None)
                            if row: break
                    state = end_status(row, view['state'] if view else 'unsupported')
                    ends.append({'node': inventory or '', 'label': by_id.get(ep['node'], {}).get('label', ep['node']), 'interface': ep['interface'],
                                 'nos_interface': row['name'] if row else '', 'state': state,
                                 'rx_bps': row.get('rx_bps') if row else None, 'tx_bps': row.get('tx_bps') if row else None,
                                 'oper': row.get('oper', '') if row else '', 'at': row.get('at', 0) if row else 0})
                status, mismatch = link_status(ends[0]['state'], ends[1]['state'])
                links.append({'index': index, 'status': status, 'mismatch': mismatch, 'ends': ends})
        summary = summarize([n['state'] for n in nodes])
        return {'lab_id': lab['id'], 'lab_name': lab.get('name', ''), 'generated_at': now(), 'enabled': self.enabled, 'unavailable': self.unavailable,
                'grafana': self.grafana,
                'settings': {**settings, 'profile_label': profile['label'] if profile else ''},
                'method': METHOD, 'sample_interval': INTERVAL, 'stale_after': STALE_AFTER, 'windows': list(WINDOWS),
                'summary': summary, 'nodes': nodes, 'links': links, 'linked': bool(lab.get('deployment_name')),
                'password_profiles': [{'id': p['id'], 'label': p['label'], 'platform': p['platform']} for p in lab['profiles'] if p.get('auth') == 'password']}

    # ---- API ----------------------------------------------------------------
    def install(self, app):
        manager = self

        def lab_for(lab_id):
            lab = self.store.lab(lab_id)
            if not lab: raise HTTPException(404, 'Lab not found')
            return lab

        class Settings(BaseModel):
            model_config = ConfigDict(extra='forbid')
            auto: bool
            profile_id: str = Field(default='', max_length=64)

        class NodeChoice(BaseModel):
            model_config = ConfigDict(extra='forbid')
            node: str = Field(default='', max_length=200)

        @app.get('/api/telemetry/health')
        def health():
            return manager.health()

        @app.get('/api/telemetry/metrics')
        def metrics():
            """Prometheus text exposition for the optional Grafana stack; names only, no secrets."""
            from fastapi.responses import PlainTextResponse
            from .telemetry_metrics import render
            with self.store.lock:
                labs = [copy.deepcopy(l) for l in self.store.state['labs'] if l.get('deployment_name')]
            body = render([manager.lab_view(lab) for lab in labs], time.time())
            return PlainTextResponse(body, media_type='text/plain; version=0.0.4; charset=utf-8')

        @app.get('/api/labs/{lab_id}/telemetry')
        def view(lab_id: str):
            with self.store.lock:
                lab = copy.deepcopy(lab_for(lab_id))
            return manager.lab_view(lab)

        @app.get('/api/labs/{lab_id}/telemetry/series')
        def series(lab_id: str, node: str = Query(..., min_length=1, max_length=200), interface: str = Query(..., min_length=1, max_length=64),
                   window: int = Query(WINDOWS[0])):
            if window not in WINDOWS: raise HTTPException(400, 'Choose a window of 300, 900 or 3600 seconds.')
            with self.store.lock:
                lab = lab_for(lab_id)
                if not any(n['name'] == node for n in lab['nodes']): raise HTTPException(404, 'Node not found')
            points = self.data.series(lab_id, node, interface, window)
            if points is None: raise HTTPException(404, 'No telemetry for this interface in the current session.')
            return {'node': node, 'interface': interface, 'window': window, 'interval': INTERVAL, 'points': points, 'generated_at': now()}

        @app.get('/api/labs/{lab_id}/telemetry/bgp-series')
        def bgp_series(lab_id: str, node: str = Query(..., min_length=1, max_length=200), peer: str = Query(..., min_length=1, max_length=64),
                       instance: str = Query('default', max_length=64), window: int = Query(WINDOWS[0])):
            if window not in WINDOWS: raise HTTPException(400, 'Choose a window of 300, 900 or 3600 seconds.')
            with self.store.lock:
                lab = lab_for(lab_id)
                if not any(n['name'] == node for n in lab['nodes']): raise HTTPException(404, 'Node not found')
            points = self.data.peer_series(lab_id, node, instance, peer, window)
            if points is None: raise HTTPException(404, 'No telemetry for this neighbour in the current session.')
            return {'node': node, 'peer': peer, 'instance': instance, 'window': window, 'points': points, 'generated_at': now()}

        @app.put('/api/labs/{lab_id}/telemetry/settings')
        def settings(lab_id: str, data: Settings):
            with self.store.lock:
                lab = lab_for(lab_id)
                if data.profile_id:
                    profile = next((p for p in lab['profiles'] if p['id'] == data.profile_id), None)
                    if not profile: raise HTTPException(400, 'Credential profile not found')
                    if profile.get('auth') != 'password': raise HTTPException(400, 'gNMI needs a password profile; SSH keys cannot be used.')
                current = lab.setdefault('telemetry', {'auto': False, 'decided': False, 'profile_id': '', 'applied': {}})
                current.update(auto=data.auto, decided=True, profile_id=data.profile_id)
                current.setdefault('applied', {})
                self.store.save()
                self.store.event('telemetry.settings', f"Automatic telemetry {'enabled' if data.auto else 'disabled'}; gNMI login: "
                                 + ('profile ' + data.profile_id if data.profile_id else 'each node\'s saved password login'), lab_id=lab_id)
                lab = copy.deepcopy(lab)
            if not data.auto:
                self.clear_lab(lab_id, 'automatic telemetry disabled')
            self.wake.set()
            return manager.lab_view(lab)

        @app.post('/api/labs/{lab_id}/telemetry/retry')
        def retry(lab_id: str, data: NodeChoice):
            with self.store.lock:
                lab = lab_for(lab_id)
                names = [n['name'] for n in lab['nodes'] if not data.node or n['name'] == data.node]
                if data.node and not names: raise HTTPException(404, 'Node not found')
            for name in names:
                key = (lab_id, name)
                with self.lock:
                    status = self.status.get(key)
                    if status and status['state'] in ('failed', 'stale', 'unsupported'):
                        status.update(retry_at=0.0, attempts=0, provisioned=None)
                        self.stop_collector(key)
                        status.update(state='waiting', message='Retry requested.', at=now())
            self.wake.set()
            return {'retried': names}

        @app.post('/api/labs/{lab_id}/telemetry/remove-config')
        def remove_config(lab_id: str, data: NodeChoice):
            with self.store.lock:
                lab = copy.deepcopy(lab_for(lab_id))
            settings = settings_of(lab)
            if settings['auto']:
                raise HTTPException(409, 'Disable automatic telemetry first; otherwise the lines would be added again.')
            state = self.store.snapshot()
            fresh = discovery_fresh(state)
            started = []
            skipped = []
            with self.services.lock: checks = {k: v.get('status') for k, v in self.services.checks.items()}
            for node in lab['nodes']:
                if data.node and node['name'] != data.node: continue
                key = (lab_id, node['name'])
                owned = self.owned_lines(lab_id, node['name'])
                adapter = adapter_for(node.get('platform'))
                if not owned or adapter is None:
                    skipped.append(node['name']); continue
                if not (fresh and node_available(state, lab, node)) or checks.get(key) != 'reachable':
                    skipped.append(node['name']); continue
                ssh = effective_credentials(lab, node)
                if not ssh.get('username'):
                    skipped.append(node['name']); continue
                with self.lock:
                    if key in self.inflight:
                        skipped.append(node['name']); continue
                    self.inflight.add(key)
                generation = 'remove:' + now()
                self.set(key, 'disabled', 'Removing the telemetry lines the manager added.', generation=generation)
                try:
                    self.pool.submit(self.provision_node, key, copy.deepcopy(node), copy.deepcopy(ssh), None, adapter,
                                     self.signature(lab, node), generation, 'remove')
                    started.append(node['name'])
                except RuntimeError:
                    with self.lock: self.inflight.discard(key)
                    skipped.append(node['name'])
            if data.node and not started and not skipped: raise HTTPException(404, 'Node not found')
            return {'started': started, 'skipped': skipped,
                    'message': 'Removal runs over SSH; only lines recorded as added by the manager are removed.'}
