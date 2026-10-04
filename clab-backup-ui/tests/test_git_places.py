"""One answer per folder (docs/git-redesign/DESIGN.md 2.5 to 2.9, 3.8 N3, 7.4; PROMPT 6.1 and 6.2).

Every test here is about the pure module `app/git_places.py`: no manager, no VM helper, no files. The
helper's own path rule (`host_git.relpath`) is imported so that what the module calls a usable folder is
checked against the code that will receive it."""
import random
import unittest

from app import git_places, host_git
from app.git_places import clean_folder, colliding, default_place, folder_answers, folder_name, place_answer, state_name, state_rows

FIELDS = {'folder', 'typed', 'kind', 'exists', 'label', 'lab', 'layout', 'collision', 'adjusted', 'beside', 'mark', 'same_name'}
ME = {'id': 'lab-1', 'name': 'UX-TEST-003', 'prefix': None}
OTHER = {'id': 'lab-2', 'name': 'BGP'}


def lab(prefix=None, **more): return dict(ME, prefix=prefix, **more)
def reg(prefix, who=None, rid=None): return {'id': rid or 'r-' + prefix, 'prefix': prefix, 'lab': who}
def summary(lab_id='course', lab_name='Course', **more): return dict({'lab_id': lab_id, 'lab_name': lab_name, 'kind': '', 'captured_at': '', 'topology_digest': '', 'devices': []}, **more)


def checkout(registrations=(), files=(), dirs=None, states=None, planned=(), pending=(), **more):
    return dict({'registrations': list(registrations), 'files': list(files), 'dirs': dirs, 'states': states or {}, 'planned': list(planned),
                 'pending_states': list(pending), 'truncated': False}, **more)


HOSTILE = ['', ' ', '/', '//', 'a//b', 'a/b/', '/a/b', ' a / b ', 'my lab', 'UX TEST (3)', 'é', 'Übung/größe', '日本語', 'a\\b', '\\\\server\\share',
           '..', '.', '../..', 'a/../b', 'a/./b', '.hidden', '..hidden', '-dash', '--', '-.-', '.git', '.GIT', 'a/.git/b', '.Git/hooks', '.gitignore',
           'a\x00b', 'a\nb', '\t', '\x7f', 'a\r\n/b', 'latest', 'a/latest', 'checkpoints/x', 'x' * 600, 'x' * 181, 'x' * 182, '-' * 300 + 'a',
           '/'.join(['ab'] * 166), '/'.join(['a'] * 250), 'a' * 250 + '/' + 'b' * 249, 'a?', '?a', 'a?b', 'a-', 'a.', 'a..b', '~', '$(rm -rf)', 'a;b|c',
           'a​b', '﻿a', 'a' + '/' * 50 + 'b', None, 7, 'CON', 'a:b', '%2e%2e', 'a/%2f/b']


class CleanFolder(unittest.TestCase):
    def test_examples(self):
        for typed, cleaned in (('', ''), ('/', ''), (' a / b ', 'a/b'), ('a//b/', 'a/b'), ('my lab', 'my-lab'), ('UX TEST (3)', 'UX-TEST-3'),
                               ('a\\b', 'a-b'), ('..', ''), ('.', ''), ('a/../b', 'a/b'), ('.hidden', 'hidden'), ('-dash', 'dash'), ('.git', 'git'),
                               ('.GIT', 'git'), ('a/.git/b', 'a/git/b'), ('.gitignore', 'gitignore'), ('a\x00b', 'a-b'), ('é', ''), ('grö ße', 'gr-e'),
                               ('a-', 'a-'), ('a?', 'a'), ('_x', '_x'), (None, ''), (7, '7'), ('x' * 182, 'x' * 181), ('BGP/start', 'BGP/start')):
            self.assertEqual(clean_folder(typed), cleaned, repr(typed))

    def test_every_result_passes_the_helpers_path_rule(self):
        for typed in HOSTILE:
            try: cleaned = clean_folder(typed)
            except ValueError: continue
            self.assertEqual(host_git.relpath(cleaned, empty=True), cleaned, repr(typed))

    def test_idempotent(self):
        for typed in HOSTILE:
            try: cleaned = clean_folder(typed)
            except ValueError: continue
            self.assertEqual(clean_folder(cleaned), cleaned, repr(typed))

    def test_the_only_error_is_a_result_over_500_characters(self):
        self.assertEqual(len(clean_folder('/'.join(['ab'] * 167))), 500)
        for typed in ('/'.join(['ab'] * 168), '/'.join(['a'] * 251), 'a' * 181 + '/' + 'b' * 181 + '/' + 'c' * 181):
            with self.assertRaises(ValueError): clean_folder(typed)
        self.assertEqual(clean_folder('x' * 600), 'x' * 181)   # one long name is cut, not refused
        self.assertEqual(clean_folder(' ' * 600 + 'a'), 'a')    # what is dropped does not count

    def test_the_copied_limits_are_the_helpers(self):
        self.assertEqual(git_places.RESERVED, host_git.RESERVED)
        self.assertTrue(host_git.PATH_PART.fullmatch('a' * git_places.PART_LIMIT))
        self.assertFalse(host_git.PATH_PART.fullmatch('a' * (git_places.PART_LIMIT + 1)))
        self.assertEqual(host_git.relpath('/'.join(['ab'] * 167)), '/'.join(['ab'] * 167))
        with self.assertRaises(ValueError): host_git.relpath('/'.join(['ab'] * 167) + 'c')

    def test_folder_name_avoids_the_saved_state_names_in_any_case(self):
        """Fourth risk review, finding 5: `Latest` is another folder than `latest` on the VM, but a clone on a file
        system that ignores case would fold the two together."""
        for name, expected in (('Latest', 'lab-Latest'), ('LATEST', 'lab-LATEST'), ('Baseline', 'lab-Baseline'), ('Checkpoints', 'lab-Checkpoints'),
                               ('latest', 'lab-latest'), ('Latest-2', 'Latest-2'), ('my-latest', 'my-latest')):
            self.assertEqual(folder_name(name), expected, name)
        self.assertEqual(folder_name('Latest', 'state'), 'state-Latest')

    def test_folder_name_is_one_safe_name_and_never_a_saved_state_folder(self):
        self.assertEqual(folder_name('UX-TEST-003'), 'UX-TEST-003')
        self.assertEqual(folder_name('my lab / two'), 'my-lab---two')
        self.assertEqual(folder_name(''), 'lab')
        self.assertEqual(folder_name('é'), 'lab')
        self.assertEqual(folder_name('latest'), 'lab-latest')
        self.assertEqual(folder_name('checkpoints', 'state'), 'state-checkpoints')
        self.assertEqual(len(folder_name('n' * 300)), 60)


class Colliding(unittest.TestCase):
    def test_only_the_same_files_collide(self):
        for a, b in (('x', 'x/latest'), ('x', 'x/latest/y'), ('x', 'x/baseline'), ('x', 'x/checkpoints'), ('x', 'x/checkpoints/a'), ('', 'latest/foo'),
                     ('', 'checkpoints/a'), ('a', 'a/checkpoints/x/y')):
            self.assertTrue(colliding(a, b), (a, b)); self.assertTrue(colliding(b, a), (b, a))
        for a, b in (('x', 'x/y'), ('', 'x'), ('x', 'y'), ('x', 'x/latest-notes'), ('x', 'x/checkpoints2'), ('x', 'y/latest'), ('a/b', 'a'), ('x/latest', 'x/baseline')):
            self.assertFalse(colliding(a, b), (a, b)); self.assertFalse(colliding(b, a), (b, a))

    def test_review_F16_a_folder_does_not_collide_with_itself_the_top_level_included(self):
        for a in ('', 'x', 'x/latest', 'a/b/c'): self.assertFalse(colliding(a, a), a)

    def test_equals_the_helpers_rule(self):
        if not hasattr(host_git, 'colliding'):
            self.skipTest('app.host_git has no colliding() in this checkout yet (slice S0 adds it, DESIGN.md 2.3 H1); nothing to compare with.')
        rng = random.Random(16); names = ['a', 'b', 'latest', 'baseline', 'checkpoints', 'latest2']
        for _ in range(5000):
            a = '/'.join(rng.choice(names) for _ in range(rng.randrange(4))); b = '/'.join(rng.choice(names) for _ in range(rng.randrange(4)))
            self.assertEqual(colliding(a, b), host_git.colliding(a, b), (a, b))


class PromptRows(unittest.TestCase):
    """PROMPT 6.2, one test per row, and the owner's situation of 6.1."""

    def test_owner_situation_a_checkout_registered_only_at_its_top_level_blocks_nothing(self):
        repo = checkout([reg('')], files=['README.md'])
        first = place_answer(ME, repo, 'UX-TEST-003')
        self.assertEqual((first['kind'], first['folder'], first['exists'], first['adjusted'], first['mark']), ('free', 'UX-TEST-003', False, '', ''))
        top = place_answer(ME, repo, '')
        self.assertEqual((top['kind'], top['folder'], top['exists'], top['mark']), ('free', '', True, ''))
        rows = folder_answers(ME, repo)
        self.assertEqual([r['path'] for r in rows], [''])
        self.assertTrue(all(r['kind'] == 'free' and r['mark'] == '' and r['lab'] is None for r in rows))
        place = default_place(ME, [{'id': 'r-', 'name': 'Archtop-Lab', 'path': '/srv/git/Archtop-Lab', 'last_used': '', 'checkout': repo}])
        self.assertEqual((place['repository'], place['folder'], place['answer']['kind'], place['ask']), ('r-', 'UX-TEST-003', 'free', False))

    def test_a_folder_that_does_not_exist_is_created_and_used(self):
        answer = place_answer(ME, checkout(files=['README.md']), 'course/week-1/ospf')
        self.assertEqual((answer['kind'], answer['folder'], answer['exists'], answer['adjusted']), ('free', 'course/week-1/ospf', False, ''))
        planned = place_answer(ME, checkout(files=['README.md'], planned=['course/week-1']), 'course/week-1')
        self.assertEqual((planned['kind'], planned['exists']), ('free', False))   # planned is never worded as being in the repository

    def test_a_path_through_a_committed_file_is_corrected_never_refused(self):
        """The refusal audit's open case (REFUSALS.md 9.7): a typed folder whose part is a FILE of the repository.
        No folder can be made there, so that part gets -2 (the next free number) and the answer says so."""
        c = checkout([reg('')], files=['README.md', 'docs/guide.txt', 'docs/guide.txt-2', 'notes/a.txt', 'Makefile'])
        for typed, folder in (('README.md', 'README.md-2'), ('README.md/x', 'README.md-2/x'), ('docs/guide.txt/labs', 'docs/guide.txt-3/labs'),
                              ('notes/a.txt', 'notes/a.txt-2'), ('Makefile/latest', 'Makefile-2')):
            answer = place_answer(lab(), c, typed)
            self.assertEqual((answer['kind'], answer['folder'], answer['adjusted']), ('free', folder, 'past-file'), typed)
            self.assertEqual(host_git.relpath(answer['folder'], True), answer['folder'])
        # A folder of that name is used as it is, and so is a file's own folder.
        for typed in ('notes', 'docs', 'docs/new'):
            answer = place_answer(lab(), c, typed)
            self.assertEqual((answer['kind'], answer['folder'], answer['adjusted']), ('free', typed, ''), typed)
        # The longest name still gets its number inside the helper's limit for one part.
        long = 'x' * 181
        answer = place_answer(lab(), checkout([reg('')], files=[long]), long)
        self.assertEqual((answer['folder'], len(answer['folder']), answer['adjusted']), ('x' * 179 + '-2', 181, 'past-file'))
        # A first save of a lab named like a file of the repository goes beside the file without a question.
        place = default_place({'id': 'lab-9', 'name': 'Makefile', 'prefix': None}, [{'id': 'r', 'path': '/p', 'name': 'repo', 'checkout': c}])
        self.assertEqual((place['folder'], place['ask'], place['answer']['kind']), ('Makefile-2', False, 'free'))

    def test_an_existing_folder_with_ordinary_files_and_no_saved_state_is_used(self):
        answer = place_answer(ME, checkout(files=['notes/todo.md', 'notes/img/a.png']), 'notes')
        self.assertEqual((answer['kind'], answer['folder'], answer['exists'], answer['adjusted'], answer['beside']), ('free', 'notes', True, '', ''))

    def test_the_repositorys_top_level_is_used(self):
        for repo in (checkout(), checkout(files=['README.md']), checkout([reg('BGP', OTHER)], files=['BGP/latest/manifest.json']), checkout([reg('')])):
            answer = place_answer(ME, repo, '/')
            self.assertEqual((answer['kind'], answer['folder'], answer['exists']), ('free', '', True))

    def test_a_folder_inside_above_or_beside_a_folder_another_lab_saves_to_is_used(self):
        repo = checkout([reg('course/BGP', OTHER)], states={'course/BGP/latest': summary('lab-2', 'BGP')})
        for folder in ('course/BGP/mine', 'course/BGP/deep/er', 'course', '', 'course/OSPF', 'BGP'):
            answer = place_answer(ME, repo, folder)
            self.assertEqual((answer['kind'], answer['folder'], answer['collision'], answer['adjusted']), ('free', folder, False, ''), folder)
        top = checkout([reg('', OTHER)], states={'latest': summary('lab-2', 'BGP')})   # another lab at the top level
        self.assertEqual(place_answer(ME, top, 'UX-TEST-003')['kind'], 'free')

    def test_the_very_folder_another_connected_lab_saves_to_asks_one_question(self):
        repo = checkout([reg('BGP', OTHER)], states={'BGP/latest': summary('lab-2', 'BGP')})
        answer = place_answer(ME, repo, 'BGP')
        self.assertEqual((answer['kind'], answer['lab'], answer['collision'], answer['beside'], answer['mark']),
                         ('lab', OTHER, False, 'BGP/UX-TEST-003', 'BGP saves here'))
        never_saved = place_answer(ME, checkout([reg('BGP', OTHER)]), 'BGP')   # connected but no save yet: the same question
        self.assertEqual((never_saved['kind'], never_saved['exists'], never_saved['beside']), ('lab', False, 'BGP/UX-TEST-003'))

    def test_a_folder_that_already_holds_a_saved_state_from_another_lab_or_a_course_asks_one_question(self):
        repo = checkout(states={'course/start/latest': summary(), 'Final': summary('gone', 'Old lab')})
        answer = place_answer(ME, repo, 'course/start')
        self.assertEqual((answer['kind'], answer['label'], answer['layout'], answer['beside'], answer['mark'], answer['same_name']),
                         ('state', 'Start', 'latest', 'course/start/UX-TEST-003', 'Lab state: Start', False))
        flat = place_answer(ME, repo, 'Final')
        self.assertEqual((flat['kind'], flat['label'], flat['layout'], flat['beside']), ('state', 'Final', 'flat', 'Final/UX-TEST-003'))

    def test_a_folder_that_is_part_of_a_saved_state_uses_the_lab_folder_above_it(self):
        repo = checkout([reg('BGP', OTHER)], states={'BGP/latest': summary('lab-2', 'BGP'), 'BGP/checkpoints/before': summary('lab-2', 'BGP')})
        for folder in ('BGP/latest', 'BGP/baseline', 'BGP/checkpoints', 'BGP/checkpoints/before', 'BGP/latest/sub', 'BGP/checkpoints/before/x/y'):
            answer = place_answer(ME, repo, folder)
            self.assertEqual((answer['folder'], answer['adjusted'], answer['kind'], answer['typed'], answer['mark']), ('BGP', 'above-state', 'lab', folder, ''), folder)
        mine = place_answer(lab('OSPF'), repo, 'OSPF/checkpoints/one')
        self.assertEqual((mine['folder'], mine['adjusted'], mine['kind']), ('OSPF', 'above-state', 'own'))

    def test_a_name_with_characters_that_are_not_safe_in_a_path_is_corrected_as_typed(self):
        answer = place_answer(ME, checkout(), 'my course/week 1 (ospf)')
        self.assertEqual((answer['folder'], answer['adjusted'], answer['kind'], answer['typed']), ('my-course/week-1-ospf', 'corrected', 'free', 'my course/week 1 (ospf)'))
        self.assertEqual(place_answer(ME, checkout(), ' /a//b/ ')['adjusted'], '')   # spaces and slashes around names are not a correction

    def test_a_folder_while_a_save_of_this_lab_still_waits_for_upload_is_never_a_refusal(self):
        # Waiting saves are not an input of this module: the answer is the same with them, and question 3
        # (DESIGN.md 2.6) is asked by the route around it. What is pinned here is that nothing is refused.
        mine = lab('old/place')
        repo = checkout([reg('old/place', {'id': 'lab-1', 'name': 'UX-TEST-003'})], states={'old/place/latest': summary('lab-1', 'UX-TEST-003')})
        answer = place_answer(mine, repo, 'new/place')
        self.assertEqual((answer['kind'], answer['folder']), ('free', 'new/place'))
        self.assertEqual(place_answer(mine, repo, 'old/place')['kind'], 'own')

    def test_a_folder_registered_on_the_vm_that_no_lab_uses_is_invisible(self):
        repo = checkout([reg(''), reg('spare'), reg('deep/er/spare')], files=['README.md'])
        self.assertEqual([r['path'] for r in folder_answers(ME, repo)], [''])   # no row of its own
        for folder in ('', 'spare', 'spare/inside', 'deep', 'deep/er/spare', 'beside'):
            answer = place_answer(ME, repo, folder)
            self.assertEqual((answer['kind'], answer['mark'], answer['lab'], answer['exists'] and folder != ''), ('free', '', None, False), folder)
            self.assertEqual(answer, place_answer(ME, checkout(files=['README.md']), folder), folder)


class Steps(unittest.TestCase):
    """DESIGN.md 2.5, clause by clause."""

    def test_the_answer_has_exactly_the_contract_fields(self):
        self.assertEqual(set(place_answer(ME, checkout(), 'a')), FIELDS)
        self.assertEqual(set(folder_answers(ME, checkout())[0]), FIELDS | {'path'})

    def test_step_2_a_reserved_name_as_the_last_part(self):
        for folder, used in (('course/latest', 'course'), ('course/baseline', 'course'), ('course/checkpoints', 'course'), ('latest', ''), ('a/b/latest', 'a/b')):
            answer = place_answer(ME, checkout(), folder)
            self.assertEqual((answer['folder'], answer['adjusted'], answer['kind']), (used, 'above-state', 'free'), folder)

    def test_step_2_checkpoints_followed_by_one_name(self):
        for folder, used in (('course/checkpoints/before-bgp', 'course'), ('checkpoints/one', '')):
            self.assertEqual((place_answer(ME, checkout(), folder)['folder'], place_answer(ME, checkout(), folder)['adjusted']), (used, 'above-state'), folder)
        self.assertEqual(place_answer(ME, checkout(), 'course/checkpoints/a/b')['folder'], 'course/checkpoints/a/b')   # two names: an ordinary path

    def test_step_2_the_folder_above_is_a_lab_folder(self):
        repo = checkout([reg('course', OTHER)])
        self.assertEqual(place_answer(ME, repo, 'course/latest/working')['folder'], 'course')
        self.assertEqual(place_answer(ME, repo, 'course/checkpoints/a/b/c')['folder'], 'course')
        own = place_answer(lab(''), checkout(), 'latest/working')   # this lab saves at the top level
        self.assertEqual((own['folder'], own['kind'], own['adjusted']), ('', 'own', 'above-state'))

    def test_step_2_the_tree_shows_a_manifest_there(self):
        repo = checkout(files=['course/latest/manifest.json', 'x/checkpoints/a/manifest.json'])
        self.assertEqual((place_answer(ME, repo, 'course/latest/working')['folder'], place_answer(ME, repo, 'course/latest/working')['kind']), ('course', 'state'))
        self.assertEqual(place_answer(ME, repo, 'x/checkpoints/a/b/c')['folder'], 'x')
        self.assertEqual(place_answer(ME, repo, 'x/checkpoints/other/b/c')['folder'], 'x/checkpoints/other/b/c')

    def test_step_2_a_latest_in_the_middle_of_a_path_is_an_ordinary_folder(self):
        for repo in (checkout(), checkout(files=['course/latest/working/notes.md']), checkout([reg('course')])):
            answer = place_answer(ME, repo, 'course/latest/working')
            self.assertEqual(answer['folder'], 'course/latest/working')
            self.assertEqual(answer['adjusted'], '')
        self.assertEqual(place_answer(ME, checkout(), 'course/latest/working')['kind'], 'free')

    def test_step_2_repeats_until_no_saved_state_is_left(self):
        self.assertEqual(place_answer(ME, checkout(), 'a/latest/latest')['folder'], 'a')
        self.assertEqual(place_answer(ME, checkout(), 'a/baseline/checkpoints/x')['folder'], 'a')

    def test_step_2_a_legacy_lab_folder_named_latest_is_taken_as_it_is(self):
        legacy = lab('x/latest')
        repo = checkout([reg('x/latest', {'id': 'lab-1', 'name': 'UX-TEST-003'}), reg('y/latest', OTHER)], states={'x/latest/latest': summary('lab-1', 'UX-TEST-003')})
        own = place_answer(legacy, repo, 'x/latest')
        self.assertEqual((own['folder'], own['kind'], own['adjusted']), ('x/latest', 'own', ''))
        self.assertEqual(place_answer(legacy, repo, 'x/latest/latest')['folder'], 'x/latest')
        other = place_answer(legacy, repo, 'y/latest')
        self.assertEqual((other['folder'], other['kind'], other['collision']), ('y/latest', 'lab', False))

    def test_step_3_own(self):
        answer = place_answer(lab('BGP'), checkout(states={'BGP/latest': summary('someone-else', 'x')}), 'BGP')
        self.assertEqual((answer['kind'], answer['mark'], answer['beside'], answer['layout']), ('own', 'This lab saves here', '', ''))
        self.assertEqual(place_answer(lab(''), checkout(), '')['kind'], 'own')
        self.assertEqual(place_answer(lab(None), checkout(), '')['kind'], 'free')   # no folder yet is not the top level

    def test_step_3_own_before_by_the_manifests_lab_id(self):
        repo = checkout(states={'old/latest': summary('lab-1', 'renamed since'), 'flat': summary('lab-1', 'UX-TEST-003')})
        answer = place_answer(ME, repo, 'old')
        self.assertEqual((answer['kind'], answer['layout'], answer['label'], answer['beside'], answer['same_name']), ('own-before', 'latest', 'Old', '', False))
        self.assertEqual((place_answer(ME, repo, 'flat')['kind'], place_answer(ME, repo, 'flat')['layout']), ('own-before', 'flat'))

    def test_review_F3_a_state_of_a_lab_with_the_same_name_and_another_id_is_a_state_never_own_before(self):
        repo = checkout(states={'UX-TEST-003/latest': summary('instructor', 'UX-TEST-003')})
        answer = place_answer(ME, repo, 'UX-TEST-003')
        self.assertEqual((answer['kind'], answer['same_name'], answer['beside']), ('state', True, 'UX-TEST-003/UX-TEST-003'))
        unknown = place_answer(ME, checkout(states={'UX-TEST-003/latest': None}), 'UX-TEST-003')   # an unreadable manifest proves nothing
        self.assertEqual((unknown['kind'], unknown['same_name']), ('state', False))
        nameless = place_answer({'id': '', 'name': 'x', 'prefix': None}, checkout(states={'x/latest': summary('', 'x')}), 'x')
        self.assertEqual(nameless['kind'], 'state')   # two empty ids are not the same lab

    def test_step_3_lab_by_collision_with_any_registration(self):
        used = checkout([reg('x/latest', OTHER)])   # a legacy registration of a connected lab
        answer = place_answer(ME, used, 'x')
        self.assertEqual((answer['kind'], answer['collision'], answer['lab'], answer['beside'], answer['mark']), ('lab', True, OTHER, 'x/UX-TEST-003', ''))

    def test_review_F6_a_folder_that_collides_with_a_registration_no_lab_uses_is_not_free(self):
        answer = place_answer(ME, checkout([reg('x/latest')]), 'x')
        self.assertEqual((answer['kind'], answer['collision'], answer['lab'], answer['beside']), ('lab', True, None, 'x/UX-TEST-003'))
        inside = place_answer(ME, checkout([reg('')]), 'latest/working')   # inside the saved states of an unused top-level registration
        self.assertEqual((inside['kind'], inside['collision'], inside['lab'], inside['folder']), ('lab', True, None, 'latest/working'))
        self.assertEqual(inside['beside'], 'UX-TEST-003')   # nothing below it is usable: the suggestion is beside the registered folder
        self.assertEqual(place_answer(ME, checkout(), 'latest/working')['kind'], 'free')

    def test_review_F5_a_collision_is_told_apart_from_the_identical_folder(self):
        repo = checkout([reg('BGP', OTHER), reg('y/checkpoints/a/deep', OTHER)])
        self.assertFalse(place_answer(ME, repo, 'BGP')['collision'])       # two buttons: the identical folder
        collision = place_answer(ME, repo, 'y')
        self.assertEqual((collision['kind'], collision['collision'], collision['lab']), ('lab', True, OTHER))   # one button
        self.assertEqual(collision['beside'], 'y/UX-TEST-003')

    def test_a_collision_names_a_connected_lab_before_an_unused_registration(self):
        repo = checkout([reg('x/latest'), reg('x/baseline', OTHER)])
        self.assertEqual(place_answer(ME, repo, 'x')['lab'], OTHER)

    def test_review_F11_a_folder_a_lab_state_is_being_saved_into_is_a_state(self):
        repo = checkout(pending=[{'prefix': 'course/start', 'name': 'Start'}])
        answer = place_answer(ME, repo, 'course/start')
        self.assertEqual((answer['kind'], answer['label'], answer['layout'], answer['exists'], answer['beside']), ('state', 'Start', 'latest', False, 'course/start/UX-TEST-003'))
        self.assertEqual(place_answer(ME, repo, 'course/start', purpose='state', name='start')['kind'], 'state')
        self.assertEqual(place_answer(ME, repo, 'course/start/latest/x')['folder'], 'course/start')   # its saved state already counts
        unnamed = place_answer(ME, checkout(pending=[{'prefix': 'course/broken', 'name': ''}]), 'course/broken')
        self.assertEqual(unnamed['label'], 'Broken')
        self.assertEqual(place_answer(ME, repo, 'course')['kind'], 'free')

    def test_step_3_state_latest_layout_comes_before_flat(self):
        repo = checkout(states={'s': summary('lab-1', 'UX-TEST-003'), 's/latest': summary('other', 'Other')})
        answer = place_answer(ME, repo, 's')   # a save would replace s/latest, which is not this lab's
        self.assertEqual((answer['kind'], answer['layout']), ('state', 'latest'))

    def test_step_3_the_top_level_can_hold_a_state(self):
        self.assertEqual((place_answer(ME, checkout(files=['manifest.json']), '')['kind'], place_answer(ME, checkout(files=['manifest.json']), '')['layout']), ('state', 'flat'))
        top = place_answer(ME, checkout(states={'latest': summary()}), '')
        self.assertEqual((top['kind'], top['layout'], top['label'], top['beside']), ('state', 'latest', 'Top level', 'UX-TEST-003'))

    def test_step_3_free_is_everything_else(self):
        repo = checkout([reg('BGP', OTHER)], files=['Final/manifest.json', 'Final/r1.cfg', 'docs/a.md'])
        for folder in ('Final/inside', 'docs', 'docs/new', 'BGP/x', 'nowhere'):
            self.assertEqual(place_answer(ME, repo, folder)['kind'], 'free', folder)

    def test_step_4_someones_own_latest_folder_moves_the_lab_beside_it(self):
        repo = checkout(files=['proj/latest/readme.txt'])
        answer = place_answer(ME, repo, 'proj')
        self.assertEqual((answer['kind'], answer['folder'], answer['adjusted'], answer['typed'], answer['exists'], answer['mark']),
                         ('free', 'proj/UX-TEST-003', 'beside-files', 'proj', False, ''))
        taken = checkout(files=['proj/latest/readme.txt', 'proj/UX-TEST-003/latest/manifest.json'])
        self.assertEqual(place_answer(ME, taken, 'proj')['folder'], 'proj/UX-TEST-003-2')
        self.assertEqual(place_answer(ME, checkout(dirs=['latest']), '')['folder'], 'UX-TEST-003')   # at the top level
        self.assertEqual(place_answer(lab('proj'), repo, 'proj')['adjusted'], '')   # the lab's own folder is left alone
        self.assertEqual(place_answer(ME, checkout(planned=['proj/latest']), 'proj')['adjusted'], '')   # a planned folder holds nothing

    def test_step_4_the_labs_own_earlier_folder_inside_this_folders_saved_states(self):
        legacy = lab('x/latest')
        answer = place_answer(legacy, checkout([reg('x/latest', {'id': 'lab-1', 'name': 'UX-TEST-003'})]), 'x')
        self.assertEqual((answer['kind'], answer['folder'], answer['adjusted'], answer['collision']), ('free', 'x/UX-TEST-003', 'beside-files', False))

    def test_exists_is_true_only_for_what_is_committed(self):
        repo = checkout([reg('BGP', OTHER)], files=['a/b/c.txt'], dirs=['only/dirs'], states={'s/latest': None}, planned=['p'])
        for folder, there in (('', True), ('a', True), ('a/b', True), ('only', True), ('only/dirs', True), ('s', True), ('p', False), ('BGP', False), ('new', False)):
            self.assertEqual(place_answer(ME, repo, folder)['exists'], there, folder)

    def test_a_large_repository_falls_back_to_registrations_and_summaries(self):
        repo = checkout([reg('far/BGP', OTHER)], files=['a.txt'], states={'far/away/start/latest': summary()}, truncated=True)
        self.assertEqual(place_answer(ME, repo, 'far/away/start')['kind'], 'state')
        self.assertEqual(place_answer(ME, repo, 'far/BGP')['kind'], 'lab')
        self.assertEqual(place_answer(ME, repo, 'far/unseen')['kind'], 'free')

    def test_files_may_be_paths_or_the_helpers_rows(self):
        rows = checkout(files=[{'path': 'a/latest/manifest.json', 'size': 3}, {'size': 1}, 7, None])
        self.assertEqual(place_answer(ME, rows, 'a')['kind'], 'state')

    def test_never_raises_for_a_folder_string_except_the_length_rule(self):
        repo = checkout([reg('', OTHER), reg('x/latest')], files=['latest/manifest.json', 'a/latest/b'], pending=[{'prefix': 'p', 'name': 'P'}])
        for typed in HOSTILE:
            for purpose in ('save', 'state'):
                try: answer = place_answer(ME, repo, typed, purpose=purpose, name='start')
                except ValueError as error:
                    self.assertEqual(str(error), git_places.TOO_LONG); continue
                self.assertIn(answer['kind'], git_places.KINDS)
                self.assertEqual(host_git.relpath(answer['folder'], empty=True), answer['folder'])
        with self.assertRaises(ValueError): place_answer(ME, repo, '/'.join(['ab'] * 200))
        for broken in (None, {}, {'registrations': [None, {}, {'prefix': 3}], 'files': None, 'states': None, 'planned': None, 'pending_states': [None, {}]}):
            self.assertEqual(place_answer({}, broken, 'a')['kind'], 'free')


class Questions(unittest.TestCase):
    """DESIGN.md 2.6: what each question needs from the answer."""

    def test_question_1_the_identical_folder_has_two_answers(self):
        answer = place_answer(ME, checkout([reg('BGP', OTHER)]), 'BGP')
        self.assertEqual((answer['kind'], answer['collision'], answer['lab']['name'], answer['beside']), ('lab', False, 'BGP', 'BGP/UX-TEST-003'))

    def test_question_1_a_collision_has_one_answer(self):
        answer = place_answer(ME, checkout([reg('BGP/baseline/odd', OTHER)]), 'BGP')
        self.assertEqual((answer['kind'], answer['collision'], answer['beside']), ('lab', True, 'BGP/UX-TEST-003'))

    def test_question_2_replace_it_for_a_state_in_latest(self):
        answer = place_answer(ME, checkout(states={'start/latest': summary()}), 'start')
        self.assertEqual((answer['kind'], answer['layout'], answer['label']), ('state', 'latest', 'Start'))

    def test_question_2_a_state_stored_directly_in_the_folder_cannot_be_replaced(self):
        answer = place_answer(ME, checkout(states={'Final': summary()}), 'Final')
        self.assertEqual((answer['kind'], answer['layout'], answer['label']), ('state', 'flat', 'Final'))

    def test_the_suggestion_is_the_first_folder_that_is_itself_free(self):
        repo = checkout([reg('BGP', OTHER), reg('BGP/UX-TEST-003', {'id': 'lab-3', 'name': 'Third'}), reg('BGP/UX-TEST-003-3/latest')],
                        states={'BGP/UX-TEST-003-2/latest': summary()}, files=['BGP/UX-TEST-003-4/latest/x'])
        answer = place_answer(ME, repo, 'BGP')
        self.assertEqual(answer['beside'], 'BGP/UX-TEST-003-5')
        again = place_answer(ME, repo, answer['beside'])
        self.assertEqual((again['kind'], again['folder'], again['adjusted']), ('free', 'BGP/UX-TEST-003-5', ''))

    def test_the_suggestion_for_a_lab_named_like_a_saved_state_folder(self):
        answer = place_answer({'id': 'lab-9', 'name': 'latest', 'prefix': None}, checkout([reg('BGP', OTHER)]), 'BGP')
        self.assertEqual(answer['beside'], 'BGP/lab-latest')

    def test_no_suggestion_when_it_would_not_fit(self):
        deep = '/'.join(['ab'] * 166)
        answer = place_answer(ME, checkout([reg(deep, OTHER)]), deep)
        self.assertEqual((answer['kind'], answer['beside']), ('lab', ''))


class StateDestination(unittest.TestCase):
    """DESIGN.md 2.9: a destination for Save as a lab state."""
    repo = checkout([reg('BGP', {'id': 'lab-1', 'name': 'UX-TEST-003'}), reg('OSPF', OTHER)],
                    states={'BGP/latest': summary('lab-1', 'UX-TEST-003'), 'BGP/start/latest': summary('lab-1', 'UX-TEST-003'), 'OSPF/start/latest': summary('lab-2', 'BGP')})

    def test_a_free_folder_goes_on(self):
        answer = place_answer(lab('BGP'), self.repo, 'BGP/broken', purpose='state', name='broken')
        self.assertEqual((answer['kind'], answer['folder'], answer['adjusted']), ('free', 'BGP/broken', ''))

    def test_an_existing_state_is_a_state_whoever_wrote_it(self):
        own = place_answer(lab('BGP'), self.repo, 'BGP/start', purpose='state', name='start')   # this lab's id: still Replace it / Use another name
        self.assertEqual((own['kind'], own['label'], own['folder'], own['layout']), ('state', 'Start', 'BGP/start', 'latest'))
        self.assertEqual(place_answer(lab('BGP'), self.repo, 'OSPF/start', purpose='state', name='start')['kind'], 'state')

    def test_the_labs_own_folder_is_never_the_destination(self):
        answer = place_answer(lab('BGP'), self.repo, 'BGP', purpose='state', name='final')
        self.assertEqual((answer['kind'], answer['folder'], answer['adjusted'], answer['typed']), ('free', 'BGP/final', 'inside-lab', 'BGP'))
        taken = place_answer(lab('BGP'), self.repo, 'BGP', purpose='state', name='start')
        self.assertEqual((taken['kind'], taken['folder'], taken['adjusted']), ('state', 'BGP/start', 'inside-lab'))
        through = place_answer(lab('BGP'), self.repo, 'BGP/latest', purpose='state', name='Final State')
        self.assertEqual((through['folder'], through['adjusted']), ('BGP/Final-State', 'inside-lab'))

    def test_another_labs_folder_is_never_the_destination(self):
        answer = place_answer(lab('BGP'), self.repo, 'OSPF', purpose='state', name='final')
        self.assertEqual((answer['kind'], answer['folder'], answer['adjusted']), ('free', 'OSPF/final', 'inside-lab'))
        nested = checkout([reg('BGP', OTHER), reg('BGP/final', {'id': 'lab-3', 'name': 'Third'})])
        self.assertEqual(place_answer(ME, nested, 'BGP', purpose='state', name='final')['folder'], 'BGP/final-2')

    def test_a_state_name_is_made_a_folder_name(self):
        self.assertEqual(place_answer(lab('BGP'), self.repo, 'BGP', purpose='state', name='latest')['folder'], 'BGP/state-latest')
        self.assertEqual(place_answer(lab('BGP'), self.repo, 'BGP', purpose='state')['folder'], 'BGP/state')

    def test_someones_own_latest_folder_is_avoided(self):
        answer = place_answer(ME, checkout(files=['proj/latest/x']), 'proj', purpose='state', name='start')
        self.assertEqual((answer['kind'], answer['folder'], answer['adjusted']), ('free', 'proj/start', 'beside-files'))

    def test_a_folder_the_manager_wrote_as_a_lab_state_is_not_this_labs_earlier_folder(self):
        marked = dict(self.repo, lab_states=['BGP/start'])
        self.assertEqual(place_answer(lab('BGP'), marked, 'BGP/start')['kind'], 'state')
        self.assertEqual(place_answer(lab('BGP'), self.repo, 'BGP/start')['kind'], 'own-before')   # without the mark only the lab id speaks

    def test_a_lab_state_says_so_in_its_manifest_and_is_never_this_labs_earlier_folder(self):
        # "Save as a lab state…" writes `state: <name>` into the manifest; the helper's summary carries it.
        authored = checkout(states={'BGP/week-2/latest': summary(lab_id=ME['id'], lab_name=ME['name'], state='Start (week 2)')})
        answer = place_answer(lab('BGP'), authored, 'BGP/week-2')
        self.assertEqual((answer['kind'], answer['label'], answer['same_name']), ('state', 'Start (week 2)', False))
        self.assertEqual([(row['group'], row['name']) for row in state_rows(lab('BGP'), authored)], [('state', 'Start (week 2)')])
        for odd in (7, '', None, ['x']):   # anything but a name is no mark
            plain = checkout(states={'BGP/week-2/latest': summary(lab_id=ME['id'], lab_name=ME['name'], state=odd)})
            self.assertEqual(place_answer(lab('BGP'), plain, 'BGP/week-2')['kind'], 'own-before', odd)


class FolderAnswers(unittest.TestCase):
    repo = checkout([reg('', None), reg('BGP', OTHER), reg('unused/spare'), reg('mine', {'id': 'lab-1', 'name': 'UX-TEST-003'})],
                    files=['README.md', 'BGP/latest/manifest.json', 'BGP/latest/r1.cfg', 'BGP/checkpoints/one/manifest.json', 'course/start/latest/manifest.json',
                           'docs/a/b.md', 'My Docs/x.txt'],
                    dirs=['empty-dir'], states={'course/start/latest': summary()}, planned=['later/on'])

    def test_lists_every_folder_once_sorted_with_the_same_answer_as_place_answer(self):
        rows = folder_answers(lab('mine'), self.repo)
        listed = [r['path'] for r in rows]
        self.assertEqual(listed, sorted(listed))
        self.assertEqual(listed, ['', 'BGP', 'BGP/checkpoints', 'BGP/checkpoints/one', 'BGP/latest', 'My Docs', 'course', 'course/start', 'course/start/latest',
                                  'docs', 'docs/a', 'empty-dir', 'later', 'later/on', 'mine'])
        for row in rows:
            self.assertEqual({k: v for k, v in row.items() if k != 'path'}, place_answer(lab('mine'), self.repo, row['path']), row['path'])

    def test_marks(self):
        marks = {r['path']: r['mark'] for r in folder_answers(lab('mine'), self.repo)}
        self.assertEqual({p: m for p, m in marks.items() if m}, {'BGP': 'BGP saves here', 'course/start': 'Lab state: Start', 'mine': 'This lab saves here'})

    def test_saved_state_folders_are_listed_with_their_adjusted_answer(self):
        rows = {r['path']: r for r in folder_answers(lab('mine'), self.repo)}
        for path, used, kind in (('BGP/latest', 'BGP', 'lab'), ('BGP/checkpoints', 'BGP', 'lab'), ('BGP/checkpoints/one', 'BGP', 'lab'), ('course/start/latest', 'course/start', 'state')):
            self.assertEqual((rows[path]['folder'], rows[path]['adjusted'], rows[path]['kind'], rows[path]['mark']), (used, 'above-state', kind, ''), path)

    def test_a_committed_folder_the_helper_would_not_take_is_listed_with_its_corrected_folder(self):
        row = next(r for r in folder_answers(lab('mine'), self.repo) if r['path'] == 'My Docs')
        self.assertEqual((row['folder'], row['adjusted'], row['exists']), ('My-Docs', 'corrected', False))

    def test_a_planned_folder_is_listed_and_does_not_exist(self):
        rows = {r['path']: r for r in folder_answers(lab('mine'), self.repo)}
        self.assertEqual((rows['later/on']['kind'], rows['later/on']['exists'], rows['later']['exists']), ('free', False, False))

    def test_an_empty_checkout_lists_the_top_level(self):
        self.assertEqual([r['path'] for r in folder_answers(ME, checkout())], [''])
        self.assertEqual([r['path'] for r in folder_answers(ME, {})], [''])


class DefaultPlace(unittest.TestCase):
    def entry(self, rid, name, repo=None, last_used='', **more): return dict({'id': rid, 'name': name, 'path': '/srv/git/' + name, 'last_used': last_used, 'checkout': repo or checkout()}, **more)

    def test_no_repository_is_no_default(self):
        self.assertIsNone(default_place(ME, []))

    def test_the_repository_the_lab_used_last_then_the_most_recent_then_the_first_by_name(self):
        entries = [self.entry('c', 'Zeta', last_used='2026-01-01'), self.entry('a', 'alpha'), self.entry('b', 'Beta', last_used='2026-05-01')]
        self.assertEqual(default_place(lab(last_repository='/srv/git/alpha'), entries)['repository'], 'a')
        self.assertEqual(default_place(lab(last_repository='/srv/git/gone'), entries)['repository'], 'b')
        self.assertEqual(default_place(ME, entries)['repository'], 'b')
        self.assertEqual(default_place(ME, [self.entry('c', 'Zeta'), self.entry('a', 'alpha'), self.entry('b', 'Beta')])['repository'], 'a')

    def test_the_folder_named_after_the_lab(self):
        place = default_place(ME, [self.entry('a', 'alpha')])
        self.assertEqual((place['folder'], place['answer']['kind'], place['ask']), ('UX-TEST-003', 'free', False))
        self.assertEqual(default_place({'id': 'x', 'name': '', 'prefix': None}, [self.entry('a', 'alpha')])['folder'], 'lab')
        self.assertEqual(default_place({'id': 'x', 'name': 'my lab', 'prefix': None}, [self.entry('a', 'alpha')])['folder'], 'my-lab')

    def test_the_labs_own_earlier_folder_is_continued(self):
        repo = checkout(states={'UX-TEST-003/latest': summary('lab-1', 'UX-TEST-003')})
        place = default_place(ME, [self.entry('a', 'alpha', repo)])
        self.assertEqual((place['folder'], place['answer']['kind'], place['ask']), ('UX-TEST-003', 'own-before', False))

    def test_the_folder_the_lab_saves_to_now(self):
        repo = checkout([reg('elsewhere', {'id': 'lab-1', 'name': 'UX-TEST-003'})])
        place = default_place(ME, [self.entry('a', 'alpha', repo, prefix='elsewhere')])
        self.assertEqual((place['folder'], place['answer']['kind']), ('elsewhere', 'own'))
        place = default_place(lab('elsewhere', last_repository='/srv/git/alpha'), [self.entry('a', 'alpha', repo)])
        self.assertEqual((place['folder'], place['answer']['kind']), ('elsewhere', 'own'))
        other = default_place(lab('elsewhere', last_repository='/srv/git/gone'), [self.entry('a', 'alpha')])   # its folder in another repository says nothing here
        self.assertEqual((other['folder'], other['answer']['kind']), ('UX-TEST-003', 'free'))

    def test_review_F3_the_saves_of_a_lab_of_the_same_name_are_never_continued_silently(self):
        repo = checkout(states={'UX-TEST-003/latest': summary('instructor', 'UX-TEST-003'), 'UX-TEST-003-2/latest': summary('x', 'y')})
        place = default_place(ME, [self.entry('a', 'alpha', repo)])
        self.assertEqual((place['folder'], place['ask'], place['beside'], place['answer']['kind'], place['answer']['same_name'], place['answer']['beside']),
                         ('UX-TEST-003', True, 'UX-TEST-003-3', 'state', True, 'UX-TEST-003-3'))

    def test_otherwise_the_first_numbered_folder_that_needs_no_question(self):
        repo = checkout([reg('UX-TEST-003', OTHER)], states={'UX-TEST-003-2/latest': summary('course', 'Start')})
        place = default_place(ME, [self.entry('a', 'alpha', repo)])
        self.assertEqual((place['folder'], place['answer']['kind'], place['ask']), ('UX-TEST-003-3', 'free', False))
        mine = checkout([reg('UX-TEST-003', OTHER)], states={'UX-TEST-003-2/latest': summary('lab-1', 'UX-TEST-003')})
        self.assertEqual(default_place(ME, [self.entry('a', 'alpha', mine)])['answer']['kind'], 'own-before')

    def test_the_default_can_always_be_saved_to_without_a_question(self):
        repo = checkout(files=['UX-TEST-003/latest/readme.txt'])   # someone's own folder named latest
        place = default_place(ME, [self.entry('a', 'alpha', repo)])
        self.assertEqual((place['folder'], place['answer']['kind'], place['answer']['adjusted']), ('UX-TEST-003/UX-TEST-003', 'free', 'beside-files'))


class StateRows(unittest.TestCase):
    def test_state_name(self):
        for path, name in (('BGP/start/latest', 'Start'), ('BGP/start', 'Start'), ('Final', 'Final'), ('course/BGP', 'BGP'), ('course/bgp-1/latest', 'Bgp-1'),
                           ('', 'Top level'), ('latest', 'Top level'), ('/', 'Top level'), ('BGP/checkpoints/before-ospf', 'before-ospf'),
                           ('checkpoints/one', 'one'), ('BGP/baseline', 'Baseline'), ('a/myLab', 'myLab'), ('a/123', '123'), (None, 'Top level')):
            self.assertEqual(state_name(path), name, path)

    repo = checkout([reg('BGP', {'id': 'lab-1', 'name': 'UX-TEST-003'}), reg('OSPF', OTHER), reg('spare')],
                    states={'BGP/latest': summary('lab-1', 'UX-TEST-003'), 'BGP/baseline': summary('lab-1', 'UX-TEST-003'),
                            'BGP/checkpoints/zeta': summary('lab-1', 'UX-TEST-003'), 'BGP/checkpoints/alpha': summary('lab-1', 'UX-TEST-003', kind='network-design'),
                            'BGP/start/latest': summary('lab-1', 'UX-TEST-003'), 'OSPF/start/latest': summary('lab-2', 'BGP'), 'OSPF/latest': summary('lab-2', 'BGP'),
                            'OSPF/checkpoints/x': summary('lab-2', 'BGP'), 'course/final': summary('c', 'Course'), 'spare/latest': None, 'broken/latest': summary('c', 'Course')})

    def test_groups_names_and_order(self):
        rows = state_rows(lab('BGP'), self.repo)
        self.assertEqual([(r['path'], r['group'], r['name']) for r in rows], [
            ('BGP/latest', 'latest', 'BGP'), ('BGP/checkpoints/alpha', 'checkpoint', 'alpha'), ('BGP/checkpoints/zeta', 'checkpoint', 'zeta'),
            ('BGP/baseline', 'baseline', 'Baseline'), ('broken/latest', 'state', 'Broken'), ('course/final', 'state', 'Final'), ('spare/latest', 'state', 'Spare'),
            ('BGP/start/latest', 'state', 'Start · BGP'), ('OSPF/start/latest', 'state', 'Start · OSPF'),
            ('OSPF/latest', 'other-lab', 'OSPF'), ('OSPF/checkpoints/x', 'other-lab', 'x')])
        by = {r['path']: r for r in rows}
        self.assertEqual(set(by['BGP/latest']), {'path', 'name', 'group', 'lab', 'kind', 'summary', 'layout'})
        self.assertEqual((by['OSPF/latest']['lab'], by['course/final']['lab'], by['spare/latest']['lab']), ('BGP', 'Course', ''))
        self.assertEqual((by['BGP/checkpoints/alpha']['kind'], by['BGP/checkpoints/zeta']['kind'], by['spare/latest']['kind']), ('design', 'capture', 'capture'))
        self.assertEqual((by['BGP/latest']['layout'], by['course/final']['layout'], by['BGP/checkpoints/zeta']['layout']), ('latest', 'flat', 'flat'))
        self.assertIs(by['spare/latest']['summary'], None)
        self.assertEqual(by['course/final']['summary']['lab_id'], 'c')

    def test_a_lab_without_a_folder_owns_no_row(self):
        groups = {r['group'] for r in state_rows(ME, self.repo)}
        self.assertEqual(groups, {'state', 'other-lab'})

    def test_a_state_of_a_registration_no_lab_uses_is_a_plain_state(self):
        self.assertEqual(next(r for r in state_rows(ME, self.repo) if r['path'] == 'spare/latest')['group'], 'state')

    def test_equal_names_add_the_parent_and_then_the_path(self):
        repo = checkout(states={'a/start/latest': None, 'b/start': None, 'start': None, 'a/start': None, 'solo/latest': None})
        names = {r['path']: r['name'] for r in state_rows(ME, repo)}
        self.assertEqual(names, {'a/start/latest': 'Start · a/start/latest', 'a/start': 'Start · a/start', 'b/start': 'Start · b', 'start': 'Start · Top level', 'solo/latest': 'Solo'})

    def test_states_at_the_top_level(self):
        rows = state_rows(lab(''), checkout(files=['latest/manifest.json', 'checkpoints/one/manifest.json', 'manifest.json']))
        self.assertEqual([(r['path'], r['group'], r['name']) for r in rows], [('latest', 'latest', 'Top level'), ('checkpoints/one', 'checkpoint', 'one'), ('', 'state', 'Top level')])

    def test_a_legacy_lab_folder_named_latest(self):
        rows = state_rows(lab('x/latest'), checkout(states={'x/latest/latest': None}))
        self.assertEqual([(r['path'], r['group']) for r in rows], [('x/latest/latest', 'latest')])


class Randomized(unittest.TestCase):
    """A few thousand random folder strings against random small checkouts, fixed seed."""
    NAMES = ['a', 'b', 'lab', 'UX-TEST-003', 'UX-TEST-003-2', 'start', 'latest', 'baseline', 'checkpoints', 'x y', '..', '.git', 'é', '', ' ', 'c?']
    SAFE = ['a', 'b', 'lab', 'UX-TEST-003', 'UX-TEST-003-2', 'start', 'latest', 'baseline', 'checkpoints']

    def path(self, rng, names, most=5): return '/'.join(rng.choice(names) for _ in range(rng.randrange(most)))

    def repo(self, rng):
        labs = [None, None, OTHER, {'id': 'lab-3', 'name': 'UX-TEST-003'}, {'id': 'lab-1', 'name': 'UX-TEST-003'}]
        regs = [reg(self.path(rng, self.SAFE, 4), rng.choice(labs)) for _ in range(rng.randrange(5))]
        files = [self.path(rng, self.SAFE, 4) + rng.choice(['/manifest.json', '/r1.cfg', '/x/y.txt']) for _ in range(rng.randrange(6))]
        owners = [None, summary('lab-1', 'UX-TEST-003'), summary('lab-3', 'UX-TEST-003'), summary()]
        states = {self.path(rng, self.SAFE, 4): rng.choice(owners) for _ in range(rng.randrange(4))}
        return checkout(regs, files=[f.lstrip('/') for f in files], dirs=rng.choice([None, [self.path(rng, self.SAFE, 4)]]), states=states,
                        planned=[self.path(rng, self.SAFE, 3) for _ in range(rng.randrange(2))],
                        pending=[{'prefix': self.path(rng, ['a', 'b', 'start'], 3), 'name': 'S'} for _ in range(rng.randrange(2))])

    def test_invariants(self):
        rng = random.Random(20261004); asked = suggested = 0
        for _ in range(600):
            repo = self.repo(rng); me = lab(rng.choice([None, None, '', 'a', 'a/b', 'lab', 'a/latest']))
            tree = git_places.Tree(me, repo)
            folders = [r['prefix'] for r in repo['registrations']] + ([me['prefix']] if me['prefix'] is not None else [])
            possible = not any(colliding(a, b) for a in folders for b in folders)
            spare = reg(self.path(rng, self.SAFE, 4)); wider = dict(repo, registrations=repo['registrations'] + [spare])
            for row in folder_answers(me, repo):
                self.assertEqual({k: v for k, v in row.items() if k != 'path'}, place_answer(me, repo, row['path']), (row['path'], repo))
            for _ in range(8):
                typed = self.path(rng, self.NAMES, 6); asked += 1
                for purpose in ('save', 'state'):
                    answer = place_answer(me, repo, typed, purpose=purpose, name=rng.choice(['start', 'latest', 'Broken 1', '']))
                    self.assertEqual(set(answer), FIELDS)
                    self.assertIn(answer['kind'], git_places.KINDS, (typed, repo))
                    self.assertEqual(host_git.relpath(answer['folder'], empty=True), answer['folder'], (typed, repo))
                    self.assertIn(answer['adjusted'], ('', 'corrected', 'above-state', 'beside-files', 'inside-lab'))
                    self.assertEqual(answer['collision'] and answer['kind'] != 'lab', False)
                    self.assertEqual(bool(answer['layout']), answer['kind'] in ('state', 'own-before'), (typed, repo))
                    if answer['adjusted'] == 'beside-files': self.assertEqual(answer['kind'], 'free', (typed, repo))
                    if answer['beside']:
                        beside = place_answer(me, repo, answer['beside'])
                        self.assertEqual((beside['kind'], beside['folder'], beside['adjusted']), ('free', answer['beside'], ''), (typed, repo))
                answer = place_answer(me, repo, typed)
                # A question always has its suggestion (short paths; a registry the helper could hold: it refuses a colliding pair).
                if answer['kind'] in ('lab', 'state') and possible: self.assertTrue(answer['beside'], (typed, repo)); suggested += 1
                # The index answers exactly what the helper's rule answers, registration by registration.
                brute = [r for r in repo['registrations'] if colliding(answer['folder'], r['prefix'])]
                self.assertEqual(bool(tree.collisions(answer['folder'])), bool(brute) or (me['prefix'] is not None and colliding(answer['folder'], me['prefix'])), (typed, repo))
                # A registration no lab uses changes an answer only where the helper would refuse it.
                seen = place_answer(me, wider, typed)
                if seen != answer:
                    near = {answer['folder'], answer['beside'], clean_folder(typed)} | {seen['folder'], seen['beside']}
                    near |= {f.rsplit('/', 1)[0] if '/' in f else '' for f in list(near)}
                    self.assertTrue(any(colliding(spare['prefix'], f) for f in near), (typed, spare, answer, seen))
                if not any(colliding(spare['prefix'], f) for f in (answer['folder'], answer['beside'], clean_folder(typed), answer['folder'].rsplit('/', 1)[0] if '/' in answer['folder'] else '')):
                    self.assertEqual(seen, answer, (typed, spare))
                self.assertEqual(place_answer(me, dict(repo, registrations=repo['registrations'] + [reg(answer['folder'])]), typed), answer, (typed, repo))
        self.assertGreater(asked, 4000); self.assertGreater(suggested, 300)

    def test_default_place_always_needs_no_question_or_asks(self):
        rng = random.Random(7)
        for _ in range(400):
            repo = self.repo(rng)
            place = default_place(ME, [{'id': 'r', 'name': 'n', 'path': '/p', 'last_used': '', 'checkout': repo}])
            self.assertEqual(host_git.relpath(place['folder'], empty=True), place['folder'])
            if place['ask']:
                self.assertTrue(place['answer']['same_name'])
                self.assertEqual(place_answer(ME, repo, place['beside'])['kind'], 'free')
            else: self.assertIn(place['answer']['kind'], ('free', 'own', 'own-before'), repo)


if __name__ == '__main__':
    unittest.main()
