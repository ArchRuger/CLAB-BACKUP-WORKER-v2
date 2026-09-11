import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from app.store import Store
from app.drawio_export import drawio
from app.topology import parse_drawing
import test_discovery as discovery_tests


class ManagerResetTests(unittest.TestCase):
    setUp = discovery_tests.DiscoveryTests.setUp
    register = discovery_tests.DiscoveryTests.register
    host = discovery_tests.DiscoveryTests.host

    def tearDown(self):
        self.app.state.operations.close()
        discovery_tests.DiscoveryTests.tearDown(self)

    def reset(self, confirmation='RESET'):
        return self.client.post('/api/manager/reset', json={'confirmation': confirmation})

    def test_no_login_and_cross_origin_requests_refused(self):
        self.assertEqual(self.client.get('/api/state').status_code, 200)
        self.assertFalse((self.store.root/'ui.token').exists())
        for headers in ({'Origin':'https://other.example'}, {'Sec-Fetch-Site':'cross-site'}):
            self.assertEqual(self.client.get('/api/state', headers=headers).status_code, 403)
            self.assertEqual(self.client.post('/api/manager/reset', headers=headers, json={'confirmation':'RESET'}).status_code, 403)

    def test_reset_preserves_host_key_and_unknown_files_only(self):
        self.host(); self.register()
        self.store.state['host']['fingerprint']='SHA256:fixture'
        self.store.state['ignored_labs']=['excluded']
        self.store.state['operations']=[{'id':'done','status':'succeeded'}]
        self.store.save()
        host = copy.deepcopy(self.store.state['host']); key = (self.store.root/'state.key').read_bytes()
        backup = self.store.root/'backups'/'lab'/'history'; backup.mkdir(parents=True)
        (backup/'config.txt').write_text('fixture config')
        (self.store.root/'unrelated.txt').write_text('retain')
        self.store.event('old.log','old history')
        self.service.sources['old']={}; self.service.import_previews['old']={}
        self.app.state.node_services.tickets['old']=('unused',)
        self.assertEqual(self.reset('wrong').status_code,400)
        self.assertTrue(backup.exists())
        response=self.reset(); self.assertEqual(response.status_code,200,response.text)
        saved=Store(self.tmp.name)
        for field in ('labs','jobs','operations','ignored_labs'): self.assertEqual(saved.state[field],[])
        self.assertNotEqual(saved.state['host']['revision'],host.pop('revision'))
        for k,v in host.items():self.assertEqual(saved.state['host'][k],v)
        self.assertEqual((saved.root/'state.key').read_bytes(),key)
        self.assertFalse((saved.root/'backups').exists())
        self.assertTrue((saved.root/'unrelated.txt').exists())
        self.assertNotIn('old history',(saved.root/'events.jsonl').read_text())
        self.assertEqual(self.service.sources,{})
        self.assertEqual(self.app.state.node_services.tickets,{})

    def test_busy_guards_and_discovery_lock(self):
        self.register()
        for collection in ('jobs','operations'):
            self.store.state[collection]=[{'status':'running','lab_id':'fixture'}]
            self.assertEqual(self.reset().status_code,409)
            self.store.state[collection]=[]
        self.app.state.node_services.clients.add('fixture')
        self.assertEqual(self.reset().status_code,409)
        self.app.state.node_services.clients.clear()
        self.service.lock.acquire()
        try:self.assertEqual(self.reset().status_code,409)
        finally:self.service.lock.release()
        self.assertEqual(len(self.store.state['labs']),1)

    def test_interrupted_commit_resumes_on_restart(self):
        self.host();self.register()
        root=self.store.root;backup=root/'backups';backup.mkdir();(backup/'config').write_text('old')
        real=self.store.atomic
        def fail_commit(path,content):
            if path==self.store.path:raise OSError('disk fixture')
            real(path,content)
        with patch.object(self.store,'atomic',side_effect=fail_commit):
            self.assertEqual(self.reset().status_code,500)
        self.assertTrue(self.store.reset_pending)
        self.assertEqual(self.client.get('/api/state').status_code,503)
        saved=Store(self.tmp.name)
        self.assertEqual(saved.state['labs'],[])
        self.assertEqual(saved.state['host']['password'],'host-secret')
        self.assertFalse(saved.reset_pending);self.assertFalse(backup.exists())

    def test_clear_exclusion_is_persistent_and_does_not_import(self):
        self.store.state['ignored_labs']=['training','other'];self.store.save()
        response=self.client.post('/api/discovery/forget-exclusion',json={'name':'training'})
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(Store(self.tmp.name).state['ignored_labs'],['other'])
        self.assertEqual(self.store.state['labs'],[])

    def test_cleanup_failure_keeps_journal_until_retry(self):
        self.host();self.register()
        backup=self.store.root/'backups';backup.mkdir();(backup/'old').write_text('old')
        with patch('app.store.shutil.rmtree',side_effect=OSError('cleanup fixture')):
            self.assertEqual(self.reset().status_code,500)
        self.assertTrue((self.store.root/'.reset-pending'/'new-state.enc').exists())
        self.assertEqual(self.store.state['labs'],[])
        self.assertEqual(self.reset().status_code,200)
        self.assertFalse(self.store.reset_pending)
        self.assertEqual(Store(self.tmp.name).state['host']['password'],'host-secret')

    def test_export_current_coordinates_does_not_change_saved_layout(self):
        lab=self.register();saved=copy.deepcopy(self.store.lab(lab['id'])['drawing'])
        ident=saved['nodes'][0]['id']
        url='/api/labs/'+lab['id']+'/drawio'
        response=self.client.post(url,json={'positions':{ident:[900,800]}})
        self.assertEqual(response.status_code,200,response.text)
        self.assertIn("training.drawio",response.headers['content-disposition'])
        node=ET.fromstring(response.content).find('.//mxCell[@id="node-0"]/mxGeometry')
        self.assertEqual(float(node.get('x')),900)
        self.assertEqual(self.store.lab(lab['id'])['drawing'],saved)
        self.assertEqual(self.client.post(url,json={'positions':{ident:[True,0]}}).status_code,400)


class DrawioExportTests(unittest.TestCase):
    def test_full_fixture_preserves_annotations_labels_positions_and_connections(self):
        fixture=Path(__file__).parent/'fixtures'/'map'
        drawing=parse_drawing((fixture/'annotations.json').read_bytes(),(fixture/'topology-data.json').read_bytes())
        root=ET.fromstring(drawio({'name':'Training & learning','drawing':drawing}))
        cells={c.get('id'):c for c in root.findall('.//mxCell')}
        self.assertEqual(len(cells),len(root.findall('.//mxCell')))
        for i,d in enumerate(drawing['decorations']):
            cell=cells[f'annotation-{i}'];self.assertEqual(cell.get('value'),d.get('text',''))
            self.assertEqual(float(cell.find('mxGeometry').get('x')),d['x'])
        for i,n in enumerate(drawing['nodes']):
            c=cells[f'node-{i}'];g=c.find('mxGeometry');x=float(g.get('x'));y=float(g.get('y'))
            if c.get('parent')!='1':
                pg=cells[c.get('parent')].find('mxGeometry');x+=float(pg.get('x'));y+=float(pg.get('y'))
            self.assertAlmostEqual(x,n['x']);self.assertAlmostEqual(y,n['y'])
            self.assertEqual(c.get('value'),n.get('label') or n.get('alias') or n['id'])
        for i,pair in enumerate(drawing['links']):
            c=cells[f'link-{i}'];self.assertIn(c.get('source'),cells);self.assertIn(c.get('target'),cells)
            for j,endpoint in enumerate(pair):self.assertEqual(cells[f'interface-{i}-{j}'].get('value'),endpoint['interface'])

    def test_xml_escapes_text_and_rejects_removed_layouts(self):
        lab={'name':'<unsafe>','drawing':{'nodes':[],'links':[],'decorations':[dict(type='text',x=0,y=0,width=100,height=40,text='<script>&') ]}}
        raw=drawio(lab);self.assertIn(b'&lt;script&gt;&amp;',raw)
        with self.assertRaises(ValueError):drawio(lab,'horizontal')
