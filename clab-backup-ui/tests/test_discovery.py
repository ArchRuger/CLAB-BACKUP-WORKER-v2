import copy
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from app.main import create_app
from app.discovery import (parse_definition, parse_inspect, lab_status, automatic_ready,
                           node_available, PinnedHostKey)
from app.store import Store
import paramiko

YAML = b'''name: training
topology:
  defaults:
    kind: cisco_xrv9k
  nodes:
    r1: {}
    r2:
      kind: juniper_cjunosevolved
  links:
    - endpoints: ["r1:Gi0/0/0/1", "r2:eth4"]
'''


def response(name='training', ip='172.20.20.2', second=True):
    rows=[dict(lab_name=name,name='clab-'+name+'-r1',state='running',kind='cisco_xrv9k',ipv4_address=ip+'/24')]
    if second: rows.append(dict(lab_name=name,name='clab-'+name+'-r2',state='running',kind='juniper_cjunosevolved',ipv4_address='172.20.20.3/24'))
    return json.dumps({name:rows}).encode()


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.app=create_app(self.tmp.name)
        self.client=TestClient(self.app)
        self.auth={'Authorization':'Bearer '+self.app.state.store.token}
        self.store=self.app.state.store
        self.service=self.app.state.discovery

    def tearDown(self):
        self.app.state.git_progress.close()
        self.service.close();self.app.state.runner.close();self.app.state.node_services.close()
        self.client.close();self.tmp.cleanup()

    def register(self, raw=YAML, **fields):
        r=self.client.post('/api/lab-definitions',headers=self.auth,data=fields,
                           files={'definition':('training.clab.yaml',raw,'application/yaml')})
        self.assertEqual(r.status_code,200,r.text)
        return r.json()

    def host(self, **changes):
        payload=dict(address='127.0.0.1',port=22,username='fixture',auth='password',password='host-secret')
        payload.update(changes)
        r=self.client.put('/api/host',headers=self.auth,json=payload)
        self.assertEqual(r.status_code,200,r.text)
        return r.json()

    def poll(self, raw=None, error=None):
        with patch('app.discovery.inspect_host',side_effect=error,
                   return_value=(parse_inspect(response() if raw is None else raw),'SHA256:fixture')):
            return self.service.refresh()

    def test_registration_offline_and_discovery_addresses(self):
        lab=self.register()
        self.assertEqual(lab['deployment']['status'],'Unknown')
        self.assertFalse(lab['nodes'][0]['ssh_ready'])
        self.assertEqual(lab['nodes'][0]['platform'],'cisco_xrv9k')
        self.host();self.poll()
        saved=self.store.lab(lab['id'])
        self.assertEqual(lab_status(self.store.state,saved)['status'],'Running')
        self.assertEqual(saved['nodes'][0]['address'],'172.20.20.2')
        self.assertTrue(node_available(self.store.state,saved,saved['nodes'][0]))
        self.assertEqual(len(saved['drawing']['links']),1)

    def test_offline_error_and_missing_lab_do_not_erase_workspace(self):
        lab=self.register();self.host();self.poll()
        saved=self.store.lab(lab['id']);saved['profiles']=[{'id':'p','label':'router','platform':'cisco_xrv9k','username':'clab','auth':'password','password':'device-secret'}]
        self.poll(error=OSError('host-secret should never leak'))
        self.assertEqual(lab_status(self.store.state,saved)['status'],'Unknown')
        self.assertEqual(saved['nodes'][0]['address'],'172.20.20.2')
        self.assertFalse(automatic_ready(self.store.state,saved))
        self.assertNotIn('host-secret',json.dumps(self.service.public()))
        self.poll(raw=b'{}')
        self.assertEqual(lab_status(self.store.state,saved)['status'],'Not deployed')
        self.assertEqual(saved['profiles'][0]['password'],'device-secret')
        self.assertEqual(len(saved['nodes']),2)

    def test_redeploy_preserves_manual_endpoints_and_updates_auto(self):
        lab=self.register();self.host();self.poll()
        saved=self.store.lab(lab['id']);saved['nodes'][1].update(endpoint_mode='manual',address='10.0.0.10',port=30022)
        self.poll(response(ip='172.20.20.88'))
        self.assertEqual(saved['nodes'][0]['address'],'172.20.20.88')
        self.assertEqual((saved['nodes'][1]['address'],saved['nodes'][1]['port']),('10.0.0.10',30022))

    def test_reimport_preserves_identity_credentials_jobs_and_map(self):
        lab=self.register();saved=self.store.lab(lab['id'])
        saved['nodes'][0].update(name='historical-r1',profile_id='p',endpoint_mode='manual',address='10.0.0.2',port=2022)
        saved['drawing']['custom_test']=True
        saved['profiles']=[dict(id='p',label='test',platform='cisco_xrv9k',username='clab',auth='password',password='secret')]
        saved['interval']=5;saved['next_run']=1234
        self.store.state['jobs']=[dict(id='past',lab_id=lab['id'],status='succeeded',nodes=[])]
        result=self.register(lab_id=lab['id'])
        self.assertEqual(result['id'],lab['id'])
        self.assertEqual(result['nodes'][0]['name'],'historical-r1')
        self.assertEqual(result['nodes'][0]['port'],2022)
        self.assertEqual(saved['profiles'][0]['password'],'secret')
        self.assertTrue(saved['drawing']['custom_test'])
        self.assertEqual(saved['next_run'],1234)
        self.assertEqual(self.store.state['jobs'][0]['id'],'past')

    def test_persistence_encryption_and_secret_exclusion(self):
        lab=self.register(YAML+b'# password: example-yaml-secret\n')
        self.host();self.poll();self.store.save()
        saved=Store(self.tmp.name)
        self.assertEqual(saved.state['host']['password'],'host-secret')
        self.assertEqual(saved.lab(lab['id'])['deployment_name'],'training')
        self.assertEqual(saved.token,self.store.token)
        raw=(Path(self.tmp.name)/'state.enc').read_bytes()
        self.assertNotIn(b'host-secret',raw)
        public=self.client.get('/api/state',headers=self.auth).text
        for secret in ('host-secret','example-yaml-secret','definition_yaml','private_key'):
            self.assertNotIn(secret,public)
        self.assertNotIn('host-secret',(Path(self.tmp.name)/'events.jsonl').read_text())

    def test_stale_and_partial_pause_schedules_and_unavailable_node_actions(self):
        lab=self.register();self.host();self.poll(response(second=False))
        saved=self.store.lab(lab['id'])
        self.assertEqual(lab_status(self.store.state,saved)['status'],'Partially running')
        with self.assertRaisesRegex(ValueError,'paused'):
            self.app.state.runner.submit(lab['id'],source='scheduled')
        r=self.client.post('/api/labs/'+lab['id']+'/ssh-check',headers=self.auth,json={'name':saved['nodes'][1]['name']})
        self.assertEqual(r.status_code,409)
        self.poll();self.store.state['discovery']['checked_epoch']=time.time()-100
        self.assertEqual(lab_status(self.store.state,saved)['status'],'Unknown')
        self.assertFalse(node_available(self.store.state,saved,saved['nodes'][0]))

    def test_multiple_active_labs_and_discovered_unregistered_lab(self):
        self.register();self.register(YAML.replace(b'training',b'second'))
        groups={**json.loads(response()),**json.loads(response('second')),**json.loads(response('third'))}
        self.host();self.poll(json.dumps(groups).encode())
        self.assertEqual([lab_status(self.store.state,l)['status'] for l in self.store.state['labs']],['Running','Running'])
        unlinked=[l['name'] for l in self.service.public()['discovered'] if not l['imported']]
        self.assertEqual(unlinked,['third'])

    def test_host_changes_discard_inflight_results_and_keep_secret_on_blank(self):
        self.host();revision=self.store.state['host']['revision']
        self.host(password='')
        self.assertEqual(self.store.state['host']['password'],'host-secret')
        self.assertNotEqual(self.store.state['host']['revision'],revision)
        def change(*args):
            self.store.state['host']['revision']='changed'
            return parse_inspect(response()),'SHA256:old'
        with patch('app.discovery.inspect_host',side_effect=change):self.service.refresh()
        self.assertFalse(self.store.state['discovery']['ok'])

    def test_link_existing_inventory_and_custom_name(self):
        lab=self.register()
        r=self.client.put('/api/labs/'+lab['id']+'/deployment',headers=self.auth,json={'deployed_name':'renamed','prefix':'clab'})
        self.assertEqual(r.status_code,200)
        self.host();self.poll(response('renamed'))
        saved=self.store.lab(lab['id'])
        self.assertEqual(lab_status(self.store.state,saved)['status'],'Running')
        self.assertEqual(saved['nodes'][0]['name'],'clab-training-r1')
        self.assertEqual(saved['nodes'][0]['address'],'172.20.20.2')

    def test_authentication_and_invalid_inputs(self):
        self.assertEqual(self.client.get('/api/discovery', headers={'Origin':'https://other.example'}).status_code,403)
        r=self.client.put('/api/host',headers=self.auth,json=dict(address='localhost;whoami',username='x',password='x'))
        self.assertEqual(r.status_code,400)
        r=self.client.post('/api/lab-definitions',headers=self.auth,files={'definition':('bad.yaml',b'name: x\ntopology: {}')})
        self.assertEqual(r.status_code,400)
        self.assertEqual(self.store.state['labs'],[])

    def test_restart_preserves_workspace_but_requires_fresh_discovery(self):
        lab=self.register();self.host();self.poll();self.store.save()
        other=create_app(self.tmp.name)
        try:
            self.assertEqual(other.state.store.token,self.store.token)
            self.assertEqual(other.state.store.lab(lab['id'])['nodes'][0]['address'],'172.20.20.2')
            self.assertFalse(other.state.discovery.public()['connected'])
            self.assertEqual(lab_status(other.state.store.state,other.state.store.lab(lab['id']))['status'],'Unknown')
        finally:
            other.state.discovery.close();other.state.runner.close();other.state.node_services.close()

    def test_yaml_registration_reuses_unique_legacy_workspace(self):
        lab=self.register();saved=self.store.lab(lab['id'])
        saved.pop('deployment_name')
        saved['nodes'][0].pop('endpoint_mode')
        saved['nodes'][0].update(address='10.1.1.1',port=30022,username='clab',password='saved')
        result=self.register()
        self.assertEqual(result['id'],lab['id'])
        self.assertEqual(len(self.store.state['labs']),1)
        self.assertEqual(saved['nodes'][0]['endpoint_mode'],'manual')
        self.assertEqual(saved['nodes'][0]['port'],30022)
        self.assertEqual(saved['nodes'][0]['password'],'saved')

    def test_invalid_request_never_echoes_secret_input(self):
        secret='private-request-secret'
        r=self.client.put('/api/host',headers=self.auth,json={'address':'127.0.0.1','username':'x','private_key':secret*6000})
        self.assertEqual(r.status_code,422)
        self.assertNotIn(secret,r.text)

    def test_scheduled_backup_resumes_after_lab_returns(self):
        lab=self.register();self.host();self.poll(b'{}')
        saved=self.store.lab(lab['id'])
        for n in saved['nodes']:n.update(username='fixture',password='fixture')
        saved.update(interval=5,next_run=1234)
        with self.assertRaisesRegex(ValueError,'paused'):
            self.app.state.runner.submit(lab['id'],source='scheduled')
        self.poll()
        with patch.object(self.app.state.runner.pool,'submit') as submit:
            job=self.app.state.runner.submit(lab['id'],source='scheduled')
        self.assertEqual(len(job['nodes']),2)
        self.assertEqual(saved['interval'],5)
        self.assertGreater(saved['next_run'],time.time())
        submit.assert_called_once()


class DiscoveryParserTests(unittest.TestCase):
    def test_export_formats_ipv6_and_empty(self):
        data=json.loads(response())
        self.assertEqual(parse_inspect(json.dumps(data['training']).encode()),parse_inspect(response()))
        data['training'][0].update(ipv4_address='',ipv6_address='2001:db8::1/64')
        self.assertEqual(parse_inspect(json.dumps(data).encode())['training'][0]['address'],'2001:db8::1')
        self.assertEqual(parse_inspect(b'{}'),{})
        self.assertEqual(parse_inspect(b'[]'),{})
        for value in (b'not json',b'null',b'{"error":"denied"}'):
            with self.assertRaises(ValueError):parse_inspect(value)

    def test_bad_identity_and_duplicate_entries_fail_closed(self):
        data=json.loads(response());data['training'].append(data['training'][0])
        with self.assertRaises(ValueError):parse_inspect(json.dumps(data).encode())
        data=json.loads(response());data['training'][0]['lab_name']='other'
        with self.assertRaises(ValueError):parse_inspect(json.dumps(data).encode())

    def test_prefix_defaults_and_unresolved_templates(self):
        parsed=parse_definition(b'prefix: ""\n'+YAML)
        self.assertEqual(parsed['nodes'][0]['name'],'r1')
        self.assertEqual(parsed['nodes'][0]['platform'],'cisco_xrv9k')
        with self.assertRaises(ValueError):parse_definition(YAML.replace(b'training',b'${LAB_NAME}'))

    def test_vm_host_key_pinning(self):
        first=paramiko.RSAKey.generate(1024);second=paramiko.RSAKey.generate(1024)
        client=paramiko.SSHClient();policy=PinnedHostKey('')
        policy.missing_host_key(client,'localhost',first)
        PinnedHostKey(policy.fingerprint).missing_host_key(client,'localhost',first)
        with self.assertRaisesRegex(ValueError,'host key changed'):
            PinnedHostKey(policy.fingerprint).missing_host_key(client,'localhost',second)
