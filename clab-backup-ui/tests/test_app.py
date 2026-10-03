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
        # Known kinds carry containerlab's documented default login, so the inventory
        # above is Ready as imported; a kind without a published default still blocks.
        self.assertEqual({n['credential_source'] for n in lab['nodes'] if n['enabled']},{'inventory','default'})
        with patch.dict('app.inventory.DEFAULT_CREDENTIALS',{},clear=True):
            for endpoint,data in [('schedule',{'interval':60}),('jobs',{'operation':'backup'})]:
                method=self.client.put if endpoint=='schedule' else self.client.post
                result=method(f'/api/labs/{lab["id"]}/{endpoint}',headers=self.auth,json=data)
                self.assertEqual(result.status_code,400,result.text)
    # L-19/L-29 (audit 2026-10-03): a rejected connection edit changes nothing and logs no update.
    def test_rejected_node_edit_changes_and_logs_nothing(self):
        lab=self.upload(); store=self.app.state.store
        node=next(n for n in store.lab(lab['id'])['nodes'] if n['name'].endswith('PE1'))
        before=copy.deepcopy(store.state)
        edit=dict(name=node['name'],address='10.0.0.5',port=2022,platform='cisco_xrv9k',short_name='core1')
        for changes,detail in [({'endpoint_mode':'auto'},'Link a deployed lab'),({'endpoint_mode':'bogus'},'automatic or manual'),
                               ({'short_name':'{{ core1 }}'},'Download device name')]:
            r=self.client.put(f'/api/labs/{lab["id"]}/node',headers=self.auth,json={**edit,**changes})
            self.assertEqual(r.status_code,400,r.text); self.assertIn(detail,r.json()['detail'])
            self.assertEqual(store.state,before)
            self.assertNotIn('core1',json.dumps(self.client.get('/api/state').json()))
            self.assertEqual([e for e in store.events() if e['action']=='node.edit'],[])
        r=self.client.put(f'/api/labs/{lab["id"]}/node',headers=self.auth,json={**edit,'endpoint_mode':'manual'})
        self.assertEqual(r.status_code,200,r.text)
        saved=next(n for n in r.json()['nodes'] if n['name']==node['name'])
        self.assertEqual((saved['short_name'],saved['address'],saved['port'],saved['endpoint_mode']),('core1','10.0.0.5',2022,'manual'))
        self.assertEqual(len([e for e in store.events() if e['action']=='node.edit']),1)
    # L-20 (audit 2026-10-03): when the state file cannot be written, a profile, connection, schedule or
    # inventory change is not kept in memory (where the next unrelated save would persist it) and is not logged.
    def test_failed_save_keeps_no_change_in_memory(self):
        lab=self.upload(); store=self.app.state.store
        node=next(n for n in store.lab(lab['id'])['nodes'] if n['name'].endswith('PE1'))
        requests=[
            ('credentials.create',lambda:self.client.post(f'/api/labs/{lab["id"]}/profiles',headers=self.auth,
                data={'label':'Junos admin','platform':'juniper_cjunosevolved','username':'admin','password':'private-password','make_default':'true'})),
            ('node.edit',lambda:self.client.put(f'/api/labs/{lab["id"]}/node',headers=self.auth,
                json=dict(name=node['name'],address='10.0.0.5',port=2022,platform='cisco_xrv9k',short_name='core1'))),
            ('schedule.update',lambda:self.client.put(f'/api/labs/{lab["id"]}/schedule',headers=self.auth,json={'interval':60})),
            ('inventory.import',lambda:self.client.post('/api/inventory',headers=self.auth,data={'name':'Renamed lab','lab_id':lab['id']},
                files={'inventory':('ansible-inventory.yml',INVENTORY.replace(b'172.20.20.5',b'192.0.2.5'))})),
            ('inventory.import',lambda:self.client.post('/api/inventory',headers=self.auth,data={'name':'Second lab','lab_id':''},
                files={'inventory':('ansible-inventory.yml',INVENTORY)}))]
        actions=lambda:[e['action'] for e in store.events(limit=2000)]   # newest first
        for action,request in requests:
            before=copy.deepcopy(store.state); logged=len(actions())
            with patch.object(store,'save',side_effect=OSError('Sensitive storage diagnostic')):
                r=request()
            self.assertEqual(r.status_code,500,r.text); self.assertNotIn('Sensitive',r.text)
            self.assertEqual(store.state,before,action)
            new=actions(); self.assertNotIn(action,new[:len(new)-logged])
        durable=json.loads(store.cipher.decrypt(store.path.read_bytes()))
        self.assertEqual(durable['labs'],store.state['labs'])
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
            # Call execute synchronously to make assertions deterministic. The first capture runs for the
            # inventory-only lab (no topology text in the manager: nothing to embed); the second after the lab
            # gained a topology text, as a lab from the VM has.
            for i in range(2):
                job_id='fixture'+str(i)
                if i==1: raw['definition_yaml']='name: example\ntopology:\n  nodes:\n    PE1:\n      kind: cisco_xrv9k\n'
                self.app.state.store.state['jobs'].insert(0,{'id':job_id,'lab_id':lab['id'],'lab_name':lab['name'],'status':'queued','operation':'backup','nodes':[]})
                self.app.state.runner.execute(job_id,copy.deepcopy(raw),[n for n in raw['nodes'] if n['enabled']],'backup')
        state=self.app.state.store.snapshot()
        self.assertTrue(all(j['status']=='succeeded' for j in state['jobs']),state['jobs'])
        folder=Path(self.tmp.name)/'backups'/lab['id']/'latest'
        count=subprocess.check_output(['git','-C',str(folder),'rev-list','--count','HEAD'],text=True).strip()
        self.assertEqual(count,'2','one commit per capture that changed latest/: the first wrote the configuration, the second added the topology')
        # IOS XR's running-config is its own restore candidate: one capture, the artifact is the backup text
        # under its own name, and it stays out of the download ZIP (two entries, asserted below).
        outcome=next(n for n in state['jobs'][0]['nodes'] if n['name'].endswith('PE1'))
        self.assertTrue(outcome['restore_file'].endswith('.xrcfg'),outcome)
        self.assertEqual(outcome['restore_format'],'iosxr-running-config')
        self.assertEqual((folder/outcome['restore_file']).read_bytes(),(folder/outcome['file']).read_bytes())
        # The runner records the digest of what it stored; readers refuse a capture that no longer matches it.
        import hashlib
        self.assertEqual(outcome['sha256'],hashlib.sha256((folder/outcome['file']).read_bytes()).hexdigest())
        self.assertEqual(outcome['restore_sha256'],hashlib.sha256((folder/outcome['restore_file']).read_bytes()).hexdigest())
        # The topology travels with every backup (UI/UX changes 2, item 10): written beside the configurations
        # under a stable internal name, recorded on the job with its digest and provenance (the manager's copy
        # here: no VM discovery in this test; no map, this lab has no drawing), committed into latest/ with the
        # configurations, and in the ZIP under the lab's own name beside the configuration and the manifest. The
        # first capture, taken while the manager held no topology text, carries none and downloads as before.
        first=next(j for j in state['jobs'] if j['id']=='fixture0'); job=next(j for j in state['jobs'] if j['id']=='fixture1')
        self.assertNotIn('topology',first); self.assertFalse((Path(self.tmp.name)/'backups'/lab['id']/'history'/'fixture0'/'topology.clab.yml').exists())
        self.assertEqual(job['topology']['file'],'topology.clab.yml'); self.assertEqual(job['topology']['source'],'manager')
        self.assertNotIn('annotations_file',job['topology'])
        self.assertEqual((folder/'topology.clab.yml').read_text(),raw['definition_yaml'])
        self.assertEqual(job['topology']['sha256'],hashlib.sha256(raw['definition_yaml'].encode()).hexdigest())
        history=Path(self.tmp.name)/'backups'/lab['id']/'history'/'fixture1'
        self.assertEqual((history/'topology.clab.yml').read_text(),raw['definition_yaml'])
        self.assertIn('topology.clab.yml',subprocess.check_output(['git','-C',str(folder),'ls-files'],text=True))
        self.assertEqual(subprocess.check_output(['git','-C',str(folder),'rev-list','--count','HEAD'],text=True).strip(),'2','the second capture changed latest/ (the topology arrived), so it committed')
        with zipfile.ZipFile(io.BytesIO(self.client.get('/api/jobs/fixture0/download',headers=self.auth).content)) as z:
            self.assertEqual(len(z.namelist()),2,z.namelist())
        response=self.client.get('/api/jobs/fixture1/download',headers=self.auth)
        self.assertEqual(response.status_code,200,response.text if response.status_code!=200 else '')
        with zipfile.ZipFile(io.BytesIO(response.content)) as z:
            self.assertIn('manifest.json',z.namelist())
            self.assertEqual(len(z.namelist()),3,z.namelist())
            self.assertEqual(z.read(lab['name'].replace(' ','_')+'.clab.yml').decode(),raw['definition_yaml'])
            manifest=json.loads(z.read('manifest.json'))
            self.assertEqual(manifest['topology']['file'],lab['name'].replace(' ','_')+'.clab.yml','the manifest names the file as it is in the archive')
            self.assertNotIn(b'test-secret',b''.join(z.read(n) for n in z.namelist()))
        # A third capture with the topology text gone again clears latest/ of the embedded files, so the local Git
        # history never pairs new configurations with an old topology; a drawing the map writer cannot read is no
        # failure of the backup either.
        raw.pop('definition_yaml'); raw['drawing']={'broken':True}
        self.app.state.store.state['jobs'].insert(0,{'id':'fixture2','lab_id':lab['id'],'lab_name':lab['name'],'status':'queued','operation':'backup','nodes':[]})
        with patch('app.runner.subprocess.Popen',side_effect=local_popen):
            self.app.state.runner.execute('fixture2',copy.deepcopy(raw),[n for n in raw['nodes'] if n['enabled']],'backup')
        third=next(j for j in self.app.state.store.snapshot()['jobs'] if j['id']=='fixture2')
        self.assertEqual(third['status'],'succeeded',third); self.assertNotIn('topology',third)
        self.assertFalse((folder/'topology.clab.yml').exists(),'latest/ no longer holds the earlier topology')
        self.assertTrue((Path(self.tmp.name)/'backups'/lab['id']/'history'/'fixture1'/'topology.clab.yml').exists(),'the earlier backup keeps its own copy')
        raw['definition_yaml']='name: example\ntopology:\n  nodes:\n    PE1:\n      kind: cisco_xrv9k\n'
        self.app.state.store.state['jobs'].insert(0,{'id':'fixture3','lab_id':lab['id'],'lab_name':lab['name'],'status':'queued','operation':'backup','nodes':[]})
        with patch('app.runner.subprocess.Popen',side_effect=local_popen):
            self.app.state.runner.execute('fixture3',copy.deepcopy(raw),[n for n in raw['nodes'] if n['enabled']],'backup')
        fourth=next(j for j in self.app.state.store.snapshot()['jobs'] if j['id']=='fixture3')
        self.assertEqual(fourth['status'],'succeeded',fourth); self.assertEqual(fourth['topology']['source'],'manager')
        self.assertNotIn('annotations_file',fourth['topology'],'a drawing the map writer cannot read embeds no map, and the backup still succeeds with the topology')
    @unittest.skipIf(os.name=='nt', 'Ansible control-node tests require Linux')
    def test_restore_artifacts_one_capture_when_the_backup_is_the_candidate(self):
        lab=self.upload(); raw=self.app.state.store.lab(lab['id'])
        for node in raw['nodes']: node['enabled']=node['name'].endswith(('PE2','SW1'))
        self.app.state.store.save()
        junos_node=next(n for n in raw['nodes'] if n['name'].endswith('PE2'))
        eos_node=next(n for n in raw['nodes'] if n['name'].endswith('SW1'))
        nodes=[junos_node,eos_node]
        # Junos' restore command differs from its backup command and is fetched a second time;
        # EOS' restore command equals its backup command, so it is never scheduled a second time.
        backup_hosts=make_inventory(raw,nodes,Path(self.tmp.name),'backup')['all']['children']['targets']['hosts']
        self.assertEqual(backup_hosts['node_0']['restore_command'],'show configuration | no-more')
        self.assertNotIn('restore_command',backup_hosts['node_1'])
        test_hosts=make_inventory(raw,nodes,Path(self.tmp.name),'test')['all']['children']['targets']['hosts']
        self.assertNotIn('restore_command',test_hosts['node_0']); self.assertNotIn('restore_command',test_hosts['node_1'])
        # Exercise real Ansible + production callback + archive pipeline for both tasks in backup.yml;
        # only the NOS commands are replaced by local deterministic commands.
        original_popen=subprocess.Popen
        primary='import sys\nprint("set system host-name fixture-junos" if "{{ ansible_network_os }}"=="junipernetworks.junos.junos" else "! Command: show running-config\\nhostname fixture-eos\\nend")'
        restore='print("system {\\n    host-name fixture-junos;\\n}")'
        def local_popen(args,**kwargs):
            if args[0] != 'ansible-playbook':
                return original_popen(args,**kwargs)
            inv=Path(args[2]); directory=inv.parent
            play=directory/'offline.yml'
            play.write_text(yaml.safe_dump([{'hosts':'targets','gather_facts':False,
                'tasks':[{'name':'Fetch NOS configuration','ansible.builtin.command':{'argv':[sys.executable,'-c',primary]},'changed_when':False},
                    {'name':'Fetch restore artifact','ansible.builtin.command':{'argv':[sys.executable,'-c',restore]},'changed_when':False,
                     'failed_when':False,'ignore_errors':True,'when':'restore_command is defined and restore_command | length > 0'}]}]))
            args=list(args);args[3]=str(play);args+=['-e','ansible_connection=local','-e','ansible_become=false']
            return original_popen(args,**kwargs)
        with patch('app.runner.subprocess.Popen',side_effect=local_popen):
            job_id='fixture-restore'
            self.app.state.store.state['jobs'].insert(0,{'id':job_id,'lab_id':lab['id'],'lab_name':lab['name'],'status':'queued','operation':'backup','nodes':[]})
            self.app.state.runner.execute(job_id,copy.deepcopy(raw),nodes,'backup')
        state=self.app.state.store.snapshot()
        job=next(j for j in state['jobs'] if j['id']==job_id)
        self.assertEqual(job['status'],'succeeded',job)
        outcomes={o['name']:o for o in job['nodes']}
        junos=outcomes[junos_node['name']]; eos=outcomes[eos_node['name']]
        self.assertEqual(junos['status'],'succeeded',junos); self.assertEqual(eos['status'],'succeeded',eos)
        folder=Path(self.tmp.name)/'backups'/lab['id']/'latest'
        self.assertTrue(junos['restore_file'].endswith('.jcfg'),junos)
        self.assertEqual(junos['restore_format'],'junos-hierarchical')
        self.assertIn('host-name fixture-junos;',(folder/junos['restore_file']).read_text())
        self.assertIn('set system host-name fixture-junos',(folder/junos['file']).read_text())
        self.assertTrue(eos['restore_file'].endswith('.eoscfg'),eos)
        self.assertEqual(eos['restore_format'],'eos-running-config')
        self.assertEqual((folder/eos['restore_file']).read_bytes(),(folder/eos['file']).read_bytes())
    def test_persistence_and_empty_image(self):
        self.assertEqual(self.client.get('/api/state',headers=self.auth).json()['labs'],[])
        self.upload()
        other=create_app(self.tmp.name)
        self.assertEqual(len(other.state.store.state['labs']),1)
        self.assertEqual(other.state.store.token,self.app.state.store.token)
        other.state.runner.close()
    def test_state_reflects_storage_without_re_slicing_any_job_list(self):
        # Risk review 2, item 2 (finding 7): jobs/git_jobs/restore_jobs/operations are all bounded
        # in storage at write time now (per lab for jobs); /api/state must not slice any of them
        # again on read, since a fixed read-window can cut off a protected entry the write-time
        # trim deliberately kept further back (git_jobs/restore_jobs/operations are oldest-first).
        lab=self.upload()
        jobs=[dict(id=str(i),lab_id=lab['id'],operation='backup',status='succeeded',nodes=[]) for i in range(5)]
        self.app.state.store.state['jobs']=jobs
        self.app.state.store.save()
        data=self.client.get('/api/state',headers=self.auth).json()
        self.assertEqual([j['id'] for j in data['jobs']],['0','1','2','3','4'])
    def test_topology_custom_groups_and_alias_rejection(self):
        custom=b'all:\n  children:\n    custom:\n      hosts:\n        router1:\n          ansible_host: 192.0.2.1\n'
        nodes=parse_inventory(custom,b'{"nodes":{"router1":{"kind":"arista_ceos"}}}')
        self.assertEqual(nodes[0]['platform'],'arista_ceos')
        with self.assertRaises(ValueError): parse_inventory(b'all: &a {children: {loop: *a}}')

class HostCheckTests(unittest.TestCase):
    """DNS rebinding: a page on a name the attacker's DNS controls re-resolves to the manager, so its requests carry
    a matching Host and Origin and Sec-Fetch-Site same-origin. Only the Host name itself can tell them apart."""
    EVIL={'Host':'evil.example:8081','Origin':'http://evil.example:8081','Sec-Fetch-Site':'same-origin'}
    def setUp(self, allowed=''):
        self.tmp=tempfile.TemporaryDirectory()
        with patch.dict('os.environ',{'UI_ALLOWED_HOSTS':allowed}): self.app=create_app(self.tmp.name)
        self.client=TestClient(self.app)
    def tearDown(self):
        self.app.state.runner.close()
        self.client.close()
        self.tmp.cleanup()
    def assertRefused(self, response):
        self.assertEqual(response.status_code,403,response.text)
        self.assertTrue(response.headers['content-type'].startswith('text/plain'))
        self.assertIn('IP address',response.text)
        self.assertIn('UI_ALLOWED_HOSTS',response.text)
        # Both installation routes: the source build reads clab-backup-ui/.env, a prepared image deploy/image.env.
        self.assertIn('clab-backup-ui/.env',response.text)
        self.assertIn('deploy/image.env',response.text)
        self.assertNotIn('evil',response.text)
    def test_rebinding_pair_is_refused_on_api_mutation_and_static_pages(self):
        self.assertRefused(self.client.get('/api/state',headers=self.EVIL))
        self.assertRefused(self.client.get('/api/jobs/x/download',headers=self.EVIL))
        upload=self.client.post('/api/inventory',headers=self.EVIL,data={'name':'Example lab'},files={'inventory':('ansible-inventory.yml',INVENTORY)})
        self.assertRefused(upload)
        self.assertEqual(self.app.state.store.state['labs'],[])
        for path in ('/','/static/index.html','/static/app.js','/vm-connection-guide','/nothing-here'):
            self.assertRefused(self.client.get(path,headers=self.EVIL))
        # The same name without Origin or Sec-Fetch-Site (a plain navigation or a script outside a browser) changes nothing.
        self.assertRefused(self.client.get('/api/state',headers={'Host':'evil.example'}))
    def test_rebinding_pair_is_refused_on_the_terminal_websocket(self):
        from starlette.websockets import WebSocketDisconnect
        with self.assertRaises(WebSocketDisconnect):
            with self.client.websocket_connect('/api/terminal',headers=self.EVIL): pass
        # The terminal's own Origin check still answers an allowed Host as before.
        with self.client.websocket_connect('/api/terminal',headers={'Host':'10.0.0.5:8081','Origin':'http://10.0.0.5:8081'}) as ws:
            ws.send_json({'ticket':'invalid'})
            with self.assertRaises(WebSocketDisconnect) as ctx: ws.receive_json()
            self.assertEqual(ctx.exception.code,1008)
    def test_rebinding_pair_is_refused_on_the_capture_websocket(self):
        from unittest.mock import MagicMock
        from starlette.websockets import WebSocketDisconnect
        from app.capture_sessions import COOKIE
        sessions=MagicMock()
        sessions.headers.side_effect=OSError('relay not reached')
        self.app.state.captures.sessions=sessions
        cookie={'Cookie':COOKIE+'='+'d'*64}
        with self.assertRaises(WebSocketDisconnect):
            with self.client.websocket_connect('/api/capture/sessions/'+'c'*64+'/websockify',headers={**self.EVIL,**cookie}): pass
        sessions.headers.assert_not_called()
        # Control: an IP literal with its own Origin reaches the relay (which then fails on the fake service).
        with self.assertRaises(WebSocketDisconnect):
            with self.client.websocket_connect('/api/capture/sessions/'+'c'*64+'/websockify',headers={'Host':'10.0.0.5:8081','Origin':'http://10.0.0.5:8081',**cookie}): pass
        sessions.headers.assert_called_once()
    def test_names_no_outside_dns_controls_pass(self):
        for host in ('10.0.0.5:8081','10.0.0.5','127.0.0.1:8081','[fd00::5]:8081','[::1]','localhost:8081','LOCALHOST',
                     'testserver','clab-vm:8081','Clab-VM','clab-vm.local:8081','lab.vm.local'):
            origin='http://'+host
            r=self.client.get('/api/state',headers={'Host':host,'Origin':origin,'Sec-Fetch-Site':'same-origin'})
            self.assertEqual(r.status_code,200,host)
            self.assertEqual(self.client.get('/',headers={'Host':host}).status_code,200,host)
        # The Origin guard is unchanged behind it: an allowed Host with a foreign Origin is still refused.
        r=self.client.get('/api/state',headers={'Host':'10.0.0.5:8081','Origin':'http://evil.example:8081'})
        self.assertEqual(r.status_code,403)
        self.assertEqual(r.json()['detail'],'Use this manager from its own browser page.')
    def test_dns_names_and_malformed_hosts_are_refused(self):
        for host in ('evil.example','evil.example.','manager.example.edu:8081','10.0.0.5.evil.example','localhost.evil.example',
                     'x.local.evil.example','1.2.3.999','[fd00::5','[evil.example]:8081','fd00::5','10.0.0.5:http',
                     '10.0.0.5:123456','user@10.0.0.5','10.0.0.5/x','','*'):
            self.assertRefused(self.client.get('/api/state',headers={'Host':host}))
    def test_forwarded_host_changes_nothing(self):
        self.assertRefused(self.client.get('/api/state',headers={**self.EVIL,'X-Forwarded-Host':'10.0.0.5:8081'}))
        r=self.client.get('/api/state',headers={'Host':'10.0.0.5:8081','X-Forwarded-Host':'evil.example:8081'})
        self.assertEqual(r.status_code,200)
    def test_configured_names_pass(self):
        self.tearDown()
        self.setUp(' Manager.Example.edu:8081 , other.example,, not a name ')
        for host in ('manager.example.edu:8081','MANAGER.EXAMPLE.EDU','manager.example.edu:443','other.example'):
            r=self.client.get('/api/state',headers={'Host':host,'Origin':'http://'+host,'Sec-Fetch-Site':'same-origin'})
            self.assertEqual(r.status_code,200,host)
        self.assertRefused(self.client.get('/api/state',headers=self.EVIL))
        self.assertRefused(self.client.get('/api/state',headers={'Host':'sub.manager.example.edu'}))

class HostCheckMiddlewareTests(unittest.TestCase):
    """The pure ASGI layer on its own: a missing or repeated Host, lifespan pass-through, WebSocket refusal."""
    def call(self, scope_type, headers, allowed=()):
        import asyncio
        from app.allowed_hosts import HostCheck
        reached=[]; sent=[]
        async def inner(scope, receive, send): reached.append(scope['type'])
        async def receive(): return {'type':scope_type+'.connect' if scope_type=='websocket' else 'http.request','body':b''}
        async def send(message): sent.append(message)
        scope={'type':scope_type,'path':'/api/state','headers':[(k.encode('latin-1'),v.encode('latin-1')) for k,v in headers]}
        asyncio.run(HostCheck(inner,allowed=allowed)(scope,receive,send))
        return reached,sent
    def test_missing_repeated_and_non_ascii_hosts_are_refused(self):
        for headers in ([],[('host','10.0.0.5'),('host','evil.example')],[('host','10.0.0.5'),('host','10.0.0.5')],[('host','réseau')]):
            reached,sent=self.call('http',headers)
            self.assertEqual(reached,[],headers)
            self.assertEqual(sent[0]['status'],403,headers)
            reached,sent=self.call('websocket',headers)
            self.assertEqual(reached,[],headers)
            self.assertEqual(sent,[{'type':'websocket.close','code':1008}],headers)
    def test_allowed_host_and_lifespan_pass_through(self):
        self.assertEqual(self.call('http',[('host','10.0.0.5:8081')])[0],['http'])
        self.assertEqual(self.call('websocket',[('host','clab-vm')])[0],['websocket'])
        self.assertEqual(self.call('lifespan',[])[0],['lifespan'])
        self.assertEqual(self.call('http',[('host','manager.example.edu')],allowed=('manager.example.edu',))[0],['http'])
    def test_configured_hosts_parsing(self):
        from app.allowed_hosts import configured_hosts
        self.assertEqual(configured_hosts(' Manager.Example.edu:8081 , other.example,,[fd00::5]:8081, not a name,*'),
                         frozenset({'manager.example.edu','other.example','[fd00::5]'}))
        self.assertEqual(configured_hosts(''),frozenset())
        self.assertEqual(configured_hosts(None),frozenset())

if __name__=='__main__': unittest.main()
