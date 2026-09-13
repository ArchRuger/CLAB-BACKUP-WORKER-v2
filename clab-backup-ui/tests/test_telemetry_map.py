"""The Grafana lab map: SVG, Flow panel cells and the provisioned dashboard generated per lab."""
import json
import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock
import xml.etree.ElementTree as ET

from fastapi.testclient import TestClient

from app import telemetry_map as maps
from app.main import create_app
from app.telemetry_metrics import STATE_CODES

SVG = '{http://www.w3.org/2000/svg}'


def lab(**overrides):
    base = dict(id='a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6', name='ceos-pair', nodes=[
        dict(name='clab-ceos-pair-ceos1', short_name='ceos1', platform='arista_ceos'),
        dict(name='clab-ceos-pair-ceos2', short_name='ceos2', platform='arista_ceos'),
        dict(name='clab-ceos-pair-xr1', short_name='xr1', platform='cisco_xrv9k')])
    base.update(overrides)
    return base


def node(ident, x, y, inventory, **extra):
    base = dict(id=ident, alias=ident, label=ident, x=x, y=y, icon='router', iconColor='#0066ff', labelPosition='bottom',
                direction='up', iconCornerRadius=4, inventory_name=inventory)
    base.update(extra)
    return base


def drawing(**overrides):
    base = dict(schema=3, revision='r1', settings={'labelMode': 'show-all', 'endpointOffset': 20},
                nodes=[node('ceos1', 100, 100, 'clab-ceos-pair-ceos1'), node('ceos2', 400, 100, 'clab-ceos-pair-ceos2', icon='switch'),
                       node('xr1', 250, 300, 'clab-ceos-pair-xr1'), node('host', 400, 300, None, icon='server')],
                links=[[{'node': 'ceos1', 'interface': 'eth1'}, {'node': 'ceos2', 'interface': 'eth1'}],
                       [{'node': 'ceos2', 'interface': 'eth2'}, {'node': 'xr1', 'interface': 'eth1'}],
                       [{'node': 'xr1', 'interface': 'eth2'}, {'node': 'host', 'interface': 'eth1'}]],
                decorations=[dict(type='group', x=50, y=40, width=450, height=160, text='Fabric', fillColor='#e5e7eb', fillOpacity=.3,
                                  borderColor='#78909c', borderWidth=1, borderStyle='dashed', cornerRadius=8, color='#607d8b',
                                  labelPosition='top-left', fontSize=12, zIndex=-1)])
    base.update(overrides)
    return base


class RenderTests(unittest.TestCase):
    def test_svg_is_well_formed_with_one_element_per_cell(self):
        rendered = maps.render(drawing(), lab())
        root = ET.fromstring(rendered['svg'])
        by_id = {e.get('id'): e for e in root.iter() if e.get('id')}
        self.assertEqual(set(by_id), {'cell-' + c for c in rendered['cells']}, 'every cell has exactly one SVG element and nothing else carries an id')
        self.assertEqual({e.tag for i, e in by_id.items() if i.startswith('cell-link:')}, {SVG + 'path'})
        self.assertEqual({e.tag for i, e in by_id.items() if i.startswith(('cell-port:', 'cell-node:'))}, {SVG + 'circle'})
        rate = by_id['cell-rate:ceos1:eth1']
        self.assertEqual((rate.tag, len(list(rate)), rate.text), (SVG + 'text', 0, '↑'), 'a leaf holding one text node: the plugin appends the value')
        self.assertIn('flow', by_id['cell-link:ceos1:eth1'].get('class'))
        style = root.find(SVG + 'style').text
        self.assertIn('@keyframes clab-flow', style); self.assertIn('animation-duration:0s', style)
        self.assertEqual(root.find(SVG + 'rect').get('fill'), maps.CANVAS, 'the canvas colour makes the map theme independent')
        texts = [e.text for e in root.iter(SVG + 'text')]
        self.assertIn('eth1', texts); self.assertIn('Fabric', texts); self.assertIn('host', texts)
        x, y, w, h = rendered['bounds']
        self.assertTrue(w >= 320 and h >= 200 and x < 100 and y < 40)
        # The unmatched host and its link stay static: no cells bind to nodes the inventory does not know.
        self.assertFalse(any(':host' in c or 'xr1:eth2' in c for c in rendered['cells']))

    def test_cells_bind_to_exported_series_with_nos_interface_names(self):
        cells = maps.render(drawing(), lab())['cells']
        # A half-link shows what its node sends, measured as the far end's receive rate.
        self.assertEqual(cells['link:ceos1:eth1']['dataRef'], 'ceos2:Ethernet1:in')
        self.assertEqual(cells['link:ceos2:eth1']['dataRef'], 'ceos1:Ethernet1:in')
        self.assertEqual(cells['link:ceos2:eth2']['dataRef'], 'xr1:GigabitEthernet0/0/0/0:in', 'interface names follow the kind mapping')
        self.assertEqual(cells['link:xr1:eth1']['dataRef'], 'ceos2:Ethernet2:in')
        self.assertEqual(cells['rate:ceos1:eth1'], {'label': {'dataRef': 'ceos2:Ethernet1:in', 'units': 'bps', 'decimalPoints': 1, 'separator': 'space'}})
        self.assertEqual(cells['port:ceos1:eth1']['dataRef'], 'oper:ceos1:Ethernet1')
        self.assertEqual(cells['node:ceos1']['dataRef'], 'state:ceos1')
        self.assertEqual([t['level'] for t in cells['link:ceos1:eth1']['strokeColor']['thresholds']], [0, 10000, 500000, 1000000, 5000000])
        self.assertEqual(cells['link:ceos1:eth1']['flowAnimation'], dict(maps.FLOW))
        self.assertEqual({t['level'] for t in cells['node:ceos1']['fillColor']['thresholds']}, set(STATE_CODES.values()) | {-1})
        self.assertEqual([t['level'] for t in cells['port:ceos1:eth1']['fillColor']['thresholds']], [0, 1])
        hidden = maps.render(drawing(settings={'labelMode': 'hide'}), lab())
        self.assertNotIn('>eth1<', hidden['svg']); self.assertIn('cell-rate:ceos1:eth1', hidden['svg'], 'hidden interface labels keep the rate labels')

    def test_dashboard_is_provisionable_and_only_queries_series_the_cells_use(self):
        data = maps.dashboard(lab(name='de"mo\\'), drawing())
        self.assertEqual(data['uid'], 'clab-map-a1b2c3d4e5f6a7b8c9d0e1f2'); self.assertLessEqual(len(data['uid']), 40)
        self.assertFalse(data['editable']); self.assertEqual(data['refresh'], '10s'); self.assertEqual(data['templating']['list'], [])
        panel = data['panels'][0]
        self.assertEqual(panel['type'], maps.PLUGIN)
        self.assertTrue(10 <= panel['gridPos']['h'] <= 40 and panel['gridPos']['w'] == 24)
        for key in ('svg', 'panelConfig', 'siteConfig', 'animationsEnabled', 'panZoomEnabled', 'timeSliderEnabled', 'testDataEnabled'):
            self.assertIn(key, panel['options'])
        config = json.loads(panel['options']['panelConfig'])          # YAML is a superset of JSON
        self.assertEqual((config['cellIdPreamble'], config['datapoint'], config['background']['darkThemeColor']), ('cell-', 'lastNotNull', maps.CANVAS))
        legends = {t['legendFormat'] for t in panel['targets']}
        self.assertEqual(legends, {'{{node}}:{{interface}}:in', 'oper:{{node}}:{{interface}}', 'state:{{node}}'})
        for expr in (t['expr'] for t in panel['targets']):
            self.assertIn('{lab="de\\"mo\\\\"}', expr, 'the lab name is a quoted PromQL string')
        patterns = [re.compile(p) for p in (r'^[^:]+:[^:]+:in$', r'^oper:[^:]+:[^:]+$', r'^state:[^:]+$')]
        for cell in config['cells'].values():
            for ref in (cell.get('dataRef'), cell.get('label', {}).get('dataRef')):
                if ref: self.assertTrue(any(p.match(ref) for p in patterns), ref)
        self.assertTrue(all(link['url'].startswith('/d/clab-') and 'var-lab=de%22mo%5C' in link['url'] for link in data['links']))
        text = maps.dashboard_json(lab(), drawing())
        self.assertEqual(text, maps.dashboard_json(lab(), drawing()), 'deterministic output for change detection')
        self.assertEqual(maps.map_uid('weird id/with:chars!' * 3)[:9], 'clab-map-'); self.assertLessEqual(len(maps.map_uid('x' * 100)), 40)

    def test_signature_follows_the_drawing_the_name_and_the_nodes(self):
        base = maps.signature(lab(), drawing())
        self.assertEqual(base, maps.signature(lab(), drawing()))
        self.assertNotEqual(base, maps.signature(lab(name='other'), drawing()))
        self.assertNotEqual(base, maps.signature(lab(), drawing(revision='r2')))
        moved = lab(); moved['nodes'][0]['platform'] = 'cisco_xrv9k'
        self.assertNotEqual(base, maps.signature(moved, drawing()))


class PublisherTests(unittest.TestCase):
    def test_reconcile_writes_updates_and_removes_only_its_own_files(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / 'telemetry' / 'dashboards'
            publisher = maps.MapPublisher(target, True)
            first, second = lab(), lab(id='ffffffffffffffffffffffffffffffff', name='second')
            publisher.reconcile([(first, drawing()), (second, drawing()), (lab(id='nodrawing'), None)])
            files = sorted(p.name for p in target.glob('*.json'))
            self.assertEqual(files, ['clab-map-a1b2c3d4e5f6a7b8c9d0e1f2.json', 'clab-map-ffffffffffffffffffffffff.json'])
            path = target / files[0]
            self.assertEqual(path.read_text(encoding='utf-8'), maps.dashboard_json(first, drawing()))
            if os.name == 'posix': self.assertEqual(oct(path.stat().st_mode & 0o777), '0o644')
            self.assertEqual(publisher.writes, 2)
            publisher.reconcile([(first, drawing()), (second, drawing())])
            self.assertEqual(publisher.writes, 2, 'unchanged labs are not rewritten')
            (target / 'other.json').write_text('{}')
            publisher.reconcile([(lab(name='renamed'), drawing()), (second, drawing())])
            self.assertEqual(publisher.writes, 3); self.assertIn('renamed', path.read_text(encoding='utf-8'))
            publisher.reconcile([(second, drawing())])
            self.assertFalse(path.exists()); self.assertTrue((target / 'other.json').exists(), 'foreign files are left alone')
            self.assertEqual((publisher.removals, publisher.stats()['dashboards']), (1, 1))
            disabled = maps.MapPublisher(target, False)
            disabled.reconcile([(second, drawing())])
            self.assertEqual(sorted(p.name for p in target.glob('*.json')), ['other.json'], 'a disabled stack removes the generated maps')
            fresh = maps.MapPublisher(Path(folder) / 'never', False)
            fresh.reconcile([(second, drawing())])
            self.assertFalse((Path(folder) / 'never').exists())
            maps.MapPublisher(None, True).reconcile([(second, drawing())])

    def test_write_problems_are_reported_not_raised(self):
        with tempfile.TemporaryDirectory() as folder:
            blocker = Path(folder) / 'file'; blocker.write_text('x')
            publisher = maps.MapPublisher(blocker / 'dashboards', True)
            publisher.reconcile([(lab(), drawing())])
            self.assertIn('not writable', publisher.error); self.assertEqual(publisher.stats()['error'], publisher.error)


class ManagerTests(unittest.TestCase):
    def app(self, stack):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        with mock.patch.dict(os.environ, {'TELEMETRY_STACK': stack, 'TELEMETRY_GRAFANA_PORT': '3000'}):
            app = create_app(tmp.name)
        store = app.state.store
        drawn = dict(lab(), deployment_name='ceos-pair', container_prefix='clab', profiles=[], defaults={}, interval=0, next_run=None,
                     telemetry={'auto': True, 'decided': True, 'profile_id': '', 'applied': {}})
        for n in drawn['nodes']:
            n.update(definition_node=n['short_name'], address='172.20.20.2', port=22, enabled=True, profile_id='', username='', password='',
                     enable_password='', groups=[], endpoint_mode='auto', discovered=True, runtime_state='running', discovered_address='172.20.20.2')
        raw = drawing()
        for n in raw['nodes']: n.pop('inventory_name')          # bind_drawing resolves inventory names from aliases
        drawn['drawing'] = raw
        store.state['labs'].append(drawn)
        store.state['labs'].append(dict(id='blank', name='blank', deployment_name='', nodes=[], profiles=[], defaults={}, interval=0, next_run=None))
        store.save()
        return app, TestClient(app), Path(tmp.name)

    def test_manager_publishes_maps_and_serves_previews_when_the_stack_is_on(self):
        app, client, root = self.app('grafana')
        manager = app.state.telemetry
        manager.publish_maps(app.state.store.snapshot())
        path = root / 'telemetry' / 'dashboards' / 'clab-map-a1b2c3d4e5f6a7b8c9d0e1f2.json'
        self.assertTrue(path.is_file())
        self.assertEqual(json.loads(path.read_text(encoding='utf-8'))['panels'][0]['type'], maps.PLUGIN)
        view = client.get('/api/labs/a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6/telemetry').json()
        self.assertEqual(view['grafana']['map_uid'], 'clab-map-a1b2c3d4e5f6a7b8c9d0e1f2')
        self.assertEqual(client.get('/api/labs/blank/telemetry').json()['grafana']['map_uid'], '', 'no drawing, no map')
        svg = client.get('/api/labs/a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6/telemetry/map.svg')
        self.assertEqual((svg.status_code, svg.headers['content-type']), (200, 'image/svg+xml'))
        self.assertIn('cell-link:ceos1:eth1', svg.text); self.assertIn('cell-node:xr1', svg.text)
        config = json.loads(client.get('/api/labs/a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6/telemetry/map.yml').text)
        self.assertEqual(config['cells']['link:ceos1:eth1']['dataRef'], 'ceos2:Ethernet1:in')
        self.assertEqual(client.get('/api/labs/a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6/telemetry/map.json').json()['uid'], 'clab-map-a1b2c3d4e5f6a7b8c9d0e1f2')
        self.assertEqual(client.get('/api/labs/blank/telemetry/map.svg').status_code, 404)
        self.assertEqual(client.get('/api/labs/nope/telemetry/map.svg').status_code, 404)
        health = client.get('/api/telemetry/health').json()['maps']
        self.assertEqual((health['enabled'], health['dashboards'], health['error'], health['plugin']), (True, 1, '', maps.PLUGIN))
        with app.state.store.lock:
            app.state.store.state['labs'] = [l for l in app.state.store.state['labs'] if l['id'] == 'blank']; app.state.store.save()
        manager.publish_maps(app.state.store.snapshot())
        self.assertFalse(path.exists(), 'a removed lab loses its map')

    def test_nothing_is_written_while_the_stack_is_off(self):
        app, client, root = self.app('disabled')
        app.state.telemetry.publish_maps(app.state.store.snapshot())
        self.assertFalse((root / 'telemetry').exists())
        self.assertEqual(client.get('/api/labs/a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6/telemetry').json()['grafana']['map_uid'], '')
        self.assertEqual(client.get('/api/labs/a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6/telemetry/map.svg').status_code, 200, 'previews work without the stack')


if __name__ == '__main__':
    unittest.main()
