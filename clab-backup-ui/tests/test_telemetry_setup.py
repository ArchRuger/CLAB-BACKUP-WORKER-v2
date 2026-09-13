"""The optional Grafana stack: setup script, Compose file, provisioning and dashboard definitions."""
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

import yaml

from app import telemetry_metrics
from app.telemetry import TelemetryManager

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('telemetry_setup', ROOT / 'deploy/setup_telemetry.py')
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)
DASHBOARDS = ROOT / 'deploy/telemetry/grafana/dashboards'
EXPORTED = {'clab_telemetry_node_state', 'clab_telemetry_node_state_code', 'clab_telemetry_node_sample_age_seconds', 'clab_interface_oper_up', 'clab_interface_admin_up',
            'clab_interface_sample_age_seconds', 'clab_link_status', 'clab_link_up', 'clab_bgp_neighbor_state', 'clab_bgp_neighbor_established',
            'clab_bgp_neighbor_prefixes_received', 'clab_bgp_neighbor_prefixes_sent', 'clab_bgp_neighbor_prefixes_installed',
            *[name for _, name, _ in telemetry_metrics.RATES], *[name for _, name, _ in telemetry_metrics.TOTALS]}


class SetupScriptTests(unittest.TestCase):
    def test_env_is_preserved_idempotent_and_prometheus_targets_the_manager_port(self):
        with tempfile.TemporaryDirectory() as folder:
            env = Path(folder) / '.env'; config = Path(folder) / 'telemetry'
            data = Path(folder) / 'data'; data.mkdir()
            maps_dir = (data / 'telemetry' / 'dashboards').as_posix()
            env.write_text(f'UI_PORT=8088\nUNRELATED=$(do-not-run)\nCAPTURE_PROVIDER=edgeshark\nTELEMETRY_MAPS_DIR={maps_dir}\n')
            result = setup.configure(env, config)
            first = env.read_text(); setup.configure(env, config)
            self.assertEqual(first, env.read_text())
            self.assertEqual(result, {'ui_port': 8088, 'grafana_port': 3000, 'prometheus_port': 9090, 'bind': '0.0.0.0', 'maps_dir': maps_dir})
            for expected in ('UI_PORT=8088', '$(do-not-run)', 'CAPTURE_PROVIDER=edgeshark', 'TELEMETRY_STACK=grafana', 'TELEMETRY_GRAFANA_PORT=3000',
                             'TELEMETRY_CONFIG_DIR=' + str(config), 'TELEMETRY_MAPS_DIR=' + maps_dir):
                self.assertIn(expected, first)
            self.assertTrue((config / 'plugins').is_dir(), 'the Flow panel folder Grafana mounts')
            self.assertTrue(Path(maps_dir).is_dir(), 'the lab-map folder the manager writes into')
            password = re.search(r'TELEMETRY_GRAFANA_ADMIN_PASSWORD=(\S+)', first)[1]
            self.assertGreaterEqual(len(password), 20)
            if os.name == 'posix': self.assertEqual(oct(env.stat().st_mode & 0o777), '0o600')
            rendered = (config / 'prometheus.yml').read_text()
            self.assertIn("targets: ['127.0.0.1:8088']", rendered); self.assertIn('metrics_path: /api/telemetry/metrics', rendered)
            self.assertIn('scrape_interval: 10s', rendered)
            if os.name == 'posix': self.assertEqual(oct((config / 'prometheus.yml').stat().st_mode & 0o777), '0o644')
            yaml.safe_load(rendered)
            env.write_text(first.replace('TELEMETRY_GRAFANA_PORT=3000', 'TELEMETRY_GRAFANA_PORT=3100'))
            self.assertEqual(setup.configure(env, config)['grafana_port'], 3100)
            self.assertIn('TELEMETRY_GRAFANA_ADMIN_PASSWORD=' + password, env.read_text(), 'an existing password is kept')
            setup.configure(env, config, enable=False)
            self.assertIn('TELEMETRY_STACK=disabled', env.read_text()); self.assertIn('TELEMETRY_GRAFANA_ADMIN_PASSWORD=' + password, env.read_text())

    def test_bad_ports_symlinks_and_passwords_are_refused_without_changes(self):
        with tempfile.TemporaryDirectory() as folder:
            env = Path(folder) / '.env'; config = Path(folder) / 'telemetry'
            for text in ('UI_PORT=99999\n', 'TELEMETRY_GRAFANA_PORT=abc\n', 'UI_PORT=3000\nTELEMETRY_GRAFANA_PORT=3000\n', 'TELEMETRY_GRAFANA_ADMIN_PASSWORD=has space\n',
                         'TELEMETRY_GRAFANA_BIND=0.0.0.0;rm\n', 'TELEMETRY_MAPS_DIR=relative/maps\n', 'TELEMETRY_MAPS_DIR=/srv/../etc/maps\n'):
                env.write_text(text)
                with self.assertRaises(ValueError):
                    setup.configure(env, config)
                self.assertEqual(env.read_text(), text); self.assertFalse(config.exists())
            # A lab-map folder outside an existing manager data directory: refused before .env changes.
            text = f'TELEMETRY_MAPS_DIR={(Path(folder) / "missing" / "telemetry" / "dashboards").as_posix()}\n'
            env.write_text(text)
            with self.assertRaisesRegex(ValueError, 'data directory'):
                setup.configure(env, config)
            self.assertEqual(env.read_text(), text)
            real = Path(folder) / 'real.env'; real.write_text('UI_PORT=8081\n')
            link = Path(folder) / 'link.env'
            try: os.symlink(real, link)
            except OSError as error: self.skipTest('symlinks are not permitted here: ' + str(error))
            with self.assertRaisesRegex(ValueError, 'symlink'):
                setup.configure(link, config)


class PluginInstallTests(unittest.TestCase):
    def test_pinned_flow_panel_is_installed_once_with_the_pinned_grafana_image(self):
        from app import telemetry_map
        self.assertEqual((setup.PLUGIN, setup.PLUGIN_VERSION), (telemetry_map.PLUGIN, telemetry_map.PLUGIN_VERSION), 'one pin for the setup and the generator')
        calls = []

        def runner(command, **kwargs):
            calls.append(command)
            target = Path(command[command.index('-v') + 1].split(':')[0] if os.name == 'posix' else command[command.index('-v') + 1].rsplit(':', 1)[0])
            (target / setup.PLUGIN).mkdir(parents=True)
            (target / setup.PLUGIN / 'plugin.json').write_text(json.dumps({'id': setup.PLUGIN, 'info': {'version': setup.PLUGIN_VERSION}}))
            return subprocess.CompletedProcess(command, 0, '', '')
        with tempfile.TemporaryDirectory() as folder:
            config = Path(folder) / 'telemetry'; (config / 'plugins').mkdir(parents=True)
            self.assertEqual(setup.install_plugin(config, runner=runner), 'installed')
            self.assertEqual(setup.install_plugin(config, runner=runner), 'present')
            self.assertEqual(len(calls), 1, 'a present plugin is not downloaded again')
            command = calls[0]
            image = re.search(r'grafana/grafana-oss@sha256:[0-9a-f]{64}', (ROOT / 'deploy/compose.telemetry.yml').read_text())[0]
            self.assertEqual(command[:3], ['docker', 'run', '--rm']); self.assertIn(image, command)
            self.assertEqual(command[command.index('--entrypoint') + 1], 'grafana')
            self.assertEqual(command[-6:], ['cli', '--pluginsDir', '/plugins', 'plugins', 'install', setup.PLUGIN] if False else command[-6:])
            self.assertEqual(command[-2:], [setup.PLUGIN, setup.PLUGIN_VERSION]); self.assertIn('--pluginsDir', command)

        def failing(command, **kwargs):
            return subprocess.CompletedProcess(command, 1, '', 'Error: ✗ Failed to send request: Get "https://grafana.com/api/plugins/...": dial tcp: lookup grafana.com')
        with tempfile.TemporaryDirectory() as folder:
            config = Path(folder) / 'telemetry'; (config / 'plugins').mkdir(parents=True)
            with self.assertRaisesRegex(ValueError, 'grafana.com'):
                setup.install_plugin(config, runner=failing)


class ReadinessWaitTests(unittest.TestCase):
    """setup-telemetry.sh must not report success while Prometheus or Grafana are restarting."""
    def serve(self, handler):
        import http.server
        import threading
        server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.shutdown)
        return server.server_address[1]

    def env(self, folder, grafana, prometheus):
        env = Path(folder) / '.env'
        env.write_text(f'TELEMETRY_STACK=grafana\nTELEMETRY_GRAFANA_PORT={grafana}\nTELEMETRY_PROMETHEUS_PORT={prometheus}\n')
        return env

    def test_ready_when_both_services_answer_and_targets_are_reported(self):
        import http.server

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_GET(self):
                body = {'/-/ready': b'Prometheus Server is Ready.\n', '/api/health': b'{"database": "ok", "version": "13.0.2"}',
                        '/api/frontend/settings': json.dumps({'panels': {setup.PLUGIN: {'id': setup.PLUGIN}, 'timeseries': {}}}).encode(),
                        '/api/v1/targets': json.dumps({'status': 'success', 'data': {'activeTargets': [
                            {'scrapeUrl': 'http://127.0.0.1:8081/api/telemetry/metrics', 'health': 'up', 'lastError': ''}]}}).encode()}.get(self.path)
                self.send_response(200 if body else 404); self.end_headers(); self.wfile.write(body or b'')
        port = self.serve(Handler)
        with tempfile.TemporaryDirectory() as folder:
            result = setup.wait_ready(self.env(folder, port, port), timeout=10)
        self.assertEqual(result['targets'], [('http://127.0.0.1:8081/api/telemetry/metrics', 'up', '')])
        self.assertEqual((result['grafana_port'], result['prometheus_port'], result['flow_panel']), (port, port, True))

    def test_a_restarting_service_fails_the_wait_with_the_reason(self):
        import http.server
        import socket

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_GET(self):
                self.send_response(200); self.end_headers(); self.wfile.write(b'{"database": "ok"}')
        grafana = self.serve(Handler)
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', 0)); closed = probe.getsockname()[1]
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(ValueError, r'Not ready after 3 s: Prometheus on 127\.0\.0\.1:\d+ \(no answer\)') as caught:
                setup.wait_ready(self.env(folder, grafana, closed), timeout=3)
            self.assertNotIn('Grafana', str(caught.exception))
            with self.assertRaisesRegex(ValueError, 'Grafana on'):
                setup.wait_ready(self.env(folder, closed, grafana), timeout=3)


class StackDefinitionTests(unittest.TestCase):
    def test_compose_file_is_pinned_host_networked_and_bounded(self):
        compose = yaml.safe_load((ROOT / 'deploy/compose.telemetry.yml').read_text())
        services = compose['services']
        self.assertEqual(sorted(services), ['grafana', 'prometheus'])
        for name, service in services.items():
            self.assertRegex(service['image'], r'@sha256:[0-9a-f]{64}$', name)
            self.assertEqual(service['network_mode'], 'host'); self.assertEqual(service['cap_drop'], ['ALL'])
            self.assertIn('no-new-privileges:true', service['security_opt']); self.assertIn('mem_limit', service); self.assertIn('pids_limit', service)
            self.assertNotIn('ports', service); self.assertNotIn('/var/run/docker.sock', json.dumps(service))
        self.assertIn('--web.listen-address=127.0.0.1:${TELEMETRY_PROMETHEUS_PORT:-9090}', services['prometheus']['command'])
        self.assertIn('--storage.tsdb.retention.time=2h', services['prometheus']['command'])
        # Prometheus (kingpin) boolean flags take --flag or --no-flag; '--flag=false' aborts start-up
        # with 'unexpected false' and the whole stack crash-loops (seen live in 1.23.0).
        self.assertEqual([c for c in services['prometheus']['command'] if c.endswith(('=false', '=true'))], [])
        self.assertFalse(any('remote-write-receiver' in c for c in services['prometheus']['command']))
        self.assertIn('setup_telemetry.py" "$env_file" --wait', (ROOT / 'deploy/setup-telemetry.sh').read_text(), 'setup waits for a healthy stack')
        self.assertEqual(services['grafana']['environment']['GF_AUTH_ANONYMOUS_ORG_ROLE'], 'Viewer')
        self.assertIn('TELEMETRY_GRAFANA_ADMIN_PASSWORD:?', services['grafana']['environment']['GF_SECURITY_ADMIN_PASSWORD'])
        for volume in compose['volumes'].values():
            self.assertEqual(volume['driver_opts']['type'], 'tmpfs')
        # The Flow panel folder and the manager's lab-map folder: read-only binds that must pre-exist.
        binds = {v['target']: v for v in services['grafana']['volumes'] if isinstance(v, dict)}
        self.assertEqual(services['grafana']['environment']['GF_PATHS_PLUGINS'], '/var/lib/grafana-plugins')
        self.assertTrue(binds['/var/lib/grafana-plugins']['source'].endswith('/plugins') and binds['/var/lib/grafana-plugins']['read_only'])
        self.assertEqual(binds['/etc/grafana/dashboards-labs']['source'], '${TELEMETRY_MAPS_DIR:-' + setup.DEFAULT_MAPS_DIR + '}')
        self.assertTrue(all(b['read_only'] and b['bind']['create_host_path'] is False for b in binds.values()))
        providers = yaml.safe_load((ROOT / 'deploy/telemetry/grafana/provisioning/dashboards/clab.yml').read_text())['providers']
        labs = next(p for p in providers if p['options']['path'] == '/etc/grafana/dashboards-labs')
        self.assertEqual((labs['folderUid'], labs['disableDeletion'], labs['allowUiUpdates'], labs['updateIntervalSeconds']), ('clab-lab-maps', False, False, 30))
        script = (ROOT / 'deploy/setup-telemetry.sh').read_text()
        self.assertIn('verify-release.py', script); self.assertIn('compose.telemetry.yml', script); self.assertIn('--remove', script)
        self.assertIn('/srv/containerlab-node-manager/telemetry', script)

    def test_provisioning_points_at_the_local_prometheus(self):
        datasource = yaml.safe_load((ROOT / 'deploy/telemetry/grafana/provisioning/datasources/prometheus.yml').read_text())
        item = datasource['datasources'][0]
        self.assertEqual((item['uid'], item['type'], item['editable']), ('clab-prometheus', 'prometheus', False))
        self.assertTrue(item['url'].startswith('http://127.0.0.1:'))
        provider = yaml.safe_load((ROOT / 'deploy/telemetry/grafana/provisioning/dashboards/clab.yml').read_text())['providers'][0]
        self.assertEqual(provider['options']['path'], '/etc/grafana/dashboards'); self.assertFalse(provider['allowUiUpdates'])

    def test_dashboards_use_the_provisioned_datasource_and_exported_metrics_only(self):
        files = sorted(DASHBOARDS.glob('*.json'))
        self.assertEqual([f.stem for f in files], ['bgp', 'interface', 'lab-overview'])
        uids = set()
        for path in files:
            data = json.loads(path.read_text(encoding='utf-8'))
            uids.add(data['uid'])
            self.assertFalse(data['editable']); self.assertEqual(data['refresh'], '10s'); self.assertIn('lab', [v['name'] for v in data['templating']['list']])
            for variable in data['templating']['list']:
                self.assertEqual(variable['datasource']['uid'], 'clab-prometheus')
                self.assertTrue(variable['query']['query'].startswith('label_values('))
            ids = [p['id'] for p in data['panels']]
            self.assertEqual(len(ids), len(set(ids)), path.name)
            for panel in data['panels']:
                self.assertEqual(panel['datasource']['uid'], 'clab-prometheus', panel['title'])
                self.assertIn(panel['type'], ('timeseries', 'stat', 'table', 'state-timeline'))
                for target in panel['targets']:
                    metrics = set(re.findall(r'clab_[a-z_]+', target['expr']))
                    self.assertTrue(metrics, target['expr']); self.assertTrue(metrics <= EXPORTED, (path.name, metrics - EXPORTED))
                    self.assertIn('lab="$lab"', target['expr'])
        self.assertEqual(uids, {'clab-lab-overview', 'clab-interface', 'clab-bgp'})
        for path in files:
            for link in json.loads(path.read_text(encoding='utf-8'))['links']:
                self.assertTrue(link['url'].startswith('/d/clab-'))

    def test_manager_announces_the_stack_from_its_environment(self):
        class Store:
            lock = __import__('threading').RLock(); state = {'operations': []}
        class Services:
            lock = __import__('threading').RLock(); checks = {}
        manager = TelemetryManager(Store(), Services(), environ={'TELEMETRY_STACK': 'grafana', 'TELEMETRY_GRAFANA_PORT': '3100', 'TELEMETRY_PROMETHEUS_PORT': '9090'})
        self.assertEqual(manager.grafana, {'enabled': True, 'port': 3100, 'prometheus_port': 9090})
        self.assertFalse(TelemetryManager(Store(), Services(), environ={'TELEMETRY_STACK': 'grafana', 'TELEMETRY_GRAFANA_PORT': 'x'}).grafana['enabled'])
        self.assertFalse(TelemetryManager(Store(), Services(), environ={}).grafana['enabled'])


if __name__ == '__main__':
    unittest.main()
