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

    def test_ipv4_not_available_does_not_hide_an_ipv6_address(self):
        # AUDIT-2026-10-03 L-5: the sentinel check ran after the fallback choice, so a truthy 'N/A' won.
        for v4 in ('N/A','-','',None):
            data=json.loads(response());data['training'][0].update(ipv4_address=v4,ipv6_address='2001:db8::1/64')
            self.assertEqual(parse_inspect(json.dumps(data).encode())['training'][0]['address'],'2001:db8::1',repr(v4))
        data=json.loads(response());data['training'][0].update(ipv4_address='172.20.20.2/24',ipv6_address='2001:db8::1/64')
        self.assertEqual(parse_inspect(json.dumps(data).encode())['training'][0]['address'],'172.20.20.2','IPv4 still wins when both exist')
        data=json.loads(response());data['training'][0].update(ipv4_address='172.20.20.2/24',ipv6_address='N/A')
        self.assertEqual(parse_inspect(json.dumps(data).encode())['training'][0]['address'],'172.20.20.2')
        data=json.loads(response());data['training'][0].update(ipv4_address='N/A',ipv6_address='N/A')
        self.assertEqual(parse_inspect(json.dumps(data).encode())['training'][0]['address'],'')

    def test_lab_name_prefix_gives_lab_dash_node_container_names(self):
        # AUDIT-2026-10-03 M-1: containerlab names containers <lab>-<node> for `prefix: __lab-name`.
        from app.discovery import expected_container, reconcile
        parsed=parse_definition(b'prefix: __lab-name\n'+YAML)
        self.assertEqual(parsed['prefix'],'__lab-name','the stored prefix value stays exactly as written')
        self.assertEqual([n['name'] for n in parsed['nodes']],['training-r1','training-r2'])
        lab=dict(deployment_name='training',container_prefix='__lab-name')
        self.assertEqual(expected_container(lab,dict(name='x',definition_node='r1')),'training-r1')
        rows=[dict(lab_name='training',name='training-r1',state='running',kind='cisco_xrv9k',ipv4_address='172.20.20.2/24'),
              dict(lab_name='training',name='training-r2',state='running',kind='juniper_cjunosevolved',ipv4_address='172.20.20.3/24')]
        nodes=[dict(name='__lab-name-training-r1',definition_node='r1',endpoint_mode='auto'),dict(name='__lab-name-training-r2',definition_node='r2',endpoint_mode='auto')]
        state={'labs':[dict(id='l',deployment_name='training',container_prefix='__lab-name',nodes=nodes)],
               'discovery':{'labs':parse_inspect(json.dumps({'training':rows}).encode())}}
        reconcile(state)
        self.assertEqual([n['runtime_state'] for n in nodes],['running','running'])
        self.assertEqual([n['discovered_address'] for n in nodes],['172.20.20.2','172.20.20.3'])
        # A lab saved before the fix keeps loading: its nodes carry the old composed name, matched through definition_node.
        self.assertTrue(all(n['discovered'] for n in nodes))
        # other prefixes are unchanged
        self.assertEqual(parse_definition(b'prefix: custom\n'+YAML)['nodes'][0]['name'],'custom-training-r1')
        self.assertEqual(parse_definition(YAML)['nodes'][0]['name'],'clab-training-r1')

    def test_setup_seed_with_an_unhashable_command_mode_is_ignored_not_fatal(self):
        # AUDIT-2026-10-03 L-4: a list or dict raised TypeError out of Discovery.start().
        from app.discovery import validate_host_bootstrap, consume_host_bootstrap, BOOTSTRAP_FILE
        def seed(mode):
            return {'schema':1,'created':'2026-09-23T10:00:00+00:00','password':'pw-from-setup',
                    'fingerprint':'','host':{'address':'127.0.0.1','port':22,'username':'clab-discovery','auth':'password','command_mode':mode,'enabled':True}}
        for mode in (['shell'],{'a':1},None,7,3.5,True):
            with self.assertRaises(ValueError,msg=repr(mode)):validate_host_bootstrap(seed(mode))
        self.assertEqual(validate_host_bootstrap(seed('helper'))['host']['command_mode'],'helper')
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(tmp)
            for mode in (['shell'],{'a':1}):
                path=Path(tmp)/BOOTSTRAP_FILE;path.write_text(json.dumps(seed(mode)));path.chmod(0o600)
                consume_host_bootstrap(store)
                self.assertFalse(path.exists(),'a hostile seed is removed, not retried on every start')
                self.assertNotIn('host',store.state)

    def test_setup_seed_with_an_out_of_range_date_or_deep_nesting_is_ignored_not_fatal(self):
        # AUDIT-2026-10-03 L-4 review: OverflowError from astimezone() and RecursionError from json.loads
        # escaped the ValueError handlers and crash-looped startup just like the unhashable command_mode.
        from app.discovery import validate_host_bootstrap, consume_host_bootstrap, read_host_bootstrap, BOOTSTRAP_FILE, BOOTSTRAP_MAX
        good={'schema':1,'created':'2026-09-23T10:00:00+00:00','password':'pw-from-setup',
              'fingerprint':'','host':{'address':'127.0.0.1','port':22,'username':'clab-discovery','auth':'password','command_mode':'helper','enabled':True}}
        for created in ('0001-01-01T00:00:00+14:00','9999-12-31T23:59:59-14:00'):
            with self.assertRaises(ValueError,msg=created) as caught:validate_host_bootstrap({**good,'created':created})
            self.assertIn('unsupported shape',str(caught.exception))
        deep=b'['*30000
        self.assertLess(len(deep),BOOTSTRAP_MAX)
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(tmp);path=Path(tmp)/BOOTSTRAP_FILE
            path.write_bytes(deep);path.chmod(0o600)
            with self.assertRaises(ValueError) as caught:read_host_bootstrap(str(path))
            self.assertIn('not valid JSON',str(caught.exception))
            for raw in (deep,json.dumps({**good,'created':'0001-01-01T00:00:00+14:00'}).encode()):
                path.write_bytes(raw);path.chmod(0o600)
                self.assertIsNone(consume_host_bootstrap(store))
                self.assertFalse(path.exists(),'a malformed seed is removed, not retried on every start')
                self.assertNotIn('host',store.state)

    def test_container_status_uptime_and_expected_container_names(self):
        from app.discovery import uptime_seconds, expected_container
        data=json.loads(response());data['training'][0]['status']='Up 12 minutes (healthy)'
        parsed=parse_inspect(json.dumps(data).encode())['training']
        self.assertEqual(parsed[0]['status'],'Up 12 minutes (healthy)');self.assertNotIn('status',parsed[1],'an inspect without a status line still parses')
        data['training'][0]['status']='x'*200;self.assertNotIn('status',parse_inspect(json.dumps(data).encode())['training'][0],'an odd status line is dropped, never fatal')
        for status,seconds in (('Up Less than a second',0),('Up 1 second',1),('Up 45 seconds',45),('Up About a minute',60),('Up 12 minutes',720),('Up 12 minutes (healthy)',720),('Up 59 minutes (health: starting)',3540)):
            self.assertEqual(uptime_seconds(status),seconds,status)
        for status in ('Up About an hour','Up 2 hours','Up 3 days','Exited (0) 5 minutes ago','Created','Paused',None,'','Up'):
            self.assertIsNone(uptime_seconds(status),status)
        lab=dict(deployment_name='training',container_prefix='clab')
        self.assertEqual(expected_container(lab,dict(name='x',definition_node='r1')),'clab-training-r1')
        self.assertEqual(expected_container(dict(deployment_name='training',container_prefix=''),dict(name='x',definition_node='r1')),'r1')
        self.assertEqual(expected_container(dict(deployment_name='training'),dict(name='x',short_name='r1')),'clab-training-r1')
        self.assertEqual(expected_container(dict(deployment_name='training',container_prefix='lab'),dict(name='x',definition_node='r1',short_name='R1')),'lab-training-r1','the topology node name wins over a renamed short name')
        self.assertEqual(expected_container(lab,dict(name='x')),'');self.assertEqual(expected_container(dict(),dict(name='x',definition_node='r1')),'')
        # reconcile carries the status line onto the node, and drops it with the container.
        from app.discovery import reconcile
        data['training'][0]['status']='Up 12 minutes (healthy)'
        nodes=[dict(name='clab-training-r1',definition_node='r1',endpoint_mode='auto'),dict(name='clab-training-r2',definition_node='r2',endpoint_mode='auto')]
        state={'labs':[dict(id='l',deployment_name='training',container_prefix='clab',nodes=nodes)],'discovery':{'labs':parse_inspect(json.dumps(data).encode())}}
        reconcile(state);self.assertEqual(nodes[0]['runtime_status'],'Up 12 minutes (healthy)');self.assertEqual(nodes[1]['runtime_status'],'');self.assertEqual(nodes[0]['runtime_state'],'running')
        state['discovery']['labs']={};reconcile(state);self.assertEqual((nodes[0]['runtime_status'],nodes[0]['runtime_state']),('','absent'))

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

    def test_a_node_takes_its_kind_and_settings_from_its_group_before_the_defaults(self):
        text=b'name: grouped\ntopology:\n  defaults:\n    kind: arista_ceos\n    mgmt-ipv4: 10.0.0.9\n  groups:\n    spines:\n      kind: juniper_vjunosswitch\n      mgmt-ipv4: 10.0.0.7\n  nodes:\n    leaf1: {}\n    spine1:\n      group: spines\n    spine2:\n      group: spines\n      kind: cisco_xrv9k\n      mgmt-ipv4: 10.0.0.8\n    lost:\n      group: missing\n'
        nodes={n['short_name']:n for n in parse_definition(text)['nodes']}
        self.assertEqual([nodes[n]['platform'] for n in ('leaf1','spine1','spine2','lost')],['arista_ceos','juniper_vjunosswitch','cisco_xrv9k','arista_ceos'])
        self.assertEqual([nodes[n]['address'] for n in ('leaf1','spine1','spine2')],['10.0.0.9','10.0.0.7','10.0.0.8'])
        with self.assertRaisesRegex(ValueError,'mappings'):parse_definition(text.replace(b'  groups:\n    spines:\n      kind: juniper_vjunosswitch\n      mgmt-ipv4: 10.0.0.7\n',b'  groups: [a]\n'))

    def test_vm_host_key_pinning(self):
        first=paramiko.RSAKey.generate(1024);second=paramiko.RSAKey.generate(1024)
        client=paramiko.SSHClient();policy=PinnedHostKey('')
        policy.missing_host_key(client,'localhost',first)
        PinnedHostKey(policy.fingerprint).missing_host_key(client,'localhost',first)
        with self.assertRaisesRegex(ValueError,'host key changed'):
            PinnedHostKey(policy.fingerprint).missing_host_key(client,'localhost',second)


class HostBootstrapDiscoveryTests(unittest.TestCase):
    """A connection typed in the dialog behaves as before the VM setup seed existed."""
    setUp = DiscoveryTests.setUp
    tearDown = DiscoveryTests.tearDown
    host = DiscoveryTests.host
    poll = DiscoveryTests.poll

    def test_typed_connection_reports_no_setup_prefill_and_still_connects(self):
        self.assertIsNone(self.service.public()['host'])
        public=self.host()['host']
        self.assertEqual((public['bootstrap_pending'],public['bootstrap_at'],public['bootstrap_fingerprint'],public['password_saved']),
                         (False,None,None,True))
        self.assertNotIn('password',public)
        result=self.poll()
        self.assertTrue(result['connected'])
        self.assertEqual(self.store.state['host']['fingerprint'],'SHA256:fixture')
        self.assertNotIn('bootstrap_verify',self.store.state['host'])

    def test_without_a_seed_the_host_key_rules_are_unchanged(self):
        from app.discovery import host_key_policy
        self.assertEqual(host_key_policy({}).expected,'')
        self.assertFalse(host_key_policy({'fingerprint':'SHA256:pinned'}).recorded_by_setup)
        self.host();self.poll()
        self.host(password='');self.assertEqual(self.store.state['host']['fingerprint'],'SHA256:fixture')
        self.host(password='',reset_fingerprint=True);self.assertEqual(self.store.state['host']['fingerprint'],'')
        self.assertEqual(host_key_policy(self.store.state['host']).expected,'')


class ParsedDefinitionImageTests(unittest.TestCase):
    """parse_definition carries each node's image, the source image-based logins key on."""

    def test_image_comes_from_the_node_its_kind_or_the_topology_defaults(self):
        text=(b'name: mixed\ntopology:\n'
              b'  defaults:\n    image: registry.example/default:1\n'
              b'  kinds:\n    linux:\n      image: registry.example/kind:1\n'
              b'  nodes:\n'
              b'    own:\n      kind: linux\n      image: registry.example/own:1\n'
              b'    fromkind:\n      kind: linux\n'
              b'    fromdefaults:\n      kind: cisco_xrv9k\n'
              b'    noimage:\n      kind: cisco_xrv9k\n      image: ""\n')
        # "image: ''" is falsy: parse_definition treats it the same as an absent key.
        nodes={n['short_name']:n for n in parse_definition(text)['nodes']}
        self.assertEqual(nodes['own']['image'],'registry.example/own:1')
        self.assertEqual(nodes['fromkind']['image'],'registry.example/kind:1')
        self.assertEqual(nodes['fromdefaults']['image'],'registry.example/default:1')
        # An explicit empty image on the node itself overrides the topology default,
        # the same way containerlab's own settings merge behaves for any other field.
        self.assertEqual(nodes['noimage']['image'],'')

    def test_a_node_without_any_image_setting_gets_an_empty_string(self):
        nodes={n['short_name']:n for n in parse_definition(YAML)['nodes']}
        self.assertEqual(nodes['r1']['image'],'')
        self.assertEqual(nodes['r2']['image'],'')

    def test_a_non_string_or_template_image_is_rejected_or_dropped(self):
        # A numeric image setting is not a valid reference; parse_definition treats
        # anything that is not a non-empty string as no image, rather than failing
        # the whole upload over an unrelated field.
        text=YAML.replace(b'    r1: {}\n',b'    r1: {image: 4}\n')
        nodes={n['short_name']:n for n in parse_definition(text)['nodes']}
        self.assertEqual(nodes['r1']['image'],'')
        # A template or oversized image string is dropped the same way: an odd image
        # value never blocks the whole topology (only the login default is lost).
        nodes={n['short_name']:n for n in parse_definition(YAML.replace(b'    r1: {}\n',b'    r1: {image: "{{ img }}"}\n'))['nodes']}
        self.assertEqual(nodes['r1']['image'],'')
