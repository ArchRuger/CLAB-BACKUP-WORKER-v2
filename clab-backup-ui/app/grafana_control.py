"""On-demand Grafana: started through the VM helper when someone opens it, stopped when nobody reads it.

Grafana idles at a few hundred MiB, so the telemetry stack leaves it stopped (deploy/setup-telemetry.sh,
restart policy "no" in deploy/compose.telemetry.yml). When a lab's Grafana link (Tools tab) is used the manager
starts the container through the reviewed operations helper (`docker start` of the fixed container
name), waits for Grafana's health endpoint and sends the browser on. A monitor thread then reads
Grafana's own request counters over the loopback and stops the container again after
TELEMETRY_GRAFANA_IDLE_MINUTES without a dashboard request (an open dashboard refreshes every ten
seconds, so it keeps Grafana alive; 0 turns the automatic stop off). Prometheus keeps running: with
its fifteen-minute retention it is small, and it has to scrape while a lab streams.
"""
from datetime import datetime, timezone
import logging
import os
import re
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, build_opener

from fastapi import HTTPException

DEFAULT_IDLE_MINUTES = 15
MAX_IDLE_MINUTES = 1440
POLL = 30              # seconds between health and activity probes while the stack is installed
START_TIMEOUT = 75     # seconds for /api/health after docker start (fresh tmpfs: migrations, provisioning)
GRACE = 90             # seconds after a start during which idleness does not count
COUNTER = 'grafana_http_request_duration_seconds_count'
QUIET = {'/metrics', '/api/health'}   # the manager's own probes and the install check


def idle_minutes(config):
    raw = (config.get('TELEMETRY_GRAFANA_IDLE_MINUTES', '') or '').strip()
    if not re.fullmatch(r'\d{1,4}', raw): return DEFAULT_IDLE_MINUTES
    return min(int(raw), MAX_IDLE_MINUTES)


def activity(text):
    """Requests Grafana served to someone other than the manager: its request counter summed over
    every handler except the health and metrics endpoints. Counters only grow, so a changed value
    means a viewer was there since the last look."""
    total = 0
    for line in text.splitlines():
        if not line.startswith(COUNTER + '{'): continue
        labels, _, value = line.partition('} ')
        handler = re.search(r'handler="([^"]*)"', labels)
        if handler and handler.group(1) in QUIET: continue
        try: total += int(float(value.strip()))
        except ValueError: continue
    return total


def stamp(epoch):
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat() if epoch else None


def minutes(count):
    return f'{count} minute' + ('' if count == 1 else 's')


class GrafanaControl:
    def __init__(self, store, operations, telemetry, environ=None, opener=None):
        config = os.environ if environ is None else environ
        self.store = store
        self.operations = operations
        self.enabled = bool(telemetry.grafana['enabled'])
        self.port = telemetry.grafana['port']
        self.idle = idle_minutes(config)
        self.opener = opener or build_opener(ProxyHandler({}))
        self.lock = threading.Lock()
        self.running = None          # unknown until the first probe
        self.checked = 0.0
        self.started_at = None       # epoch of the start this manager saw (or first saw it running)
        self.last_activity = None    # epoch of the last counter change
        self.requests = None         # last counter value
        self.retry_after = 0.0       # no repeated helper calls while a stop keeps failing
        self.error = ''
        self.stopping = threading.Event()
        self.wake = threading.Event()
        self.thread = None

    # ---- probes over the loopback (no SSH) --------------------------------------------
    def fetch(self, path, timeout=3):
        with self.opener.open(f'http://127.0.0.1:{self.port}{path}', timeout=timeout) as response:
            return response.read(1 << 20).decode('utf-8', 'replace')

    def probe(self):
        try: return '"database":"ok"' in self.fetch('/api/health').replace(' ', '')
        except (HTTPError, URLError, OSError, ValueError): return False

    def activity(self):
        try: return activity(self.fetch('/metrics'))
        except (HTTPError, URLError, OSError, ValueError): return None

    # ---- the reviewed helper on the VM --------------------------------------------------
    def helper(self, action):
        try: return self.operations.invoke({'mode': 'grafana', 'action': action})
        except HTTPException as exc:
            detail = str(exc.detail)
            if 'Unknown request mode' in detail:
                detail = ('The VM operations helper predates on-demand Grafana. Run sudo bash deploy/start-manager.sh '
                          'on the VM from this source, then retry.')
            raise HTTPException(409, detail)

    # ---- API -------------------------------------------------------------------------
    def message(self):
        if not self.enabled: return 'The Grafana stack is not installed on this manager.'
        if self.running is None: return 'Grafana has not been checked yet.'
        if not self.running: return 'Grafana is stopped; it starts when you open it from a lab.'
        if not self.idle: return 'Grafana is running; the automatic stop is off (TELEMETRY_GRAFANA_IDLE_MINUTES=0).'
        return f'Grafana is running; it stops after {minutes(self.idle)} without an open dashboard.'

    def status(self):
        with self.lock:
            return {'enabled': self.enabled, 'port': self.port, 'running': self.running, 'idle_minutes': self.idle,
                    'started_at': stamp(self.started_at), 'last_activity': stamp(self.last_activity),
                    'checked_at': stamp(self.checked), 'error': self.error, 'message': self.message()}

    def start(self):
        if not self.enabled:
            raise HTTPException(409, 'The Grafana stack is not installed on this manager. Run sudo bash deploy/setup-telemetry.sh on the VM.')
        if self.probe():
            self.observe(True)
            return self.status()
        result = self.helper('start')
        if result.get('state') == 'missing':
            raise HTTPException(409, 'The Grafana container does not exist on the VM. Run sudo bash deploy/setup-telemetry.sh there.')
        deadline = time.monotonic() + START_TIMEOUT
        while not self.probe():
            if time.monotonic() > deadline or self.stopping.is_set():
                raise HTTPException(409, f'Grafana was started but did not answer within {START_TIMEOUT} s. Inspect it on the VM: '
                                         'sudo docker logs --tail=80 clab-manager-grafana')
            time.sleep(1)
        # The counter baseline is taken now, so the viewer's first page load already counts as activity.
        baseline = self.activity()
        now = time.time()
        with self.lock:
            self.running = True; self.checked = now; self.started_at = now; self.last_activity = now
            self.requests = baseline; self.error = ''
        self.store.event('grafana.start', 'Grafana started on the VM for a viewer; ' + (
            f'it stops after {minutes(self.idle)} without an open dashboard' if self.idle else 'the automatic stop is off'))
        return self.status()

    def stop(self, reason='request'):
        if not self.enabled:
            raise HTTPException(409, 'The Grafana stack is not installed on this manager.')
        self.helper('stop')
        with self.lock:
            self.running = False; self.checked = time.time(); self.started_at = None
            self.requests = None; self.error = ''
        self.store.event('grafana.stop', 'Grafana stopped on the VM ' + (
            f'after {minutes(self.idle)} without an open dashboard' if reason == 'idle' else 'on request'))
        return self.status()

    # ---- the monitor ------------------------------------------------------------------
    def observe(self, running=None):
        """One pass: health, then the request counter; stop after the idle time without a viewer."""
        running = self.probe() if running is None else running
        now = time.time()
        with self.lock:
            was = self.running
            self.running = running; self.checked = now
            if not running:
                self.started_at = None; self.requests = None
                return
            if was is not True:
                # Found running: a manager restart, or someone started it by hand on the VM.
                self.started_at = self.started_at or now
                self.last_activity = self.last_activity or now
        count = self.activity()
        with self.lock:
            if count is not None and count != self.requests:
                self.requests = count; self.last_activity = now
            idle = (self.idle and self.last_activity is not None and now - self.last_activity > self.idle * 60
                    and now - (self.started_at or now) > GRACE and now >= self.retry_after)
        if idle:
            try: self.stop('idle')
            except HTTPException as exc:
                with self.lock:
                    self.error = str(exc.detail); self.retry_after = now + 300
                logging.getLogger(__name__).warning('Grafana idle stop failed: %s', exc.detail)

    def loop(self):
        while not self.stopping.is_set():
            if self.enabled:
                try: self.observe()
                except Exception:
                    logging.getLogger(__name__).warning('Grafana monitor pass failed; retrying on the next pass.')
            self.wake.wait(POLL); self.wake.clear()

    def run(self):
        self.thread = threading.Thread(target=self.loop, daemon=True)
        self.thread.start()

    def close(self):
        self.stopping.set(); self.wake.set()
        if self.thread: self.thread.join(timeout=2)

    def install(self, app):
        @app.get('/api/telemetry/grafana')
        def grafana_status():
            return self.status()

        @app.post('/api/telemetry/grafana/start')
        def grafana_start():
            return self.start()

        @app.post('/api/telemetry/grafana/stop')
        def grafana_stop():
            return self.stop()
