import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from fastapi.testclient import TestClient
import zipfile
from app.main import create_app
from app.downloads import component, config_names, archive_name, short_name

class DownloadTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.app=create_app(self.tmp.name)
        self.client=TestClient(self.app);self.store=self.app.state.store
        self.auth={'Authorization':'Bearer '+self.store.token}
        self.lab={'id':'lab','name':'BGP_TheoryToPractice','nodes':[], 'profiles':[], 'defaults':{}, 'interval':0}
        types=[('juniper_cjunosevolved','GTW-2','set','set system host-name GTW-2\n'),
               ('cisco_xrv9k','PE1','cfg','!! IOS XR Configuration 24.3.1\nhostname PE1\n'),
               ('arista_ceos','IXP-L2-Switch','cfg','! device: IXP-L2-Switch (cEOSLab, EOS-4.35.0F)\nhostname IXP-L2-Switch\nend\n')]
        self.job=dict(id='job1',lab_id='lab',lab_name=self.lab['name'],operation='backup',status='succeeded',
                      started='2026-09-10T01:02:03+00:00',finished='2026-09-10T01:09:00+00:00',nodes=[])
        self.folder=Path(self.tmp.name)/'backups/lab/history/job1';self.folder.mkdir(parents=True)
        for index,(platform,name,ext,config) in enumerate(types):
            self.lab['nodes'].append(dict(name=f'clab-BGP_TheoryToPractice-{name}',platform=platform,enabled=True))
            node=dict(name=self.lab['nodes'][-1]['name'],platform=platform,short_name=name,
                      captured_at='2026-09-09T21:04:59-04:00',status='succeeded',file=f'old-hash-{index}.{ext}',download_metadata_version=1)
            self.job['nodes'].append(node);(self.folder/node['file']).write_text(config)
        self.store.state['labs'].append(self.lab);self.store.state['jobs'].append(self.job);self.store.save()
    def tearDown(self):
        self.app.state.runner.close();self.client.close();self.tmp.cleanup()
    def get(self,path): return self.client.get(path,headers=self.auth)
    def test_each_device_download_name_type_time_and_bytes(self):
        expected=['cjunosevo_GTW-2_2026-09-10_01-04UTC.cfg','IOS-XR_PE1_2026-09-10_01-04UTC.txt','CEOS_IXP-L2-Switch_2026-09-10_01-04UTC.conf']
        for index,name in enumerate(expected):
            response=self.get(f'/api/jobs/job1/nodes/{index}/download')
            self.assertEqual(response.status_code,200,response.text)
            self.assertIn(name,response.headers['content-disposition'])
            self.assertEqual(response.content,(self.folder/self.job['nodes'][index]['file']).read_bytes())
            self.assertEqual(response.headers['content-type'],'application/octet-stream')
        logs=self.get('/api/logs?job_id=job1&node=IXP-L2-Switch').json()['events']
        self.assertTrue(any(e['action']=='download.device' for e in logs))
        self.assertNotIn('hostname IXP',json.dumps(logs))
    def test_zip_matches_individual_names_and_manifest(self):
        response=self.get('/api/jobs/job1/download')
        self.assertEqual(response.status_code,200)
        self.assertIn('BGP_TheoryToPractice_2026-09-10_01-02.zip',response.headers['content-disposition'])
        with zipfile.ZipFile(io.BytesIO(response.content)) as z:
            self.assertEqual(len(z.namelist()),4)
            manifest=json.loads(z.read('manifest.json'))
            for index,name in config_names(self.job).items():
                self.assertEqual(z.read(name),self.get(f'/api/jobs/job1/nodes/{index}/download').content)
                self.assertEqual(manifest['nodes'][index]['file'],name)
        self.assertEqual(self.job['nodes'][0]['file'],'old-hash-0.set')
    def test_legacy_backfill_preserves_stored_configs_and_snapshot_metadata(self):
        for n in self.job['nodes']:
            for k in ('platform','short_name','captured_at','download_metadata_version'): n.pop(k)
        before={p.name:(p.read_bytes(),p.stat().st_mtime_ns) for p in self.folder.iterdir()}
        self.store.save();self.app.state.runner.close();self.client.close()
        self.app=create_app(self.tmp.name);self.client=TestClient(self.app);self.store=self.app.state.store
        self.auth={'Authorization':'Bearer '+self.store.token}
        nodes=self.get('/api/state').json()['jobs'][0]['nodes']
        self.assertEqual([n['platform'] for n in nodes],['juniper_cjunosevolved','cisco_xrv9k','arista_ceos'])
        self.assertEqual(nodes[0]['download_name'],'cjunosevo_GTW-2_2026-09-10_01-09UTC.cfg')
        self.assertEqual(before,{p.name:(p.read_bytes(),p.stat().st_mtime_ns) for p in self.folder.iterdir()})
        # Future inventory rename/type edits cannot relabel a backfilled historical snapshot.
        self.store.state['labs'][0]['nodes'][0]['platform']='arista_ceos'
        self.store.state['labs'][0]['name']='New label'
        self.assertIn('cjunosevo_GTW-2',self.get('/api/jobs/job1/nodes/0/download').headers['content-disposition'])
    def test_auth_and_invalid_or_failed_nodes(self):
        self.assertEqual(self.client.get('/api/jobs/job1/nodes/0/download').status_code,401)
        for path in ('/api/jobs/missing/nodes/0/download','/api/jobs/job1/nodes/-1/download','/api/jobs/job1/nodes/99/download'):
            self.assertEqual(self.get(path).status_code,404)
        self.job['nodes'][1]['status']='failed';self.job['status']='partial'
        self.assertEqual(self.get('/api/jobs/job1/nodes/1/download').status_code,404)
        self.assertEqual(self.get('/api/jobs/job1/nodes/0/download').status_code,200)
        with zipfile.ZipFile(io.BytesIO(self.get('/api/jobs/job1/download').content)) as z:
            self.assertEqual(len(z.namelist()),3)
        self.job['status']='running'
        self.assertEqual(self.get('/api/jobs/job1/nodes/0/download').status_code,409)
        self.assertEqual(self.get('/api/jobs/job1/download').status_code,409)
        self.job['status']='succeeded';self.job['operation']='test'
        self.assertEqual(self.get('/api/jobs/job1/nodes/0/download').status_code,404)
    def test_missing_and_unsafe_files(self):
        node=self.job['nodes'][0];original=node['file']
        for value in ('../state.enc','/etc/passwd','..\\state.enc','missing.cfg'):
            node['file']=value
            self.assertEqual(self.get('/api/jobs/job1/nodes/0/download').status_code,404)
            self.assertEqual(self.get('/api/jobs/job1/download').status_code,404)
    def test_symlink_download_rejected(self):
        node=self.job['nodes'][0];original=node['file']
        (self.folder/original).unlink()
        try: (self.folder/original).symlink_to(self.store.path)
        except OSError as exc:
            if getattr(exc,'winerror',None)==1314:
                self.skipTest('Windows symlink privilege unavailable; run this security check on Linux')
            raise
        self.assertEqual(self.get('/api/jobs/job1/nodes/0/download').status_code,404)
        self.assertEqual(self.get('/api/jobs/job1/nodes/1/download').status_code,200)
    def test_windows_names_and_case_insensitive_collisions(self):
        self.job['lab_name']='Lab | "Name": ../../bad'
        self.assertEqual(archive_name(self.job),'Lab_Name_.._.._bad_2026-09-10_01-02.zip')
        a=copy.deepcopy(self.job['nodes'][0]);a['short_name']='sw/name'
        b=copy.deepcopy(a);b['short_name']='SW:NAME'
        c=copy.deepcopy(a);c['short_name']='sw_name_2'
        self.job['nodes']=[a,b,c]
        names=list(config_names(self.job).values())
        self.assertEqual(len(set(n.casefold() for n in names)),3)
        self.assertTrue(all('/' not in n and ':' not in n for n in names))
        self.assertEqual(component('CON'),'_CON')
    def test_short_names_preserve_hyphenated_devices(self):
        self.assertEqual(short_name({'name':'clab-lab-with-dashes-IXP-L2-Switch'},'lab-with-dashes'),'IXP-L2-Switch')
        self.assertEqual(short_name({'name':'clab-original-lab-GTW-2'},'Display name','set system host-name GTW-2\n'),'GTW-2')
        self.assertEqual(short_name({'name':'clab-ambiguous-lab-device'},'Other'),'clab-ambiguous-lab-device')
        self.assertEqual(short_name({'name':'long','short_name':'PE-1'}),'PE-1')
    def test_state_exposes_release_names_and_utc(self):
        state=self.get('/api/state').json()
        self.assertEqual(state['version'],'1.10.0')
        self.assertEqual(state['jobs'][0]['download_timezone'],'UTC')
        self.assertIn('archive_name',state['jobs'][0])
        self.assertTrue(all(n.get('download_name') for n in state['jobs'][0]['nodes']))

if __name__=='__main__': unittest.main()
