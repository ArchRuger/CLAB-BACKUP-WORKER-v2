import copy
import json
import tempfile
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET
from fastapi.testclient import TestClient
from app.main import create_app
from app.topology import (parse_drawing, bind_drawing, session_xml, unplaced, grid_position,
                          container_interface, displayed_interface, exported_interface)


class TopologyTests(unittest.TestCase):
    def setUp(self):
        self.lab={'id':'lab','name':'Example','profiles':[],'defaults':{},'nodes':[{'name':'clab-Example-r1','short_name':'r1','address':'192.0.2.1','port':30001,'platform':'cisco_xrv9k','enabled':True,'username':'','password':''}]}
        self.annotations={'nodeAnnotations':[{'id':'r1','position':{'x':12,'y':34}}]}
    def parse(self,data=None,topo=None):
        return parse_drawing(json.dumps(data or self.annotations).encode(),json.dumps(topo).encode() if topo else None)
    def test_placed_flag_tells_annotation_positions_from_the_default_grid(self):
        topo={'topology':{'nodes':{'r1':{},'r2':{},'r3':{}},'links':[]}}
        placed=self.parse(topo=topo)
        self.assertTrue(placed['placed']);self.assertFalse(unplaced(placed))
        grid=parse_drawing(b'{"nodeAnnotations":[]}',json.dumps(topo).encode())
        self.assertFalse(grid['placed']);self.assertTrue(unplaced(grid))
        self.assertEqual([(n['x'],n['y']) for n in grid['nodes']],[grid_position(i) for i in range(3)])
        # Annotations that name nodes without a position are the grid too.
        self.assertFalse(self.parse({'nodeAnnotations':[{'id':'r1'}]},topo)['placed'])
        # Drawings saved before the flag existed are judged by their coordinates.
        legacy={k:v for k,v in grid.items() if k!='placed'}
        self.assertTrue(unplaced(legacy))
        moved=copy.deepcopy(legacy);moved['nodes'][1]['y']=250
        self.assertFalse(unplaced(moved))
        self.assertFalse(unplaced(None));self.assertFalse(unplaced({'nodes':[]}))
    def test_layout_and_yaml_links(self):
        d=self.parse(topo={'topology':{'nodes':{'r1':{},'r2':{}},'links':[{'endpoints':['r1:eth1','r2:eth2']}]}})
        self.assertEqual(d['nodes'][0]['x'],12)
        self.assertEqual(d['links'][0][1],{'node':'r2','interface':'eth2'})
        self.lab['drawing']=d
        self.assertEqual(bind_drawing(self.lab)['nodes'][0]['inventory_name'],'clab-Example-r1')
        self.assertIsNone(bind_drawing(self.lab)['nodes'][1]['inventory_name'])
    def test_topology_data_endpoints(self):
        d=self.parse(topo={'nodes':{'r1':{'shortname':'r1'}},'links':[{'endpoints':{'a':{'node':'r1','interface':'eth1'},'z':{'node':'r2','interface':'eth2'}}}]})
        self.assertEqual(len(d['links']),1)
    def test_ambiguous_alias_fails_closed(self):
        self.lab['nodes'].append({**self.lab['nodes'][0],'name':'other'})
        self.lab['drawing']=self.parse()
        self.assertIsNone(bind_drawing(self.lab)['nodes'][0]['inventory_name'])
    def test_rejects_bad_shapes_and_coordinates(self):
        for value in [float('nan'),float('inf'),True,100001,'12']:
            a=copy.deepcopy(self.annotations);a['nodeAnnotations'][0]['position']['x']=value
            with self.assertRaises(ValueError):self.parse(a)
        with self.assertRaises(ValueError):self.parse({'nodeAnnotations':{}})
        with self.assertRaises(ValueError):parse_drawing(b'x'*1048577)
    def test_no_raw_config_or_external_style_retained(self):
        a={**self.annotations,'freeShapeAnnotations':[{'fillColor':'url(https://example.com)','secret':'hidden'}]}
        d=self.parse(a,{'topology':{'nodes':{'r1':{'env':{'PASSWORD':'hidden'}}}}})
        self.assertNotIn('hidden',json.dumps(d));self.assertNotIn('https:',json.dumps(d))
    def test_sessions_folder_shortname_and_username(self):
        n=ET.fromstring(session_xml(self.lab))[0]
        self.assertEqual(n.attrib['SessionId'],'Example/r1')
        self.assertEqual(n.attrib['Username'],'clab')
        self.assertEqual(n.attrib['Port'],'30001')
        self.assertEqual(n.attrib['ExtraArgs'],'')
    def test_profile_password_optin_and_xml_escaping(self):
        self.lab['profiles']=[{'id':'p','username':'a&b','password':'pass word','auth':'password'}]
        self.lab['defaults']={'cisco_xrv9k':'p'}
        plain=ET.fromstring(session_xml(self.lab))[0]
        self.assertEqual(plain.attrib['Username'],'a&b');self.assertEqual(plain.attrib['ExtraArgs'],'')
        secret=ET.fromstring(session_xml(self.lab,True))[0]
        self.assertEqual(secret.attrib['ExtraArgs'],'-pw "pass word"')
        self.lab['profiles'][0]['auth']='key'
        self.assertEqual(ET.fromstring(session_xml(self.lab,True))[0].attrib['ExtraArgs'],'')
    def test_duplicate_sessions_rejected(self):
        self.lab['nodes'].append(copy.deepcopy(self.lab['nodes'][0]))
        with self.assertRaises(ValueError):session_xml(self.lab)
    def test_import_retains_annotation_visual_fields(self):
        a=copy.deepcopy(self.annotations)
        a['nodeAnnotations'][0].update(labelPosition='top',iconColor='#123456',icon='switch')
        a['groupStyleAnnotations']=[{'name':'Routing','position':{'x':100,'y':200},'width':400,'height':200,'backgroundColor':'#ffcaab','backgroundOpacity':.4,'borderWidth':2,'labelPosition':'bottom-center'}]
        a['freeTextAnnotations']=[{'text':'Title','fontSize':28,'fontColor':'#112233','fontWeight':'bold','position':{'x':10,'y':20}}]
        d=self.parse(a)
        self.assertEqual(d['schema'],3)
        self.assertEqual(d['nodes'][0]['labelPosition'],'top')
        self.assertEqual(d['decorations'][0]['fillColor'],'#ffcaab')
        self.assertEqual(d['decorations'][0]['fillOpacity'],.4)
        self.assertEqual(d['decorations'][1]['fontSize'],28)
        self.assertEqual(d['decorations'][1]['fontWeight'],'bold')
    def test_topology_export_long_key_does_not_duplicate_short_annotation(self):
        d=self.parse(topo={'nodes':{'clab-Example-r1':{'shortname':'r1'}}})
        self.assertEqual([n['id'] for n in d['nodes']],['r1'])
    def test_authenticated_api_persistence_and_public_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            app=create_app(tmp);app.state.store.state['labs'].append(self.lab)
            client=TestClient(app);auth={'Authorization':'Bearer '+app.state.store.token}
            path='/api/labs/lab/topology'
            self.assertEqual(client.get(path, headers={'Origin':'https://other.example'}).status_code,403)
            result=client.post(path,headers=auth,files={'annotations':('lab.annotations.json',json.dumps(self.annotations),'application/json')})
            self.assertEqual(result.status_code,200,result.text)
            self.assertNotIn('drawing',client.get('/api/state',headers=auth).json()['labs'][0])
            self.assertEqual(client.get(path,headers=auth).json()['nodes'][0]['inventory_name'],'clab-Example-r1')
            export=client.post('/api/labs/lab/superputty',headers=auth,json={})
            self.assertEqual(export.status_code,200,export.text)
            self.assertIn("filename*=UTF-8''Example.xml",export.headers['content-disposition'])
            self.assertEqual(ET.fromstring(export.content).tag,'ArrayOfSessionData')
            bad=client.post(path,headers=auth,files={'annotations':('bad.json','{}','application/json')})
            self.assertEqual(bad.status_code,400)
            self.assertEqual(client.get(path,headers=auth).json(),result.json())
            app.state.node_services.close();app.state.runner.close();client.close()


class ActualMapRegressionTests(unittest.TestCase):
    """Geometry from the reported lab; credentials, addresses and images removed."""
    def setUp(self):
        self.fixture=Path(__file__).parent/'fixtures'/'map'
        self.annotations=(self.fixture/'annotations.json').read_bytes()

    def test_yaml_and_exported_topology_have_identical_nos_endpoints(self):
        yaml=parse_drawing(self.annotations,(self.fixture/'lab.yaml').read_bytes())
        exported=parse_drawing(self.annotations,(self.fixture/'topology-data.json').read_bytes())
        self.assertEqual(len(exported['nodes']),13)
        self.assertEqual(len(exported['links']),16)
        self.assertEqual(yaml['links'],exported['links'])
        self.assertEqual(exported['links'][0][1]['interface'],'Gi0/0/0/1')
        self.assertEqual(exported['links'][7][0]['interface'],'eth7')
        self.assertEqual(exported['links'][10][0]['label_offset'],20)

    def test_annotation_geometry_legacy_text_and_alpha_are_retained(self):
        d=parse_drawing(self.annotations,(self.fixture/'lab.yaml').read_bytes())
        pe=next(n for n in d['nodes'] if n['id']=='PE1')
        self.assertEqual((pe['x'],pe['y']),(60,100))
        self.assertEqual(pe['labelPosition'],'top')
        note=next(a for a in d['decorations'] if a['text']=='AS 64101')
        self.assertEqual(note['paragraphMargin'],18)
        self.assertEqual(note['fontFamily'],'Arial')
        circle=next(a for a in d['decorations'] if a['type']=='circle')
        self.assertEqual(circle['fillColor'],'rgb(127,127,127)')
        self.assertEqual(circle['fillOpacity'],.2)

    def test_every_drawing_node_binds_to_its_own_inventory_identity(self):
        d=parse_drawing(self.annotations,(self.fixture/'lab.yaml').read_bytes())
        lab={'name':'BGP_TheoryToPractice','drawing':d,'nodes':[{'name':'clab-BGP_TheoryToPractice-'+n['id'],'short_name':n['id']} for n in d['nodes']]}
        mapped=bind_drawing(lab)
        for n in mapped['nodes']:
            self.assertEqual(n['inventory_name'],'clab-BGP_TheoryToPractice-'+n['id'])


class ContainerInterfaceTests(unittest.TestCase):
    """D1: the container veth Wireshark captures on for a drawn NOS port name, per kind, both
    directions, confirmed against containerlab.dev's own kind pages (see PORT_RULES)."""
    def test_juniper_vjunos_family_ge_ports(self):
        for kind in ('juniper_vjunosswitch','juniper_vjunosevolved','juniper_vjunosrouter'):
            self.assertEqual(container_interface(kind,'ge-0/0/0'),'eth1')
            self.assertEqual(container_interface(kind,'ge-0/0/2'),'eth3')
            self.assertEqual(container_interface(kind,'GE-0/0/2'),'eth3')  # case variant
            self.assertEqual(displayed_interface(kind,'eth1'),'ge-0/0/0')
            self.assertEqual(displayed_interface(kind,'eth3'),'ge-0/0/2')
    def test_juniper_cjunosevolved_reserves_eth1_to_eth3(self):
        self.assertEqual(container_interface('juniper_cjunosevolved','et-0/0/0'),'eth4')
        self.assertEqual(container_interface('juniper_cjunosevolved','et-0/0/1'),'eth5')
        self.assertEqual(container_interface('juniper_cjunosevolved','ET-0/0/1'),'eth5')  # case variant
        self.assertEqual(displayed_interface('juniper_cjunosevolved','eth4'),'et-0/0/0')
        self.assertEqual(displayed_interface('juniper_cjunosevolved','eth5'),'et-0/0/1')
        # The image's own reserved eth1-eth3 have no et-0/0/N label; the veth name is kept.
        for reserved in ('eth1','eth2','eth3'):
            self.assertEqual(displayed_interface('juniper_cjunosevolved',reserved),reserved)
    def test_juniper_vqfx_xe_ports(self):
        self.assertEqual(container_interface('juniper_vqfx','xe-0/0/0'),'eth1')
        self.assertEqual(container_interface('juniper_vqfx','xe-0/0/4'),'eth5')
        self.assertEqual(displayed_interface('juniper_vqfx','eth5'),'xe-0/0/4')
    def test_cisco_xrv9k_gi_ports_including_first(self):
        for alias in ('Gi0/0/0/0','GigabitEthernet0/0/0/0','gi0/0/0/0'):
            self.assertEqual(container_interface('cisco_xrv9k',alias),'eth1')
        self.assertEqual(container_interface('cisco_xrv9k','Gi0/0/0/1'),'eth2')
        self.assertEqual(container_interface('vr-xrv9k','Gi0/0/0/1'),'eth2')
        self.assertEqual(displayed_interface('cisco_xrv9k','eth1'),'Gi0/0/0/0')
        self.assertEqual(displayed_interface('cisco_xrv9k','eth2'),'Gi0/0/0/1')
    def test_arista_ceos_ethernet_ports_and_identity(self):
        self.assertEqual(container_interface('arista_ceos','Ethernet1'),'eth1')
        self.assertEqual(container_interface('arista_ceos','Et3'),'eth3')
        self.assertEqual(container_interface('arista_ceos','eth2'),'eth2')  # already a container name
        self.assertEqual(displayed_interface('arista_ceos','eth1'),'Ethernet1')
    def test_linux_and_unknown_kinds_pass_through_container_style_names(self):
        for kind in ('linux','',None,'unknown_kind'):
            self.assertEqual(container_interface(kind,'eth7'),'eth7')
            self.assertEqual(container_interface(kind,'e7'),'eth7')
        self.assertEqual(container_interface('unknown_kind','ge-0/0/0'),'')
    def test_nokia_srlinux_keeps_its_own_name(self):
        self.assertEqual(container_interface('nokia_srlinux','e1-5'),'e1-5')
        self.assertEqual(container_interface('nokia_srlinux','ethernet-1/5'),'e1-5')
        self.assertEqual(container_interface('nokia_srlinux','Ethernet-1/5'),'e1-5')  # case variant
        self.assertEqual(displayed_interface('nokia_srlinux','e1-5'),'e1-5')
    def test_breakouts_and_subinterfaces_are_unrecognised(self):
        for kind,name in [('juniper_vjunosswitch','ge-0/0/1:0'),('juniper_cjunosevolved','et-0/0/0.100'),
                          ('cisco_xrv9k','Gi0/0/0/1.100'),('arista_ceos','Ethernet1/1'),
                          ('juniper_vqfx','xe-0/0/0:1')]:
            with self.subTest(kind=kind,name=name):
                self.assertEqual(container_interface(kind,name),'')
    def test_unrecognised_inputs_return_empty_not_a_guess(self):
        self.assertEqual(container_interface('juniper_vjunosswitch','fabric'),'')
        self.assertEqual(container_interface('cisco_xrv9k',''),'')
        self.assertEqual(container_interface('cisco_xrv9k',None),'')
        self.assertEqual(container_interface(None,'ge-0/0/0'),'')
    def test_both_ends_of_a_mixed_kind_link(self):
        # cJunosEvolved et-0/0/0 to XRv9k Gi0/0/0/0, the actual restore-square wiring.
        self.assertEqual(container_interface('juniper_cjunosevolved','et-0/0/0'),'eth4')
        self.assertEqual(container_interface('cisco_xrv9k','Gi0/0/0/0'),'eth1')
    def test_exported_interface_reverses_only_xrv9k_including_its_first_port(self):
        self.assertEqual(exported_interface('eth1','cisco_xrv9k'),'Gi0/0/0/0')
        self.assertEqual(exported_interface('eth2','cisco_xrv9k'),'Gi0/0/0/1')
        self.assertEqual(exported_interface('eth1','vr-xrv9k'),'Gi0/0/0/0')
        # Other kinds and non-eth shapes are left exactly as exported.
        self.assertEqual(exported_interface('eth4','juniper_cjunosevolved'),'eth4')
        self.assertEqual(exported_interface('eth1','arista_ceos'),'eth1')
        self.assertEqual(exported_interface('Gi0/0/0/1','cisco_xrv9k'),'Gi0/0/0/1')


class BindDrawingCaptureInterfaceTests(unittest.TestCase):
    """D1: bind_drawing attaches the container interface to each link endpoint, confirmed
    against the node's own inventory platform, so the browser never has to guess it."""
    def lab(self,platform_a='juniper_cjunosevolved',platform_b='cisco_xrv9k'):
        return {'id':'lab','name':'Example','profiles':[],'defaults':{},
                'nodes':[{'name':'clab-Example-a','short_name':'a','platform':platform_a},
                         {'name':'clab-Example-b','short_name':'b','platform':platform_b}],
                'drawing':{'nodes':[{'id':'a','alias':'a','label':'a'},{'id':'b','alias':'b','label':'b'}],
                          'links':[[{'node':'a','interface':'et-0/0/0'},{'node':'b','interface':'Gi0/0/0/0'}]],
                          'decorations':[]}}
    def test_capture_interface_present_on_both_endpoints(self):
        bound=bind_drawing(self.lab())
        ep_a,ep_b=bound['links'][0]
        self.assertEqual(ep_a['capture_interface'],'eth4')
        self.assertEqual(ep_b['capture_interface'],'eth1')
        # The drawn interface name itself is preserved unchanged next to the new field.
        self.assertEqual(ep_a['interface'],'et-0/0/0');self.assertEqual(ep_b['interface'],'Gi0/0/0/0')
    def test_capture_interface_is_empty_for_an_unmatched_or_unknown_node(self):
        lab=self.lab(platform_a='')
        bound=bind_drawing(lab)
        self.assertEqual(bound['links'][0][0]['capture_interface'],'')
        lab['nodes'].append({**lab['nodes'][1],'name':'clab-Example-b2'})  # ambiguous alias 'b'
        bound=bind_drawing(lab)
        self.assertIsNone(bound['nodes'][1]['inventory_name'])
        self.assertEqual(bound['links'][0][1]['capture_interface'],'')
