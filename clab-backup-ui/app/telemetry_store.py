"""Session-only telemetry buffers.

Everything here lives in process memory: a bounded ring per interface and per BGP
neighbour, a bounded number of interfaces and neighbours per node and of nodes per
manager. Nothing is written to the encrypted state, the backups, Git or the data
directory, so a manager restart starts empty and a browser refresh changes nothing.

Rates are derived from counter deltas over the elapsed device time. A counter that
goes backwards (device restart, interface re-creation) is recorded as a reset and
produces no rate; the first sample of a series and a sample that follows a long gap
produce no rate either, so a chart never shows a negative value or a giant spike.
Out-of-order samples are ignored. A record whose generation is not the generation
the store currently accepts for that node (an earlier deployment of the same lab and
node name, possibly with the same address) is dropped and counted.
"""
from collections import deque
import threading
import time

INTERVAL = 10                   # counter sample spacing the collector asks for, seconds
WINDOW = 3600                   # seconds of history kept per series
POINTS = WINDOW // INTERVAL + 40  # ring size per series; bursts of on-change updates cannot grow it
MAX_INTERFACES = 96             # per node
MAX_PEERS = 64                  # per node
MAX_NODES = 512                 # per manager
MAX_GAP = 300                   # seconds; a longer gap between counter samples restarts the rate
MIN_GAP = 0.5                   # seconds; closer samples are merged into the previous point
STALE_AFTER = 45                # seconds without a sample marks a node or series stale
COUNTERS = {'in-octets': 'rx_bps', 'out-octets': 'tx_bps', 'in-pkts': 'rx_pps', 'out-pkts': 'tx_pps',
            'in-errors': 'rx_errors', 'out-errors': 'tx_errors',
            'in-discards': 'rx_discards', 'out-discards': 'tx_discards'}
RATE_FIELDS = ('rx_bps', 'tx_bps', 'rx_pps', 'tx_pps', 'rx_errors', 'tx_errors', 'rx_discards', 'tx_discards')
BITS = {'rx_bps', 'tx_bps'}
STATES = ('oper-status', 'admin-status')
WINDOWS = (300, 900, 3600)


def _number(value):
    """Counters arrive as ints (proto) or as decimal strings (JSON_IETF uint64)."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _enum(value):
    """'UP', 'openconfig-bgp-types:ESTABLISHED' and 'up' all normalise to the bare upper-case token."""
    if not isinstance(value, str):
        return ''
    return value.rsplit(':', 1)[-1].strip().upper()[:32]


class Series:
    """One interface: latest snapshot plus a bounded ring of rate points."""
    __slots__ = ('name', 'points', 'last', 'latest', 'resets', 'method', 'at')

    def __init__(self, name):
        self.name = name
        self.points = deque(maxlen=POINTS)   # dicts: t plus the RATE_FIELDS that were computable
        self.last = {}                       # counter leaf -> (t, value) of the previous sample
        self.latest = {}                     # counter leaf -> value; plus oper/admin status
        self.resets = 0
        self.method = ''
        self.at = 0.0

    def counter(self, leaf, value, t):
        """Record a counter sample; return (field, rate) or None when no rate is derivable."""
        field = COUNTERS[leaf]
        previous = self.last.get(leaf)
        self.last[leaf] = (t, value)
        self.latest[leaf] = value
        if previous is None:
            return None
        elapsed = t - previous[0]
        if elapsed <= 0 or elapsed > MAX_GAP:
            return None
        if value < previous[1]:
            self.resets += 1
            return None
        rate = (value - previous[1]) / elapsed
        return field, rate * 8 if field in BITS else rate

    def point(self, t):
        """The ring point for time t: the previous one when t is within MIN_GAP, else a new one."""
        if self.points and abs(self.points[-1]['t'] - t) < MIN_GAP:
            return self.points[-1]
        if self.points and t < self.points[-1]['t']:
            return None
        item = {'t': t}
        self.points.append(item)
        return item


class PeerSeries:
    __slots__ = ('peer', 'instance', 'points', 'latest', 'at', 'method')

    def __init__(self, peer, instance):
        self.peer = peer
        self.instance = instance
        self.points = deque(maxlen=POINTS)   # dicts: t, received, sent
        self.latest = {}                     # state, afi, received, sent
        self.at = 0.0
        self.method = ''


class NodeBuffers:
    __slots__ = ('generation', 'interfaces', 'peers', 'last_sample', 'samples', 'dropped', 'overflow', 'started')

    def __init__(self, generation):
        self.generation = generation
        self.interfaces = {}
        self.peers = {}
        self.last_sample = 0.0
        self.samples = 0
        self.dropped = 0        # records of another generation or out of order
        self.overflow = 0       # interfaces or peers beyond the per-node bounds
        self.started = time.time()


class TelemetryStore:
    def __init__(self):
        self.lock = threading.Lock()
        self.nodes = {}     # (lab id, node name) -> NodeBuffers
        self.rejected = 0   # records for nodes the store does not track

    # ---- lifecycle -------------------------------------------------------
    def begin(self, lab_id, node, generation):
        """Start (or restart) the buffers of a node for a deployment generation."""
        with self.lock:
            key = (lab_id, node)
            if key not in self.nodes and len(self.nodes) >= MAX_NODES:
                return False
            self.nodes[key] = NodeBuffers(generation)
            return True

    def generation(self, lab_id, node):
        with self.lock:
            item = self.nodes.get((lab_id, node))
            return item.generation if item else None

    def clear_node(self, lab_id, node):
        with self.lock:
            self.nodes.pop((lab_id, node), None)

    def clear_lab(self, lab_id):
        with self.lock:
            for key in [k for k in self.nodes if k[0] == lab_id]:
                self.nodes.pop(key, None)

    def clear_all(self):
        with self.lock:
            self.nodes.clear()

    # ---- ingestion -------------------------------------------------------
    def ingest(self, record):
        """Apply one normalised record. Returns True when it changed a series."""
        with self.lock:
            item = self.nodes.get((record.get('lab_id'), record.get('node')))
            if item is None:
                self.rejected += 1
                return False
            if record.get('generation') != item.generation:
                item.dropped += 1
                return False
            t = record.get('ts')
            if not isinstance(t, (int, float)) or t <= 0:
                item.dropped += 1
                return False
            kind = record.get('kind')
            if kind == 'interface':
                changed = self._interface(item, record, float(t))
            elif kind == 'bgp':
                changed = self._peer(item, record, float(t))
            else:
                item.dropped += 1
                return False
            if changed:
                item.samples += 1
                item.last_sample = max(item.last_sample, float(t))
            return changed

    def _interface(self, item, record, t):
        name = record.get('ident')
        if not isinstance(name, str) or not name or len(name) > 64:
            item.dropped += 1
            return False
        series = item.interfaces.get(name)
        if series is None:
            if len(item.interfaces) >= MAX_INTERFACES:
                item.overflow += 1
                return False
            series = item.interfaces[name] = Series(name)
        metric = record.get('metric')
        value = record.get('value')
        series.method = record.get('method') or series.method
        if metric in COUNTERS:
            number = _number(value)
            if number is None:
                return False
            if t + MIN_GAP < series.at:
                item.dropped += 1
                return False
            result = series.counter(metric, number, t)
            series.at = max(series.at, t)
            # A point exists for every counter sample, so a reset or a gap reads as
            # "no rate" rather than as the previous rate lingering in the chart.
            point = series.point(t)
            if result and point is not None:
                point[result[0]] = result[1]
            return True
        if metric in STATES:
            text = _enum(value)
            if not text:
                return False
            if t + MIN_GAP < series.at:
                item.dropped += 1
                return False
            series.latest[metric] = text
            series.at = max(series.at, t)
            return True
        return False

    def _peer(self, item, record, t):
        peer = record.get('ident')
        instance = record.get('instance') or 'default'
        if not isinstance(peer, str) or not peer or len(peer) > 64 or len(str(instance)) > 64:
            item.dropped += 1
            return False
        key = (str(instance), peer)
        series = item.peers.get(key)
        if series is None:
            if len(item.peers) >= MAX_PEERS:
                item.overflow += 1
                return False
            series = item.peers[key] = PeerSeries(peer, str(instance))
        metric = record.get('metric')
        value = record.get('value')
        series.method = record.get('method') or series.method
        if metric == 'session-state':
            text = _enum(value)
            if not text:
                return False
            series.latest['state'] = text
            series.at = max(series.at, t)
            return True
        if metric in ('received', 'sent', 'installed'):
            number = _number(value)
            if number is None:
                return False
            afi = record.get('afi')
            if afi and (not series.latest.get('afi') or series.latest.get('afi') == afi):
                series.latest['afi'] = str(afi)[:32]
            elif afi and series.latest.get('afi') != afi:
                return False   # one address family per neighbour chart; the first seen wins
            series.latest[metric] = number
            series.at = max(series.at, t)
            if series.points and abs(series.points[-1]['t'] - t) < MIN_GAP:
                series.points[-1][metric] = number
            elif not series.points or t >= series.points[-1]['t']:
                series.points.append({'t': t, metric: number})
            return True
        return False

    # ---- reads -----------------------------------------------------------
    def _expire(self, item, now):
        cutoff = now - WINDOW
        for series in list(item.interfaces.values()) + list(item.peers.values()):
            while series.points and series.points[0]['t'] < cutoff:
                series.points.popleft()

    def snapshot(self, lab_id, node, now=None):
        """Latest values per interface and neighbour, with freshness. Bounded by the node limits."""
        now = time.time() if now is None else now
        with self.lock:
            item = self.nodes.get((lab_id, node))
            if item is None:
                return None
            self._expire(item, now)
            interfaces = []
            for series in item.interfaces.values():
                latest = series.points[-1] if series.points else {}
                row = {'name': series.name, 'oper': series.latest.get('oper-status', ''),
                       'admin': series.latest.get('admin-status', ''),
                       'at': series.at, 'fresh': now - series.at <= STALE_AFTER, 'method': series.method,
                       'resets': series.resets, 'totals': {k: v for k, v in series.latest.items() if k in COUNTERS}}
                for field in RATE_FIELDS:
                    row[field] = latest.get(field) if now - latest.get('t', 0) <= STALE_AFTER else None
                interfaces.append(row)
            peers = []
            for series in item.peers.values():
                peers.append({'peer': series.peer, 'instance': series.instance, 'state': series.latest.get('state', ''),
                              'afi': series.latest.get('afi', ''), 'received': series.latest.get('received'),
                              'sent': series.latest.get('sent'), 'installed': series.latest.get('installed'),
                              'at': series.at, 'fresh': now - series.at <= STALE_AFTER, 'method': series.method})
            return {'generation': item.generation, 'last_sample': item.last_sample,
                    'fresh': bool(item.last_sample) and now - item.last_sample <= STALE_AFTER,
                    'samples': item.samples, 'dropped': item.dropped, 'overflow': item.overflow,
                    'interfaces': sorted(interfaces, key=lambda r: r['name']),
                    'peers': sorted(peers, key=lambda r: (r['instance'], r['peer']))}

    def series(self, lab_id, node, interface, window, now=None):
        """Rate points of one interface within the window, oldest first (at most POINTS)."""
        now = time.time() if now is None else now
        window = window if window in WINDOWS else WINDOWS[0]
        with self.lock:
            item = self.nodes.get((lab_id, node))
            if item is None or interface not in item.interfaces:
                return None
            self._expire(item, now)
            cutoff = now - window
            return [dict(p) for p in item.interfaces[interface].points if p['t'] >= cutoff]

    def peer_series(self, lab_id, node, instance, peer, window, now=None):
        now = time.time() if now is None else now
        window = window if window in WINDOWS else WINDOWS[0]
        with self.lock:
            item = self.nodes.get((lab_id, node))
            if item is None or (instance, peer) not in item.peers:
                return None
            self._expire(item, now)
            cutoff = now - window
            return [dict(p) for p in item.peers[(instance, peer)].points if p['t'] >= cutoff]

    def stats(self):
        with self.lock:
            return {'nodes': len(self.nodes),
                    'series': sum(len(i.interfaces) + len(i.peers) for i in self.nodes.values()),
                    'points': sum(sum(len(s.points) for s in list(i.interfaces.values()) + list(i.peers.values()))
                                  for i in self.nodes.values()),
                    'dropped': sum(i.dropped for i in self.nodes.values()), 'rejected': self.rejected,
                    'bounds': {'points_per_series': POINTS, 'interfaces_per_node': MAX_INTERFACES,
                               'peers_per_node': MAX_PEERS, 'nodes': MAX_NODES, 'window_seconds': WINDOW}}
