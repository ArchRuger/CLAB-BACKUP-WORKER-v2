"""gNMI dial-in worker for one node, and the normalisation of what it receives.

The worker connects to the node's management address with the same password login
the manager uses for SSH, checks the advertised models, subscribes to interface
counters and state (and BGP neighbours where the model is advertised) and turns
every notification into small normalised records for the session store. Vendors
differ in how they split a notification (prefix plus leaf updates, whole JSON
subtrees, module-prefixed names, string-encoded uint64), so the flattening below
produces one canonical leaf path per value before any metric is recognised.
"""
import queue
import re
import threading
import time

try:
    from pygnmi.client import gNMIclient, gNMIException
    AVAILABLE = True
except ImportError:            # the manager still starts; telemetry reports itself unavailable
    gNMIclient = None
    gNMIException = Exception
    AVAILABLE = False

from .telemetry_store import COUNTERS, STATES

CONNECT_TIMEOUT = 8
FIRST_SAMPLE_TIMEOUT = 45      # seconds for the first usable interface record after subscribing
GROUP_IDLE = 120               # seconds without any notification before a group is reported idle (it stays open)
CLOCK_SLACK = 300              # device timestamps further from now than this are replaced by receive time
KEYS = {'interface': ('name',), 'subinterface': ('index',), 'neighbor': ('neighbor-address',),
        'afi-safi': ('afi-safi-name',), 'network-instance': ('name',), 'protocol': ('identifier', 'name')}
MODULE = re.compile(r'^[\w.-]+:')
INTERFACE = re.compile(r'^interfaces/interface\[name=([^\]]+)\]/state/(?:counters/)?([\w-]+)$')
BGP_STATE = re.compile(r'^network-instances/network-instance\[name=([^\]]+)\]/protocols/protocol\[[^/]*\]/bgp/neighbors/neighbor\[neighbor-address=([^\]]+)\]/state/session-state$')
BGP_PREFIXES = re.compile(r'^network-instances/network-instance\[name=([^\]]+)\]/protocols/protocol\[[^/]*\]/bgp/neighbors/neighbor\[neighbor-address=([^\]]+)\]/afi-safis/afi-safi\[afi-safi-name=([^\]]+)\]/state/prefixes/(received|sent|installed)$')
GROUPS = ('interfaces', 'bgp')


def _elem(name):
    return MODULE.sub('', name.strip())


def _join(prefix, path):
    parts = []
    for piece in (prefix or '', path or ''):
        for elem in piece.strip('/').split('/'):
            if elem:
                parts.append(_elem(elem))
    return '/'.join(parts)


def flatten(prefix, path, value):
    """Yield (canonical leaf path, value) pairs for one gNMI update, whatever its shape."""
    base = _join(prefix, path)
    if isinstance(value, dict):
        for key, inner in value.items():
            key = _elem(str(key))
            if isinstance(inner, list) and key in KEYS:
                for entry in inner:
                    if not isinstance(entry, dict):
                        continue
                    keys = [f'{k}={_elem(str(entry.get(k, "")))}' for k in KEYS[key] if k in entry]
                    if len(keys) != len(KEYS[key]):
                        continue
                    rest = {k: v for k, v in entry.items() if _elem(k) not in KEYS[key]}
                    yield from flatten(base, key + ''.join(f'[{k}]' for k in keys), rest)
            else:
                yield from flatten(base, key, inner)
    elif isinstance(value, list):
        return
    else:
        yield base, value


def classify(path, value):
    """One normalised record for a leaf we chart, else None."""
    match = INTERFACE.match(path)
    if match:
        name, leaf = match[1], match[2]
        if leaf in COUNTERS or leaf in STATES:
            return {'kind': 'interface', 'ident': name, 'metric': leaf, 'value': value}
        return None
    match = BGP_STATE.match(path)
    if match:
        return {'kind': 'bgp', 'instance': match[1], 'ident': match[2], 'metric': 'session-state', 'value': value}
    match = BGP_PREFIXES.match(path)
    if match:
        return {'kind': 'bgp', 'instance': match[1], 'ident': match[2], 'afi': match[3].rsplit(':', 1)[-1],
                'metric': match[4], 'value': value}
    return None


def normalize(message, received_at=None):
    """Records from one pygnmi telemetryParser dict (an 'update' message)."""
    now = time.time() if received_at is None else received_at
    body = (message or {}).get('update')
    if not isinstance(body, dict):
        return []
    stamp = body.get('timestamp') or 0
    ts = stamp / 1e9 if isinstance(stamp, (int, float)) and stamp > 1e15 else stamp
    # The device timestamp only orders the samples of one leaf (EOS stamps each notification
    # with the last change time of its leaves); rates, charts and freshness use the receive time.
    synthetic = not isinstance(ts, (int, float)) or abs(ts - now) > CLOCK_SLACK
    if synthetic:
        ts = now
    records = []
    for update in body.get('update', []) or []:
        if not isinstance(update, dict) or 'val' not in update:
            continue
        for path, value in flatten(body.get('prefix', ''), update.get('path') or '', update['val']):
            record = classify(path, value)
            if record:
                record['ts'] = ts
                record['received'] = now
                record['synthetic'] = synthetic
                records.append(record)
    return records


def failure_reason(error):
    """Controlled description of a gRPC/pygnmi failure; never the raw exception text."""
    code = ''
    original = getattr(error, 'orig_exc', None)
    for candidate in (error, original):
        try:
            code = candidate.code().name
            break
        except Exception:
            continue
    text = str(error).lower()
    if code in ('UNAUTHENTICATED', 'PERMISSION_DENIED') or 'authentic' in text or 'permission denied' in text or 'unauthorized' in text:
        return 'auth', 'The NOS refused the gNMI login. The SSH password login is used for gNMI; assign a password profile or a telemetry profile with a NOS account that may use gNMI.'
    if code in ('UNAVAILABLE', 'DEADLINE_EXCEEDED') or 'connect' in text or 'timed out' in text or 'ssl certificate' in text or 'channel' in text:
        return 'connect', 'The gNMI port did not answer. The service may still be starting, the port may differ from the configured one, or TLS may be required.'
    if code in ('INVALID_ARGUMENT', 'UNIMPLEMENTED') or 'encoding' in text or 'unsupported' in text or 'not supported' in text:
        return 'unsupported', 'The NOS rejected the subscription (path or encoding not supported by this image).'
    return 'error', 'The gNMI session failed unexpectedly.'


class NodeCollector(threading.Thread):
    """One thread per node: connect, subscribe per metric group, push records, report state."""
    def __init__(self, key, generation, target, creds, adapter, transport, sink, report, stopping=None):
        super().__init__(daemon=True, name='telemetry-' + key[1])
        self.key = key
        self.generation = generation
        self.target = target              # (address, port)
        self.creds = creds                # {'username', 'password'}
        self.adapter = adapter
        self.transport = transport        # preferred: 'plaintext' or 'tls'
        self.sink = sink                  # queue.Queue of records
        self.report = report              # callable(event: dict)
        self.stopping = stopping or threading.Event()
        self.client = None
        self.streams = {}                 # group -> subscriber
        self.last = {}                    # group -> monotonic time of the last notification
        self.usable = set()               # groups that delivered a chartable record
        self.idle = set()                 # groups reported idle since their last notification
        self.dropped = 0

    def stop(self):
        self.stopping.set()

    def emit(self, **event):
        try: self.report({'key': self.key, 'generation': self.generation, **event})
        except Exception: pass

    def connect(self):
        """Try the preferred transport, then the other one; only a login refusal stops the probe."""
        order = [self.transport] + [t for t in ('plaintext', 'tls') if t != self.transport]
        last = None
        for transport in order:
            if self.stopping.is_set():
                raise RuntimeError('stopped')
            client = gNMIclient(target=self.target, username=self.creds.get('username', ''),
                                password=self.creds.get('password', ''), insecure=transport == 'plaintext',
                                skip_verify=transport == 'tls', gnmi_timeout=CONNECT_TIMEOUT,
                                keepalive_time_ms=30000)
            try:
                client.connect()
                caps = client.capabilities() or {}
                return client, transport, caps
            except Exception as error:
                try: client.close()
                except Exception: pass
                kind, message = failure_reason(error)
                if kind == 'auth':
                    raise
                last = error
        raise last or RuntimeError('unreachable')

    def run(self):
        try:
            self.session()
        except Exception as error:
            kind, message = failure_reason(error)
            if self.stopping.is_set():
                return
            self.emit(event='failed', reason=kind, message=message)
        finally:
            self.close()

    def subscribe(self, group, encodings):
        """Open a stream for a group, trying each path variant and encoding until one syncs."""
        for variant in self.adapter.subscriptions(group):
            for encoding in encodings:
                if self.stopping.is_set():
                    return None
                request = {'mode': 'stream', 'encoding': encoding, 'subscription': [dict(v) for v in variant]}
                subscriber = None
                try:
                    subscriber = self.client.subscribe2(subscribe=request)
                    first = self.first_update(subscriber, FIRST_SAMPLE_TIMEOUT)
                except Exception as error:
                    failure = getattr(subscriber, 'error', None) or error
                    if subscriber is not None:
                        try: subscriber.close()
                        except Exception: pass
                    if failure_reason(failure)[0] == 'auth':
                        raise failure
                    continue
                modes = {v['path'].rsplit('/', 1)[-1]: v.get('mode', 'sample') for v in variant}
                return subscriber, first, modes, encoding
        return None

    @staticmethod
    def first_update(subscriber, timeout):
        """The initial batch (updates until sync_response), failing fast when the NOS rejects the
        subscription instead of waiting the whole first-sample timeout."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if subscriber.error is not None:
                raise subscriber.error
            if not subscriber._subscribe_thread.is_alive():
                raise RuntimeError('closed')
            if subscriber.peek():
                # Devices send the initial updates and the sync marker back to back.
                return subscriber.get_update(timeout=10)
            time.sleep(0.1)
        raise TimeoutError('No update from target')

    def session(self):
        self.emit(event='connecting')
        self.client, transport, caps = self.connect()
        models = caps.get('supported_models', [])
        supported = [e for e in self.adapter.encodings if e in caps.get('supported_encodings', self.adapter.encodings)] or list(self.adapter.encodings)
        self.emit(event='connected', transport=transport, models=len(models), encodings=supported)
        methods = {}
        for group in GROUPS:
            if not self.adapter.models_present(group, models):
                self.emit(event='group', group=group, status='unsupported',
                          message='The node does not advertise the OpenConfig model for this group.')
                continue
            opened = self.subscribe(group, supported)
            if not opened:
                self.emit(event='group', group=group, status='unsupported',
                          message='Every subscription variant was rejected by the NOS.')
                continue
            subscriber, first, modes, encoding = opened
            self.streams[group] = subscriber
            self.last[group] = time.monotonic()
            methods[group] = ('gnmi-on-change' if any(m == 'on_change' for m in modes.values()) else 'gnmi-sample-10s', modes)
            self.emit(event='group', group=group, status='subscribed', message=f'Subscribed ({encoding}).', encoding=encoding)
            self.handle(group, first, methods[group])
        if not self.streams:
            raise RuntimeError('unsupported')
        while not self.stopping.is_set() and self.streams:
            for group, subscriber in list(self.streams.items()):
                try:
                    message = subscriber.get_update(timeout=0.25)
                except TimeoutError:
                    if subscriber.error is not None or (not subscriber._subscribe_thread.is_alive()):
                        reason, text = failure_reason(subscriber.error or RuntimeError('closed'))
                        self.drop_group(group, reason, text)
                    elif group not in self.idle and time.monotonic() - self.last.get(group, 0) > GROUP_IDLE:
                        # A sampled path with nothing behind it (no BGP neighbour configured) sends
                        # nothing at all on EOS; that is not a failure and the stream stays open. A
                        # dead transport surfaces through subscriber.error and gRPC keepalive instead.
                        self.idle.add(group)
                        self.emit(event='group', group=group, status='idle',
                                  message='No notifications for two minutes; the subscription stays open and the node has nothing to report on this path.')
                    continue
                except Exception as error:
                    reason, text = failure_reason(error)
                    self.drop_group(group, reason, text)
                    continue
                self.last[group] = time.monotonic()
                if group in self.idle:
                    self.idle.discard(group)
                    self.emit(event='group', group=group, status='streaming' if group in self.usable else 'subscribed',
                              message='Notifications resumed.')
                self.handle(group, message, methods[group])
        if not self.stopping.is_set():
            raise RuntimeError('closed')

    def drop_group(self, group, reason, text):
        subscriber = self.streams.pop(group, None)
        if subscriber is not None:
            try: subscriber.close()
            except Exception: pass
        status = 'unsupported' if reason == 'unsupported' else 'failed'
        self.emit(event='group', group=group, status=status, message=text)

    def handle(self, group, message, method):
        if not message or 'update' not in message:
            return
        label, modes = method
        now = time.time()
        records = normalize(message, now)
        if not records:
            return
        lab_id, node = self.key
        for record in records:
            record.update(lab_id=lab_id, node=node, generation=self.generation,
                          method='gnmi-on-change' if modes.get(record['metric']) == 'on_change' else 'gnmi-sample-10s')
            try:
                self.sink.put_nowait(record)
            except queue.Full:
                self.dropped += 1
        if group not in self.usable:
            self.usable.add(group)
            self.emit(event='group', group=group, status='streaming', message='Usable samples are arriving.')

    def close(self):
        for subscriber in list(self.streams.values()):
            try: subscriber.close()
            except Exception: pass
        self.streams.clear()
        if self.client is not None:
            try: self.client.close()
            except Exception: pass
            self.client = None
