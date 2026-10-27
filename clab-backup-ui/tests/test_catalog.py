import json
import re
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app

JS = Path(__file__).resolve().parents[1] / 'app' / 'static' / 'lab-builder-page.js'


def js_templates():
    text = JS.read_text()
    block = re.search(r'const BUILDER_TEMPLATES=\[\n(.*?)\n\];', text, re.S).group(1)
    out = []
    for line in block.splitlines():
        line = line.strip().rstrip(',')
        if not line:
            continue
        line = line.replace("'", '"')
        line = re.sub(r'([{,])(name|kind|image|pinned|env|match|baseName|interfacePattern|icon|CPTX_AUTO_CONFIG):', r'\1"\2":', line)
        out.append(json.loads(line))
    return out


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.app = create_app(self.tmp.name)
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)
        resp = self.client.get('/api/catalog')
        self.assertEqual(resp.status_code, 200)
        self.body = resp.json()
        self.by = {e['kind']: e for e in self.body['entries']}

    def test_seven_entries_and_composition(self):
        self.assertEqual(len(self.body['entries']), 7)
        self.assertEqual(self.body['kinds'], [e['kind'] for e in self.body['entries']])
        self.assertTrue(hasattr(self.app.state, 'catalog'))

    def test_vsrx(self):
        e = self.by['juniper_vsrx']
        self.assertTrue(e['login_default'])
        # design True since B05 phase 1 (exact netlab `vsrx` profile, generated_not_live_tested); restore True since B04 phase 1 (the Junos
        # driver proven live on the exact image, evidence/b04-vsrx-*); the console stays gated until its own proof through the manager.
        self.assertEqual(e['capabilities'], {'backup': True, 'restore': True, 'design': True, 'console': False})
        self.assertEqual(e['aliases'], ['vr-vsrx', 'vsrx'])
        self.assertEqual(e['interfaces']['first_port'], 'ge-0/0/0')
        self.assertNotIn('(?i)', e['interfaces']['container_pattern'])
        self.assertNotIn('(?i)', e['interfaces']['pattern'])
        rx = re.compile(e['interfaces']['pattern'], re.I)
        self.assertTrue(rx.match('GE-0/0/3'))

    def test_first_data_port_follows_the_offset(self):
        # NOS port N is eth(N + offset) and eth0 is management: the first data port is max(0, 1 - offset).
        self.assertEqual(self.by['juniper_vjunosswitch']['interfaces']['first_port'], 'ge-0/0/0')   # offset 1
        self.assertEqual(self.by['juniper_cjunosevolved']['interfaces']['first_port'], 'et-0/0/0')  # offset 4
        self.assertEqual(self.by['arista_ceos']['interfaces']['first_port'], 'Ethernet1')           # offset 0: eth1

    def test_reserved(self):
        self.assertEqual(self.by['juniper_cjunosevolved']['interfaces']['reserved'], ['eth1', 'eth2', 'eth3'])
        self.assertEqual(self.by['arista_ceos']['interfaces']['reserved'], [])

    def test_linux(self):
        e = self.by['linux']
        self.assertIsNone(e['interfaces'])
        self.assertFalse(any(e['capabilities'].values()))
        self.assertEqual(e['label'], 'Linux host')

    def test_no_secret(self):
        text = json.dumps(self.body).lower()
        self.assertNotIn('password', text)
        self.assertNotIn('admin', text)
        self.assertNotIn('clab@123', text)

    def test_js_fallback_equals_catalog(self):
        templates = js_templates()
        self.assertEqual(len(templates), 7)
        for t in templates:
            e = self.by[t['kind']]
            self.assertEqual(t['image'], e['image'])
            tpl = e['template']
            for field in ('name', 'baseName', 'interfacePattern', 'icon', 'match'):
                self.assertEqual(t[field], tpl[field], (t['kind'], field))
            self.assertEqual(bool(t.get('pinned', False)), tpl['pinned'], t['kind'])
            self.assertEqual(t.get('env'), tpl.get('env'), t['kind'])


if __name__ == '__main__':
    unittest.main()
