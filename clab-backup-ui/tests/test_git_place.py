"""The place routes (app/git_place.py): a lab can be placed in any folder of a repository, and no folder choice is ever
refused (docs/git-redesign/PROMPT.md 6.1 and 6.2, DESIGN.md 2.4 to 2.8, 4 and 7.4).

Every test drives the HTTP routes against `FakeVM`, a helper that keeps its records the way the real one does: new folders
are planned with the real `host_git.plan_prefix` (so the collision rule is the helper's own `colliding()`), a connect follows
`host_git.plan_connect`'s matching of known repositories, and a retire is refused while a save made through that record
waits for upload (DESIGN.md 2.3 H7). Only temporary data directories are used.
"""
import ast
import copy
import threading
import types
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

import test_discovery as discovery_tests
from app import __version__, host_git
from app.git_place import FORBIDDEN, IN_USE, TOO_LONG
from app.git_progress import PROTOCOL, digest as git_digest, job_pending

LOOKUP = lambda owner: types.SimpleNamespace(pw_uid=1000, pw_gid=1000, pw_dir='/home/' + owner)
EMPTY_SENTENCE = 'This repository has no commits yet. Start it with a README.md file, or add one on GitHub first.'
WAITING_SENTENCE = 'A save made through this folder registration still waits for upload; it was not retired.'
BUSY = 'Another repository connection is being changed. Try again in a moment.'
HOSTILE = ['', ' ', '/', '//', 'a//b', 'a/b/', '/a/b', ' a / b ', 'my lab', 'UX TEST (3)', 'é', 'Übung/größe', '日本語', 'a\\b', '\\\\server\\share',
           '..', '.', '../..', 'a/../b', 'a/./b', '.hidden', '..hidden', '-dash', '--', '-.-', '.git', '.GIT', 'a/.git/b', '.Git/hooks', '.gitignore',
           'a\x00b', 'a\nb', '\t', '\x7f', 'a\r\n/b', 'latest', 'a/latest', 'checkpoints/x', 'x' * 600, 'x' * 181, 'x' * 182, '-' * 300 + 'a',
           'a?', '?a', 'a?b', 'a-', 'a.', 'a..b', '~', '$(rm -rf)', 'a;b|c', 'a​b', '﻿a', 'a' + '/' * 50 + 'b', 'CON', 'a:b', '%2e%2e', 'a/%2f/b']


class FakeVM:
    """The VM helper as the manager meets it, with the real helper's record rules."""

    def __init__(self):
        self.registry = []; self.files = {}; self.summaries = {}; self.empty = set(); self.waiting = set()
        self.sent = []; self.cap = host_git.MAX_TREE; self.connect_error = ''; self.count = 0
        self.gate = None; self.entered = threading.Event()

    def add(self, name, prefix='', path=None):
        """A record as guided setup or an older release left it."""
        self.count += 1
        reg = dict(id='r%03d' % self.count, label=name + (' / ' + prefix if prefix else ''), owner='ben', path=path or '/home/ben/labs/' + name, remote='origin',
                   push_url='https://github.com/ben/' + name + '.git', branch='main', prefix=prefix, revision='rev-%03d' % self.count)
        self.registry.append(reg)
        return dict(reg)

    def put(self, path, *names, size=10):
        self.files.setdefault(path, {}).update({n: size for n in names})

    def state(self, path, folder, **summary):
        """A saved state committed at HEAD: its manifest in the tree and its summary in `history` (H3)."""
        self.put(path, folder + '/manifest.json', folder + '/r1.cfg'); self.summaries.setdefault(path, {})[folder] = summary

    def find(self, request):
        reg = next((r for r in self.registry if r['id'] == request.get('binding_id')), None)
        if not reg: raise ValueError('Select a registered Git repository.')
        if reg['revision'] != request.get('revision'): raise ValueError('The repository binding changed. Select it again.')
        return reg

    def new(self, source, prefix, **more):
        self.count += 1
        return dict(source, id='r%03d' % self.count, prefix=prefix, revision='rev-%03d' % self.count, label=source['label'].split(' / ')[0] + (' / ' + prefix if prefix else ''), **more)

    def __call__(self, host, request, stopping=None):
        self.sent.append(copy.deepcopy(request)); mode = request['mode']
        if mode == 'list': return dict(protocol=PROTOCOL, version=__version__, repositories=[dict(r) for r in self.registry])
        if mode == 'connect':
            url = host_git.clone_url(request['url']); prefix = host_git.relpath(request['prefix'], empty=True)
            known = [b for b in self.registry if host_git.same_repository(b['push_url'], url)]
            if known:
                existing = next((b for b in known if b['prefix'] == prefix), None)
                if existing: return dict(existing)
                host_git.base_prefix(prefix); path = known[0]['path']
            else:
                host_git.base_prefix(prefix); path = '/home/ben/labs/' + host_git.repository_name(url)
                if any(b['path'] == path for b in self.registry): raise ValueError('The VM folder for this repository name already holds another registered repository.')
            host_git.check_collision({'repositories': self.registry}, path, prefix)
            if self.connect_error: raise ValueError(self.connect_error)
            if url in self.empty:
                if request.get('initialize') is not True: raise ValueError(EMPTY_SENTENCE)
                self.empty.discard(url); self.put(path, 'README.md')
            name = host_git.repository_name(url)
            reg = self.new(dict(label=name, owner='ben', path=path, remote='origin', push_url=url, branch='main'), prefix)
            self.registry.append(reg); return dict(reg)
        if mode == 'register-prefix':
            if self.gate: self.entered.set(); self.gate.wait(10)
            existing, planned = host_git.plan_prefix({'repositories': self.registry}, request, LOOKUP)
            retire = request.get('retire') is True
            if existing and not retire: return dict(existing)
            if retire and request['binding_id'] in self.waiting: raise ValueError(WAITING_SENTENCE)
            source = next(b for b in self.registry if b['id'] == request['binding_id'])
            reg = existing or self.new(source, planned['prefix'])
            if retire and source['id'] != reg['id']: self.registry.remove(source)
            if not existing: self.registry.append(reg)
            return dict(reg)
        reg = self.find(request)
        tree = self.files.get(reg['path'], {})
        if mode == 'browse':
            paths = sorted(tree)
            dirs = sorted({'/'.join(p.split('/')[:i]) for p in paths for i in range(1, p.count('/') + 1)})
            return dict(repository=dict(reg), head='a' * 40, files=[dict(path=p, size=tree[p]) for p in paths[:self.cap]], truncated=len(paths) > self.cap,
                        dirs=dirs, saved={'latest': None, 'baseline': None, 'checkpoints': None},
                        folders=[dict(id=r['id'], label=r['label'], prefix=r['prefix']) for r in self.registry if r['path'] == reg['path']])
        if mode == 'history':
            folders = sorted(p[:-len('/manifest.json')] if '/' in p else '' for p in tree if p == 'manifest.json' or p.endswith('/manifest.json'))
            return dict(head='a' * 40, commits=[], versions=[dict(path=f, name=f, commit='a' * 40, summary=self.summaries.get(reg['path'], {}).get(f)) for f in folders])
        if mode == 'status': return dict(repository=dict(reg), ready=True, problem='', head='a' * 40, baseline_revision='', latest_manifest=None)
        if mode == 'move': return dict(status='committed', commit='c' * 40, pushed=False, changed_files=[], snapshot_path='', message='Moved; not pushed.')
        raise AssertionError(mode)


class PlaceTests(unittest.TestCase):
    setUp_base = discovery_tests.DiscoveryTests.setUp
    register = discovery_tests.DiscoveryTests.register
    host = discovery_tests.DiscoveryTests.host

    def setUp(self):
        self.setUp_base()
        self.progress = self.app.state.git_progress
        self.host(); self.store.state['host']['fingerprint'] = 'SHA256:fixture'
        self.vm = FakeVM()
        patch('app.git_progress.remote_git', side_effect=self.vm).start()
        self.addCleanup(patch.stopall)
        self.submit = patch.object(self.progress.pool, 'submit').start()
        self.repo = self.vm.add('Archtop-Lab')             # guided setup: the checkout at its top level, no lab connected
        self.path = self.repo['path']

    def tearDown(self):
        self.app.state.operations.close()
        discovery_tests.DiscoveryTests.tearDown(self)

    # ----- helpers

    def lab(self, name):
        return self.register(discovery_tests.YAML.replace(b'name: training', b'name: ' + name.encode()))

    def places(self, lab, repository=''):
        response = self.client.get('/api/labs/' + lab['id'] + '/git/places' + ('?repository=' + repository if repository else ''))
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def check(self, lab, folder, expect=200, repository=None, **more):
        response = self.client.post('/api/labs/' + lab['id'] + '/git/places/check', json=dict(repository=repository or self.repo['id'], folder=folder, **more))
        self.assertEqual(response.status_code, expect, response.text)
        return response.json()

    def place(self, lab, folder, expect=200, **body):
        data = dict(folder=folder, acknowledge=True); data.update(body)
        if 'url' not in data and 'repository' not in data: data['repository'] = self.repo['id']
        response = self.client.post('/api/labs/' + lab['id'] + '/git/place', json=data)
        self.assertEqual(response.status_code, expect, response.text)
        return response.json()

    def placed(self, lab, folder, **body):
        answer = self.place(lab, folder, **body)
        self.assertTrue(answer.get('saved'), answer)
        return answer

    def binding(self, lab): return self.store.lab(lab['id']).get('git_binding')

    def sent(self, mode): return [r for r in self.vm.sent if r['mode'] == mode]

    def waiting_save(self, lab, commit='d' * 40, **fields):
        """A save of `lab` that waits for upload with its commit on the VM, carrying its own frozen binding (DESIGN.md 3.1)."""
        with self.store.lock:
            stored = self.store.lab(lab['id'])
            binding = copy.deepcopy(stored.get('git_binding'))
            job = dict(id=uuid.uuid4().hex, lab_id=lab['id'], lab_name=stored['name'], created='2026-10-01T10:00:00+00:00', status='review_pending',
                       message='Saved on VM; not pushed.', backup_job_id='', target='latest', checkpoint='', note='OSPF done', pushed=False,
                       review_before_push=True, binding_digest=git_digest(binding) if binding else '', binding=binding,
                       request=dict(target='latest', push=False, message='x'), want_push=False, node_names=list((binding or {}).get('node_names') or []),
                       capture_context={}, commit=commit, changed_files=['latest/r1.cfg'],
                       destination=dict(checkout=(binding or {}).get('repository', {}).get('path', ''), path='x'), host_identity=(binding or {}).get('host_identity'))
            job.update(fields)
            self.store.state['git_jobs'].append(job); self.store.save()
        return job

    def assert_plain(self, value):
        """No message the person can see names the VM's plumbing."""
        texts = [value] if isinstance(value, str) else [v for k, v in value.items() if k in ('detail', 'sentence', 'move_reason', 'mark') and isinstance(v, str)]
        for text in texts:
            for word in FORBIDDEN: self.assertNotIn(word, text.lower())

    # ----- PROMPT 6.2, row by row

    def test_row_a_folder_that_does_not_exist_is_created_and_used(self):
        lab = self.lab('ux-a')
        answer = self.check(lab, 'labs/new-one')
        self.assertEqual((answer['kind'], answer['folder'], answer['exists']), ('free', 'labs/new-one', False))
        done = self.placed(lab, 'labs/new-one')
        self.assertEqual(done['binding']['repository']['prefix'], 'labs/new-one')
        self.assertEqual(self.binding(lab)['repository']['prefix'], 'labs/new-one')
        self.assertEqual([r['prefix'] for r in self.sent('register-prefix')], ['labs/new-one'])
        self.assertFalse([r for r in self.sent('register-prefix') if r.get('retire')], 'a folder change retires nothing')
        self.assertIn('labs/new-one', self.progress.planned_folders(self.path))

    def test_row_an_existing_folder_with_ordinary_files_and_no_saved_state_is_used(self):
        self.vm.put(self.path, 'notes/readme.md', 'notes/deep/plan.txt')
        lab = self.lab('ux-a')
        answer = self.check(lab, 'notes')
        self.assertEqual((answer['kind'], answer['exists'], answer['mark']), ('free', True, ''))
        self.assertEqual(self.placed(lab, 'notes')['binding']['repository']['prefix'], 'notes')

    def test_row_the_repositorys_top_level_is_used(self):
        lab = self.lab('ux-a')
        self.assertEqual(self.check(lab, '')['kind'], 'free')
        done = self.placed(lab, '')
        self.assertEqual(done['binding']['binding_id'], self.repo['id'], "guided setup's top-level record is reused")
        self.assertEqual(len(self.vm.registry), 1)

    def test_row_a_folder_inside_above_or_beside_a_folder_another_lab_saves_to_is_used(self):
        other = self.lab('other-lab'); self.placed(other, 'BGP')
        self.vm.state(self.path, 'BGP/latest', lab_id=other['id'], lab_name='other-lab')
        lab = self.lab('ux-a')
        for folder in ('BGP/inner', '', 'OSPF'):           # inside, above (the top level), beside
            answer = self.check(lab, folder)
            self.assertEqual(answer['kind'], 'free', (folder, answer))
            done = self.place(lab, folder)
            self.assertTrue(done.get('saved'), (folder, done))
            self.assertEqual(self.binding(lab)['repository']['prefix'], folder)
        self.assertEqual(self.binding(other)['repository']['prefix'], 'BGP')

    def test_row_the_very_folder_another_connected_lab_saves_to_asks_one_question_save_beside_it(self):
        other = self.lab('other-lab'); self.placed(other, 'BGP')
        lab = self.lab('ux-a')
        question = self.place(lab, 'BGP')['question']
        self.assertEqual((question['kind'], question['lab']['name'], question['collision'], question['beside']), ('lab', 'other-lab', False, 'BGP/ux-a'))
        self.assertEqual(question['mark'], 'other-lab saves here')
        self.assertIsNone(self.binding(lab), 'a question changes nothing')
        done = self.placed(lab, 'BGP', choice='beside')
        self.assertEqual(done['binding']['repository']['prefix'], 'BGP/ux-a')
        self.assertEqual(self.binding(other)['repository']['prefix'], 'BGP')

    def test_row_a_folder_that_holds_a_saved_state_asks_one_question_save_beside_or_replace_it(self):
        self.vm.state(self.path, 'course/start/latest', lab_id='course-lab', lab_name='Course', state='Start')
        lab = self.lab('ux-a')
        question = self.place(lab, 'course/start')['question']
        self.assertEqual((question['kind'], question['label'], question['layout'], question['beside']), ('state', 'Start', 'latest', 'course/start/ux-a'))
        self.assertEqual(self.placed(lab, 'course/start', choice='beside')['binding']['repository']['prefix'], 'course/start/ux-a')
        second = self.lab('ux-b')
        self.assertEqual(self.placed(second, 'course/start', choice='take')['binding']['repository']['prefix'], 'course/start')

    def test_row_a_folder_that_holds_a_flat_saved_state_is_used_anyway_and_the_state_stays(self):
        self.vm.state(self.path, 'course/flat', lab_id='course-lab', lab_name='Course')
        lab = self.lab('ux-a')
        question = self.place(lab, 'course/flat')['question']
        self.assertEqual((question['kind'], question['layout']), ('state', 'flat'))
        self.assertEqual(self.placed(lab, 'course/flat', choice='take')['binding']['repository']['prefix'], 'course/flat')

    def test_row_a_folder_that_is_part_of_a_saved_state_uses_the_lab_folder_above(self):
        lab = self.lab('ux-a')
        for typed in ('fresh/latest', 'fresh/checkpoints/x', 'fresh/baseline'):
            answer = self.check(lab, typed)
            self.assertEqual((answer['folder'], answer['adjusted'], answer['kind']), ('fresh', 'above-state', 'free'), typed)
        self.assertEqual(self.placed(lab, 'fresh/checkpoints/x')['binding']['repository']['prefix'], 'fresh')

    def test_row_a_name_with_characters_that_are_not_safe_in_a_path_is_corrected_as_typed(self):
        lab = self.lab('ux-a')
        answer = self.check(lab, ' my lab (2) / Übung?')
        self.assertEqual((answer['folder'], answer['adjusted']), ('my-lab-2/bung', 'corrected'))
        done = self.placed(lab, ' my lab (2) / Übung?')
        self.assertEqual(done['binding']['repository']['prefix'], 'my-lab-2/bung')
        self.assertEqual(host_git.relpath(self.sent('register-prefix')[-1]['prefix'], empty=True), 'my-lab-2/bung')

    def test_row_a_folder_while_a_save_of_this_lab_waits_for_upload_asks_upload_it_or_keep_it(self):
        lab = self.lab('ux-a'); self.placed(lab, 'a')
        job = self.waiting_save(lab)
        question = self.place(lab, 'b')['question']
        self.assertEqual((question['kind'], question['count'], question['names']), ('pending', 1, ['OSPF done']))
        self.assertEqual(self.binding(lab)['repository']['prefix'], 'a')
        # Move and keep that save on the VM only: nothing is dismissed, the save keeps waiting.
        self.assertEqual(self.placed(lab, 'b', pending='keep')['binding']['repository']['prefix'], 'b')
        kept = self.progress.get_job(job['id'])
        self.assertEqual(kept['status'], 'review_pending'); self.assertTrue(job_pending(kept))
        self.assertEqual(kept['binding']['repository']['prefix'], 'a', 'the waiting save keeps its own frozen binding')

    def test_row_a_folder_while_a_save_waits_upload_it_then_move(self):
        lab = self.lab('ux-a'); self.placed(lab, 'a')
        job = self.waiting_save(lab)
        self.assertEqual(self.place(lab, 'b')['question']['kind'], 'pending')
        self.progress.update(job['id'], status='synced', pushed=True)       # the page's one upload function went through
        self.assertEqual(self.placed(lab, 'b')['binding']['repository']['prefix'], 'b')

    def test_row_a_folder_registered_on_the_vm_that_no_lab_uses_is_invisible_and_reused(self):
        unused = self.vm.add('Archtop-Lab', 'old-folder', path=self.path)
        lab = self.lab('ux-a')
        tree = self.places(lab, self.repo['id'])['tree']
        self.assertNotIn('old-folder', [f['path'] for f in tree['folders']])
        self.assertEqual((self.check(lab, 'old-folder')['kind'], self.check(lab, 'old-folder')['mark']), ('free', ''))
        done = self.placed(lab, 'old-folder')
        self.assertEqual(done['binding']['binding_id'], unused['id'])
        self.assertEqual(len(self.vm.registry), 2)

    def test_row_a_folder_that_collides_with_an_unused_record_replaces_it(self):
        legacy = self.vm.add('Archtop-Lab', 'x/latest', path=self.path)  # an older release's `x/latest` lab folder, no lab
        lab = self.lab('ux-a')
        done = self.placed(lab, 'x')
        self.assertEqual(done['binding']['repository']['prefix'], 'x')
        self.assertNotIn(legacy['id'], [r['id'] for r in self.vm.registry])
        retired = [r for r in self.sent('register-prefix') if r.get('retire')]
        self.assertEqual([(r['binding_id'], r['prefix']) for r in retired], [(legacy['id'], 'x')])

    # ----- the owner's situation of PROMPT 6.1

    def test_the_owners_repository_registered_only_at_its_top_level_takes_every_lab_without_a_question(self):
        first = self.lab('UX-TEST-003')
        answer = self.places(first)
        self.assertEqual(answer['repositories'], [dict(id=self.repo['id'], name='Archtop-Lab', remote='https://github.com/ben/Archtop-Lab.git', path=self.path, current=False)])
        default = answer['default']
        self.assertEqual((default['repository'], default['folder'], default['ask'], default['answer']['kind'], default['answer']['exists']),
                         (self.repo['id'], 'UX-TEST-003', False, 'free', False))
        self.assertNotIn('question', self.placed(first, default['folder'], node_names=None))
        second = self.lab('UX-TEST-004')
        default = self.places(second)['default']
        self.assertEqual(default['folder'], 'UX-TEST-004')
        self.placed(second, default['folder'])
        # A lab moves into a folder inside another lab's folder, and the top level itself can be chosen.
        self.placed(second, 'UX-TEST-003/inner')
        self.placed(first, '')
        self.assertEqual((self.binding(first)['repository']['prefix'], self.binding(second)['repository']['prefix']), ('', 'UX-TEST-003/inner'))
        self.assertEqual(self.places(first)['repositories'][0]['current'], True)
        self.assertFalse([r for r in self.sent('register-prefix') if r.get('retire')])

    # ----- the questions, each answer

    def test_use_this_folder_anyway_disconnects_the_other_lab_and_leaves_its_waiting_save_pending(self):
        other = self.lab('other-lab'); self.placed(other, 'BGP')
        theirs = self.waiting_save(other)
        lab = self.lab('ux-a')
        self.assertEqual(self.place(lab, 'BGP')['question']['kind'], 'lab')
        done = self.placed(lab, 'BGP', choice='take')
        self.assertEqual(done['binding']['repository']['prefix'], 'BGP')
        self.assertIsNone(self.binding(other), 'the other lab is disconnected')
        self.assertTrue(job_pending(self.progress.get_job(theirs['id'])), 'its waiting save keeps waiting')
        self.assertEqual(self.progress.get_job(theirs['id'])['binding']['repository']['prefix'], 'BGP')
        events = [e for e in self.store.events() if e.get('action') == 'git.unlink']
        self.assertTrue(events)

    def test_a_folder_whose_saves_hold_another_connected_lab_has_only_the_beside_answer(self):
        legacy = self.vm.add('Archtop-Lab', 'y/latest', path=self.path)
        other = self.lab('other-lab')
        names = [n['name'] for n in self.store.lab(other['id'])['nodes']]
        linked = self.client.put('/api/labs/' + other['id'] + '/git', json=dict(binding_id=legacy['id'], node_names=names))
        self.assertEqual(linked.status_code, 200, linked.text)                # an older lab still saving in a legacy folder
        lab = self.lab('ux-a')
        question = self.place(lab, 'y')['question']
        self.assertEqual((question['kind'], question['collision'], question['lab']['name'], question['beside']), ('lab', True, 'other-lab', 'y/ux-a'))
        self.assertEqual(self.place(lab, 'y', choice='take')['question']['collision'], True, 'take is not offered for a collision')
        self.assertEqual(self.placed(lab, 'y', choice='beside')['binding']['repository']['prefix'], 'y/ux-a')
        self.assertIn(legacy['id'], [r['id'] for r in self.vm.registry])

    def test_a_record_holding_a_waiting_save_is_never_retired_the_person_is_asked(self):
        legacy = self.vm.add('Archtop-Lab', 'x/latest', path=self.path)
        self.vm.waiting.add(legacy['id'])                                # the helper refuses the retire (H7)
        lab = self.lab('ux-a')
        question = self.place(lab, 'x')['question']
        self.assertEqual((question['kind'], question['collision'], question['lab'], question['sentence']), ('lab', True, None, IN_USE))
        self.assertEqual(question['beside'], 'x/ux-a')
        self.assertNotIn(WAITING_SENTENCE, str(question))
        self.assertIn(legacy['id'], [r['id'] for r in self.vm.registry])
        self.assertIsNone(self.binding(lab))
        self.assertEqual(self.placed(lab, 'x', choice='beside')['binding']['repository']['prefix'], 'x/ux-a')

    def test_a_record_a_waiting_save_names_is_not_retired_by_the_manager(self):
        legacy = self.vm.add('Archtop-Lab', 'x/latest', path=self.path)
        gone = self.lab('gone-lab')
        self.waiting_save(gone, binding=dict(binding_id=legacy['id'], revision=legacy['revision'], repository=legacy, host_identity='h', node_names=[]))
        lab = self.lab('ux-a')
        question = self.place(lab, 'x')['question']
        self.assertEqual((question['collision'], question['sentence']), (True, IN_USE))
        self.assertFalse([r for r in self.sent('register-prefix') if r.get('retire')], 'decided under the store lock, before the VM is asked')

    def test_a_lab_of_the_same_name_is_asked_once_and_continue_there_takes_the_folder(self):
        self.vm.state(self.path, 'ux-a/latest', lab_id='someone-else', lab_name='ux-a')
        lab = self.lab('ux-a')
        default = self.places(lab)['default']
        self.assertEqual((default['ask'], default['folder'], default['beside']), (True, 'ux-a', 'ux-a-2'))
        self.assertTrue(default['answer']['same_name'])
        self.assertEqual(self.placed(lab, default['beside'])['binding']['repository']['prefix'], 'ux-a-2')
        second = self.lab('ux-b')
        self.assertEqual(self.placed(second, 'ux-a', choice='take')['binding']['repository']['prefix'], 'ux-a')

    # ----- connecting by address

    def test_an_address_of_a_new_repository_is_connected_at_its_top_level_then_the_lab_is_placed(self):
        lab = self.lab('ux-a')
        done = self.placed(lab, 'ux-a', url='https://github.com/ben/new-repo')
        connect = self.sent('connect')
        self.assertEqual(connect, [dict(mode='connect', url='https://github.com/ben/new-repo', prefix='')])
        self.assertEqual((done['binding']['repository']['path'], done['binding']['repository']['prefix']), ('/home/ben/labs/new-repo', 'ux-a'))
        self.assertIn('', [r['prefix'] for r in self.vm.registry if r['path'] == '/home/ben/labs/new-repo'])

    def test_an_address_of_a_known_repository_uses_the_checkout_on_the_vm(self):
        lab = self.lab('ux-a')
        done = self.placed(lab, 'ux-a', url='https://github.com/ben/Archtop-Lab')
        self.assertEqual(done['binding']['repository']['path'], self.path)
        self.assertEqual(len({r['path'] for r in self.vm.registry}), 1)

    def test_an_empty_repository_is_a_question_and_start_the_repository_initializes_it(self):
        self.vm.empty.add('https://github.com/ben/blank.git')
        lab = self.lab('ux-a')
        question = self.place(lab, 'ux-a', url='https://github.com/ben/blank.git')['question']
        self.assertEqual((question['kind'], question['name']), ('empty', 'blank'))
        self.assertFalse(self.sent('register-prefix')); self.assertNotIn('initialize', self.sent('connect')[0])
        done = self.placed(lab, 'ux-a', url='https://github.com/ben/blank.git', initialize=True)
        self.assertIs(self.sent('connect')[-1]['initialize'], True)
        self.assertEqual(done['binding']['repository']['prefix'], 'ux-a')

    def test_a_helper_refusal_to_connect_is_shown_in_its_own_words_and_the_acknowledgement_is_required(self):
        lab = self.lab('ux-a')
        refused = self.place(lab, 'ux-a', expect=400, url='https://github.com/ben/x', acknowledge=False)
        self.assertIn('Acknowledge', refused['detail']); self.assertFalse(self.vm.sent, 'nothing reached the VM')
        refused = self.place(lab, 'ux-a', expect=400, acknowledge=False)
        self.assertIn('Acknowledge', refused['detail']); self.assertIsNone(self.binding(lab))
        self.vm.connect_error = 'The VM account is not signed in to GitHub. On the VM, run gh auth login.'
        refused = self.place(lab, 'ux-a', expect=409, url='https://github.com/ben/x')
        self.assertEqual(refused['detail'], self.vm.connect_error)
        self.placed(lab, 'ux-a')
        self.assertTrue(self.place(lab, 'other', acknowledge=False).get('saved'), 'a connected lab moves without the acknowledgement')

    # ----- housekeeping, inputs, large trees

    def test_housekeeping_at_201_records_retires_up_to_five_unused_ones_oldest_first(self):
        used = self.lab('used-lab'); self.placed(used, 'used')
        named = self.vm.add('Archtop-Lab', 'named', path=self.path)
        gone = self.lab('gone-lab')
        self.waiting_save(gone, binding=dict(binding_id=named['id'], revision=named['revision'], repository=named, host_identity='h', node_names=[]))
        while len(self.vm.registry) < 200: self.vm.add('Archtop-Lab', 'old/%03d' % len(self.vm.registry), path=self.path)
        order = [r['id'] for r in self.vm.registry]
        unused = [rid for rid in order if rid not in (self.binding(used)['binding_id'], named['id'])]
        self.vm.waiting.add(unused[2])                                   # a refusal is ignored
        lab = self.lab('ux-a')
        done = self.placed(lab, 'fresh')
        left = [r['id'] for r in self.vm.registry]
        self.assertEqual(len(left), 201 - 4)
        self.assertEqual([rid for rid in unused[:5] if rid not in left], [unused[0], unused[1], unused[3], unused[4]])
        for kept in (unused[2], named['id'], self.binding(used)['binding_id'], done['binding']['binding_id']): self.assertIn(kept, left)
        self.assertEqual({r['prefix'] for r in self.sent('register-prefix') if r.get('retire')}, {'fresh'})

    def test_a_typed_path_with_any_unsafe_input_is_corrected_never_refused_except_its_length(self):
        lab = self.lab('ux-a')
        for typed in HOSTILE:
            response = self.client.post('/api/labs/' + lab['id'] + '/git/places/check', json=dict(repository=self.repo['id'], folder=typed))
            if response.status_code == 400:
                self.assertEqual(response.json()['detail'], TOO_LONG, repr(typed)); continue
            self.assertEqual(response.status_code, 200, (repr(typed), response.text))
            answer = response.json()
            self.assertEqual(host_git.relpath(answer['folder'], empty=True), answer['folder'], repr(typed))
            self.assertIn(answer['kind'], ('free', 'own', 'own-before', 'lab', 'state'))
        self.assertEqual(self.check(lab, 'a/' * 300, expect=400)['detail'], TOO_LONG)
        self.assertEqual(self.place(lab, 'a/' * 300, expect=400)['detail'], TOO_LONG)
        self.assertEqual(self.place(lab, 'x' * 5000, expect=400)['detail'], TOO_LONG)
        for typed in ('..', '../..', 'a/.git/b', '$(rm -rf)', '\\\\server\\share', 'a\x00b', 'latest', '.hidden', 'UX TEST (3)'):
            done = self.place(lab, typed)
            self.assertTrue(done.get('saved'), (repr(typed), done))
            folder = self.sent('register-prefix')[-1]['prefix']
            self.assertEqual(host_git.relpath(folder, empty=True), folder)
            host_git.base_prefix(folder)
        for request in self.vm.sent:
            self.assertLessEqual(set(request), {'mode', 'prefix', 'url', 'retire', 'initialize', 'binding_id', 'revision'})

    def test_a_tree_larger_than_the_helpers_file_cap_still_answers_a_typed_path(self):
        self.vm.cap = 50
        self.vm.put(self.path, *('bulk/f%03d.txt' % i for i in range(120)))
        self.vm.state(self.path, 'zz/start/latest', lab_id='course', lab_name='Course', state='Start')
        lab = self.lab('ux-a')
        tree = self.places(lab, self.repo['id'])['tree']
        self.assertTrue(tree['truncated']); self.assertEqual(len(tree['files']), 50)
        self.assertNotIn('zz/start/latest/manifest.json', [f['path'] for f in tree['files']])
        answer = self.check(lab, 'zz/start')
        self.assertEqual((answer['kind'], answer['label']), ('state', 'Start'))
        self.assertEqual(self.place(lab, 'zz/start')['question']['kind'], 'state')

    # ----- concurrency

    def test_two_placements_at_once_the_second_is_asked_to_try_again(self):
        first = self.lab('ux-a'); self.placed(first, 'a')
        second = self.lab('ux-b')
        self.vm.gate = threading.Event(); self.vm.entered.clear()
        result = {}
        worker = threading.Thread(target=lambda: result.setdefault('first', self.place(first, 'moved')))
        worker.start()
        try:
            self.assertTrue(self.vm.entered.wait(10))
            refused = self.place(second, 'b', expect=409)
            self.assertEqual(refused['detail'], BUSY)
            save = self.client.post('/api/labs/' + first['id'] + '/git/save', json=dict(request_id=uuid.uuid4().hex, target='latest', push=True, note='x'))
            self.assertEqual(save.status_code, 409, save.text)
            self.assertIn('repository connection is being changed', save.json()['detail'])
        finally:
            self.vm.gate.set(); worker.join(10)
        self.vm.gate = None
        self.assertTrue(result['first'].get('saved'), result)
        self.assertTrue(self.placed(second, 'b'))

    def test_a_lab_state_being_saved_into_a_folder_makes_that_folder_a_state(self):
        maker = self.lab('maker'); self.placed(maker, 'BGP')
        lab = self.lab('ux-a')
        target = self.vm.add('Archtop-Lab', 'course/start', path=self.path)
        state = dict(binding_id=target['id'], revision=target['revision'], repository=target, host_identity=self.binding(maker)['host_identity'], node_names=[])
        self.waiting_save(maker, commit='', kind='state', status='capturing', note='Start', binding=state)
        answer = self.check(lab, 'course/start')
        self.assertEqual((answer['kind'], answer['label']), ('state', 'Start'))
        self.assertEqual(self.place(lab, 'course/start')['question']['kind'], 'state')

    # ----- the stored binding, devices, bringing files along

    def test_the_stored_binding_is_replaced_never_edited_and_devices_default_to_the_selection(self):
        lab = self.lab('ux-a')
        names = [n['name'] for n in self.store.lab(lab['id'])['nodes']]
        self.assertEqual(self.place(lab, 'a', expect=400, node_names=[])['detail'], 'Select distinct supported devices from this lab.')
        self.assertEqual(self.place(lab, 'a', expect=400, node_names=['nope'])['detail'], 'Select distinct supported devices from this lab.')
        self.placed(lab, 'a', node_names=names[:1])
        stored = self.binding(lab); frozen = copy.deepcopy(stored)
        done = self.placed(lab, 'b')
        self.assertEqual(stored, frozen, 'the old binding dict was not edited')
        self.assertIsNot(self.binding(lab), stored)
        self.assertEqual(done['binding']['node_names'], names[:1], "the lab's current selection")
        again = self.placed(lab, 'b')
        self.assertIsNone(again['job']); self.assertEqual(again['binding'], done['binding'], 'its own folder changes nothing')

    def test_the_saved_files_come_along_only_when_every_save_of_the_lab_has_its_commit(self):
        lab = self.lab('ux-a'); self.placed(lab, 'a')
        self.vm.put(self.path, 'a/latest/manifest.json', 'a/latest/r1.cfg', 'a/checkpoints/one/r1.cfg')
        self.vm.state(self.path, 'b-full/latest', lab_id='x', lab_name='X')
        self.progress.forget_views()
        tree = self.places(lab, self.repo['id'])['tree']
        self.assertEqual(tree['own'], dict(folder='a', files=3))
        self.assertEqual(self.check(lab, 'b')['bring'], {'offered': True, 'files': 3, 'from': 'a', 'reason': ''})
        rows = {f['path']: f for f in tree['folders']}
        self.assertEqual(rows['a']['bring']['offered'], False)
        self.assertEqual(rows['b-full']['bring']['reason'], 'not-empty')
        unfinished = self.waiting_save(lab, commit='', status='capturing')
        self.assertEqual(self.check(lab, 'b')['bring']['reason'], 'unfinished')
        done = self.placed(lab, 'b', move_files=True, pending='keep')
        self.assertEqual((done['moved'], done['job']), (False, None))
        self.assertEqual(done['move_reason'], 'A save of this lab has not finished. Its files stay in a.')
        self.progress.update(unfinished['id'], status='dismissed')
        self.vm.put(self.path, 'b/latest/manifest.json', 'b/latest/r1.cfg'); self.progress.forget_views()
        self.assertEqual(self.check(lab, 'c')['bring'], {'offered': True, 'files': 2, 'from': 'b', 'reason': ''})
        done = self.placed(lab, 'c', move_files=True)
        self.assertTrue(done['moved'])
        job = self.progress.get_job(done['job']['id'])
        self.assertEqual((job['target'], job['want_push'], job['request']['source_prefix'], job['request']['push']), ('move', False, 'b', False))
        self.assertEqual(job['binding_digest'], git_digest(done['binding'])); self.assertEqual(job['binding'], done['binding'])
        self.submit.assert_called()

    # ----- the listing and New folder…

    def test_places_lists_one_row_per_checkout_and_builds_only_the_default_view(self):
        self.vm.add('Archtop-Lab', 'sub', path=self.path)
        other = self.vm.add('Zeta')
        lab = self.lab('ux-a')
        answer = self.places(lab)
        self.assertEqual([r['name'] for r in answer['repositories']], ['Archtop-Lab', 'Zeta'])
        self.assertEqual(answer['repositories'][0]['id'], self.repo['id'], 'the top-level record is the handle')
        self.assertEqual(answer['default']['repository'], self.repo['id'], 'the first by name')
        self.assertEqual({r['binding_id'] for r in self.sent('browse')}, {self.repo['id']})
        self.assertEqual(answer['default']['answer']['bring']['offered'], False)
        self.placed(lab, 'here', repository=other['id'])
        answer = self.places(lab)
        self.assertEqual(answer['default']['repository'], self.binding(lab)['binding_id'])
        self.assertEqual(answer['default']['folder'], 'here')
        self.assertEqual([r['current'] for r in answer['repositories']], [False, True])
        self.vm.registry.clear(); self.progress.forget_views()
        self.assertEqual(self.places(lab), dict(repositories=[], default=None))

    def test_new_folder_is_always_possible_and_an_existing_name_selects_that_folder(self):
        lab = self.lab('ux-a'); other = self.lab('other-lab'); self.placed(other, 'BGP'); before = len(self.sent('register-prefix'))
        url = '/api/git/repositories/' + self.repo['id'] + '/folders/new'
        made = self.client.post(url, json=dict(lab_id=lab['id'], parent='', name='Week 1'))
        self.assertEqual(made.status_code, 200, made.text)
        self.assertEqual({k: made.json()[k] for k in ('folder', 'existed', 'adjusted')}, dict(folder='Week-1', existed=False, adjusted='corrected'))
        self.assertIs(made.json()['answer']['exists'], False, 'a planned folder is never worded as existing')
        again = self.client.post(url, json=dict(lab_id=lab['id'], parent='', name='Week-1')).json()
        self.assertEqual((again['folder'], again['existed']), ('Week-1', True))
        self.vm.state(self.path, 'BGP/latest', lab_id=other['id'], lab_name='other-lab'); self.progress.forget_views()
        inside = self.client.post(url, json=dict(lab_id=lab['id'], parent='BGP/latest', name='mine')).json()
        self.assertEqual((inside['folder'], inside['adjusted'], inside['existed']), ('BGP/mine', 'above-state', False))
        nested = self.client.post(url, json=dict(lab_id=lab['id'], parent='BGP', name='a/b')).json()
        self.assertEqual(nested['folder'], 'BGP/a/b')
        self.assertEqual(self.client.post(url, json=dict(lab_id=lab['id'], parent='', name='')).json()['folder'], 'folder')
        self.assertEqual(len(self.sent('register-prefix')), before, 'nothing is written or registered on the VM')
        self.assertEqual(self.client.post(url, json=dict(lab_id=lab['id'], parent='a/' * 300, name='x')).status_code, 400)

    # ----- words

    def test_no_message_of_the_place_routes_names_the_vms_plumbing(self):
        source = Path(__file__).resolve().parents[1] / 'app' / 'git_place.py'
        tree = ast.parse(source.read_text(encoding='utf-8'))
        docstrings = {id(node.body[0].value) for node in ast.walk(tree)
                      if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef)) and node.body and isinstance(node.body[0], ast.Expr)
                      and isinstance(node.body[0].value, ast.Constant)}
        messages = [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str) and ' ' in n.value and id(n) not in docstrings]
        self.assertGreater(len(messages), 15)
        for text in messages:
            for word in FORBIDDEN: self.assertNotIn(word, text.lower(), text)
        # A helper sentence that names them is replaced before it reaches a person.
        lab = self.lab('ux-a')
        self.vm.connect_error = 'Another Git registration for this checkout folder was saved meanwhile.'
        refused = self.place(lab, 'ux-a', expect=409, url='https://github.com/ben/x')
        self.assert_plain(refused)


if __name__ == '__main__':
    unittest.main()
