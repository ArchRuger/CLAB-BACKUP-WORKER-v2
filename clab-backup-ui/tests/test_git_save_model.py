"""The save model of the Git save and load redesign (docs/git-redesign/DESIGN.md sections 3, 4 and 7.3).

A save carries its own binding; its name is optional and written from what changed; a checkpoint can be made
from a save without reading a device; the review of a save names everything its upload carries and the upload is
bound to the checkout's HEAD; lab states; `git_status` for the header chip. The VM is `Vm` below: one checkout
with its commits, journals and remote branch, answering the helper's modes the way host_git.py does (what a push
may carry, which journal belongs to which registration, what `compare` and `history` return).
"""
import ast
import base64
import copy
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import uuid

from app import __version__
from app import git_progress
from app.git_progress import (GitProgress, PROTOCOL, ANOTHER_SAVE, NOT_OURS, NOT_WHOLE, NO_DEVICES, REVIEW_FIRST, TOPOLOGY_FAILED,
                              WAITING_FIRST, HELPER_PROBLEMS, MANAGER_PROBLEMS, MAX_SAVE_NAMES, GIT_JOB_CAP, _append_git_job,
                              change_name, checkpoint_slug, file_role, free_checkpoint, manifest_changes, problem_code,
                              save_summary, review_files, digest as git_digest, pending_progress)
from app.host_git import content_digest
from app.store import Store
import test_discovery as discovery_tests

TOPOLOGY = 'name: training\ntopology:\n  nodes:\n    r1: {kind: cisco_xrv9k}\n'
PRIVATE = ('binding', 'binding_digest', 'request', 'auto_note', 'renamed', 'state_name', 'own_capture', 'first_save', 'host_identity',
           'snapshot_digest', 'expected_head', 'capture_context', 'node_names', 'retry_push', 'want_push')


class Vm:
    """One checkout on the VM. `order` is its branch, oldest first; `remote` is the newest commit the remote has."""

    def __init__(self, repo):
        self.registry = [dict(repo)]; self.path = repo['path']
        self.order = ['a' * 40]; self.remote = 'a' * 40; self.trees = {'a' * 40: {}}
        self.log = {}; self.journals = {}; self.problem = ''; self.push_error = ''; self.compare_error = ''; self.lost = set()

    @property
    def head(self): return self.order[-1]

    def commit(self, tree, operation, subject, files):
        commit = '%040x' % (len(self.order) + 0xc0de0000)
        self.trees[commit] = tree; self.log[commit] = dict(commit=commit, operation_id=operation, subject=subject, files=files)
        self.order.append(commit)
        return commit

    def by_hand(self, subject='Edited on the VM', files=('notes.txt',)):
        """A commit the repository's owner made on the VM, outside the manager."""
        return self.commit(copy.deepcopy(self.trees[self.head]), None, subject, list(files))

    def summary(self, manifest):
        return dict(lab_id=manifest.get('lab_id', ''), lab_name=manifest.get('lab_name', ''), captured_at=manifest.get('captured_at', ''),
                    kind=manifest.get('kind', 'capture'), topology_digest=manifest.get('topology_digest'), state=manifest.get('state', ''),
                    devices=[dict(node=f['node'], short_name=f.get('short_name', ''), platform=f.get('platform', ''), restore=bool(f.get('restore_artifact')))
                             for f in manifest['files'] if not f.get('kind')])

    def answer(self, request):
        mode = request['mode']
        if mode == 'list': return dict(protocol=PROTOCOL, version=__version__, repositories=[dict(r) for r in self.registry])
        if mode == 'register-prefix':
            source = next(r for r in self.registry if r['id'] == request['binding_id'])
            found = next((r for r in self.registry if r['path'] == source['path'] and r['prefix'] == request['prefix']), None)
            if not found:
                name = request['prefix'].replace('/', '-') or 'root'
                found = dict(source, id='reg-' + name, prefix=request['prefix'], revision='rev-' + name, label='Bens lab / ' + name)
                self.registry.append(found)
            return dict(found)
        repo = next((r for r in self.registry if r['id'] == request.get('binding_id')), None)
        if not repo: raise ValueError('Select a registered Git repository.')
        if request.get('revision') != repo['revision']: raise ValueError('The repository binding changed. Select it again.')
        scope = lambda name: '/'.join(p for p in (repo['prefix'], name) if p)
        tree = self.trees[self.head]
        if mode == 'status':
            if repo['path'] != self.path: return dict(repository=repo, ready=True, problem='', head='f' * 40, baseline_revision='', latest_manifest=None)
            latest = tree.get(scope('latest'))
            return dict(repository=repo, ready=not self.problem, problem=self.problem, head=self.head, baseline_revision='',
                        latest_manifest=copy.deepcopy(latest['manifest']) if latest else None)
        if mode == 'publish':
            operation = request['operation_id']; body = git_digest(request); journal = self.journals.get(operation)
            if journal:
                if journal['digest'] != body: raise ValueError('This operation ID already belongs to a different snapshot or save action.')
                return copy.deepcopy(journal['result'])
            folders = [] if request['target'] == 'baseline' else [scope('latest')]
            if request['target'] == 'baseline': folders.append(scope('baseline'))
            if request['target'] == 'checkpoint': folders.append(scope('checkpoints/' + request['checkpoint']))
            result = dict(pushed=False, snapshot_path=folders[-1], synced_operations=None)
            if request['expected_head'] != self.head:
                result.update(status='needs_attention', commit=None, changed_files=[], message='The repository changed since it was selected. Refresh status and retry the preserved snapshot.')
            else:
                new = copy.deepcopy(tree); changed = []
                for folder in folders:
                    old = tree.get(folder); snapshot = request['snapshot']
                    if folder.rsplit('/', 2)[-2:-1] == ['checkpoints'] and old: raise AssertionError('checkpoint exists')
                    if old and content_digest(old['manifest']) == content_digest(snapshot['manifest']): continue
                    before = old['files'] if old else {}
                    if set(before) - set(snapshot['files']) and not request.get('allow_removed'):
                        raise AssertionError('removal not allowed')
                    changed += [folder + '/' + name for name in sorted(set(before) | set(snapshot['files'])) if before.get(name) != snapshot['files'].get(name)]
                    changed.append(folder + '/manifest.json'); new[folder] = copy.deepcopy(snapshot)
                if not changed: result.update(status='unchanged', commit=self.head, changed_files=[], message='No configuration changes.', pushed=None)
                else:
                    parent = self.head
                    result.update(status='committed', commit=self.commit(new, operation, request['message'], changed), changed_files=changed,
                                  message='Saved in the VM repository; not pushed.')
                    result['parent'] = parent
            self.journals[operation] = dict(digest=body, revision=request['revision'], result={k: v for k, v in result.items() if k != 'parent'},
                                            parent=result.get('parent'), commit=result.get('commit'), folder=folders[-1], changed=result['changed_files'])
            if operation in self.lost:
                self.lost.discard(operation); raise ValueError('Git connection interrupted. Retry this saved operation to reconcile its result.')
            return copy.deepcopy(self.journals[operation]['result'])
        if mode == 'push':
            journal = self.journals.get(request['operation_id'])
            if not journal or journal['revision'] != request['revision']: raise ValueError('Saved progress journal not found for this binding.')
            commit = journal['commit']; out = dict(commit=commit, changed_files=journal['changed'], snapshot_path=journal['folder'])
            if self.push_error: return dict(out, status='needs_attention', pushed=False, message=self.push_error, synced_operations=None)
            if self.order.index(commit) > self.order.index(self.remote):
                if commit != self.head:
                    return dict(out, status='needs_attention', pushed=False, synced_operations=None,
                                message='The checkout moved since this save. Push the newest saved progress or resolve it as the repository owner.')
                between = self.order[self.order.index(self.remote) + 1:]
                if any(self.log[c]['operation_id'] is None for c in between):
                    return dict(out, status='needs_attention', pushed=False, synced_operations=None,
                                message='The push would include commits created outside manager saves. Publish or resolve them as the repository owner first.')
                self.remote = commit
            there = set(self.order[:self.order.index(self.remote) + 1])
            synced = [op for op, j in self.journals.items() if j['commit'] in there and j['changed']]
            if request['operation_id'] not in synced: synced.append(request['operation_id'])
            return dict(out, status='synced', pushed=True, message='Saved to Git.', synced_operations=synced)
        if mode == 'compare':
            if self.compare_error: raise ValueError(self.compare_error)
            journal = self.journals.get(request['operation_id'])
            if not journal or not journal['commit'] or journal['revision'] != request['revision']: raise ValueError('Select saved progress with a recorded commit.')
            outgoing = [copy.deepcopy(self.log[c]) for c in self.order[self.order.index(self.remote) + 1:]]
            if not journal['changed']: return dict(files=[], head=self.head, outgoing=outgoing)
            text = lambda files, name: base64.b64decode(files[name]).decode() if name in files else ''
            after = self.trees[journal['commit']][journal['folder']]['files']
            before = (self.trees[journal['parent']].get(journal['folder']) or {'files': {}})['files']
            files = [dict(name=name, status='added' if name not in before else 'removed' if name not in after else 'changed',
                          before=text(before, name), after=text(after, name)) for name in sorted(set(before) | set(after)) if before.get(name) != after.get(name)]
            return dict(files=files, head=self.head, outgoing=outgoing)
        if mode == 'history':
            own = (scope('latest'), scope('baseline'))
            versions = [dict(name=folder, path=folder, commit=self.head, connected=folder in own or folder.startswith(scope('checkpoints') + '/'),
                             summary=self.summary(snapshot['manifest'])) for folder, snapshot in sorted(tree.items())]
            commits = [dict(commit=c, time=1789128000 + n, message=self.log[c]['subject']) for n, c in enumerate(self.order) if c in self.log]
            return dict(commits=list(reversed(commits)), versions=versions, head=self.head)
        if mode == 'browse':
            files = [dict(path='README.md', size=12)]
            for folder, snapshot in sorted(tree.items()):
                files += [dict(path=folder + '/' + name, size=10) for name in list(snapshot['files']) + ['manifest.json']]
            dirs = sorted({'/'.join(f['path'].split('/')[:n]) for f in files for n in range(1, f['path'].count('/') + 1)})
            return dict(repository=repo, head=self.head, files=files, dirs=dirs, truncated=False, saved={},
                        folders=[dict(id=r['id'], label=r['label'], prefix=r['prefix']) for r in self.registry if r['path'] == repo['path']])
        if mode == 'read-version':
            found = self.trees.get(request['commit'], {}).get(request['path'])
            if not found: raise ValueError('This folder holds no saved configuration (manifest.json) at the selected commit.')
            return {'snapshot': copy.deepcopy(found)}
        if mode == 'update':
            if self.remote != self.head: raise ValueError('Local and remote history diverged or local commits are pending. Resolve them as the repository owner.')
            return dict(status='updated', head=self.head, message='Updated from remote using fast-forward only.')
        raise AssertionError(mode)


class SaveModelCase(unittest.TestCase):
    setUp_base = discovery_tests.DiscoveryTests.setUp
    register = discovery_tests.DiscoveryTests.register
    host = discovery_tests.DiscoveryTests.host

    def setUp(self):
        self.setUp_base()
        self.progress = self.app.state.git_progress
        self.host(); self.store.state['host']['fingerprint'] = 'SHA256:fixture'
        self.lab = self.register(); self.url = '/api/labs/' + self.lab['id'] + '/git'
        self.repo = dict(id='bens-lab', label='Bens lab', owner='ben', path='/home/ben/labs/bgp', remote='origin', branch='main',
                         prefix='', revision='binding-1', push_url='https://github.com/ben/bgp.git')
        self.vm = Vm(self.repo); self.sent = []
        self.texts = {}                 # a device's configuration, by node name, when a test changes it
        self.topology = TOPOLOGY; self.map = '{"nodeAnnotations": []}'
        self.missing = ''               # what the capture records as `topology_missing`
        self.helper = patch('app.git_progress.remote_git', side_effect=self.remote).start()
        self.addCleanup(patch.stopall)
        self.dispatch = patch.object(self.progress.pool, 'submit').start()
        self.names = [n['name'] for n in self.store.lab(self.lab['id'])['nodes']]
        response = self.client.put(self.url, json=dict(binding_id=self.repo['id'], node_names=self.names))
        self.assertEqual(response.status_code, 200, response.text)
        self.sent.clear()

    def tearDown(self):
        self.app.state.operations.close()
        discovery_tests.DiscoveryTests.tearDown(self)

    def remote(self, host, request, stopping=None):
        self.sent.append(copy.deepcopy(request))
        return self.vm.answer(request)

    def modes(self, start=0): return [r['mode'] for r in self.sent[start:]]

    def capture(self, lab_id=None, **kwargs):
        """A backup as the runner leaves it: one file per device (and a restore artifact), the topology and the map."""
        lab_id = lab_id or self.lab['id']; lab = self.store.lab(lab_id)
        job_id = uuid.uuid4().hex; folder = self.store.root / 'backups' / lab_id / 'history' / job_id
        folder.mkdir(parents=True); nodes = []
        for index, node in enumerate(lab['nodes']):
            if kwargs.get('node_names') and node['name'] not in kwargs['node_names']: continue
            text = self.texts.get(node['name'], 'hostname router-%d\n' % index)
            (folder / ('n%d.cfg' % index)).write_text(text, encoding='utf-8'); (folder / ('n%d.restore' % index)).write_text('restore of ' + text, encoding='utf-8')
            nodes.append(dict(name=node['name'], status='succeeded', file='n%d.cfg' % index, restore_file='n%d.restore' % index,
                              platform=node['platform'], short_name='r' + str(index + 1)))
        job = dict(id=job_id, lab_id=lab_id, lab_name=lab['name'], operation='backup', status='succeeded',
                   created='2026-09-11T10:00:00+00:00', finished='2026-09-11T10:01:00+00:00', nodes=nodes)
        if self.missing: job['topology_missing'] = self.missing
        if self.topology and self.missing != 'error':
            definition = self.topology.encode(); (folder / 'topology.clab.yml').write_bytes(definition)
            job['topology'] = dict(file='topology.clab.yml', size=len(definition), sha256=hashlib.sha256(definition).hexdigest(), source='manager', path='', read_at='x')
            if self.map and self.missing != 'map-error':
                annotations = self.map.encode(); (folder / 'topology.clab.yml.annotations.json').write_bytes(annotations)
                job['topology'].update(annotations_file='topology.clab.yml.annotations.json', annotations_size=len(annotations), annotations_sha256=hashlib.sha256(annotations).hexdigest())
        for key in ('progress_context', 'progress_id'):
            if kwargs.get(key): job[key] = copy.deepcopy(kwargs[key])
        self.store.state['jobs'].insert(0, job); self.store.save()
        return copy.deepcopy(job)

    def post(self, lab_id=None, expect=200, **fields):
        data = dict(request_id=uuid.uuid4().hex, target='latest', push=True, note=''); data.update(fields)
        response = self.client.post('/api/labs/' + (lab_id or self.lab['id']) + '/git/save', json=data)
        self.assertEqual(response.status_code, expect, response.text)
        return response.json()

    def run_job(self, job):
        with patch.object(self.app.state.runner, 'submit', side_effect=self.capture) as submit:
            self.progress.execute(job['id'])
        return self.client.get('/api/git/jobs/' + job['id']).json(), submit

    def saved(self, lab_id=None, **fields):
        """A save that ran: on the VM, waiting for upload."""
        outcome, _ = self.run_job(self.post(lab_id, **fields))
        return outcome

    def review(self, job, lab_id=None):
        response = self.client.post('/api/labs/' + (lab_id or job['lab_id']) + '/git/compare', json={'job_id': job['id']})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def upload(self, job, expect=200, **body):
        response = self.client.post('/api/git/jobs/' + job['id'] + '/retry', json=dict(dict(push=True, reviewed=True), **body))
        self.assertEqual(response.status_code, expect, response.text)
        if expect != 200: return response.json()
        self.progress.execute(response.json()['id'])
        return self.client.get('/api/git/jobs/' + response.json()['id']).json()

    def stored(self, job): return self.progress.get_job(job['id'])

    def second_lab(self, prefix='sibling'):
        """Another lab saving to its own folder of the same checkout."""
        self.vm.registry.append(dict(self.repo, id='reg-' + prefix, prefix=prefix, revision='rev-' + prefix, label='Bens lab / ' + prefix))
        other = self.register(discovery_tests.YAML.replace(b'name: training', b'name: other-lab'))
        names = [n['name'] for n in self.store.lab(other['id'])['nodes']]
        response = self.client.put('/api/labs/' + other['id'] + '/git', json=dict(binding_id='reg-' + prefix, node_names=names))
        self.assertEqual(response.status_code, 200, response.text)
        return other

    def public_views(self, job):
        """Every way a save reaches a page."""
        state = next(j for j in self.client.get('/api/state').json()['git_jobs'] if j['id'] == job['id'])
        listed = next(j for j in self.client.get('/api/labs/' + job['lab_id'] + '/git').json()['jobs'] if j['id'] == job['id'])
        return state, listed, self.client.get('/api/git/jobs/' + job['id']).json()


class OwnBindingTests(SaveModelCase):
    """DESIGN.md 3.1: a save is executed, retried, reviewed and uploaded through the binding it was made with."""

    def test_the_binding_is_a_private_copy_that_no_public_view_shows(self):
        job = self.saved(note='First')
        stored = self.stored(job); binding = self.store.lab(self.lab['id'])['git_binding']
        self.assertEqual(stored['binding'], binding); self.assertIsNot(stored['binding'], binding)
        self.assertEqual(stored['binding_digest'], git_digest(binding), 'the digest it stores stays true')
        views = self.public_views(job)
        self.assertEqual(views[0], views[1]); self.assertEqual(views[1], views[2], 'one function decorates a public save')
        for view in views:
            for key in PRIVATE: self.assertNotIn(key, view)
        state = self.client.get('/api/state').json()
        for word in ('binding_digest', 'host_identity', '"binding"', 'hostname router-'): self.assertNotIn(word, json.dumps(state['git_jobs']))
        self.assertNotIn('git_save_names', state)
        # A design export and a folder move carry theirs too.
        moved = self.client.post(self.url + '/destination', json=dict(prefix='bgp', move_files=True)).json()
        self.assertEqual(self.stored(moved['job'])['binding'], moved['binding']); self.assertNotIn('binding', moved['job'])

    def test_a_waiting_save_still_uploads_after_the_lab_changed_folder_devices_and_repository_and_was_disconnected(self):
        self.vm.registry.append(dict(self.repo, id='elsewhere', path='/home/ben/labs/other', revision='rev-elsewhere', label='Other', push_url='https://github.com/ben/other.git'))
        changes = (lambda: self.client.post(self.url + '/destination', json=dict(prefix='moved')),
                   lambda: self.client.put(self.url, json=dict(binding_id=self.store.lab(self.lab['id'])['git_binding']['binding_id'], node_names=self.names[:1])),
                   lambda: self.client.put(self.url, json=dict(binding_id='elsewhere', node_names=self.names)),
                   lambda: self.client.post(self.url + '/unlink', json={}))
        for n, change in enumerate(changes):
            self.texts[self.names[0]] = 'hostname change-%d\n' % n
            self.client.put(self.url, json=dict(binding_id='bens-lab', node_names=self.names))
            job = self.saved(note='Save %d' % n)
            self.assertEqual(job['status'], 'review_pending', job)
            frozen = copy.deepcopy(self.stored(job)['binding'])
            response = change(); self.assertEqual(response.status_code, 200, response.text)
            self.assertNotEqual(self.store.lab(self.lab['id']).get('git_binding'), frozen)
            self.assertEqual(self.stored(job)['binding'], frozen, 'a stored binding is never rewritten')
            self.assertEqual(self.client.get('/api/state').json()['labs'][0]['git_status']['waiting'], 1 if n < 2 else 0 if n == 2 else 1)
            self.assertTrue(self.review(job)['files'], 'it can still be reviewed')
            sent = len(self.sent)
            outcome = self.upload(job)
            self.assertEqual((outcome['status'], outcome['pushed'], outcome['destination']['path']), ('synced', True, 'latest'), n)
            push = next(r for r in self.sent[sent:] if r['mode'] == 'push')
            self.assertEqual((push['binding_id'], push['revision'], push['operation_id']), ('bens-lab', 'binding-1', job['id']))
        self.assertEqual(self.vm.remote, self.vm.head)

    def test_start_up_copies_the_labs_binding_into_pending_saves_of_an_older_release(self):
        job = self.saved(note='Old release')
        kept = self.saved(note='Kept'); self.client.post('/api/git/jobs/' + kept['id'] + '/dismiss', json={'acknowledge': True})
        done = self.saved(note='Done')
        with self.store.lock:
            binding = copy.deepcopy(self.store.lab(self.lab['id'])['git_binding'])
            for j in self.store.state['git_jobs']: j.pop('binding')
            self.stored(done).update(status='synced', pushed=True)
            other = dict(copy.deepcopy(self.stored(job)), id='e' * 32, binding_digest='made-with-an-earlier-binding')
            self.store.state['git_jobs'].append(other); self.store.save()
        loaded = Store(self.tmp.name); restarted = GitProgress(loaded, self.app.state.runner)
        try:
            jobs = {j['id']: j for j in loaded.state['git_jobs']}
            self.assertEqual(jobs[job['id']]['binding'], binding)
            self.assertEqual(jobs[kept['id']]['binding'], binding, 'a kept save may still be the one an upload goes through')
            self.assertNotIn('binding', jobs[done['id']], 'a finished save needs none')
            self.assertNotIn('binding', jobs['e' * 32], 'a save made with another binding gets no guess')
            self.assertEqual(jobs[job['id']]['binding_digest'], git_digest(binding))
            self.assertEqual({j['id']: j.get('binding') for j in Store(self.tmp.name).state['git_jobs']}, {j['id']: j.get('binding') for j in loaded.state['git_jobs']}, 'stored')
        finally: restarted.close()

    def test_a_save_of_an_older_release_without_a_binding_keeps_the_comparison_with_its_labs(self):
        job = self.saved(note='Old release')
        with self.store.lock: self.stored(job).pop('binding'); self.store.save()
        self.assertTrue(self.review(job)['files'], 'while the lab is still connected the same way it works as before')
        self.assertEqual(self.client.put(self.url, json=dict(binding_id='bens-lab', node_names=self.names[:1])).status_code, 200)
        refused = self.client.post('/api/git/jobs/' + job['id'] + '/retry', json=dict(push=True, reviewed=True))
        self.assertEqual(refused.status_code, 409); self.assertIn('Repository settings changed', refused.text)
        reviewed = self.client.post(self.url + '/compare', json={'job_id': job['id']})
        self.assertEqual(reviewed.status_code, 409); self.assertIn('Reconnect the original repository', reviewed.text)
        self.progress.update(job['id'], status='queued', retry=True); self.progress.execute(job['id'])
        self.assertIn('Repository settings changed', self.stored(job)['message'])
        self.assertNotIn('push', self.modes())


class UploadTests(SaveModelCase):
    """DESIGN.md 3.4: an upload is of the repository's waiting saves, through the save at HEAD, as the review showed."""

    def test_two_labs_of_one_checkout_save_side_by_side_and_one_upload_carries_both(self):
        other = self.second_lab()
        mine = self.saved(note='Mine')                                   # A saves and waits
        theirs = self.saved(other['id'], note='Theirs')                  # B's save works on top of it
        self.assertEqual((mine['status'], theirs['status']), ('review_pending', 'review_pending'))
        self.assertEqual(self.vm.head, theirs['commit']); self.assertNotEqual(mine['commit'], theirs['commit'])
        for lab in self.client.get('/api/state').json()['labs']: self.assertEqual(lab['git_status']['waiting'], 2, 'both labs see both')
        # The review of either names the other, and names the save the upload goes through.
        of_mine, of_theirs = self.review(mine), self.review(theirs)
        self.assertEqual(of_mine['also_sends'], [dict(job_id=theirs['id'], lab='other-lab', name='Theirs', kind='save', target='latest')])
        self.assertEqual(of_theirs['also_sends'], [dict(job_id=mine['id'], lab=self.lab['name'], name='Mine', kind='save', target='latest')])
        for answer in (of_mine, of_theirs):
            self.assertEqual((answer['head'], answer['upload_job']), (theirs['commit'], theirs['id']))
            self.assertEqual((answer['also_sends_count'], answer['also_sends_other_labs'], answer['also_sends_kept']), (1, 1, []))
            self.assertNotIn('upload_blocked', answer)
        # Each row can be opened from either lab: the other lab's save through this lab's route.
        self.assertTrue(self.review(theirs, self.lab['id'])['files'])
        # Upload pressed in A's panel: the save at HEAD is pushed, through its own binding.
        outcome = self.upload(mine, head=of_mine['head'])
        self.assertEqual((outcome['id'], outcome['status']), (theirs['id'], 'synced'))
        pushes = [r for r in self.sent if r['mode'] == 'push']
        self.assertEqual([(r['operation_id'], r['binding_id']) for r in pushes], [(theirs['id'], 'reg-sibling')])
        for job in (mine, theirs):
            stored = self.stored(job)
            self.assertEqual((stored['status'], stored['pushed'], bool(stored['reviewed'])), ('synced', True, True))
        self.assertEqual(self.vm.remote, self.vm.head)
        self.assertEqual([lab['git_status']['waiting'] for lab in self.client.get('/api/state').json()['labs']], [0, 0])

    def test_a_save_that_lands_between_the_review_and_upload_sends_the_person_back_to_the_review(self):
        other = self.second_lab()
        mine = self.saved(note='Mine'); shown = self.review(mine)
        self.assertEqual((shown['head'], shown['upload_job'], shown['also_sends']), (mine['commit'], mine['id'], []))
        theirs = self.saved(other['id'], note='Theirs')                  # lands after the review was shown
        before = copy.deepcopy(self.store.state['git_jobs']); sent = len(self.sent)
        refused = self.upload(mine, expect=409, head=shown['head'])
        self.assertEqual(refused['detail'], ANOTHER_SAVE)
        self.assertNotIn('push', self.modes(sent)); self.assertEqual(self.vm.remote, 'a' * 40, 'nothing was pushed')
        self.assertEqual(self.store.state['git_jobs'], before, 'and nothing changed: no review is recorded for a refused upload')
        self.dispatch.reset_mock()
        again = self.review(mine)
        self.assertEqual((again['head'], again['upload_job'], [row['job_id'] for row in again['also_sends']]), (theirs['commit'], theirs['id'], [theirs['id']]))
        self.assertEqual(self.upload(mine, head=again['head'])['status'], 'synced')
        self.assertEqual(self.stored(mine)['status'], 'synced')

    def test_an_upload_without_head_from_an_older_page_still_goes_through_the_save_at_head(self):
        other = self.second_lab()
        mine = self.saved(note='Mine'); theirs = self.saved(other['id'], note='Theirs')
        outcome = self.upload(mine)
        self.assertEqual(outcome['id'], theirs['id']); self.assertEqual(self.stored(mine)['status'], 'synced')

    def test_a_review_recorded_for_an_earlier_head_does_not_upload_a_save_that_landed_since(self):
        other = self.second_lab()
        mine = self.saved(note='Mine')
        self.vm.push_error = 'The commit is saved on the VM, but push failed. Check authentication, branch permissions or remote changes, then retry.'
        self.assertEqual(self.upload(mine)['status'], 'push_pending'); self.assertTrue(self.stored(mine)['reviewed'])
        self.vm.push_error = ''
        theirs = self.saved(other['id'], note='Theirs')
        sent = len(self.sent)
        refused = self.upload(mine, expect=409, reviewed=False)       # Try again from a page that shows the old review
        self.assertEqual(refused['detail'], REVIEW_FIRST); self.assertNotIn('push', self.modes(sent))
        self.assertNotIn('reviewed', self.stored(theirs))
        self.assertEqual(self.upload(mine)['id'], theirs['id'])

    def test_a_commit_the_manager_did_not_make_at_head_stops_the_upload_and_is_named_in_the_review(self):
        mine = self.saved(note='Mine')
        foreign = self.vm.by_hand('Edited by hand', ['README.md'])
        answer = self.review(mine)
        self.assertEqual((answer['head'], answer['upload_job']), (foreign, None))
        self.assertEqual(answer['also_sends'], [dict(commit=foreign, name='Edited by hand', files=['README.md'])])
        sent = len(self.sent)
        refused = self.upload(mine, expect=409, head=foreign)
        self.assertEqual(refused['detail'], NOT_OURS); self.assertNotIn('push', self.modes(sent))
        self.assertEqual(self.stored(mine)['status'], 'review_pending')

    def test_a_save_the_manager_no_longer_holds_is_named_by_its_commit(self):
        other = self.second_lab()
        theirs = self.saved(other['id'], note='From a removed lab')
        mine = self.saved(note='Mine')
        with self.store.lock:   # Remove lab dropped the manager's record of it; the commit is still on the VM
            self.store.state['git_jobs'] = [j for j in self.store.state['git_jobs'] if j['id'] != theirs['id']]; self.store.save()
        answer = self.review(mine)
        self.assertEqual(answer['also_sends'], [dict(commit=theirs['commit'], name='From a removed lab', files=theirs['changed_files'])])
        self.assertEqual(answer['upload_job'], mine['id'])

    def test_an_upload_needs_its_review_and_nothing_else_in_the_manager_pushes(self):
        mine = self.saved(note='Mine')
        for body in (dict(push=True), dict(push=True, reviewed=False), {}):
            refused = self.client.post('/api/git/jobs/' + mine['id'] + '/retry', json=body)
            self.assertEqual((refused.status_code, refused.json()['detail']), (409, REVIEW_FIRST))
        self.assertNotIn('push', self.modes())
        # A worker that finds a push asked for without a recorded review does not push either.
        self.progress.update(mine['id'], status='queued', retry=True, retry_push=True); self.progress.execute(mine['id'])
        self.assertNotIn('push', self.modes()); self.assertFalse(self.stored(mine)['pushed'])
        # Not now: a retry on the VM only never uploads.
        self.assertEqual(self.client.post('/api/git/jobs/' + mine['id'] + '/retry', json=dict(push=False)).status_code, 200)
        self.progress.execute(mine['id']); self.assertNotIn('push', self.modes())
        # In the source: the helper's push is asked for in one place, and one route queues it.
        source = Path(git_progress.__file__).read_text(encoding='utf-8')
        self.assertEqual(source.count("'mode': 'push'"), 1); self.assertEqual(source.count('retry_push=True'), 1)
        self.assertEqual(source.count("'push': True"), 0); self.assertEqual(source.count('want_push=True'), 0)
        route = source[source.index("@app.post('/api/git/jobs/{job_id}/retry')"):source.index("@app.post('/api/git/jobs/{job_id}/dismiss')")]
        self.assertIn('retry_push=True', route); self.assertLess(route.index('REVIEW_FIRST'), route.index('retry_push=True'))
        self.assertEqual(self.upload(mine)['status'], 'synced'); self.assertEqual(self.modes().count('push'), 1)

    def test_a_folder_move_and_a_kept_save_at_head_are_what_the_upload_goes_through(self):
        first = self.saved(note='Before the move')
        moved = self.client.post(self.url + '/destination', json=dict(prefix='bgp')).json()
        self.assertEqual(moved['binding']['binding_id'], 'reg-bgp')
        self.texts[self.names[0]] = 'hostname second\n'
        kept = self.saved(note='Kept on the VM')                        # in the new folder, on top of the first save
        self.assertEqual(self.client.post('/api/git/jobs/' + kept['id'] + '/dismiss', json={'acknowledge': True}).status_code, 200)
        answer = self.review(first)
        self.assertEqual((answer['upload_job'], answer['also_sends_kept']), (kept['id'], [dict(lab=self.lab['name'], note='Kept on the VM')]))
        self.assertEqual(answer['also_sends'], [dict(job_id=kept['id'], lab=self.lab['name'], name='Kept on the VM', kind='save', target='latest')])
        outcome = self.upload(first, head=answer['head'])
        self.assertEqual((outcome['id'], outcome['status']), (kept['id'], 'synced'))
        self.assertEqual(next(r for r in self.sent if r['mode'] == 'push')['binding_id'], 'reg-bgp')
        self.assertEqual((self.stored(first)['status'], self.stored(first)['pushed']), ('synced', True))
        # A kept save that is not asked to upload stays refused, as before.
        again = self.saved(note='Another'); self.client.post('/api/git/jobs/' + again['id'] + '/dismiss', json={'acknowledge': True})
        self.assertEqual(self.client.post('/api/git/jobs/' + again['id'] + '/retry', json=dict(push=False)).status_code, 409)

    def test_a_failed_upload_stays_retryable_and_the_chip_learns_why(self):
        mine = self.saved(note='Mine')
        self.vm.push_error = 'The commit is saved on the VM, but push failed. Check authentication, branch permissions or remote changes, then retry.'
        outcome = self.upload(mine)
        self.assertEqual(outcome['status'], 'push_pending')
        status = self.client.get('/api/state').json()['labs'][0]['git_status']
        self.assertEqual((status['ready'], status['code'], status['waiting']), (False, 'account', 1)); self.assertIn('push failed', status['problem'])
        self.vm.push_error = ''
        self.assertEqual(self.upload(mine, reviewed=False)['status'], 'synced', 'the review is recorded with the first attempt')
        self.assertTrue(self.client.get('/api/state').json()['labs'][0]['git_status']['ready'])

    def test_update_from_the_repository_waits_while_a_save_waits_in_the_checkout(self):
        other = self.second_lab()
        theirs = self.saved(other['id'], note='Theirs')
        sent = len(self.sent)
        refused = self.client.post(self.url + '/update', json={})
        self.assertEqual((refused.status_code, refused.json()['detail']), (409, WAITING_FIRST))
        self.assertEqual(self.modes(sent), [], 'the VM was not asked')
        self.upload(theirs)
        self.assertEqual(self.client.post(self.url + '/update', json={}).status_code, 200)
        self.assertIn('update', self.modes(sent))


class NameTests(SaveModelCase):
    """DESIGN.md 3.2: the name is optional; the manager writes it from what changed and it can be changed afterwards."""

    def manifest(self, devices=(), topology=None, map_=None, restore=False, suffix='cfg'):
        files = [dict(path=name + '.' + suffix, sha256=sha, node='clab-lab-' + name, **({'restore_artifact': name + '.xrcfg', 'restore_sha256': restore} if restore else {}))
                 for name, sha in devices]
        if topology: files.append(dict(path='lab.clab.yml', sha256=topology, kind='topology'))
        if map_: files.append(dict(path='lab.clab.yml.annotations.json', sha256=map_, kind='annotations'))
        return dict(schema=2, files=files)

    def name(self, old, new): return change_name(manifest_changes(old, new))

    def test_the_automatic_name_says_what_changed(self):
        base = [('ceos', 'a'), ('cjunos', 'b'), ('xrv9k', 'c'), ('srl', 'd')]
        old = self.manifest(base, 't', 'm')
        change = lambda *names: [(n, s + '2' if n in names else s) for n, s in base]
        table = ((self.manifest(change('ceos'), 't', 'm'), 'ceos changed'),
                 (self.manifest(change('ceos', 'xrv9k'), 't', 'm'), 'ceos and xrv9k changed'),
                 (self.manifest(change('ceos', 'cjunos', 'xrv9k'), 't', 'm'), 'ceos, cjunos and xrv9k changed'),
                 (self.manifest(change('ceos', 'cjunos', 'xrv9k', 'srl'), 't', 'm'), '4 devices changed'),
                 (self.manifest(base, 't2', 'm'), 'Topology changed'),
                 (self.manifest(base, 't', 'm2'), 'Map changed'),
                 (self.manifest(base, 't2', 'm2'), 'Topology and map changed'),
                 (self.manifest(base, 't', None), 'Map changed'),
                 (self.manifest(change('ceos'), 't2', 'm'), 'ceos changed, topology changed'),
                 (self.manifest(change('ceos', 'srl'), 't2', 'm2'), 'ceos and srl changed, topology and map changed'),
                 (self.manifest(base[:3], 't', 'm'), 'srl changed'),
                 (self.manifest(base + [('new', 'n')], 't', 'm'), 'new changed'),
                 (self.manifest(base, 't', 'm'), ''))
        for new, expected in table: self.assertEqual(self.name(old, new), expected)
        self.assertEqual(self.name(None, old), 'First save')
        self.assertEqual(manifest_changes(old, self.manifest(base[:3], 't', 'm'))['removed_devices'], ['srl'])

    def test_devices_are_paired_by_device_never_by_file_name_and_a_restore_artifact_is_no_second_change(self):
        old = self.manifest([('r2', 'a')], suffix='set'); new = self.manifest([('r2', 'a')], suffix='cfg')
        self.assertEqual(self.name(old, new), '', 'the same device under a renamed file is no change')
        self.assertEqual(self.name(old, self.manifest([('r2', 'b')], suffix='cfg')), 'r2 changed')
        both = manifest_changes(self.manifest([('r2', 'a')], restore='x'), self.manifest([('r2', 'b')], restore='y'))
        self.assertEqual(both['devices'], ['r2'], 'one device, once')
        self.assertEqual(self.name(self.manifest([('r2', 'a')], restore='x'), self.manifest([('r2', 'a')], restore='y')), 'r2 changed')
        legacy = dict(schema=1, files=[dict(path='r2.set', sha256='a')])   # an entry saved without its device name
        self.assertEqual(self.name(legacy, new), '')
        long = [('device-with-a-very-long-name-number-%d-of-the-lab' % n, 'x') for n in range(3)]
        self.assertEqual(self.name(self.manifest([(n, 'y') for n, _ in long], 't'), self.manifest(long, 't2')), '3 devices changed, topology changed')

    def test_a_save_is_named_once_before_its_first_publication_and_the_body_never_changes(self):
        first = self.post(note='')
        self.assertEqual((first['note'], first['note_auto']), ('', False))
        self.vm.lost.add(first['id'])                                   # the VM commits, the answer is lost
        outcome, _ = self.run_job(first)
        self.assertEqual((outcome['status'], outcome['note'], outcome['note_auto']), ('export_pending', 'First save', True))
        self.assertEqual(self.client.post('/api/git/jobs/' + first['id'] + '/retry', json=dict(push=True)).status_code, 200)
        outcome, submit = self.run_job(first); submit.assert_not_called()
        self.assertEqual((outcome['status'], outcome['note']), ('review_pending', 'First save'))
        published = [r for r in self.sent if r['mode'] == 'publish']
        self.assertEqual(len(published), 2); self.assertEqual(published[0], published[1], 'the retry replays the identical body')
        self.assertEqual((published[0]['message'], published[0]['allow_removed']), ('First save', True))
        self.assertEqual(self.vm.log[outcome['commit']]['subject'], 'First save')
        self.upload(first)
        # The next save names the device that changed, by the label a person sees; a typed name is kept as typed.
        self.texts[self.names[0]] = 'hostname changed\n'
        second = self.saved()
        self.assertEqual((second['note'], second['note_auto'], second['summary']['devices']), ('r1 changed', True, ['r1']))
        self.texts[self.names[1]] = 'hostname changed too\n'; self.topology = TOPOLOGY + '# edited\n'
        typed = self.saved(note='OSPF adjacencies up')
        self.assertEqual((typed['note'], typed['note_auto']), ('OSPF adjacencies up', False))
        self.assertEqual(self.stored(typed)['auto_note'], 'r2 changed, topology changed', 'kept privately, so a rename can return to it')
        self.upload(typed)
        # A save that changed nothing stays unnamed and makes no commit.
        same = self.saved()
        self.assertEqual((same['status'], same['note'], same['changed_files']), ('unchanged', '', [])); self.assertNotIn('summary', same)

    def test_renaming_changes_what_the_manager_shows_and_never_a_commit(self):
        job = self.saved()
        self.assertEqual((job['note'], job['note_auto']), ('First save', True))
        running = self.post(note='Running meanwhile')                   # queued: every route held by idle() refuses now
        self.assertEqual(self.client.post(self.url + '/unlink', json={}).status_code, 409)
        sent = len(self.sent)
        renamed = self.client.post('/api/git/jobs/' + job['id'] + '/name', json=dict(note='  BGP sessions up  '))
        self.assertEqual(renamed.status_code, 200, renamed.text)
        self.assertEqual((renamed.json()['note'], renamed.json()['note_auto']), ('BGP sessions up', False))
        self.assertEqual(self.modes(sent), [], 'the VM is not asked and no commit is touched')
        self.assertEqual(self.vm.log[job['commit']]['subject'], 'First save')
        for bad in ('two\nlines', 'tab\there', 'x' * 121):
            response = self.client.post('/api/git/jobs/' + job['id'] + '/name', json=dict(note=bad))
            self.assertEqual(response.status_code, 400, bad)
        self.assertEqual(self.stored(job)['note'], 'BGP sessions up')
        self.assertEqual(self.client.post('/api/git/jobs/' + 'f' * 32 + '/name', json=dict(note='x')).status_code, 404)
        for view in self.public_views(job):
            self.assertEqual(view['note'], 'BGP sessions up')
            for key in PRIVATE: self.assertNotIn(key, view)
        self.assertEqual(self.store.state['git_save_names'], {job['commit']: 'BGP sessions up'})
        # An empty name returns to the automatic one, here and by commit.
        back = self.client.post('/api/git/jobs/' + job['id'] + '/name', json=dict(note=''))
        self.assertEqual((back.json()['note'], back.json()['note_auto']), ('First save', True))
        self.assertEqual(self.store.state['git_save_names'], {})
        self.progress.update(running['id'], status='dismissed')

    def test_a_renamed_save_keeps_its_name_after_the_job_cap_and_remove_lab_while_its_commit_is_listed(self):
        job = self.saved()
        self.client.post('/api/git/jobs/' + job['id'] + '/name', json=dict(note='BGP sessions up'))
        self.assertEqual(self.upload(job)['status'], 'synced')
        history = lambda url=self.url: {row['commit']: row.get('name') for row in self.client.get(url + '/history').json()['commits']}
        self.assertEqual(history(), {job['commit']: 'BGP sessions up'})
        # The job cap lets the save go.
        newer = self.saved(note='Newer')                                 # nothing changed: the newest uploaded save of the binding, always kept
        self.assertEqual((newer['status'], newer['pushed']), ('unchanged', True))
        with self.store.lock, patch('app.git_progress.GIT_JOB_CAP', 3):
            for n in range(3): _append_git_job(self.store.state, dict(id='later%d' % n, lab_id='other', status='dismissed'))
            self.store.save()
        self.assertNotIn(job['id'], [j['id'] for j in self.store.state['git_jobs']])
        self.assertEqual(history()[job['commit']], 'BGP sessions up')
        self.assertEqual(Store(self.tmp.name).state['git_save_names'], {job['commit']: 'BGP sessions up'}, 'stored')
        # Remove lab drops every save of the lab; another lab of the repository still lists the commit under its name.
        other = self.second_lab()
        removed = self.client.request('DELETE', '/api/labs/' + self.lab['id'], json={'name': self.lab['name']})
        self.assertEqual(removed.status_code, 200, removed.text)
        self.assertFalse([j for j in self.store.state['git_jobs'] if j.get('lab_id') == self.lab['id']])
        self.assertEqual(history('/api/labs/' + other['id'] + '/git')[job['commit']], 'BGP sessions up')
        self.assertNotIn('git_save_names', self.client.get('/api/state').json())

    def test_the_names_kept_by_commit_are_capped_oldest_out(self):
        with self.store.lock:
            for n in range(MAX_SAVE_NAMES + 5): self.progress.remember_name('%040x' % n, 'Name %d' % n)
            names = self.store.state['git_save_names']
        self.assertEqual(len(names), MAX_SAVE_NAMES)
        self.assertNotIn('%040x' % 4, names); self.assertEqual(list(names)[0], '%040x' % 5); self.assertEqual(list(names)[-1], '%040x' % (MAX_SAVE_NAMES + 4))


class CheckpointFromSaveTests(SaveModelCase):
    """DESIGN.md 3.5: *Keep as a checkpoint* is the save route with the save's capture; no device is read."""

    def test_a_checkpoint_from_a_save_takes_its_name_and_reads_no_device(self):
        save = self.saved(note='OSPF adjacencies up!')
        self.assertEqual((save['captured'], save['capture_kept'], save['capture_whole']), (True, True, True))
        kept = self.post(target='checkpoint', backup_job_id=save['backup_job_id'], checkpoint='')
        self.assertEqual((kept['checkpoint'], kept['note'], kept['destination']['path']), ('ospf-adjacencies-up', 'OSPF adjacencies up!', 'checkpoints/ospf-adjacencies-up'))
        outcome, submit = self.run_job(kept); submit.assert_not_called()
        self.assertEqual(outcome['status'], 'review_pending', outcome)
        self.assertEqual((outcome['captured'], outcome['capture_kept'], outcome['capture_whole']), (False, True, True))
        published = [r for r in self.sent if r['mode'] == 'publish'][-1]
        self.assertEqual((published['target'], published['checkpoint'], published['message']), ('checkpoint', 'ospf-adjacencies-up', 'OSPF adjacencies up!'))
        self.assertIn('checkpoints/ospf-adjacencies-up/manifest.json', outcome['changed_files'])
        # The name is taken: the next one counts on, from the lab's saves and from what the repository holds.
        again = self.post(target='checkpoint', backup_job_id=save['backup_job_id'], checkpoint='')
        self.assertEqual(again['checkpoint'], 'ospf-adjacencies-up-2')
        self.progress.update(again['id'], status='dismissed')
        with self.store.lock:
            self.store.state['git_jobs'] = [j for j in self.store.state['git_jobs'] if j['id'] not in (kept['id'], again['id'])]; self.store.save()
        self.progress.forget_views()
        third = self.post(target='checkpoint', backup_job_id=save['backup_job_id'], checkpoint='')
        self.assertEqual(third['checkpoint'], 'ospf-adjacencies-up-2', 'the first is in the repository, the second never got there')
        # A name the manager wrote is carried as automatic; a save without any name still gets a folder.
        self.progress.update(third['id'], status='dismissed'); self.progress.update(save['id'], note='ceos changed', note_auto=True)
        auto = self.post(target='checkpoint', backup_job_id=save['backup_job_id'], checkpoint='')
        self.assertEqual((auto['checkpoint'], auto['note'], auto['note_auto']), ('ceos-changed', 'ceos changed', True))
        self.progress.update(auto['id'], status='dismissed'); self.progress.update(save['id'], note='')
        self.assertEqual(self.post(target='checkpoint', backup_job_id=save['backup_job_id'], checkpoint='')['checkpoint'], 'checkpoint')

    def test_the_folder_name_is_made_in_the_helpers_alphabet(self):
        for note, slug in (('ceos and xrv9k changed', 'ceos-and-xrv9k-changed'), ('First save', 'first-save'), ('  Über/Lab: 2!  ', 'ber-lab-2'),
                           ('_x_', 'x'), ('', 'checkpoint'), ('!!!', 'checkpoint'), ('A' * 200, 'a' * 80)):
            self.assertEqual(checkpoint_slug(note), slug); self.assertRegex(checkpoint_slug(note), r'\A[A-Za-z0-9][A-Za-z0-9_-]{0,99}\Z')
        self.assertEqual(free_checkpoint('day', []), 'day'); self.assertEqual(free_checkpoint('day', ['day', 'DAY-2']), 'day-3')

    def test_a_capture_that_is_gone_or_not_whole_is_not_saved_again_and_the_page_is_told(self):
        save = self.saved(note='Kept')
        with self.store.lock:
            capture = next(b for b in self.store.state['jobs'] if b['id'] == save['backup_job_id']); record = capture.pop('topology'); self.store.save()
        for view in self.public_views(save): self.assertEqual((view['capture_kept'], view['capture_whole']), (True, False))
        refused = self.post(expect=400, target='checkpoint', backup_job_id=save['backup_job_id'], checkpoint='')
        self.assertEqual(refused['detail'], NOT_WHOLE)
        with self.store.lock: capture['topology'] = record; capture['topology_missing'] = 'map-error'; self.store.save()
        self.assertEqual(self.post(expect=400, target='baseline', backup_job_id=save['backup_job_id'])['detail'], NOT_WHOLE)
        with self.store.lock: self.store.state['jobs'].remove(capture); self.store.save()
        for view in self.public_views(save): self.assertEqual((view['captured'], view['capture_kept'], view['capture_whole']), (True, False, False))
        missing = self.post(expect=404, target='checkpoint', backup_job_id=save['backup_job_id'], checkpoint='')
        self.assertEqual(missing['detail'], 'Capture not found in this lab.')
        self.assertEqual(len(self.store.state['git_jobs']), 1, 'nothing was queued and nothing recaptured')


class WholeLabAndDeviceTests(SaveModelCase):
    """DESIGN.md 3.9 and 3.3."""

    def test_a_capture_that_could_not_embed_the_topology_or_the_map_stops_the_save(self):
        for missing in ('error', 'map-error'):
            self.missing = missing
            outcome = self.saved()
            self.assertEqual((outcome['status'], outcome['message'], outcome['capture_whole']), ('capture_incomplete', TOPOLOGY_FAILED, False))
        self.assertNotIn('publish', self.modes())

    def test_a_lab_without_topology_text_saves_its_devices_as_before(self):
        self.missing = 'no-text'; self.topology = ''
        with self.store.lock: self.store.lab(self.lab['id'])['definition_yaml'] = ''; self.store.save()
        outcome = self.saved()
        self.assertEqual((outcome['status'], outcome['capture_whole']), ('review_pending', True))
        self.assertEqual(sorted(outcome['changed_files']), ['latest/manifest.json', 'latest/r1.cfg', 'latest/r1.xrcfg', 'latest/r2.cfg', 'latest/r2.jcfg'])

    def test_a_device_that_left_the_lab_leaves_the_selection_with_the_next_save(self):
        waiting = self.saved(note='Both devices')
        with self.store.lock:
            lab = self.store.lab(self.lab['id']); gone = lab['nodes'].pop(); old = lab['git_binding']; before = copy.deepcopy(old); self.store.save()
        self.texts[self.names[0]] = 'hostname after\n'
        job = self.post()
        new = self.store.lab(self.lab['id'])['git_binding']
        self.assertEqual(new['node_names'], self.names[:1]); self.assertIsNot(new, old)
        self.assertEqual(old, before, 'the binding the waiting save was made with is not edited')
        self.assertEqual(self.stored(waiting)['binding']['node_names'], self.names)
        self.assertEqual((self.stored(job)['binding'], self.stored(job)['binding_digest']), (new, git_digest(new)))
        outcome, submit = self.run_job(job)
        self.assertEqual(submit.call_args.kwargs['node_names'], self.names[:1])
        self.assertEqual(outcome['status'], 'review_pending', outcome)
        published = [r for r in self.sent if r['mode'] == 'publish'][-1]
        self.assertIs(published['allow_removed'], True)
        self.assertEqual(published['snapshot']['manifest']['node_names'], self.names[:1])
        self.assertEqual((outcome['summary']['removed_devices'], outcome['summary']['devices']), (['r2'], ['r1', 'r2']))
        self.assertIn('latest/r2.cfg', outcome['changed_files'])
        self.assertEqual(gone['name'], self.names[1])

    def test_no_device_left_is_cant_save_with_save_settings(self):
        with self.store.lock:
            self.store.lab(self.lab['id'])['git_binding']['node_names'] = ['gone-1', 'gone-2']; self.store.save()
        refused = self.post(expect=409)
        self.assertEqual(refused['detail'], NO_DEVICES)
        self.assertEqual(self.store.lab(self.lab['id'])['git_binding']['node_names'], ['gone-1', 'gone-2'], 'nothing was changed')
        self.assertEqual(self.store.state['git_jobs'], [])

    def test_removals_are_always_allowed_whatever_an_older_page_sends(self):
        for value in (False, True):
            self.texts[self.names[0]] = 'hostname %s\n' % value
            self.saved(allow_removed=value)
        self.assertEqual([r['allow_removed'] for r in self.sent if r['mode'] == 'publish'], [True, True])


class ReviewTests(SaveModelCase):
    """DESIGN.md 3.8 N4: the change summary on the job and the files of a review."""

    def test_the_summary_is_stored_with_the_save_as_counts_and_labels(self):
        first = self.saved()
        self.assertEqual(first['summary'], dict(devices=['r1', 'r2'], added=2, removed=0, topology=True, map=True, first=True, removed_devices=[]))
        self.texts[self.names[0]] = 'hostname router-0\ninterface Loopback0\n ip address 10.0.0.1/32\n'; self.map = '{"nodeAnnotations": [1]}'
        second = self.saved()
        self.assertEqual(second['summary'], dict(devices=['r1'], added=2, removed=0, topology=False, map=True, first=False, removed_devices=[]),
                         'the device counts once (its restore artifact changed too) and lines are those of its configuration')
        for view in self.public_views(second): self.assertEqual(view['summary'], second['summary'])
        self.assertNotIn('Loopback0', json.dumps(self.client.get('/api/state').json()), 'never configuration text')
        self.assertEqual(self.modes().count('compare'), 2, 'asked once per save')
        self.assertEqual(self.review(second)['summary'], second['summary'])

    def test_a_comparison_that_fails_leaves_the_summary_absent_and_the_save_stands(self):
        self.vm.compare_error = 'This comparison is too large to view inline. Download its saved versions instead.'
        outcome = self.saved()
        self.assertEqual(outcome['status'], 'review_pending'); self.assertNotIn('summary', outcome)
        self.assertTrue(outcome['commit'])
        self.assertTrue(self.client.get('/api/state').json()['labs'][0]['git_status']['ready'], 'a failed comparison says nothing about the save location')

    def test_every_file_of_the_review_has_its_role_and_device_and_every_changed_path_is_listed(self):
        save = self.saved(note='First', target='checkpoint', checkpoint='day-1')
        answer = self.review(save)
        rows = {f['path']: f for f in answer['files']}
        self.assertEqual(sorted(rows), sorted(save['changed_files']), 'one row for every path the commit changed')
        roles = {path: (row['role'], row['node'], 'diff' in row) for path, row in rows.items()}
        self.assertEqual(roles, {
            'checkpoints/day-1/r1.cfg': ('device', 'r1', True), 'checkpoints/day-1/r1.xrcfg': ('restore', 'r1', True),
            'checkpoints/day-1/r2.cfg': ('device', 'r2', True), 'checkpoints/day-1/r2.jcfg': ('restore', 'r2', True),
            'checkpoints/day-1/training.clab.yml': ('topology', '', True), 'checkpoints/day-1/training.clab.yml.annotations.json': ('map', '', True),
            'checkpoints/day-1/manifest.json': ('manifest', '', False),
            'latest/r1.cfg': ('device', 'r1', False), 'latest/r1.xrcfg': ('restore', 'r1', False), 'latest/r2.cfg': ('device', 'r2', False),
            'latest/r2.jcfg': ('restore', 'r2', False), 'latest/training.clab.yml': ('topology', '', False),
            'latest/training.clab.yml.annotations.json': ('map', '', False), 'latest/manifest.json': ('manifest', '', False)})
        self.assertEqual({key for key in ('files', 'summary', 'head', 'upload_job', 'also_sends', 'also_sends_count', 'also_sends_other_labs', 'also_sends_kept')}, set(answer))
        self.assertEqual((answer['head'], answer['upload_job'], answer['also_sends']), (save['commit'], save['id'], []))

    def test_roles_come_from_the_names_the_manager_gives_its_files(self):
        table = {'manifest.json': ('manifest', ''), 'latest/ceos.cfg': ('device', 'ceos'), 'r2.set': ('device', 'r2'), 'r2.jcfg': ('restore', 'r2'),
                 'x.xrcfg': ('restore', 'x'), 'x.eoscfg': ('restore', 'x'), 'lab.clab.yml': ('topology', ''), 'lab.clab.yml.annotations.json': ('map', ''),
                 'README.md': ('other', ''), 'noextension': ('other', '')}
        for name, expected in table.items(): self.assertEqual(file_role(name), expected, name)
        files = review_files([dict(name='r1.cfg', status='changed', before='a\nb\n', after='a\nc\nd\n'), dict(name='r1.xrcfg', status='changed', before='a\n', after='b\n'),
                              dict(name='r9.cfg', status='removed', before='x\ny\n', after='')], dict(snapshot_path='latest', changed_files=['latest/manifest.json']))
        self.assertEqual(save_summary(files), dict(devices=['r1', 'r9'], added=2, removed=3, topology=False, map=False, first=False, removed_devices=['r9']))
        design = review_files([dict(name='ceos.cfg', status='added', before='', after='x\n')], dict(kind='design', snapshot_path='checkpoints/d', changed_files=[]))
        self.assertEqual((design[0]['role'], design[0]['node']), ('other', ''), 'a design export holds no device file')

    def test_a_save_of_another_checkout_is_not_opened_from_this_lab(self):
        other = self.register(discovery_tests.YAML.replace(b'name: training', b'name: other-lab'))
        self.vm.registry.append(dict(self.repo, id='elsewhere', path='/home/ben/labs/other', revision='rev-elsewhere', label='Other'))
        mine = self.saved(note='Mine')
        self.client.put('/api/labs/' + other['id'] + '/git', json=dict(binding_id='elsewhere', node_names=[n['name'] for n in self.store.lab(other['id'])['nodes']]))
        refused = self.client.post('/api/labs/' + other['id'] + '/git/compare', json={'job_id': mine['id']})
        self.assertEqual(refused.status_code, 404, refused.text)
        self.assertEqual(self.client.post('/api/labs/nope/git/compare', json={'job_id': mine['id']}).status_code, 404)


class GitStatusTests(SaveModelCase):
    """DESIGN.md 3.8 N1: what the chip knows about a lab's save location."""

    def status(self, index=0): return self.client.get('/api/state').json()['labs'][index]['git_status']

    def test_the_last_check_is_kept_per_lab_and_the_poll_never_asks_the_vm(self):
        self.progress.statuses.clear()
        self.assertEqual(self.status(), dict(checked='', ready=None, problem='', code='', waiting=0))
        sent = len(self.sent)
        for _ in range(3): self.client.get('/api/state')
        self.assertEqual(self.modes(sent), [], 'the poll asks nothing')
        self.client.get(self.url)
        seen = self.status()
        self.assertEqual((seen['ready'], seen['problem'], seen['code'], seen['waiting']), (True, '', '', 0)); self.assertTrue(seen['checked'])
        self.vm.problem = 'The repository has unsaved edits in the selected scope. Resolve them before continuing.'
        self.client.get(self.url)
        self.assertEqual((self.status()['ready'], self.status()['code'], self.status()['problem']), (False, 'busy', self.vm.problem))
        # A save that the repository stops records it too, and so does one that works again.
        self.progress.statuses.clear()
        outcome = self.saved()
        self.assertEqual(outcome['status'], 'export_pending'); self.assertEqual((self.status()['ready'], self.status()['code']), (False, 'busy'))
        self.vm.problem = ''
        self.client.post('/api/git/jobs/' + outcome['id'] + '/retry', json=dict(push=False)); self.run_job(outcome)
        self.assertEqual((self.status()['ready'], self.status()['waiting']), (True, 1))
        # A VM that cannot be reached.
        self.helper.side_effect = OSError('no route'); self.client.get(self.url)
        self.assertEqual((self.status()['ready'], self.status()['code']), (False, 'vm'))
        self.assertNotIn('git_status', json.dumps(Store(self.tmp.name).state), 'kept in memory only')

    def test_waiting_counts_every_save_of_the_labs_checkout_and_a_disconnected_labs_own(self):
        other = self.second_lab()
        self.saved(note='Mine'); self.saved(other['id'], note='Theirs')
        self.assertEqual((self.status(0)['waiting'], self.status(1)['waiting']), (2, 2))
        self.assertEqual(self.client.post(self.url + '/unlink', json={}).status_code, 200)
        self.assertEqual((self.status(0)['waiting'], self.status(1)['waiting']), (1, 2), 'a disconnected lab still shows its own waiting save')

    def test_every_sentence_the_helper_can_answer_has_its_code(self):
        tree = ast.parse((Path(git_progress.__file__).parent / 'host_git.py').read_text(encoding='utf-8'))
        constants = {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)}
        for sentence in HELPER_PROBLEMS: self.assertIn(sentence, constants, 'reworded in host_git.py: ' + sentence)
        # Every sentence that `status`, `publish`, `push` and `update` can raise, with what they call, is in the table.
        reached = {'main', 'dispatch', '__init__', 'no_links', 'relpath', 'snapshot', 'take', 'command', 'root_file', 'load_registry', 'drop_owner', 'run',
                   'commit_identity', 'lock', 'validate', 'clean', 'file', 'read_manifest', 'check', 'status', 'journal_path', 'load_journal', 'remote_head',
                   'verify_tree', 'push', 'retry_push', 'finish_export', 'publish', 'update'}
        raised = set()
        for function in ast.walk(tree):
            if not isinstance(function, ast.FunctionDef) or function.name not in reached: continue
            for node in ast.walk(function):
                if isinstance(node, ast.Call) and getattr(node.func, 'id', '') in ('ValueError', 'exclusive'):
                    raised |= {a.value for a in node.args if isinstance(a, ast.Constant) and isinstance(a.value, str)}
        self.assertGreater(len(raised), 80)
        self.assertEqual(sorted(raised - set(HELPER_PROBLEMS)), [], 'a helper sentence without a code')
        own = Path(git_progress.__file__).read_text(encoding='utf-8')
        for sentence in MANAGER_PROBLEMS: self.assertIn(sentence, own)
        self.assertEqual(set(HELPER_PROBLEMS.values()) | set(MANAGER_PROBLEMS.values()), {'vm', 'account', 'busy', 'diverged', 'files', 'settings', 'other'})
        for sentence, code in (('The repository already has staged changes. If an earlier manager save failed, fix its reported issue and retry that original save: Retry commits automatically. For unrelated staged work, resolve it as the repository owner first.', 'busy'),
                               ('Finish the existing Git operation before saving lab progress.', 'busy'),
                               ('The remote branch advanced or diverged. Resolve the branch before pushing; no force push was attempted.', 'diverged'),
                               ('Local and remote history diverged or local commits are pending. Resolve them as the repository owner.', 'diverged'),
                               ('The destination contains files outside its manager manifest; preserve or move them first.', 'files'),
                               ('The Git push destination changed. Register the repository again.', 'settings'),
                               ("The remote branch is unavailable. Check connectivity and the owner's noninteractive HTTPS Git login.", 'account'),
                               ('Cannot reach the VM Git helper. The local capture is retained; check VM setup and retry.', 'vm'),
                               ('Update the VM Git helper to match manager 9.9.9 using setup-git.sh --refresh.', 'vm'),
                               ('Something nobody listed.', 'other'), ('', 'other')):
            self.assertEqual(problem_code(sentence), code, sentence)

    def test_no_message_names_the_progress_tab_or_the_vms_plumbing(self):
        # DESIGN.md 2.1, DRAWERS.md 6.4: a person is sent to Save, Load, Save settings or the save status, and never
        # reads "registration", "prefix" or "overlap". The helper's own sentences (the table's keys) are not the manager's.
        tree = ast.parse(Path(git_progress.__file__).read_text(encoding='utf-8'))
        docs = {id(n.body[0].value) for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.ClassDef, ast.Module)) and n.body
                and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant)}
        import re
        found = [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs and ' ' in n.value
                 and n.value not in HELPER_PROBLEMS and re.search(r'Progress\b|registration|\bprefix\b|overlap|Recent saves|Git history|Save location', n.value)]
        self.assertEqual(found, [])


class LabStateTests(SaveModelCase):
    """DESIGN.md 2.9: *Save as a lab state…* is a normal save into a folder of its own, through a binding of its own."""

    def state(self, lab_id=None, expect=200, **fields):
        data = dict(request_id=uuid.uuid4().hex, folder='start', name='Start'); data.update(fields)
        response = self.client.post('/api/labs/' + (lab_id or self.lab['id']) + '/git/state', json=data)
        self.assertEqual(response.status_code, expect, response.text)
        return response.json()

    def test_a_lab_state_is_saved_in_its_own_folder_and_the_labs_save_location_is_untouched(self):
        own = self.saved(note='My latest'); self.upload(own)
        before = copy.deepcopy(self.store.lab(self.lab['id'])['git_binding']); sent = len(self.sent)
        job = self.state()
        self.assertEqual((job['kind'], job['target'], job['note'], job['note_auto'], job['destination']['path'], job['status']),
                         ('state', 'latest', 'Start', False, 'start/latest', 'queued'))
        register = [r for r in self.sent[sent:] if r['mode'] == 'register-prefix']
        self.assertEqual([(r['prefix'], r.get('retire')) for r in register], [('start', None)], 'the folder is registered, nothing is retired')
        self.assertEqual(self.store.lab(self.lab['id'])['git_binding'], before)
        stored = self.stored(job)
        self.assertEqual((stored['binding']['binding_id'], stored['binding']['repository']['prefix'], stored['binding']['node_names']), ('reg-start', 'start', self.names))
        view = self.progress.checkout_view(before)
        self.assertEqual(view['pending_states'], [dict(prefix='start', name='Start')])
        again = self.client.post(self.url + '/state', json=dict(request_id=job['id'], folder='start', name='Start'))
        self.assertEqual(again.json()['id'], job['id'], 'the same request is the same save')
        outcome, submit = self.run_job(job)
        submit.assert_called_once()   # it captures the lab now
        self.assertEqual((outcome['status'], outcome['captured'], outcome['summary']['first']), ('review_pending', True, True))
        published = [r for r in self.sent if r['mode'] == 'publish'][-1]
        self.assertEqual((published['binding_id'], published['target'], published['message'], published['allow_removed']), ('reg-start', 'latest', 'Start', True))
        self.assertEqual(published['snapshot']['manifest']['state'], 'Start', 'a lab state marks itself in its manifest')
        self.assertNotIn('state', self.vm.trees[own['commit']]['latest']['manifest'], 'an ordinary save does not')
        self.assertEqual(sorted(p for p in outcome['changed_files']), sorted('start/latest/' + n for n in ('manifest.json', 'r1.cfg', 'r1.xrcfg', 'r2.cfg', 'r2.jcfg', 'training.clab.yml', 'training.clab.yml.annotations.json')))
        self.assertEqual(self.store.lab(self.lab['id'])['git_binding'], before, 'still untouched after it ran')
        self.assertEqual(self.client.get('/api/state').json()['labs'][0]['git_status']['waiting'], 1, 'it waits for upload like any save')
        # It is listed as a lab state for the lab that saved it, and is loadable as <folder>/latest.
        states = self.progress.states(self.lab['id'])
        rows = {row['path']: row for row in states['states']}
        self.assertEqual({path: (row['group'], row['name']) for path, row in rows.items()}, {'latest': ('latest', 'Top level'), 'start/latest': ('state', 'Start')})
        self.assertEqual((states['head'], states['truncated'], rows['start/latest']['commit'], rows['start/latest']['layout']), (outcome['commit'], False, outcome['commit'], 'latest'))
        self.assertEqual(set(rows['start/latest']), {'path', 'name', 'group', 'lab', 'kind', 'layout', 'saved_at', 'summary', 'commit'})
        self.assertEqual(rows['start/latest']['saved_at'], '2026-09-11T10:01:00+00:00')
        version = self.client.post(self.url + '/version', json=dict(commit=outcome['commit'], path='start/latest'))
        self.assertEqual(version.status_code, 200, version.text); self.assertEqual(version.json()['manifest']['state'], 'Start')
        listed = self.client.get('/api/labs/' + self.lab['id'] + '/restore/states').json()
        self.assertIn('start/latest', [row['path'] for row in listed['states']])
        # Its upload goes through its own binding.
        self.assertEqual(self.upload(outcome)['status'], 'synced')
        self.assertEqual([r['binding_id'] for r in self.sent if r['mode'] == 'push'][-1], 'reg-start')
        # The same name again: one question, answered with Replace it.
        asked = self.state()
        self.assertEqual((asked['question']['kind'], asked['question']['folder'], asked['question']['label']), ('state', 'start', 'Start'))
        self.assertEqual(len([j for j in self.store.state['git_jobs'] if j.get('kind') == 'state']), 1, 'a question queues nothing')
        self.texts[self.names[0]] = 'hostname replaced\n'
        replaced = self.state(choice='take')
        outcome, _ = self.run_job(replaced)
        self.assertEqual((outcome['status'], outcome['summary']['devices'], outcome['summary']['first']), ('review_pending', ['r1'], False))

    def test_a_lab_state_never_goes_into_a_labs_own_folder(self):
        other = self.second_lab()
        for folder, expected in (('', 'Start'), ('sibling', 'sibling/Start')):
            job = self.state(folder=folder, name='Start')
            self.assertEqual(job['destination']['path'], expected + '/latest', 'the state gets its own folder inside')
            self.progress.update(job['id'], status='dismissed')
        self.assertEqual(self.store.lab(other['id'])['git_binding']['binding_id'], 'reg-sibling')

    def test_a_lab_without_a_save_location_names_the_repository(self):
        self.assertEqual(self.client.post(self.url + '/unlink', json={}).status_code, 200)
        self.assertEqual(self.state(expect=400)['detail'], 'Choose the repository this lab state is saved in.')
        self.assertEqual(self.state(expect=404, repository='nope')['detail'], 'This repository is not registered on the VM. Refresh the list.')
        job = self.state(repository='bens-lab', folder='course/start', name='Course start')
        outcome, _ = self.run_job(job)
        self.assertEqual((outcome['status'], outcome['destination']['path']), ('review_pending', 'course/start/latest'))
        self.assertEqual(self.stored(job)['binding']['node_names'], self.names, 'every supported device of the lab')
        self.assertNotIn('git_binding', self.store.lab(self.lab['id']))
        # Without a save location the lab lists, views and downloads through the repository it names.
        self.assertEqual(self.client.get(self.url + '/history').status_code, 409)
        history = self.client.get(self.url + '/history', params=dict(repository='bens-lab'))
        self.assertEqual(history.status_code, 200, history.text); self.assertEqual(history.json()['commits'][0]['name'], 'Course start')
        body = dict(commit=outcome['commit'], path='course/start/latest', repository='bens-lab')
        self.assertEqual(self.client.post(self.url + '/version', json=body).status_code, 200)
        self.assertEqual(self.client.post(self.url + '/version/download', json=body).status_code, 200)
        self.assertEqual(self.client.post(self.url + '/version', json=dict(body, repository='')).status_code, 409)
        self.assertEqual(self.progress.states(self.lab['id'], 'bens-lab')['states'][0]['group'], 'state')

    def test_a_lab_state_is_validated_and_waits_for_running_work_and_other_placements(self):
        for fields in (dict(name='two\nlines'), dict(name='x' * 121), dict(name='   '), dict(choice='beside')):
            self.assertEqual(self.client.post(self.url + '/state', json=dict(dict(request_id=uuid.uuid4().hex, folder='start', name='Start'), **fields)).status_code, 400, fields)
        self.assertEqual(self.client.post(self.url + '/state', json=dict(request_id=uuid.uuid4().hex, folder='/'.join(['abcdefghij'] * 60), name='Start')).status_code, 400)
        with self.progress.changing('another-lab'):
            self.assertIn('Try again in a moment', self.state(expect=409)['detail'])
        running = self.post(note='Running')
        self.assertEqual(self.state(expect=409)['detail'], 'Wait for the active backup, Git save or lab operation to finish.')
        self.progress.update(running['id'], status='dismissed')
        with self.store.lock: self.store.lab(self.lab['id'])['git_binding']['node_names'] = ['gone']; self.store.save()
        self.assertEqual(self.state(expect=409)['detail'], NO_DEVICES)
        self.assertEqual([j for j in self.store.state['git_jobs'] if j.get('kind') == 'state'], [])

    def test_a_lab_is_not_placed_into_a_folder_a_lab_state_is_on_its_way_into(self):
        other = self.register(discovery_tests.YAML.replace(b'name: training', b'name: other-lab'))
        job = self.state()                                              # queued: nothing committed yet (review F11)
        names = [n['name'] for n in self.store.lab(other['id'])['nodes']]
        self.progress.update(job['id'], status='export_pending')         # not busy any more, still without a commit
        with self.assertRaises(Exception) as refused:
            self.progress.bind_lab(other['id'], next(r for r in self.vm.registry if r['id'] == 'reg-start'), names, True,
                                   self.stored(job)['binding']['host_identity'], 'git.connect', 'x')
        self.assertIn('A lab state is being saved into this folder right now', str(refused.exception.detail))
        self.assertNotIn('git_binding', self.store.lab(other['id']))


if __name__ == '__main__':
    unittest.main()
