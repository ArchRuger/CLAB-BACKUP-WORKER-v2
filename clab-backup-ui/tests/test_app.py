import copy
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile
import paramiko
import yaml
from fastapi.testclient import TestClient
from app.main import create_app
from app.inventory import parse_inventory
from app.runner import make_inventory, APP

INVENTORY=b'''all:
  children:
    cisco_xrv9k:
      vars:
        ansible_user: clab
        ansible_password: test-secret
      hosts:
        clab-example-PE1:
          ansible_host: 172.20.20.5
    juniper_cjunosevolved:
      hosts:
        clab-example-PE2:
          ansible_host: 172.20.20.3
    arista_ceos:
      hosts:
        clab-example-SW1:
          ansible_host: 172.20.20.9
    linux:
      hosts:
        clab-example-worker:
          ansible_host: 172.20.20.20
'''

class AppTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.app=create_app(self.tmp.name)
        self.client=TestClient(self.app)
        self.auth={'Authorization':'Bearer '+self.app.state.store.token}
    def tearDown(self):
        self.app.state.runner.close()
        self.client.close()
        self.tmp.cleanup()
    def upload(self, content=INVENTORY, lab_id=''):
        result=self.client.post('/api/inventory',headers=self.auth,
            data={'name':'Example lab','lab_id':lab_id},files={'inventory':('ansible-inventory.yml',content)})
        self.assertEqual(result.status_code,200,result.text)
        return result.json()
    def test_auth_and_inventory_secret_redaction(self):
        self.assertEqual(self.client.get('/api/state', headers={'Origin':'https://other.example'}).status_code,403)
        lab=self.upload()
        self.assertEqual(len(lab['nodes']),4)
        self.assertNotIn('test-secret',json.dumps(lab))
        self.assertFalse(next(n for n in lab['nodes'] if n['name'].endswith('worker'))['enabled'])
        self.assertEqual(next(n for n in lab['nodes'] if n['name'].endswith('PE1'))['readiness'],'Ready')
        self.assertNotIn(b'test-secret',(Path(self.tmp.name)/'state.enc').read_bytes())
    def test_profiles_and_reupload(self):
        lab=self.upload()
        r=self.client.post(f'/api/labs/{lab["id"]}/profiles',headers=self.auth,
            data={'label':'Junos admin','platform':'juniper_cjunosevolved','username':'admin','password':'private-password','make_default':'true'})
        self.assertEqual(r.status_code,200,r.text)
        self.assertNotIn('private-password',r.text)
        self.assertEqual(next(n for n in r.json()['nodes'] if n['name'].endswith('PE2'))['readiness'],'Ready')
        replacement=self.upload(INVENTORY.replace(b'172.20.20.5',b'192.0.2.5'),lab['id'])
        self.assertEqual(len(replacement['profiles']),1)
        self.assertEqual(next(n for n in replacement['nodes'] if n['name'].endswith('PE1'))['address'],'192.0.2.5')
    def test_import_template_rejected_and_plugins_ignored(self):
        malicious=INVENTORY.replace(b'172.20.20.5',b'"{{ lookup(\'pipe\',\'id\') }}"')
        r=self.client.post('/api/inventory',headers=self.auth,data={'name':'x'},files={'inventory':('x.yml',malicious)})
        self.assertEqual(r.status_code,400)
        nodes=parse_inventory(INVENTORY.replace(b'ansible_user: clab',b'ansible_connection: local\n        ansible_ssh_common_args: evil\n        ansible_user: clab'))
        node=next(n for n in nodes if n['name'].endswith('PE1'))
        lab={'nodes':nodes,'profiles':[],'defaults':{}}
        inv=make_inventory(lab,[node],Path(self.tmp.name),'backup')
        actual=inv['all']['children']['targets']['hosts']['node_0']
        self.assertEqual(actual['ansible_connection'],'ansible.netcommon.network_cli')
        self.assertNotIn('ansible_ssh_common_args',actual)
    def test_key_upload(self):
        lab=self.upload(); key=paramiko.RSAKey.generate(2048); buf=io.StringIO();key.write_private_key(buf,password='keyphrase')
        r=self.client.post(f'/api/labs/{lab["id"]}/profiles',headers=self.auth,
            data={'label':'EOS key','platform':'arista_ceos','username':'admin','auth':'key','passphrase':'keyphrase'},
            files={'private_key':('id_rsa',buf.getvalue())})
        self.assertEqual(r.status_code,200,r.text)
        self.assertNotIn('PRIVATE KEY',r.text)
        self.assertNotIn('keyphrase',r.text)
    def test_readiness_blocks_schedule_and_job(self):
        lab=self.upload()
        for endpoint,data in [('schedule',{'interval':60}),('jobs',{'operation':'backup'})]:
            method=self.client.put if endpoint=='schedule' else self.client.post
            result=method(f'/api/labs/{lab["id"]}/{endpoint}',headers=self.auth,json=data)
            self.assertEqual(result.status_code,400,result.text)
    @unittest.skipIf(os.name=='nt', 'Ansible control-node tests require Linux')
    def test_roundtrip_actual_generated_ansible_inventory(self):
        lab=self.upload(); raw=self.app.state.store.lab(lab['id']);node=next(n for n in raw['nodes'] if n['name'].endswith('PE1'))
        inv=make_inventory(raw,[node],Path(self.tmp.name),'backup')
        path=Path(self.tmp.name)/'inventory.yml';path.write_text(yaml.safe_dump(inv))
        result=subprocess.run([str(Path(sys.executable).parent/'ansible-inventory'),'-i',str(path),'--list'],
            capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertNotIn('[WARNING]',result.stderr)
        variables=json.loads(result.stdout)['_meta']['hostvars']['node_0']
        self.assertEqual(variables['ansible_network_os'],'cisco.iosxr.iosxr')
        self.assertEqual(variables['backup_command'],'show running-config')
    @unittest.skipIf(os.name=='nt', 'Ansible control-node tests require Linux')
    def test_callback_and_archive_pipeline_offline(self):
        lab=self.upload(); raw=self.app.state.store.lab(lab['id'])
        for node in raw['nodes']: node['enabled']=node['name'].endswith('PE1')
        self.app.state.store.save()
        # Exercise real Ansible + production callback + archive/Git pipeline;
        # only the NOS command is replaced by a local deterministic command.
        original_popen=subprocess.Popen
        def local_popen(args,**kwargs):
            if args[0] != 'ansible-playbook':
                return original_popen(args,**kwargs)
            inv=Path(args[2]); directory=inv.parent
            play=directory/'offline.yml'
            play.write_text(yaml.safe_dump([{'hosts':'targets','gather_facts':False,
                'tasks':[{'name':'Fetch NOS configuration','ansible.builtin.command':{'argv':[sys.executable,'-c','print("hostname fixture-router")']},'changed_when':False}]}]))
            args=list(args);args[3]=str(play);args+=['-e','ansible_connection=local']
            return original_popen(args,**kwargs)
        with patch('app.runner.subprocess.Popen',side_effect=local_popen):
            # Call execute synchronously to make assertions deterministic.
            for i in range(2):
                job_id='fixture'+str(i)
                self.app.state.store.state['jobs'].insert(0,{'id':job_id,'lab_id':lab['id'],'lab_name':lab['name'],'status':'queued','operation':'backup','nodes':[]})
                self.app.state.runner.execute(job_id,copy.deepcopy(raw),[n for n in raw['nodes'] if n['enabled']],'backup')
        state=self.app.state.store.snapshot()
        self.assertTrue(all(j['status']=='succeeded' for j in state['jobs']),state['jobs'])
        folder=Path(self.tmp.name)/'backups'/lab['id']/'latest'
        count=subprocess.check_output(['git','-C',str(folder),'rev-list','--count','HEAD'],text=True).strip()
        self.assertEqual(count,'1')
        response=self.client.get('/api/jobs/fixture1/download',headers=self.auth)
        self.assertEqual(response.status_code,200,response.text if response.status_code!=200 else '')
        with zipfile.ZipFile(io.BytesIO(response.content)) as z:
            self.assertIn('manifest.json',z.namelist())
            self.assertEqual(len(z.namelist()),2)
            self.assertNotIn(b'test-secret',b''.join(z.read(n) for n in z.namelist()))
    def test_persistence_and_empty_image(self):
        self.assertEqual(self.client.get('/api/state',headers=self.auth).json()['labs'],[])
        self.upload()
        other=create_app(self.tmp.name)
        self.assertEqual(len(other.state.store.state['labs']),1)
        self.assertEqual(other.state.store.token,self.app.state.store.token)
        other.state.runner.close()
    def test_topology_custom_groups_and_alias_rejection(self):
        custom=b'all:\n  children:\n    custom:\n      hosts:\n        router1:\n          ansible_host: 192.0.2.1\n'
        nodes=parse_inventory(custom,b'{"nodes":{"router1":{"kind":"arista_ceos"}}}')
        self.assertEqual(nodes[0]['platform'],'arista_ceos')
        with self.assertRaises(ValueError): parse_inventory(b'all: &a {children: {loop: *a}}')

if __name__=='__main__': unittest.main()
