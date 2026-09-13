"""Live acceptance of the optional Grafana dashboards on an otherwise empty Docker host (CI).

Starts Prometheus and Grafana exactly as deploy/setup-telemetry.sh does (setup_telemetry.py
plus compose.telemetry.yml) against a stand-in manager that serves the real metrics
exposition for a fixture lab on the configured UI port, waits for both services the way the
setup script does, and proves what an operator sees: Prometheus scrapes the target, Grafana's
provisioned data source reaches Prometheus, the three dashboards are provisioned read-only,
every template variable and panel query parses and answers on Prometheus, and an anonymous
viewer can run a query through Grafana. It then removes its own resources. Standard library
only; never run it against a production stack (it refuses an existing clab-manager-telemetry
project).
"""
import base64
import http.server
import importlib.util
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import tempfile
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import ProxyHandler, Request, build_opener

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'clab-backup-ui'))
from app.telemetry_metrics import render  # noqa: E402

spec = importlib.util.spec_from_file_location('telemetry_setup', ROOT / 'deploy/setup_telemetry.py')
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)

COMPOSE = ROOT / 'deploy/compose.telemetry.yml'
DASHBOARDS = ROOT / 'deploy/telemetry/grafana/dashboards'
PROJECT = 'clab-manager-telemetry'
LAB = 'smoke-lab'
UIDS = ('clab-lab-overview', 'clab-interface', 'clab-bgp')
OPENER = build_opener(ProxyHandler({}))


def command(*args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def free_port():
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        return probe.getsockname()[1]


def fetch(url, data=None, auth=None, timeout=15):
    """(status, parsed JSON or text) without raising on HTTP errors."""
    request = Request(url, data=None if data is None else json.dumps(data).encode())
    if data is not None:
        request.add_header('Content-Type', 'application/json')
    if auth:
        request.add_header('Authorization', 'Basic ' + base64.b64encode(auth.encode()).decode())
    try:
        with OPENER.open(request, timeout=timeout) as response:
            body = response.read(4 << 20)
            status = response.status
    except HTTPError as error:
        body = error.read(4 << 20)
        status = error.code
    try:
        return status, json.loads(body.decode('utf-8', 'replace'))
    except ValueError:
        return status, body.decode('utf-8', 'replace')


def eventually(callback, seconds=120, what='readiness'):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            result = callback()
            if result:
                return result
        except (URLError, OSError, ValueError, KeyError, TypeError, StopIteration, AssertionError):
            pass
        time.sleep(2)
    raise AssertionError('Telemetry smoke timed out waiting for ' + what)


def fixture_view():
    """A streaming two-node lab with one wired link and one BGP neighbour, in lab_view() shape."""
    now = time.time()

    def node(name, short, peer, neighbour):
        return {'name': name, 'short_name': short, 'platform': 'arista_ceos', 'state': 'streaming', 'last_sample': now - 2,
                'interfaces': [{'name': 'Ethernet1', 'oper': 'UP', 'admin': 'UP', 'at': now - 2, 'fresh': True, 'rx_bps': 8000.0, 'tx_bps': 4000.0,
                                'rx_pps': 10.0, 'tx_pps': 5.0, 'totals': {'in-errors': 0, 'out-errors': 0, 'in-discards': 0, 'out-discards': 1,
                                                                            'in-octets': 123456, 'out-octets': 65432},
                                'peer': peer, 'peer_interface': 'eth1', 'role': 'physical'},
                               {'name': 'Management0', 'oper': 'UP', 'admin': 'UP', 'at': now - 2, 'fresh': True, 'rx_bps': 100.0, 'tx_bps': 50.0,
                                'rx_pps': 1.0, 'tx_pps': 0.5, 'totals': {'in-errors': 0, 'out-errors': 0, 'in-octets': 10, 'out-octets': 5},
                                'peer': '', 'peer_interface': '', 'role': 'management'}],
                'peers': [{'peer': neighbour, 'instance': 'default', 'afi': 'IPV4_UNICAST', 'state': 'ESTABLISHED',
                           'received': 3, 'sent': 2, 'installed': 3, 'fresh': True}]}
    return {'lab_id': 'smoke', 'lab_name': LAB,
            'nodes': [node('clab-smoke-lab-r1', 'r1', 'r2', '10.0.0.2'), node('clab-smoke-lab-r2', 'r2', 'r1', '10.0.0.1')],
            'links': [{'status': 'up', 'mismatch': False, 'ends': [{'label': 'r1', 'interface': 'eth1'}, {'label': 'r2', 'interface': 'eth1'}]}]}


class Manager(http.server.BaseHTTPRequestHandler):
    """The only thing Prometheus needs from the manager: /api/telemetry/metrics."""
    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path != '/api/telemetry/metrics':
            self.send_response(404)
            self.end_headers()
            return
        body = render([fixture_view()], time.time()).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'text/plain; version=0.0.4; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def substitute(expr):
    return expr.replace('$lab', LAB).replace('$node', '.*').replace('$interface', '.*')


def check_promql(prometheus, path):
    """Every variable and panel query of one dashboard file parses and answers on Prometheus."""
    data = json.loads(path.read_text(encoding='utf-8'))
    for variable in data['templating']['list']:
        match = re.fullmatch(r'label_values\((.+),\s*(\w+)\)', variable['query']['query'])
        assert match, (path.name, variable['name'])
        status, answer = fetch(f'{prometheus}/api/v1/label/{match[2]}/values?' + urlencode({'match[]': substitute(match[1])}))
        assert status == 200 and answer.get('status') == 'success', (path.name, variable['name'], status, answer)
        if variable['name'] == 'lab':
            assert LAB in answer['data'], (path.name, answer)
    checked = 0
    for panel in data['panels']:
        for target in panel['targets']:
            query = substitute(target['expr'])
            status, answer = fetch(f'{prometheus}/api/v1/query?' + urlencode({'query': query}))
            assert status == 200 and answer.get('status') == 'success', (path.name, panel['title'], query, status, answer)
            if target.get('instant'):
                assert answer['data']['result'], (path.name, panel['title'], 'instant query answered nothing for the fixture lab')
            checked += 1
    return checked


def main():
    existing = command('docker', 'ps', '-aq', '--filter', 'label=com.docker.compose.project=' + PROJECT,
                       capture_output=True, text=True).stdout.strip()
    if existing:
        sys.exit('Refusing to touch an existing telemetry dashboards stack. Run on an isolated Docker host.')
    ui_port, grafana_port, prometheus_port = free_port(), free_port(), free_port()
    folder = Path(tempfile.mkdtemp(prefix='clab-telemetry-smoke-'))
    # Prometheus runs as nobody and reads the rendered scrape configuration through a bind mount.
    os.chmod(folder, 0o755)
    env_file = folder / '.env'
    env_file.write_text(f'UI_PORT={ui_port}\nUNRELATED=kept\nTELEMETRY_GRAFANA_PORT={grafana_port}\n'
                        f'TELEMETRY_PROMETHEUS_PORT={prometheus_port}\nTELEMETRY_GRAFANA_BIND=127.0.0.1\n')
    config_dir = folder / 'telemetry'
    result = setup.configure(env_file, config_dir)
    assert result == {'ui_port': ui_port, 'grafana_port': grafana_port, 'prometheus_port': prometheus_port, 'bind': '127.0.0.1'}, result
    assert 'UNRELATED=kept' in env_file.read_text(encoding='utf-8')
    password = re.search(r'^TELEMETRY_GRAFANA_ADMIN_PASSWORD=(\S+)$', env_file.read_text(encoding='utf-8'), re.M)[1]
    server = http.server.ThreadingHTTPServer(('127.0.0.1', ui_port), Manager)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    compose = ['docker', 'compose', '--env-file', str(env_file), '-f', str(COMPOSE)]
    prometheus = f'http://127.0.0.1:{prometheus_port}'
    grafana = f'http://127.0.0.1:{grafana_port}'
    admin = 'admin:' + password
    try:
        command(*compose, 'pull', '--quiet')
        command(*compose, 'up', '-d', '--force-recreate', '--remove-orphans')
        # The same gate deploy/setup-telemetry.sh applies before it reports success.
        ready = setup.wait_ready(env_file, timeout=120)
        assert ready['prometheus_port'] == prometheus_port, ready

        def scraping():
            status, answer = fetch(prometheus + '/api/v1/targets')
            targets = answer['data']['activeTargets']
            return status == 200 and any(t['health'] == 'up' and t['scrapeUrl'].endswith(f':{ui_port}/api/telemetry/metrics') for t in targets)
        eventually(scraping, what='Prometheus to scrape the manager target')

        def stored():
            status, answer = fetch(prometheus + '/api/v1/query?' + urlencode({'query': f'clab_telemetry_node_state{{lab="{LAB}"}}'}))
            return status == 200 and len(answer['data']['result']) == 2
        eventually(stored, what='the fixture series to be stored')

        status, source = fetch(grafana + '/api/datasources/uid/clab-prometheus', auth=admin)
        assert status == 200 and source['type'] == 'prometheus' and source['url'] == prometheus, (status, source)
        status, health = fetch(grafana + '/api/datasources/uid/clab-prometheus/health', auth=admin)
        assert status == 200 and health.get('status') == 'OK', (status, health)
        for uid in UIDS:
            status, dashboard = fetch(grafana + '/api/dashboards/uid/' + uid)      # anonymous viewer
            assert status == 200 and dashboard['meta']['provisioned'] and not dashboard['meta']['canEdit'], (uid, status, dashboard.get('meta'))
            assert dashboard['dashboard']['uid'] == uid and dashboard['dashboard']['panels'], uid
        checked = sum(check_promql(prometheus, path) for path in sorted(DASHBOARDS.glob('*.json')))
        assert checked >= 20, checked
        status, streaming = fetch(prometheus + '/api/v1/query?' + urlencode({'query': f'count(clab_telemetry_node_state{{lab="{LAB}", state="streaming"}}) or vector(0)'}))
        assert status == 200 and streaming['data']['result'][0]['value'][1] == '2', streaming
        # What a browser does on the Lab overview page: an anonymous query through Grafana's proxy.
        status, answer = fetch(grafana + '/api/ds/query', data={'from': 'now-5m', 'to': 'now', 'queries': [
            {'refId': 'A', 'datasource': {'type': 'prometheus', 'uid': 'clab-prometheus'}, 'expr': f'clab_link_status{{lab="{LAB}"}}',
             'instant': True, 'range': False, 'format': 'table', 'intervalMs': 10000, 'maxDataPoints': 100}]})
        assert status == 200 and answer['results']['A'].get('frames'), (status, answer)
        assert not answer['results']['A'].get('error'), answer
        # An anonymous viewer cannot change anything.
        status, _ = fetch(grafana + '/api/datasources', data={'name': 'x', 'type': 'prometheus'})
        assert status in (401, 403), status
        print(f'PASS: Prometheus scrapes the manager exposition, Grafana provisioned the data source and {len(UIDS)} read-only dashboards, '
              f'{checked} panel queries and every template variable answer, anonymous viewer queries work.')
    finally:
        server.shutdown()
        command(*compose, 'down', '--volumes', '--remove-orphans')


if __name__ == '__main__':
    main()
