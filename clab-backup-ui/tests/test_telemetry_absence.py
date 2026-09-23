import sys
from pathlib import Path
import unittest

import test_discovery as discovery_tests
import test_vm_files as vm_tests

INVENTORY = b'''all:
  hosts:
    clab-example-r1:
      ansible_host: 172.20.20.5
      ansible_user: clab
      ansible_password: test-secret
'''


class TelemetryAbsenceTests(unittest.TestCase):
    """The telemetry and Grafana feature is removed from the backend: no module, no
    route, no persisted field, no dependency, no frontend reference survives it."""
    setUp = discovery_tests.DiscoveryTests.setUp
    tearDown = discovery_tests.DiscoveryTests.tearDown
    register = discovery_tests.DiscoveryTests.register
    host = discovery_tests.DiscoveryTests.host
    poll = vm_tests.VMFilesTests.poll
    confirm_import = vm_tests.VMFilesTests.confirm_import

    def test_no_telemetry_or_grafana_module_or_pygnmi_is_loaded(self):
        # app.telemetry_retirement is the intentional migration shim main.py imports; every
        # other app.telemetry* / app.grafana_control module must be absent from sys.modules.
        self.assertFalse(any(name == 'pygnmi' or name.startswith('pygnmi.') for name in sys.modules),
                         'pygnmi must not be importable by the running app')
        self.assertFalse(any(name == 'app.grafana_control' or (name.startswith('app.telemetry') and name != 'app.telemetry_retirement')
                             for name in sys.modules),
                         'no app.telemetry* / app.grafana_control module may be loaded')

    def test_telemetry_and_grafana_routes_answer_404(self):
        for path in ('/api/telemetry/health', '/api/telemetry/metrics', '/api/telemetry/grafana'):
            self.assertEqual(self.client.get(path, headers=self.auth).status_code, 404, path)
        lab = self.register()
        for path in (f'/api/labs/{lab["id"]}/telemetry', f'/api/labs/{lab["id"]}/telemetry/map.svg'):
            self.assertEqual(self.client.get(path, headers=self.auth).status_code, 404, path)
        settings = self.client.post(f'/api/labs/{lab["id"]}/telemetry/settings', headers=self.auth, json={})
        self.assertEqual(settings.status_code, 404, settings.text)

    def test_inventory_import_carries_no_telemetry_key(self):
        r = self.client.post('/api/inventory', headers=self.auth, data={'name': 'Example lab', 'lab_id': ''},
                             files={'inventory': ('ansible-inventory.yml', INVENTORY)})
        self.assertEqual(r.status_code, 200, r.text)
        lab = r.json()
        self.assertNotIn('telemetry', lab)
        stored = self.store.lab(lab['id'])
        self.assertNotIn('telemetry', stored)

    def test_discovery_registered_lab_carries_no_telemetry_key(self):
        lab = self.register()
        self.assertNotIn('telemetry', lab)
        stored = self.store.lab(lab['id'])
        self.assertNotIn('telemetry', stored)

    def test_vm_import_lab_carries_no_telemetry_key(self):
        self.host(); self.poll()
        lab = self.store.state['labs'][0]
        self.assertNotIn('telemetry', lab)

    def test_state_labs_and_nodes_carry_no_telemetry_field(self):
        lab = self.register()
        state = self.client.get('/api/state', headers=self.auth).json()
        found = next(l for l in state['labs'] if l['id'] == lab['id'])
        self.assertNotIn('telemetry', found)
        for node in found['nodes']:
            self.assertNotIn('telemetry', node)

    def test_index_html_carries_no_telemetry_or_grafana_reference(self):
        html = (Path(__file__).parent.parent / 'app' / 'static' / 'index.html').read_text()
        # Exact ids: the migration notice's own menu item is id="menu-telemetry-retired" and must stay.
        markers = ('id="menu-telemetry"', 'id="grafana-open"', 'id="tools-telemetry-settings"', 'id="telemetry-line"',
                   'id="i-telemetry"', 'grafana.js')
        present = [marker for marker in markers if marker in html]
        self.assertEqual(present, [], 'app/static/index.html still references telemetry/Grafana UI')
        self.assertIn('id="menu-telemetry-retired"', html, 'the retirement notice keeps its Advanced options entry')

    def test_requirements_has_no_pygnmi(self):
        requirements = (Path(__file__).parent.parent / 'requirements.txt').read_text()
        self.assertNotIn('pygnmi', requirements)

    def test_no_telemetry_or_grafana_control_module_file_exists(self):
        # telemetry_retirement.py is the intentional migration shim that replaces the
        # removed feature; every other app/telemetry*.py and app/grafana_control.py is gone.
        app_dir = Path(__file__).parent.parent / 'app'
        leftover = sorted(p.name for p in app_dir.glob('telemetry*.py') if p.name != 'telemetry_retirement.py')
        if (app_dir / 'grafana_control.py').exists(): leftover.append('grafana_control.py')
        self.assertEqual(leftover, [])


if __name__ == '__main__': unittest.main()
