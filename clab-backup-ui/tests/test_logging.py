import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from app.main import create_app
from app.inventory import parse_inventory, PLATFORMS
from app.runner import make_inventory, normalized, filename
from app.store import Store

class LoggingTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.app=create_app(self.tmp.name)
        self.store=self.app.state.store
        self.client=TestClient(self.app)
        self.auth={'Authorization':'Bearer '+self.store.token}
        self.nodes=[dict(name=kind,address='192.0.2.1',port=30001+i,platform=kind,
                         enabled=True,username='admin',password='login-sensitive',enable_password='enable-sensitive')
                    for i,kind in enumerate(PLATFORMS)]
        self.lab=dict(id='lab',name='Lab',nodes=self.nodes,profiles=[],defaults={},interval=0)
        self.store.state['labs'].append(self.lab)
    def tearDown(self):
        self.app.state.runner.close();self.client.close();self.tmp.cleanup()
    def test_exact_drivers_and_enable_mode(self):
        hosts=make_inventory(self.lab,self.nodes,Path(self.tmp.name),'backup')['all']['children']['targets']['hosts']
        for i,node in enumerate(self.nodes):
            host=hosts[f'node_{i}']
            self.assertEqual(host['ansible_network_os'],PLATFORMS[node['platform']]['os'])
            self.assertEqual(host['ansible_port'],node['port'])
            self.assertFalse(host['ansible_persistent_log_messages'])
            if node['platform']=='arista_ceos':
                self.assertTrue(host['ansible_become'])
                self.assertEqual(host['ansible_become_method'],'enable')
                self.assertEqual(host['ansible_become_password'],'enable-sensitive')
            else: self.assertNotIn('ansible_become',host)
        self.assertIn('| no-more',hosts['node_0']['backup_command'])
        test=make_inventory(self.lab,self.nodes,Path(self.tmp.name),'test')['all']['children']['targets']['hosts']
        self.assertTrue(all(h['backup_command']=='show version' for h in test.values()))
    def test_enable_profile_and_import_do_not_expose_secret(self):
        node=parse_inventory(b'all:\n  children:\n    arista_ceos:\n      hosts:\n        sw:\n          ansible_user: admin\n          ansible_password: login-sensitive\n          ansible_become_password: enable-sensitive\n')[0]
        self.assertEqual(node['enable_password'],'enable-sensitive')
        self.lab['nodes']=[node]
        r=self.client.post('/api/labs/lab/profiles',headers=self.auth,data=dict(label='EOS',platform='arista_ceos',username='admin',password='login-sensitive',enable_password='enable-sensitive'))
        self.assertEqual(r.status_code,200,r.text)
        self.assertNotIn('enable-sensitive',r.text)
        self.assertNotIn('enable-sensitive',self.client.get('/api/state',headers=self.auth).text)
        self.assertNotIn('enable-sensitive',(Path(self.tmp.name)/'events.jsonl').read_text())
    def execute_fixture(self, outputs, job_id='run'):
        job=dict(id=job_id,lab_id='lab',operation='backup',status='queued',nodes=[])
        self.store.state['jobs'].insert(0,job)
        store=self.store
        class Process:
            returncode=0
            def __init__(self,args,**kwargs):
                self.count=0
                self.path=Path(kwargs['env']['BACKUP_EVENT_FILE'])
                self.path.write_text(''.join(json.dumps(dict(host=f'node_{i}',status='running',task='Fetch NOS configuration'))+'\n' for i in range(len(outputs))))
            def poll(self):
                self.count+=1
                if self.count==1: return None
                if self.count==2:
                    # The worker must publish task events before subprocess completion.
                    assert any(e['action']=='ssh.task.running' for e in store.events(job_id=job_id))
                    with self.path.open('a') as f:
                        for i,result in enumerate(outputs):
                            f.write(json.dumps(dict(host=f'node_{i}',task='Fetch NOS configuration',**result))+'\n')
                return self.returncode
        with patch('app.runner.subprocess.Popen',side_effect=Process), patch('app.runner.subprocess.run') as git, patch('app.runner.time.sleep'):
            git.return_value.stdout=''
            self.app.state.runner.execute(job_id,copy.deepcopy(self.lab),self.nodes,'backup')
        return job
    def test_live_events_partial_results_preserve_previous_backup(self):
        latest=Path(self.tmp.name)/'backups/lab/latest';latest.mkdir(parents=True)
        eos=latest/filename(self.nodes[2]);eos.write_text('previous EOS config\n')
        job=self.execute_fixture([dict(status='ok',stdout='set system host-name junos\n'),
                                  dict(status='ok',stdout='hostname xr\n'),
                                  dict(status='failed',message='enable failed login-sensitive enable-sensitive')])
        self.assertEqual(job['status'],'partial')
        self.assertEqual(eos.read_text(),'previous EOS config\n')
        logs=self.store.events(job_id='run')
        rendered=json.dumps(logs)
        self.assertNotIn('login-sensitive',rendered);self.assertNotIn('enable-sensitive',rendered)
        self.assertNotIn('set system host-name',rendered)
        self.assertTrue(any(e['node']=='arista_ceos' and e['level']=='error' for e in logs))
    def test_empty_and_cli_error_outputs_never_replace_backups(self):
        for kind in PLATFORMS:
            for value in ('','% Invalid input','error: configuration database locked','System is not yet ready...',None):
                with self.subTest(kind=kind,value=value),self.assertRaises(ValueError): normalized(kind,value)
    def test_log_auth_filters_and_restart_persistence(self):
        self.store.event('fixture','failure',lab_id='lab',job_id='run',node='SW1',level='error')
        self.assertEqual(self.client.get('/api/logs', headers={'Origin':'https://other.example'}).status_code,403)
        r=self.client.get('/api/logs?lab_id=lab&job_id=run&node=sw&level=error',headers=self.auth)
        self.assertEqual(len(r.json()['events']),1)
        self.assertEqual(self.client.get('/api/logs?limit=9999',headers=self.auth).status_code,422)
        reopened=Store(self.tmp.name)
        self.assertEqual(len(reopened.events(job_id='run')),1)
    def test_rotation_retains_recent_events(self):
        path=Path(self.tmp.name)/'events.jsonl'
        self.store.event('fixture','rotate me',job_id='retained')
        with path.open('a') as f: f.write(' '* (5*1024*1024)+'\n')
        self.store.event('fixture','new event')
        self.assertTrue(path.with_name('events.jsonl.1').exists())
        self.assertEqual(len(self.store.events(job_id='retained')),1)

if __name__=='__main__': unittest.main()
