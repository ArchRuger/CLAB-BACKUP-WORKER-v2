import copy
import hashlib
import json
from pathlib import Path
import tempfile
import time
import sys
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from app.host_operations import HostOperations, LIFECYCLE, digest, capture, stream
from app.lab_operations import LabOperations, scrub, drawio, sharing_links
from app.store import Store
import test_discovery as discovery_tests
from test_discovery import YAML


class HostOperationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)
        self.path = self.root/'training.clab.yaml'; self.path.write_bytes(YAML)
        self.rows = {'training': [dict(name='clab-training-r1', lab_name='training', state='running', container_id='original', absLabPath=str(self.path))]}
        self.missing = set(); self.calls = []
        def run(argv):
            self.calls.append(argv)
            if '--help' in argv: return (1, '') if argv[1] in self.missing else (0, '--name --cleanup --graceful help')
            if argv[1:2] == ['inspect']: return 0, json.dumps(self.rows)
            return 0, 'fixture'
        self.host = HostOperations(dict(clab='/usr/bin/containerlab', docker='/usr/bin/docker', git='/usr/bin/git', roots=[str(self.root)], projects=str(self.root), network=True, sharing=True), run)

    def tearDown(self): self.tmp.cleanup()
    def request(self, action, **options): return dict(action=action, name='training', path=str(self.path), options=options)
    def test_lifecycle_exact_scoped_argv_and_capabilities(self):
        for action in LIFECYCLE:
            plan = self.host.plan(self.request(action))
            self.assertEqual(plan['argv'][:4], ['/usr/bin/containerlab',action,'-t',str(self.path)])
            self.assertIn('--name',plan['argv']); self.assertEqual(plan['affected'][0]['id'],'original')
        self.missing.add('apply'); self.assertFalse(self.host.capabilities()['actions']['apply']['available'])
        with self.assertRaisesRegex(ValueError,'does not support'): self.host.plan(self.request('apply'))

    def test_redeploy_fallback_order_cleanup_and_name(self):
        self.missing.add('redeploy')
        plan=self.host.plan(self.request('redeploy',cleanup=True))
        self.assertEqual([a[1] for a in plan['steps']],['destroy','deploy'])
        self.assertIn('--cleanup',plan['steps'][0]);self.assertNotIn('--cleanup',plan['steps'][1])
        self.assertTrue(self.host.capabilities()['actions']['redeploy']['available'])
        outputs=[];req={**self.request('redeploy',cleanup=True),'digest':plan['digest']}
        with patch('app.host_operations.stream',return_value=7) as stream:
            self.assertEqual(self.host.execute(req,outputs.append)['exit_code'],7)
            self.assertEqual(stream.call_count,1)

    def test_source_state_and_options_changes_invalidate_review(self):
        req=self.request('destroy');req['digest']=self.host.plan(req)['digest']
        for kind in ('source','state','options'):
            self.path.write_bytes(YAML);self.rows['training'][0]['state']='running';req['options']={}
            if kind=='source':self.path.write_bytes(YAML+b'\n# edited')
            if kind=='state':self.rows['training'][0]['state']='exited'
            if kind=='options':req['options']={'cleanup':True}
            with patch('app.host_operations.stream') as stream:
                with self.assertRaisesRegex(ValueError,'changed'):self.host.execute(req,lambda _:None)
                stream.assert_not_called()

    def test_paths_unknown_actions_injection_and_wrong_deployment(self):
        for path in ('relative.yaml',str(self.root.parent/'outside.yaml'),str(self.root/'..'/'bad.yaml')):
            with self.assertRaises(ValueError):self.host.plan({**self.request('deploy'),'path':path})
        for value in ({**self.request('deploy'),'name':'lab; touch /tmp/bad'},self.request('shell'),self.request('deploy',shell=True),self.request('deploy',cleanup='true')):
            with self.assertRaises(ValueError):self.host.plan(value)
        self.rows['training'][0]['absLabPath']=str(self.root/'other.yaml')
        with self.assertRaisesRegex(ValueError,'different topology'):self.host.plan(self.request('destroy'))

    def test_symlink_refused_where_supported(self):
        link=self.root/'linked.yaml'
        try:link.symlink_to(self.path)
        except OSError:self.skipTest('Symlink creation requires Windows privilege')
        with self.assertRaisesRegex(ValueError,'Symlink'):self.host.read(str(link))

    def test_write_delete_recovery_and_deployed_delete_refusal(self):
        with self.assertRaisesRegex(ValueError,'Destroy'):self.host.plan(self.request('delete'))
        changed=YAML.decode()+'\n# replacement\n';req=self.request('write',text=changed);req['digest']=self.host.plan(req)['digest']
        result=self.host.execute(req,lambda _:None)
        self.assertEqual(self.path.read_text(),changed);self.assertEqual(Path(result['recovery_path']).read_bytes(),YAML)
        self.rows={};req=self.request('delete');req['digest']=self.host.plan(req)['digest']
        result=self.host.execute(req,lambda _:None)
        self.assertFalse(self.path.exists());self.assertEqual(Path(result['recovery_path']).read_text(),changed)

    def test_create_never_overwrites_and_limits_reads(self):
        req={**self.request('create',text=YAML.decode()),'path':str(self.root/'new.yaml')};req['digest']=self.host.plan(req)['digest']
        self.host.execute(req,lambda _:None)
        with self.assertRaises(ValueError):self.host.plan(req)
        self.path.write_bytes(b'x'*(1024*1024+1))
        with self.assertRaises(ValueError):self.host.read(str(self.path))

    def test_clone_and_optional_tools_are_bounded(self):
        req=self.request('clone',url='https://github.com/srl-labs/example',project='example');plan=self.host.plan(req)
        self.assertIn('--',plan['argv']);self.assertEqual(plan['path'],str(self.root/'example'))
        for url in ('https://user:pass@host/repo','file:///tmp/repo','https://host/repo?token=secret','https://host/repo\n'):
            with self.assertRaises(ValueError):self.host.plan(self.request('clone',url=url,project='example'))
        self.host.config['network']=False
        with self.assertRaises(ValueError):self.host.plan(req)
        self.assertEqual(self.host.plan(self.request('gotty-attach',port=8082))['argv'][-2:],['--port','8082'])
        with self.assertRaises(ValueError):self.host.plan(self.request('gotty-attach',port=22))
        self.host.config['sharing']=False
        with self.assertRaises(ValueError):self.host.plan(self.request('sshx-attach'))
        plan=self.host.plan(self.request('fcli',query='bgp-peers --format json',network='clab'))
        self.assertEqual(plan['argv'][-3:],['bgp-peers','--format','json']);self.assertIn('never',plan['argv'])
        self.assertTrue(any(arg.endswith(':/topo.yml:ro') for arg in plan['argv']))
        with self.assertRaises(ValueError):self.host.plan(self.request('fcli',query='--privileged'))

    def test_inspection_stderr_does_not_corrupt_json(self):
        code, out=capture([sys.executable,'-c','import sys; print("[]"); print("INFO inspection",file=sys.stderr)'],cwd=str(self.root))
        self.assertEqual(code,0);self.assertEqual(json.loads(out),[])

    def test_disconnect_terminates_streaming_subprocess(self):
        marker=self.root/'must-not-run.txt'
        code='import time,pathlib; print("started",flush=True); time.sleep(3); pathlib.Path('+repr(str(marker))+').write_text("unexpected")'
        def emit(value):raise BrokenPipeError('Disconnected fixture')
        with self.assertRaises(BrokenPipeError):stream([sys.executable,'-u','-c',code],str(self.root),emit)
        self.assertFalse(marker.exists())


class OperationAPITests(unittest.TestCase):
    setUp = discovery_tests.DiscoveryTests.setUp
    register = discovery_tests.DiscoveryTests.register
    host = discovery_tests.DiscoveryTests.host
    def tearDown(self):
        self.app.state.operations.close();discovery_tests.DiscoveryTests.tearDown(self)

    def fixture(self):
        self.host();lab=self.register();self.lab_id=lab['id']
        self.store.lab(lab['id'])['vm_project_path']='/etc/containerlab/training.clab.yaml'
        self.store.state['host']['fingerprint']='SHA256:fixture'
        self.raw=YAML
        def remote(host,req,*args):
            if req['mode']=='read':return dict(text=self.raw.decode(),sha256=hashlib.sha256(self.raw).hexdigest())
            if req['mode']=='preview':return dict(action=req['action'],name=req['name'],path=req['path'],source_hash=hashlib.sha256(self.raw).hexdigest(),digest=digest(req),warnings=[],affected=[],argv=[],steps=[])
            if req['mode']=='run':args[0]('first line\nhost-secret\npassword: should-not-persist\n'+self.store.token+'\n');return dict(exit_code=0)
            return {}
        return patch('app.lab_operations.remote',side_effect=remote)

    def preview(self,action='deploy',**extra):
        response=self.client.post('/api/operations/preview',headers=self.auth,json=dict(action=action,lab_id=self.lab_id,**extra))
        self.assertEqual(response.status_code,200,response.text);return response.json()
    def confirm(self,token):return self.client.post('/api/operations/confirm',headers=self.auth,json={'token':token})

    def test_auth_review_cancel_and_single_use_confirmation(self):
        with self.fixture(),patch.object(self.app.state.operations.pool,'submit') as submit:
            self.assertEqual(self.client.get('/api/operations/capabilities').status_code,401)
            preview=self.preview();self.assertEqual(self.store.state['operations'],[])
            response=self.confirm(preview['token']);self.assertEqual(response.status_code,200,response.text)
            self.assertEqual(self.confirm(preview['token']).status_code,409);submit.assert_called_once()
            self.assertEqual(Store(self.tmp.name).state['operations'][0]['status'],'queued')

    def test_host_revision_expiry_and_backup_conflicts(self):
        with self.fixture(),patch.object(self.app.state.operations.pool,'submit') as submit:
            preview=self.preview();self.store.state['host']['revision']='new';self.assertEqual(self.confirm(preview['token']).status_code,409)
            preview=self.preview();self.app.state.operations.previews[preview['token']]['expires']=0;self.assertEqual(self.confirm(preview['token']).status_code,409)
            preview=self.preview();self.store.state['jobs'].append(dict(id='b',lab_id=self.lab_id,status='running'))
            self.assertEqual(self.confirm(preview['token']).status_code,409);submit.assert_not_called()

    def test_pending_operation_blocks_changes_and_backup(self):
        with self.fixture(),patch.object(self.app.state.operations.pool,'submit'):
            self.confirm(self.preview()['token'])
            response=self.client.request('DELETE','/api/labs/'+self.lab_id,headers=self.auth,json={'name':'training'})
            self.assertEqual(response.status_code,409)
            response=self.client.post('/api/lab-definitions',headers=self.auth,files={'definition':('x.yaml',YAML)})
            self.assertEqual(response.status_code,409)
            response=self.client.put('/api/labs/'+self.lab_id+'/operations-settings',headers=self.auth,json={'favorite':True})
            self.assertEqual(response.status_code,409)
            with self.assertRaisesRegex(ValueError,'operation'):self.app.state.runner.submit(self.lab_id,'backup')

    def test_output_redaction_persistence_and_restart(self):
        with self.fixture(),patch.object(self.service,'refresh'),patch.object(self.app.state.operations.pool,'submit') as submit:
            job=self.confirm(self.preview()['token']).json();args=submit.call_args.args
            args[0](*args[1:])
            saved=self.store.state['operations'][0];self.assertEqual(saved['status'],'succeeded');self.assertIn('first line',saved['output'])
            for secret in ('host-secret','should-not-persist',self.store.token):self.assertNotIn(secret,saved['output'])
            self.assertNotIn('output',self.client.get('/api/state',headers=self.auth).json()['operations'][0])
            self.assertEqual(Store(self.tmp.name).state['operations'][0]['status'],'succeeded')
            saved['status']='running';self.store.save()
            second=LabOperations(self.store,self.service);second.close();self.assertEqual(saved['status'],'interrupted')

    def test_yaml_validation_diff_stale_source_and_name_override(self):
        with self.fixture():
            changed=YAML.decode()+'\n# edit\n';preview=self.preview('write',options={'text':changed});self.assertIn('+# edit',preview['diff'])
            response=self.client.post('/api/operations/preview',headers=self.auth,json=dict(action='write',lab_id=self.lab_id,options={'text':changed.replace('name: training','name: other')}))
            self.assertEqual(response.status_code,400)
            self.store.lab(self.lab_id)['deployment_name']='training-override'
            preview=self.preview('write',options={'text':changed});self.assertEqual(preview['name'],'training-override')

    def test_layout_drawio_favorite_and_no_vm_mutation(self):
        with self.fixture():
            lab=self.store.lab(self.lab_id);alias=lab['drawing']['nodes'][0]['alias']
            response=self.client.put('/api/labs/'+self.lab_id+'/layout',headers=self.auth,json={'positions':{alias:[600,300]}})
            self.assertEqual(response.status_code,200,response.text)
            for layout in ('interactive','horizontal','vertical'):
                response=self.client.get('/api/labs/'+self.lab_id+'/drawio?layout='+layout,headers=self.auth)
                self.assertEqual(response.status_code,200);root=ET.fromstring(response.content)
                self.assertEqual(len(root.findall('.//mxCell[@vertex="1"]')),2)
                self.assertEqual(len(root.findall('.//mxCell[@edge="1"]')),1)
            response=self.client.put('/api/labs/'+self.lab_id+'/operations-settings',headers=self.auth,json={'favorite':True})
            self.assertEqual(response.status_code,200);self.assertTrue(Store(self.tmp.name).lab(self.lab_id)['favorite'])
            self.assertEqual(self.store.state['operations'],[])

    def test_secrets_multiline_private_key_and_output_limit(self):
        state={'labs':[],'host':{'password':'verysecret'}}
        result=scrub('verysecret\n-----BEGIN RSA PRIVATE KEY-----\nabc\ndef\n-----END RSA PRIVATE KEY-----\nokay',state)
        self.assertNotIn('abc',result);self.assertNotIn('verysecret',result);self.assertIn('okay',result)
        self.assertLessEqual(len(scrub('x'*600000,state)),512*1024)

    def test_gotty_json_ports_and_host_ip_placeholder_links(self):
        self.assertEqual(sharing_links('Info\n[{"port":8082}]','gotty-attach',{'address':'127.0.0.1'}),['http://HOST_IP:8082'])
        self.assertEqual(sharing_links('http://HOST_IP:8082','gotty-reattach',{'address':'2001:db8::1'}),['http://[2001:db8::1]:8082'])
        self.assertEqual(sharing_links('http://user:secret@example.test','sshx-attach',{'address':'host'}),[])

    def test_failed_persistent_save_keeps_review_and_does_not_submit(self):
        with self.fixture(),patch.object(self.app.state.operations.pool,'submit') as submit:
            preview=self.preview();original=list(self.store.state['operations'])
            # Fail only the operation save; permit the request audit write.
            with patch.object(self.store,'save',side_effect=OSError('disk fixture')):
                self.assertEqual(self.confirm(preview['token']).status_code,500)
            self.assertEqual(self.store.state['operations'],original)
            self.assertIn(preview['token'],self.app.state.operations.previews);submit.assert_not_called()

    def test_fcli_rejects_incompatible_lab_and_uses_current_vm_network(self):
        with self.fixture() as remote:
            response=self.client.post('/api/operations/preview',headers=self.auth,json=dict(action='fcli',lab_id=self.lab_id))
            self.assertEqual(response.status_code,400)
            self.store.lab(self.lab_id)['nodes'][0]['kind']='nokia_srlinux'
            self.raw=YAML+b'\nmgmt:\n  network: training-network\n'
            self.preview('fcli',options={'query':'lldp'})
            req=next(c.args[1] for c in reversed(remote.call_args_list) if c.args[1]['mode']=='preview')
            self.assertEqual(req['options']['network'],'training-network')
