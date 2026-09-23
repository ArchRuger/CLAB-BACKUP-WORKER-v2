import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
import sys
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from app.host_operations import HostOperations, LIFECYCLE, digest, capture, stream
from app.lab_operations import LabOperations, scrub, drawio
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
        self.host = HostOperations(dict(clab='/usr/bin/containerlab', docker='/usr/bin/docker', git='/usr/bin/git', roots=[str(self.root)], projects=str(self.root), network=True), run)

    def tearDown(self): self.tmp.cleanup()

    def test_browser_filters_non_topologies_before_entry_limit(self):
        for i in range(505):
            (self.root / f'noise-{i:03}.json').write_text('{}')
        (self.root/'other.clab.yml').write_bytes(YAML)
        (self.root/'training.clab.yaml.annotations.json').write_text('{}')
        (self.root/'ansible-inventory.yml').write_text('all: {}')
        (self.root/'nested').mkdir()
        entries=self.host.browse(str(self.root))['entries']
        self.assertEqual({entry['name'] for entry in entries}, {'training.clab.yaml','other.clab.yml','nested'})
        self.assertTrue(next(e for e in entries if e['name']=='nested')['directory'])

    def request(self, action, **options): return dict(action=action, name='training', path=str(self.path), options=options)
    def test_lifecycle_exact_scoped_argv_and_capabilities(self):
        for action in LIFECYCLE:
            plan = self.host.plan(self.request(action))
            self.assertEqual(plan['argv'][:4], ['/usr/bin/containerlab',action,'-t',str(self.path)])
            self.assertIn('--name',plan['argv']); self.assertEqual(plan['affected'][0]['id'],'original')
        self.missing.add('apply'); self.assertFalse(self.host.capabilities()['actions']['apply']['available'])
        with self.assertRaisesRegex(ValueError,'does not support'): self.host.plan(self.request('apply'))

    def test_grafana_mode_starts_stops_and_inspects_the_named_container_only(self):
        from app.host_operations import GRAFANA_CONTAINER
        states = {'inspect': (0, 'exited\n')}
        def run(argv):
            self.calls.append(argv)
            if argv[1] == 'start': states['inspect'] = (0, 'running\n'); return 0, ''
            if argv[1] == 'stop': states['inspect'] = (0, 'exited\n'); return 0, ''
            if argv[1] == 'inspect': return states['inspect']
            return 1, ''
        host = HostOperations(dict(clab='/usr/bin/containerlab', docker='/usr/bin/docker', roots=[str(self.root)], projects=str(self.root)), run)
        self.assertEqual(host.grafana('status'), {'container': GRAFANA_CONTAINER, 'state': 'exited'})
        self.assertEqual(host.grafana('start'), {'container': GRAFANA_CONTAINER, 'state': 'running'})
        self.assertEqual(host.grafana('stop'), {'container': GRAFANA_CONTAINER, 'state': 'exited'})
        self.assertEqual([a[1:] for a in self.calls], [
            ['inspect', '--type', 'container', '--format', '{{.State.Status}}', GRAFANA_CONTAINER],
            ['start', GRAFANA_CONTAINER], ['inspect', '--type', 'container', '--format', '{{.State.Status}}', GRAFANA_CONTAINER],
            ['stop', '-t', '10', GRAFANA_CONTAINER], ['inspect', '--type', 'container', '--format', '{{.State.Status}}', GRAFANA_CONTAINER]])
        self.assertTrue(all(a[0] == '/usr/bin/docker' for a in self.calls))
        states['inspect'] = (1, '')
        self.assertEqual(host.grafana('status')['state'], 'missing')
        states['inspect'] = (0, 'running; rm -rf /\n')
        self.assertEqual(host.grafana('status')['state'], 'missing', 'only a plain word is reported')
        for action in ('restart', 'rm', '', None, ['start']):
            with self.assertRaisesRegex(ValueError, 'Unsupported Grafana action'): host.grafana(action)
        failing = HostOperations(dict(clab='/usr/bin/containerlab', docker='/usr/bin/docker', roots=[str(self.root)], projects=str(self.root)), lambda argv: (1, ''))
        with self.assertRaisesRegex(ValueError, 'Could not start the Grafana container'): failing.grafana('start')

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
        with self.assertRaisesRegex(ValueError,'Unsupported'): self.host.plan(self.request('write',text='replacement'))
        self.assertEqual(self.path.read_bytes(),YAML)
        self.rows={};req=self.request('delete');req['digest']=self.host.plan(req)['digest']
        result=self.host.execute(req,lambda _:None)
        self.assertFalse(self.path.exists());self.assertEqual(Path(result['recovery_path']).read_bytes(),YAML)

    def test_create_never_overwrites_and_limits_reads(self):
        req={**self.request('create',text=YAML.decode()),'path':str(self.root/'new.yaml')};req['digest']=self.host.plan(req)['digest']
        self.host.execute(req,lambda _:None)
        with self.assertRaises(ValueError):self.host.plan(req)
        self.path.write_bytes(b'x'*(1024*1024+1))
        with self.assertRaises(ValueError):self.host.read(str(self.path))
        # The lab builder tells a file that is not there from a VM it could not ask by this wording
        # (builderAbsent in static/lab-builder-page.js): a missing topology, and a missing lab folder.
        for gone in (self.root/'gone.clab.yml',self.root/'no-folder'/'gone.clab.yml'):
            with self.assertRaisesRegex(ValueError,'no longer exists'):self.host.read(str(gone))

    def test_clone_and_optional_tools_are_bounded(self):
        req=self.request('clone',url='https://github.com/srl-labs/example',project='example');plan=self.host.plan(req)
        self.assertIn('--',plan['argv']);self.assertEqual(plan['path'],str(self.root/'example'))
        for url in ('https://user:pass@host/repo','file:///tmp/repo','https://host/repo?token=secret','https://host/repo\n'):
            with self.assertRaises(ValueError):self.host.plan(self.request('clone',url=url,project='example'))
        self.host.config['network']=False
        with self.assertRaises(ValueError):self.host.plan(req)
        for action in ('write','fcli','sshx-attach','sshx-detach','sshx-reattach','gotty-attach','gotty-detach','gotty-reattach'):
            with self.assertRaises(ValueError): self.host.plan(self.request(action))
            self.assertNotIn(action,self.host.capabilities()['actions'])

    @unittest.skipUnless(os.name == 'posix', 'POSIX file modes')
    def test_created_topology_is_readable_and_group_editable_in_engineer_folders(self):
        import stat as st
        plain = self.root / 'plain.clab.yaml'
        req = {**self.request('create', text=YAML.decode()), 'path': str(plain)}; req['digest'] = self.host.plan(req)['digest']
        self.host.execute(req, lambda _: None)
        self.assertEqual(st.S_IMODE(plain.stat().st_mode), 0o644)
        engineer = self.root / 'engineer'; engineer.mkdir()
        os.chmod(engineer, 0o2775)
        if not engineer.stat().st_mode & st.S_ISGID: self.skipTest('setgid not supported on this filesystem')
        shared = engineer / 'shared.clab.yaml'
        req = {**self.request('create', text=YAML.decode()), 'path': str(shared)}; req['digest'] = self.host.plan(req)['digest']
        self.host.execute(req, lambda _: None)
        self.assertEqual(st.S_IMODE(shared.stat().st_mode), 0o664)
        self.assertEqual(shared.read_bytes(), YAML)

    def test_create_preserves_file_created_after_final_plan(self):
        target = self.root / 'racing.clab.yaml'
        req = {**self.request('create', text=YAML.decode()), 'path': str(target)}
        plan = self.host.plan(req); req['digest'] = plan['digest']
        # A VM editor can create this path after the final plan's existence check.
        def raced_plan(_):
            target.write_bytes(b'operator-created topology')
            return plan
        with patch.object(self.host, 'plan', side_effect=raced_plan):
            with self.assertRaises((ValueError, FileExistsError)):
                self.host.execute(req, lambda _: None)
        self.assertEqual(target.read_bytes(), b'operator-created topology')

    # --- create: an optional map file (uploaded alongside the topology) travels with it -------------

    def test_create_with_a_map_file_writes_it_beside_the_topology_and_the_digest_covers_it(self):
        layout = json.dumps({'nodeAnnotations': [{'id': 'r1', 'position': {'x': 1, 'y': 2}}]})
        target = self.root / 'mapped.clab.yaml'
        req = {**self.request('create', text=YAML.decode(), annotations=layout), 'path': str(target)}
        plan = self.host.plan(req)
        self.assertEqual(plan['warnings'], [])
        bare = self.host.plan({**self.request('create', text=YAML.decode()), 'path': str(target)})
        self.assertNotEqual(plan['digest'], bare['digest'], 'the digest must cover the map layout too')
        self.host.execute({**req, 'digest': plan['digest']}, lambda _: None)
        side = target.with_name(target.name + '.annotations.json')
        self.assertEqual(side.read_text(), layout)
        self.assertEqual(target.read_bytes(), YAML)
        # No annotations option at all: nothing is written beside the topology.
        other = self.root / 'no-map.clab.yaml'
        plain = {**self.request('create', text=YAML.decode()), 'path': str(other)}
        self.host.execute({**plain, 'digest': self.host.plan(plain)['digest']}, lambda _: None)
        self.assertFalse(other.with_name(other.name + '.annotations.json').exists())

    def test_create_rejects_a_map_file_that_is_not_a_json_object_or_is_too_large(self):
        target = self.root / 'bad-map.clab.yaml'
        for layout in ('[1]', '"just text"', 'not json at all', 'x' * (1024 * 1024 + 1)):
            req = {**self.request('create', text=YAML.decode(), annotations=layout), 'path': str(target)}
            with self.assertRaises(ValueError): self.host.plan(req)
        self.assertFalse(target.exists(), 'a refused map file plans no write of the topology either')

    def test_create_never_overwrites_an_existing_map_file_silently(self):
        target = self.root / 'existing-map.clab.yaml'
        side = target.with_name(target.name + '.annotations.json')
        side.write_text('{"nodeAnnotations": [{"id": "old"}]}')
        layout = json.dumps({'nodeAnnotations': [{'id': 'new'}]})
        req = {**self.request('create', text=YAML.decode(), annotations=layout), 'path': str(target)}
        plan = self.host.plan(req)
        self.assertIn('Replaces the existing map file', plan['warnings'][0])
        result = self.host.execute({**req, 'digest': plan['digest']}, lambda _: None)
        self.assertEqual(side.read_text(), layout, 'the new map file is written')
        self.assertEqual(Path(result['layout_recovery_path']).read_text(), '{"nodeAnnotations": [{"id": "old"}]}', 'the previous one is kept, not lost')

    # --- lab builder: publish a new lab folder, revise a lab that is not deployed -------------------
    BUILT = b'name: built\ntopology:\n  nodes:\n    r1:\n      kind: linux\n      image: alpine:latest\n'
    LAYOUT = '{"nodeAnnotations":[{"id":"r1","position":{"x":10,"y":20}}]}'

    def publish(self, name='built', **options):
        options = {'root': str(self.root), 'text': self.BUILT.decode(), 'annotations': self.LAYOUT, **options}
        req = dict(action='publish', name=name, options=options); plan = self.host.plan(req)
        return req, plan

    def test_publish_derives_every_path_and_writes_the_layout_before_the_topology(self):
        req, plan = self.publish(); folder = self.root/'built'
        self.assertEqual(plan['path'], str(folder/'built.clab.yml')); self.assertEqual(plan['files'], ['built.clab.yml', 'built.clab.yml.annotations.json'])
        order = []; place = self.host.place
        with patch.object(self.host, 'place', side_effect=lambda fd, name, *a, **k: (order.append(name), place(fd, name, *a, **k))[1]):
            result = self.host.execute({**req, 'digest': plan['digest']}, lambda _: None)
        self.assertEqual(order, ['built.clab.yml.annotations.json', 'built.clab.yml'])
        self.assertEqual(result['published_path'], plan['path'])
        self.assertEqual((folder/'built.clab.yml').read_bytes(), self.BUILT); self.assertEqual((folder/'built.clab.yml.annotations.json').read_text(), self.LAYOUT)
        self.assertEqual(sorted(p.name for p in folder.iterdir()), plan['files'])
        if os.name == 'posix':
            self.assertEqual((folder/'built.clab.yml').stat().st_mode & 0o777, 0o644); self.assertEqual(folder.stat().st_mode & 0o7777, 0o755)
        self.assertIn(str(folder/'built.clab.yml'), [e['path'] for e in self.host.browse(str(folder))['entries']])
        for bad in (dict(root=str(self.root/'built')), dict(root='/'), dict(root=str(self.root) + '/../x'), dict(text=''), dict(text='x' * (512 * 1024 + 1)), dict(annotations=7)):
            with self.assertRaises(ValueError): self.publish(name='other', **bad)
        with self.assertRaisesRegex(ValueError, 'literal'): self.publish(name='../escape')
        with self.assertRaisesRegex(ValueError, 'Unsupported operation options'): self.host.plan(dict(action='publish', name='x', options={'root': str(self.root), 'text': 'a', 'path': '/etc/passwd'}))

    def test_publish_never_overwrites_and_a_repeat_with_the_same_content_is_a_no_op(self):
        req, plan = self.publish(); self.host.execute({**req, 'digest': plan['digest']}, lambda _: None)
        again = self.host.plan(req); self.assertEqual(again['digest'], plan['digest']); self.assertIn('already saved', again['warnings'][0])
        before = (self.root/'built'/'built.clab.yml').stat().st_mtime_ns
        self.assertEqual(self.host.execute({**req, 'digest': again['digest']}, lambda _: None), {'exit_code': 0, 'already_published': True})
        self.assertEqual((self.root/'built'/'built.clab.yml').stat().st_mtime_ns, before)
        with self.assertRaisesRegex(ValueError, 'already exists'): self.publish(text=self.BUILT.decode() + '# changed\n')
        (self.root/'taken').mkdir(); (self.root/'taken'/'notes.txt').write_text('mine')
        with self.assertRaisesRegex(ValueError, 'already exists'): self.publish(name='taken')
        self.assertEqual((self.root/'taken'/'notes.txt').read_text(), 'mine')

    def test_publish_resumes_only_what_its_own_write_order_can_leave_behind(self):
        folder = self.root/'built'; folder.mkdir(); (folder/'built.clab.yml.annotations.json').write_text(self.LAYOUT); (folder/'.clab-manager-0123').write_text('partial')
        req, plan = self.publish(); self.assertIn('stopped half way', plan['warnings'][0])
        self.assertTrue(self.host.execute({**req, 'digest': plan['digest']}, lambda _: None)['resumed'])
        self.assertEqual(sorted(p.name for p in folder.iterdir()), ['built.clab.yml', 'built.clab.yml.annotations.json'])
        # A topology without the layout that was asked for is a state this helper never produces.
        other = self.root/'other'; other.mkdir(); (other/'other.clab.yml').write_bytes(self.BUILT)
        with self.assertRaisesRegex(ValueError, 'already exists'): self.publish(name='other')

    def test_publish_takes_back_only_its_own_files_when_a_write_fails(self):
        req, plan = self.publish(); place = self.host.place
        def fail_on_topology(fd, name, *a, **k):
            if not name.endswith('.json'): raise OSError('disk full')
            return place(fd, name, *a, **k)
        with patch.object(self.host, 'place', side_effect=fail_on_topology), self.assertRaises(OSError):
            self.host.execute({**req, 'digest': plan['digest']}, lambda _: None)
        self.assertFalse((self.root/'built').exists())
        self.assertEqual(self.host.plan(req)['warnings'], [])

    def test_revise_needs_an_undeployed_lab_the_opened_versions_and_keeps_recovery_copies(self):
        req, plan = self.publish(); self.host.execute({**req, 'digest': plan['digest']}, lambda _: None)
        path = Path(plan['path']); side = Path(plan['path'] + '.annotations.json'); sha = lambda b: hashlib.sha256(b).hexdigest()
        changed = self.BUILT.decode() + '    r2:\n      kind: linux\n'
        revise = lambda **options: dict(action='revise', name='built', path=str(path), options={'text': changed, 'annotations': '{"nodeAnnotations":[]}', 'base': {'yaml': sha(self.BUILT), 'annotations': sha(self.LAYOUT.encode())}, **options})
        with self.assertRaisesRegex(ValueError, 'changed on the VM'): self.host.plan(revise(base={'yaml': 'stale', 'annotations': sha(self.LAYOUT.encode())}))
        with self.assertRaisesRegex(ValueError, 'changed on the VM'): self.host.plan(revise(base={'yaml': sha(self.BUILT), 'annotations': ''}))
        self.rows['built'] = [dict(name='clab-built-r1', lab_name='built', state='running', container_id='x', absLabPath=str(path))]
        with self.assertRaisesRegex(ValueError, 'deployed'): self.host.plan(revise())
        self.rows.pop('built'); self.rows['renamed'] = [dict(name='clab-renamed-r1', lab_name='renamed', state='running', container_id='x', absLabPath=str(path))]
        with self.assertRaisesRegex(ValueError, 'deployed'): self.host.plan(revise())
        self.rows.pop('renamed')
        request = revise(); review = self.host.plan(request); result = self.host.execute({**request, 'digest': review['digest']}, lambda _: None)
        self.assertEqual(path.read_text(), changed); self.assertEqual(side.read_text(), '{"nodeAnnotations":[]}')
        self.assertEqual(Path(result['recovery_path']).read_bytes(), self.BUILT)
        self.assertEqual(Path(result['recovery_paths'][side.name]).read_text(), self.LAYOUT)
        self.assertEqual(sorted(p.name for p in path.parent.iterdir() if not p.name.startswith('.')), [path.name, side.name])
        with self.assertRaisesRegex(ValueError, 'changed'): self.host.execute({**request, 'digest': review['digest']}, lambda _: None)
        # The layout is left alone when the request carries none.
        keep = dict(action='revise', name='built', path=str(path), options={'text': self.BUILT.decode(), 'base': {'yaml': sha(changed.encode())}})
        self.host.execute({**keep, 'digest': self.host.plan(keep)['digest']}, lambda _: None)
        self.assertEqual(side.read_text(), '{"nodeAnnotations":[]}')

    def test_deleting_a_built_lab_takes_its_layout_along_and_frees_the_name(self):
        req, plan = self.publish(); self.host.execute({**req, 'digest': plan['digest']}, lambda _: None)
        path = Path(plan['path']); delete = dict(action='delete', name='built', path=str(path)); review = self.host.plan(delete)
        self.assertIn('map layout file', review['warnings'][0])
        result = self.host.execute({**delete, 'digest': review['digest']}, lambda _: None)
        self.assertEqual(Path(result['recovery_path']).read_bytes(), self.BUILT); self.assertEqual(Path(result['layout_recovery_path']).read_text(), self.LAYOUT)
        self.assertEqual([p.name for p in path.parent.iterdir()], ['.clab-manager-history'])
        # The recovery copies stay; the name can be used for a new lab in the same folder.
        req, plan = self.publish(text=self.BUILT.decode() + '# second attempt\n'); self.assertEqual(plan['warnings'], [])
        self.host.execute({**req, 'digest': plan['digest']}, lambda _: None)
        self.assertEqual(sorted(p.name for p in path.parent.iterdir()), ['.clab-manager-history', 'built.clab.yml', 'built.clab.yml.annotations.json'])
        self.assertEqual(len(list((path.parent/'.clab-manager-history').iterdir())), 2)
        # A topology without a layout file is deleted as before.
        lone = dict(action='delete', name='training', path=str(self.path)); self.rows.clear()
        self.assertEqual(self.host.plan(lone)['warnings'], [])

    def test_capabilities_advertise_the_builder_actions(self):
        actions = self.host.capabilities()['actions']
        self.assertTrue(actions['publish']['available']); self.assertTrue(actions['revise']['available'])

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

    def test_parse_yaml_places_nodes_from_the_annotations_file_and_falls_back_to_the_grid(self):
        annotations=json.dumps({'nodeAnnotations':[{'id':'r1','position':{'x':380,'y':360}},{'id':'r2','position':{'x':520,'y':340}}]})
        def parse(**options):
            response=self.client.post('/api/operations/parse-yaml',headers=self.auth,json={'options':{'text':YAML.decode(),**options}})
            self.assertEqual(response.status_code,200,response.text);return response.json()
        placed=parse(annotations=annotations)
        self.assertTrue(placed['annotations_used']);self.assertTrue(placed['drawing']['placed'])
        self.assertEqual({n['id']:(n['x'],n['y']) for n in placed['drawing']['nodes']},{'r1':(380,360),'r2':(520,340)})
        self.assertEqual(len(placed['drawing']['links']),1,'the wiring still comes from the YAML')
        for options in ({},{'annotations':''},{'annotations':'{not json'},{'annotations':'{"other":1}'}):
            grid=parse(**options)
            self.assertFalse(grid['annotations_used']);self.assertFalse(grid['drawing']['placed'])
            self.assertEqual([(n['x'],n['y']) for n in grid['drawing']['nodes']],[(0,0),(160,0)])
        response=self.client.post('/api/operations/parse-yaml',headers=self.auth,json={'options':{'text':'not: [a topology','annotations':annotations}})
        self.assertEqual(response.status_code,400)

    def test_auth_review_cancel_and_single_use_confirmation(self):
        with self.fixture(),patch.object(self.app.state.operations.pool,'submit') as submit:
            self.assertEqual(self.client.get('/api/operations/capabilities', headers={'Origin':'https://other.example'}).status_code,403)
            preview=self.preview();self.assertEqual(self.store.state['operations'],[])
            response=self.confirm(preview['token']);self.assertEqual(response.status_code,200,response.text)
            self.assertEqual(self.confirm(preview['token']).status_code,409);submit.assert_called_once()
            self.assertEqual(Store(self.tmp.name).state['operations'][0]['status'],'queued')

    def test_builder_save_is_checked_by_the_manager_before_the_helper_sees_it(self):
        built='name: built\ntopology:\n  nodes:\n    r1:\n      kind: linux\n'; layout='{"nodeAnnotations":[{"id":"r1","position":{"x":1,"y":2}}]}'
        post=lambda **body:self.client.post('/api/operations/preview',headers=self.auth,json=body)
        with self.fixture() as remote,patch.object(self.app.state.operations.pool,'submit') as submit:
            remote.side_effect=(lambda inner:lambda host,req,*a:{**inner(host,req,*a),'path':'/srv/labs/built/built.clab.yml'} if req['mode']=='preview' and req['action']=='publish' else inner(host,req,*a))(remote.side_effect)
            for text,reason in (('name: built\ntopology:\n  nodes: {}\n','at least one device'),('a: &x 1\nb: *x\n','cannot read'),('name: bad name\ntopology:\n  nodes:\n    r1: {}\n','cannot read')):
                refused=post(action='publish',options={'root':'/srv/labs','text':text});self.assertEqual(refused.status_code,400,refused.text);self.assertIn(reason,refused.json()['detail'])
            self.assertEqual(post(action='publish',options={'root':'/srv/labs','text':built,'annotations':'[1]'}).status_code,400)
            self.assertEqual(post(action='publish',options={'root':'/srv/labs','text':built,'path':'/etc/passwd'}).status_code,400)
            self.assertEqual(post(action='publish',options={'root':'/srv/labs','text':built+'#'+'x'*(1536*1024)}).status_code,400)
            ok=post(action='publish',options={'root':'/srv/labs','text':built,'annotations':layout});self.assertEqual(ok.status_code,200,ok.text)
            self.assertEqual(ok.json()['name'],'built');self.assertNotIn('options',{k for k in ok.json() if k=='options' and ok.json()[k]})
            # A layout the manager's map cannot read is saved for the editor, and the review says so.
            warned=post(action='publish',options={'root':'/srv/labs','text':built,'annotations':'{"nodeAnnotations":[{"id":"r1"},{"id":"r1"}]}'}).json()
            self.assertIn('default grid',warned['warnings'][0])
            # The name of a lab already in My labs with another topology file cannot be taken over.
            taken=post(action='publish',options={'root':'/srv/labs','text':YAML.decode()});self.assertEqual(taken.status_code,409,taken.text);self.assertIn('already in My labs',taken.json()['detail'])
            job=self.confirm(ok.json()['token']).json();self.assertEqual((job['action'],job['path']),('publish','/srv/labs/built/built.clab.yml'))
            self.assertNotIn('kind: linux',json.dumps(self.store.state['operations']));submit.assert_called_once()
            self.assertEqual(submit.call_args.args[3]['options']['annotations'],layout)

    def test_create_carries_an_uploaded_map_file_through_the_manager_route_untouched(self):
        layout=json.dumps({'nodeAnnotations':[{'id':'r1'}]})
        with self.fixture(),patch.object(self.app.state.operations.pool,'submit') as submit:
            response=self.client.post('/api/operations/preview',headers=self.auth,json=dict(action='create',lab_id='',
                path='/srv/containerlab-node-manager/projects/new.clab.yaml',
                options={'text':'name: new\ntopology:\n  nodes:\n    r1: {kind: linux}\n','annotations':layout}))
            self.assertEqual(response.status_code,200,response.text)
            self.confirm(response.json()['token'])
            submit.assert_called_once();self.assertEqual(submit.call_args.args[3]['options']['annotations'],layout)
            self.assertEqual(submit.call_args.args[3]['action'],'create')

    def test_known_images_come_from_the_labs_already_registered(self):
        with self.fixture():
            self.store.lab(self.lab_id)['definition_yaml']='name: t\ntopology:\n  defaults:\n    kind: arista_ceos\n  kinds:\n    arista_ceos:\n      image: site/ceos:1\n  nodes:\n    a: {}\n    b:\n      image: site/ceos:2\n    c:\n      kind: linux\n      image: "{{ templated }}"\n    d:\n      kind: linux\n      image: alpine:3\n    e: {}\n'
            found=self.client.get('/api/operations/known-images',headers=self.auth).json()['images']
        self.assertEqual(found,{'arista_ceos':['site/ceos:1','site/ceos:2'],'linux':['alpine:3']})

    def test_builder_revision_keeps_the_lab_name_and_shows_what_changes(self):
        with self.fixture():
            renamed=self.client.post('/api/operations/preview',headers=self.auth,json=dict(action='revise',path='/etc/containerlab/training.clab.yaml',options={'text':YAML.decode().replace('name: training','name: other',1),'base':{'yaml':'x'}}))
            self.assertEqual(renamed.status_code,400,renamed.text);self.assertIn('cannot change',renamed.json()['detail'])
            changed=YAML.decode()+'# a student change\n'
            review=self.client.post('/api/operations/preview',headers=self.auth,json=dict(action='revise',path='/etc/containerlab/training.clab.yaml',options={'text':changed,'base':{'yaml':hashlib.sha256(YAML).hexdigest()}}))
            self.assertEqual(review.status_code,200,review.text);self.assertIn('+# a student change',review.json()['diff'])
            # A list of differences that is cut short says so instead of ending in the middle of a line.
            long=self.client.post('/api/operations/preview',headers=self.auth,json=dict(action='revise',path='/etc/containerlab/training.clab.yaml',options={'text':YAML.decode()+''.join('# line %d\n'%i for i in range(30000)),'base':{'yaml':hashlib.sha256(YAML).hexdigest()}}))
            self.assertEqual(long.status_code,200,long.text);self.assertIn('not shown',long.json()['diff'][-120:])

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

    def test_last_deployed_is_the_real_time_of_a_succeeded_deploy_and_never_invented(self):
        from app.lab_operations import last_deployed
        public=lambda:next(l for l in self.client.get('/api/state',headers=self.auth).json()['labs'] if l['id']==self.lab_id)
        def run(action,exit_code=0):
            with self.fixture() as remote,patch.object(self.service,'refresh'),patch.object(self.app.state.operations.pool,'submit') as submit:
                remote.side_effect=(lambda inner:lambda host,req,*a:dict(exit_code=exit_code) if req['mode']=='run' else inner(host,req,*a))(remote.side_effect)
                job=self.confirm(self.preview(action)['token']).json();args=submit.call_args.args;args[0](*args[1:])
            return next(j for j in self.store.state['operations'] if j['id']==job['id'])
        self.fixture();self.assertEqual(public()['last_deployed'],'','a lab this manager never deployed has no deployment time')
        self.assertEqual(run('deploy',exit_code=1)['status'],'failed');self.assertEqual(public()['last_deployed'],'','a failed deploy is not a deployment')
        first=run('deploy');self.assertEqual(first['status'],'succeeded');self.assertEqual(public()['last_deployed'],first['finished'])
        self.assertEqual(Store(self.tmp.name).lab(self.lab_id)['last_deployed'],first['finished'],'kept on the lab: the operation history is capped')
        stopped=run('stop');self.assertEqual(stopped['status'],'succeeded');self.assertEqual(public()['last_deployed'],first['finished'],'stopping, saving or inspecting is unrelated activity')
        again=run('redeploy');self.assertEqual(public()['last_deployed'],again['finished']);self.assertGreaterEqual(again['finished'],first['finished'])
        # A lab deployed before the record existed: the newest succeeded deploy of the history, nothing else
        lab=self.store.lab(self.lab_id);del lab['last_deployed']
        self.assertEqual(last_deployed(self.store.state,lab),again['finished'])
        self.assertEqual(last_deployed({'operations':[dict(lab_id=self.lab_id,action='deploy',status='failed',finished='2026-01-01T00:00:00Z'),dict(lab_id='other',action='deploy',status='succeeded',finished='2026-01-02T00:00:00Z'),dict(lab_id=self.lab_id,action='start',status='succeeded',finished='2026-01-03T00:00:00Z')]},lab),'')

    def test_output_redaction_persistence_and_restart(self):
        with self.fixture(),patch.object(self.service,'refresh'),patch.object(self.app.state.operations.pool,'submit') as submit:
            job=self.confirm(self.preview()['token']).json();args=submit.call_args.args
            args[0](*args[1:])
            saved=self.store.state['operations'][0];self.assertEqual(saved['status'],'succeeded');self.assertIn('first line',saved['output'])
            for secret in ('host-secret','should-not-persist'):self.assertNotIn(secret,saved['output'])
            self.assertNotIn('output',self.client.get('/api/state',headers=self.auth).json()['operations'][0])
            self.assertEqual(Store(self.tmp.name).state['operations'][0]['status'],'succeeded')
            saved['status']='running';self.store.save()
            second=LabOperations(self.store,self.service);second.close();self.assertEqual(saved['status'],'interrupted')

    def test_removed_actions_rejected_even_with_legacy_host_helper(self):
        with self.fixture() as remote:
            for action in ('write','fcli','sshx-attach','sshx-detach','sshx-reattach','gotty-attach','gotty-detach','gotty-reattach'):
                response=self.client.post('/api/operations/preview',json={'action':action,'lab_id':self.lab_id})
                self.assertEqual(response.status_code,400,response.text)
            remote.assert_not_called()

    def test_layout_drawio_favorite_and_no_vm_mutation(self):
        with self.fixture():
            lab=self.store.lab(self.lab_id);alias=lab['drawing']['nodes'][0]['alias']
            response=self.client.put('/api/labs/'+self.lab_id+'/layout',headers=self.auth,json={'positions':{alias:[600,300]}})
            self.assertEqual(response.status_code,200,response.text)
            for layout in ('interactive',):
                response=self.client.get('/api/labs/'+self.lab_id+'/drawio?layout='+layout,headers=self.auth)
                self.assertEqual(response.status_code,200);root=ET.fromstring(response.content)
                self.assertEqual(len(root.findall('.//mxCell[@id="node-0"]')),1)
                self.assertEqual(len(root.findall('.//mxCell[@id="link-0"]')),1)
            response=self.client.put('/api/labs/'+self.lab_id+'/operations-settings',headers=self.auth,json={'favorite':True})
            self.assertEqual(response.status_code,200);self.assertTrue(Store(self.tmp.name).lab(self.lab_id)['favorite'])
            self.assertEqual(self.store.state['operations'],[])

    def test_secrets_multiline_private_key_and_output_limit(self):
        state={'labs':[],'host':{'password':'verysecret'}}
        result=scrub('verysecret\n-----BEGIN RSA PRIVATE KEY-----\nabc\ndef\n-----END RSA PRIVATE KEY-----\nokay',state)
        self.assertNotIn('abc',result);self.assertNotIn('verysecret',result);self.assertIn('okay',result)
        self.assertLessEqual(len(scrub('x'*600000,state)),512*1024)

    def test_failed_persistent_save_keeps_review_and_does_not_submit(self):
        with self.fixture(),patch.object(self.app.state.operations.pool,'submit') as submit:
            preview=self.preview();original=list(self.store.state['operations'])
            # Fail only the operation save; permit the request audit write.
            with patch.object(self.store,'save',side_effect=OSError('disk fixture')):
                self.assertEqual(self.confirm(preview['token']).status_code,500)
            self.assertEqual(self.store.state['operations'],original)
            self.assertIn(preview['token'],self.app.state.operations.previews);submit.assert_not_called()

    def test_the_map_document_is_kept_whole_and_the_drawing_follows_it(self):
        with self.fixture() as remote:
            url='/api/labs/'+self.lab_id+'/map-document'
            lab=self.store.lab(self.lab_id);yaml_before=lab['definition_yaml'];ids=[n['id'] for n in lab['drawing']['nodes']]
            opened=self.client.get(url,headers=self.auth);self.assertEqual(opened.status_code,200,opened.text);opened=opened.json()
            self.assertEqual(opened['yaml'],yaml_before);self.assertEqual(sorted(a['id'] for a in json.loads(opened['annotations'])['nodeAnnotations']),sorted(ids),'a lab with only a drawing opens with a document written from it')
            document={'nodeAnnotations':[{'id':ids[0],'position':{'x':400,'y':120},'groupId':'core','futureField':{'kept':True}},{'id':ids[1],'position':{'x':40,'y':60}}],
                      'groupStyleAnnotations':[{'id':'core','name':'Core','parentId':'site','level':'2','position':{'x':300,'y':60},'width':300,'height':200,'backgroundColor':'#ffeecc'}],
                      'freeShapeAnnotations':[{'id':'s1','shapeType':'line','position':{'x':0,'y':0},'endPosition':{'x':90,'y':40},'lineEndArrow':True,'lineArrowSize':12,'rotation':15}],
                      'freeTextAnnotations':[{'id':'t1','text':'Area 0','position':{'x':10,'y':10},'fontSize':20,'roundedBackground':True,'geoCoordinates':{'lat':1,'lng':2}}],
                      'trafficRateAnnotations':[{'id':'tr1','nodeId':ids[0],'interfaceName':'eth1'}],'aliasEndpointAnnotations':[{'yamlNodeId':ids[0],'interface':'eth9','aliasNodeId':'x'}],
                      'viewerSettings':{'gridStyle':'quadratic','linkLabelMode':'on-select'},'somethingNew':[1,2,3]}
            text=json.dumps(document,indent=1)
            calls=remote.call_count
            saved=self.client.put(url,headers=self.auth,json={'annotations':text,'revision':opened['revision']});self.assertEqual(saved.status_code,200,saved.text)
            self.assertEqual(remote.call_count,calls,'a map edit calls no VM helper: nothing is deployed, read or written there')
            again=self.client.get(url,headers=self.auth).json()
            self.assertEqual(again['annotations'],text,'byte for byte: group membership, nesting, arrows, geo coordinates, widgets and unknown keys are all kept')
            self.assertEqual(again['revision'],saved.json()['revision']);self.assertNotEqual(again['revision'],opened['revision'])
            lab=self.store.lab(self.lab_id);drawing=lab['drawing']
            self.assertEqual({n['id']:(n['x'],n['y']) for n in drawing['nodes']}[ids[0]],(400,120),'the Topology view follows the saved map')
            self.assertEqual(sorted(d['type'] for d in drawing['decorations']),['group','line','text']);self.assertTrue(drawing['placed']);self.assertEqual(drawing['settings']['labelMode'],'on-select')
            self.assertEqual(lab['definition_yaml'],yaml_before,'the topology text is never touched');self.assertEqual(Store(self.tmp.name).lab(self.lab_id)['annotations'],text)
            public=json.dumps(self.client.get('/api/state',headers=self.auth).json());self.assertNotIn('futureField',public);self.assertNotIn('annotations_for',public)
            # refusals change nothing
            stale=self.client.put(url,headers=self.auth,json={'annotations':text,'revision':opened['revision']});self.assertEqual(stale.status_code,409);self.assertIn('changed since it was opened',stale.text)
            for bad,reason in (('[1]','cannot read this map'),('{not json','cannot read this map'),(json.dumps({'nodeAnnotations':[{'id':''}]}),'cannot read this map')):
                refused=self.client.put(url,headers=self.auth,json={'annotations':bad,'revision':again['revision']});self.assertEqual(refused.status_code,400,bad);self.assertIn(reason,refused.text)
            self.assertEqual(self.client.put(url,headers=self.auth,json={'annotations':text,'revision':again['revision'],'yaml':'name: other'}).status_code,422,'the request cannot carry a topology')
            self.assertEqual(self.client.get(url,headers=self.auth).json()['annotations'],text)
            self.store.state['operations'].append(dict(id='busy',lab_id=self.lab_id,action='deploy',status='running',name='x'))
            self.assertEqual(self.client.put(url,headers=self.auth,json={'annotations':text,'revision':again['revision']}).status_code,409);self.store.state['operations'].pop()
            # the older dialog still saves, and its change is never served with the document it did not write
            moved=self.client.put('/api/labs/'+self.lab_id+'/layout',headers=self.auth,json={'positions':{ids[0]:[5,5]}});self.assertEqual(moved.status_code,200,moved.text)
            after=json.loads(self.client.get(url,headers=self.auth).json()['annotations'])
            self.assertEqual(next(a for a in after['nodeAnnotations'] if a['id']==ids[0])['position'],{'x':5,'y':5});self.assertNotIn('somethingNew',after)
            # a lab without a topology text keeps the simple editor
            lab['definition_yaml']='';none=self.client.get(url,headers=self.auth);self.assertEqual(none.status_code,409);self.assertIn('simple editor',none.text)

    def test_an_imported_annotations_file_is_kept_as_it_came(self):
        with self.fixture():
            lab=self.store.lab(self.lab_id);ids=[n['id'] for n in lab['drawing']['nodes']]
            text=json.dumps({'nodeAnnotations':[{'id':i,'position':{'x':10*k,'y':20},'groupId':'g'} for k,i in enumerate(ids)],'groupStyleAnnotations':[{'id':'g','name':'G','position':{'x':0,'y':0},'width':100,'height':80}],'vendorExtension':{'a':1}})
            sent=self.client.post('/api/labs/'+self.lab_id+'/topology',headers=self.auth,files={'annotations':('lab.annotations.json',text.encode(),'application/json'),'topology':('lab.clab.yaml',lab['definition_yaml'].encode(),'application/x-yaml')})
            self.assertEqual(sent.status_code,200,sent.text)
            self.assertEqual(self.client.get('/api/labs/'+self.lab_id+'/map-document',headers=self.auth).json()['annotations'],text,'Import map keeps the file, not only what the manager draws')
            from app.layout import keep_document, map_document
            keep_document(lab,b'');self.assertNotIn('annotations',lab);self.assertIn('nodeAnnotations',map_document(lab))
            keep_document(lab,'x'*(1024*1024+1));self.assertNotIn('annotations',lab,'an oversized text is not stored')

    def test_removed_drawio_layouts_rejected(self):
        with self.fixture():
            for layout in ('horizontal','vertical'):
                self.assertEqual(self.client.get('/api/labs/'+self.lab_id+'/drawio?layout='+layout).status_code,400)
