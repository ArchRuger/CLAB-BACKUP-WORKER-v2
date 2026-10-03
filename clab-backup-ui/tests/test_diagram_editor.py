import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from app.layout import decorations, annotations
from app.store import Store
from app.topology import parse_drawing
import test_discovery as discovery_tests


class DiagramEditorTests(unittest.TestCase):
    setUp=discovery_tests.DiscoveryTests.setUp
    register=discovery_tests.DiscoveryTests.register

    def tearDown(self):
        self.app.state.operations.close()
        discovery_tests.DiscoveryTests.tearDown(self)

    def prepare(self):
        self.lab=self.register();self.url='/api/labs/'+self.lab['id']
        return self.client.get(self.url+'/topology').json()

    def test_annotations_persist_and_export_without_changing_wiring(self):
        drawing=self.prepare();original=copy.deepcopy(self.store.lab(self.lab['id'])['drawing'])
        items=[{'type':'text','x':5,'y':10,'text':'<b>Training</b>\nNotes'},
               {'type':'rectangle','x':10,'y':20,'width':300,'height':200,'text':'Site A'},
               {'type':'circle','x':50,'y':20,'fillColor':'#79e8f6'},
               {'type':'line','x':10,'y':15,'x2':40,'y2':60}]
        payload={'decorations':items,'revision':drawing['revision']}
        with patch('app.lab_operations.remote') as remote:
            r=self.client.put(self.url+'/layout',json=payload)
            self.assertEqual(r.status_code,200,r.text);remote.assert_not_called()
        saved=Store(self.tmp.name).lab(self.lab['id'])['drawing']
        self.assertEqual(saved['decorations'],decorations(items))
        self.assertEqual(saved['nodes'],original['nodes']);self.assertEqual(saved['links'],original['links'])
        self.assertTrue(saved['placed'],'a layout saved by a person is never replaced by the VM annotations')
        response=self.client.post(self.url+'/drawio',json={})
        xml=ET.fromstring(response.content)
        self.assertEqual(xml.find('.//mxCell[@id="annotation-0"]').get('value'),'<b>Training</b>\nNotes')
        self.assertIn(b'&lt;b&gt;',response.content)
        data=self.client.post(self.url+'/annotations',json={})
        self.assertEqual(data.status_code,200)
        self.assertIn('.annotations.json',data.headers['content-disposition'])
        roundtrip=parse_drawing(data.content,discovery_tests.YAML)
        self.assertEqual(len(roundtrip['decorations']),4)
        self.assertEqual(len(roundtrip['links']),len(original['links']))
        self.assertIn('<b>Training</b>\nNotes',[d['text'] for d in roundtrip['decorations']])

    def test_corner_label_positions_reach_the_drawio_export(self):
        # Item 6 of UI/UX changes 2: the four corners are label positions like the others, and draw.io places
        # the label diagonally off the icon's corner (labelPosition for the side, verticalLabelPosition for top/bottom).
        self.prepare(); lab=self.store.lab(self.lab['id'])
        corners={'top-left':'labelPosition=left;verticalLabelPosition=top;align=right;verticalAlign=bottom;','top-right':'labelPosition=right;verticalLabelPosition=top;align=left;verticalAlign=bottom;',
                 'bottom-left':'labelPosition=left;verticalLabelPosition=bottom;align=right;verticalAlign=top;','bottom-right':'labelPosition=right;verticalLabelPosition=bottom;align=left;verticalAlign=top;'}
        for corner,style in corners.items():
            lab['drawing']['nodes'][0]['labelPosition']=corner; self.store.save()
            xml=ET.fromstring(self.client.post(self.url+'/drawio',json={}).content)
            self.assertIn(style,xml.find('.//mxCell[@id="node-0"]').get('style'),corner)
        lab['drawing']['nodes'][0]['labelPosition']='center'; self.store.save()
        xml=ET.fromstring(self.client.post(self.url+'/drawio',json={}).content)
        self.assertIn('align=center;verticalAlign=middle;',xml.find('.//mxCell[@id="node-0"]').get('style'),'a centred label is drawn over the icon')
        data=json.loads(self.client.post(self.url+'/annotations',json={}).content)
        self.assertEqual(data['nodeAnnotations'][0]['labelPosition'],'center')
        lab['drawing']['nodes'][0]['labelPosition']='sideways'; self.store.save()
        xml=ET.fromstring(self.client.post(self.url+'/drawio',json={}).content)
        self.assertIn('verticalLabelPosition=bottom;verticalAlign=top;',xml.find('.//mxCell[@id="node-0"]').get('style'),'an unknown value is drawn at the bottom, like the editor')
        # The manager's own export of the annotations keeps the corner for the editor and the VS Code extension.
        lab['drawing']['nodes'][0]['labelPosition']='top-right'; self.store.save()
        data=json.loads(self.client.post(self.url+'/annotations',json={}).content)
        self.assertEqual(data['nodeAnnotations'][0]['labelPosition'],'top-right')

    def test_export_unsaved_annotations_does_not_write_and_empty_list_removes(self):
        self.prepare();before=copy.deepcopy(self.store.lab(self.lab['id'])['drawing'])
        response=self.client.post(self.url+'/annotations',json={'decorations':[{'type':'text','text':'Draft'}]})
        self.assertEqual(response.json()['freeTextAnnotations'][0]['text'],'Draft')
        self.assertEqual(self.store.lab(self.lab['id'])['drawing'],before)
        self.assertEqual(self.client.put(self.url+'/layout',json={'decorations':[]}).status_code,200)
        self.assertEqual(Store(self.tmp.name).lab(self.lab['id'])['drawing']['decorations'],[])

    def test_stale_editor_and_invalid_input_leave_saved_map_untouched(self):
        drawing=self.prepare()
        self.client.put(self.url+'/layout',json={'positions':{drawing['nodes'][0]['id']:[400,300]}})
        before=copy.deepcopy(self.store.lab(self.lab['id'])['drawing'])
        response=self.client.put(self.url+'/layout',json={'revision':drawing['revision'],'decorations':[]})
        self.assertEqual(response.status_code,409)
        for item in ({'type':'script'},{'type':'text','x':True},{'type':'text','width':-1},
                     {'type':'text','fillColor':'url(https://invalid.example)'},{'type':'text','text':'x'*4001},
                     {'type':'text','fontFamily':'Arial" onload="bad'},{'type':'text','text':'bad\u0000'}):
            r=self.client.put(self.url+'/layout',json={'decorations':[item]})
            self.assertEqual(r.status_code,400,r.text)
            self.assertEqual(self.store.lab(self.lab['id'])['drawing'],before)

    def test_failed_save_rolls_back_annotations(self):
        self.prepare();before=copy.deepcopy(self.store.lab(self.lab['id'])['drawing'])
        with patch.object(self.store,'save',side_effect=OSError('fixture')):
            self.assertEqual(self.client.put(self.url+'/layout',json={'decorations':[{'type':'text','text':'Draft'}]}).status_code,500)
        self.assertEqual(self.store.lab(self.lab['id'])['drawing'],before)

    def test_imported_annotation_styles_survive_json_export(self):
        fixture=Path(__file__).parent/'fixtures/map'
        original=parse_drawing((fixture/'annotations.json').read_bytes(),(fixture/'topology-data.json').read_bytes())
        restored=parse_drawing(json.dumps(annotations(original)).encode(),(fixture/'topology-data.json').read_bytes())
        for kind in ('text','group','rectangle','circle','line'):
            before=[d for d in original['decorations'] if d['type']==kind]
            after=[d for d in restored['decorations'] if d['type']==kind]
            self.assertEqual(after,before)
