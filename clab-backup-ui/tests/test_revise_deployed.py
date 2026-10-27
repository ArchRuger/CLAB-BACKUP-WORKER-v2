"""The deployed save (campaign 2, T03; docs/parity-campaign/TOPOLOGY-EDIT-DESIGN.md section 4 and amendments A3, A11, A14).

The invariant each test below pins one clause of: `revise` writes only the topology and map files, bound to the
opened versions' hashes; on a lab with containers it runs only with `deployed: true` and binds every container found
by name or path into the digest; it never runs a containerlab command (`argv` and `steps` empty).
"""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import app.host_operations as host_operations
from app.host_operations import HostOperations, LIFECYCLE, NODE_ACTIONS, digest

SENTENCE = 'This lab has running devices. Reopen the lab in the manager and save again.'
CHANGED = 'The topology or deployment changed. Preview the operation again.'
TAIL = '. Saving replaces the topology file and the map layout on the VM; the devices are not changed. Applying the changes is a separate, reviewed step.'
BUILT = b'name: built\ntopology:\n  nodes:\n    r1:\n      kind: linux\n      image: alpine:latest\n'
LAYOUT = '{"nodeAnnotations":[{"id":"r1","position":{"x":10,"y":20}}]}'
NEW_TEXT = BUILT.decode() + '    r2:\n      kind: linux\n      image: alpine:latest\n'
NEW_LAYOUT = '{"nodeAnnotations":[]}'


def sha(data): return hashlib.sha256(data).hexdigest()


class DeployedReviseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)
        self.folder = self.root / 'built'; self.folder.mkdir()
        self.path = self.folder / 'built.clab.yml'; self.path.write_bytes(BUILT)
        self.side = Path(str(self.path) + '.annotations.json'); self.side.write_text(LAYOUT)
        self.rows = {}; self.calls = []
        def run(argv, **bounds):
            self.calls.append(list(argv))
            if '--help' in argv: return 0, '--name --cleanup --graceful --node --node-filter --dry-run help'
            if argv[1:2] == ['inspect']: return 0, json.dumps(self.rows)
            return 0, 'fixture'
        self.host = HostOperations(dict(clab='/usr/bin/containerlab', git='/usr/bin/git', roots=[str(self.root)], projects=str(self.root), network=True), run,
                                   probe=lambda argv, **bounds: (1, '', ''))

    def tearDown(self): self.tmp.cleanup()

    def row(self, container, state='running', lab='built', cid=None, path=None):
        return dict(name=container, lab_name=lab, state=state, container_id=cid or 'id-' + container, absLabPath=str(path or self.path))

    def revise(self, **options):
        return dict(action='revise', name='built', path=str(self.path),
                    options={'text': NEW_TEXT, 'annotations': NEW_LAYOUT, 'base': {'yaml': sha(BUILT), 'annotations': sha(LAYOUT.encode())}, **options})

    def run_plan(self, request, digest_value):
        with patch.object(host_operations, 'stream') as stream:
            result = self.host.execute({**request, 'digest': digest_value}, lambda _: None)
        stream.assert_not_called()
        return result

    def commands(self):
        """Containerlab argv run since the last reset, other than the inspection and help reads."""
        return [c for c in self.calls if c[1:2] != ['inspect'] and '--help' not in c and c[1:3] != ['version', '--short']]

    # --- the unflagged refusal ------------------------------------------------------------------------------
    def test_a_lab_with_containers_is_refused_without_the_flag_with_the_new_sentence(self):
        self.rows = {'built': [self.row('clab-built-r1')]}
        for options in ({}, {'deployed': False}):
            with self.subTest(options=options):
                with self.assertRaises(ValueError) as caught: self.host.plan(self.revise(**options))
                self.assertEqual(str(caught.exception), SENTENCE)
                self.assertNotIn('destroy', str(caught.exception).lower())
        # Found by topology path only (deployed with `--name`): refused the same way.
        self.rows = {'renamed': [self.row('clab-renamed-r1', lab='renamed')]}
        with self.assertRaises(ValueError) as caught: self.host.plan(self.revise())
        self.assertEqual(str(caught.exception), SENTENCE)
        # A stopped container is a container: the flag is still needed.
        self.rows = {'built': [self.row('clab-built-r1', state='exited')]}
        with self.assertRaisesRegex(ValueError, '^' + SENTENCE + '$'): self.host.plan(self.revise())
        self.assertEqual(self.path.read_bytes(), BUILT); self.assertEqual(self.side.read_text(), LAYOUT)
        self.assertEqual(SENTENCE, host_operations.RUNNING_REVISE_SENTENCE)

    # --- the flagged plan -------------------------------------------------------------------------------------
    def test_flagged_plan_under_the_yaml_name_binds_every_container_sorted_and_runs_no_containerlab_command(self):
        self.rows = {'built': [self.row('clab-built-r2'), self.row('clab-built-r1', state='exited')]}
        request = self.revise(deployed=True); review = self.host.plan(request)
        self.assertEqual(review['affected'], [{'name': 'clab-built-r1', 'id': 'id-clab-built-r1', 'state': 'exited'},
                                              {'name': 'clab-built-r2', 'id': 'id-clab-built-r2', 'state': 'running'}])
        self.assertEqual(review['argv'], []); self.assertEqual(review['steps'], [])
        self.calls.clear(); result = self.run_plan(request, review['digest'])
        self.assertEqual(self.commands(), [], 'a deployed save runs no containerlab command')
        self.assertEqual(result['exit_code'], 0)
        self.assertEqual(self.path.read_text(), NEW_TEXT); self.assertEqual(self.side.read_text(), NEW_LAYOUT)
        self.assertEqual(Path(result['recovery_path']).read_bytes(), BUILT)
        self.assertEqual(sorted(p.name for p in self.folder.iterdir()), ['.clab-manager-history', self.path.name, self.side.name], 'only the two files (and their recovery copies) are written')

    def test_flagged_plan_on_a_lab_found_by_its_topology_path_only_binds_its_containers(self):
        self.rows = {'renamed': [self.row('clab-renamed-r2', lab='renamed'), self.row('clab-renamed-r1', lab='renamed')],
                     'elsewhere': [self.row('clab-elsewhere-r1', lab='elsewhere', path=self.root / 'other.clab.yml')]}
        review = self.host.plan(self.revise(deployed=True))
        self.assertEqual([a['name'] for a in review['affected']], ['clab-renamed-r1', 'clab-renamed-r2'], 'a lab of another file is not bound')
        self.assertEqual(review['argv'], []); self.assertEqual(review['steps'], [])

    def test_containers_found_by_name_and_by_path_are_all_bound(self):
        # The same file deployed twice, once under its YAML name and once with `--name`: both deployments are bound.
        self.rows = {'built': [self.row('clab-built-r1')], 'copy': [self.row('clab-copy-r1', lab='copy')]}
        review = self.host.plan(self.revise(deployed=True))
        self.assertEqual([a['name'] for a in review['affected']], ['clab-built-r1', 'clab-copy-r1'])
        self.rows['copy'][0]['container_id'] = 'recreated'
        with self.assertRaisesRegex(ValueError, '^' + CHANGED + '$'): self.run_plan(self.revise(deployed=True), review['digest'])
        self.assertEqual(self.path.read_bytes(), BUILT)

    # --- the digest: name and id, not state ------------------------------------------------------------------
    def test_a_changed_container_id_refuses_the_run_and_a_changed_state_does_not(self):
        self.rows = {'built': [self.row('clab-built-r1'), self.row('clab-built-r2')]}
        request = self.revise(deployed=True); review = self.host.plan(request)
        self.rows['built'][1]['container_id'] = 'recreated'
        with self.assertRaises(ValueError) as caught: self.run_plan(request, review['digest'])
        self.assertEqual(str(caught.exception), CHANGED)
        self.assertEqual(self.path.read_bytes(), BUILT); self.assertEqual(self.side.read_text(), LAYOUT)
        self.rows['built'][1]['container_id'] = 'id-clab-built-r2'
        self.rows['built'][0]['state'] = 'exited'; self.rows['built'][1]['state'] = 'restarting'
        result = self.run_plan(request, review['digest'])
        self.assertEqual(result['exit_code'], 0); self.assertEqual(self.path.read_text(), NEW_TEXT)

    def test_a_container_that_appears_or_disappears_between_review_and_run_refuses_it(self):
        request = self.revise(deployed=True); review = self.host.plan(request)
        self.assertEqual(review['affected'], [])
        self.rows = {'built': [self.row('clab-built-r1')]}
        with self.assertRaisesRegex(ValueError, '^' + CHANGED + '$'): self.run_plan(request, review['digest'])
        review = self.host.plan(request); self.rows = {'built': [self.row('clab-built-r9')]}
        with self.assertRaisesRegex(ValueError, '^' + CHANGED + '$'): self.run_plan(request, review['digest'])
        self.rows = {}
        with self.assertRaisesRegex(ValueError, '^' + CHANGED + '$'): self.run_plan(request, review['digest'])
        self.assertEqual(self.path.read_bytes(), BUILT)

    def test_the_revise_digest_is_the_plan_with_state_left_out(self):
        self.rows = {'built': [self.row('clab-built-r1', state='exited')]}
        review = self.host.plan(self.revise(deployed=True))
        base = {k: v for k, v in review.items() if k not in ('digest', 'warnings')}
        self.assertEqual(review['digest'], digest({**base, 'affected': [{'name': 'clab-built-r1', 'id': 'id-clab-built-r1'}]}))
        self.assertNotEqual(review['digest'], digest(base))

    def test_every_other_action_still_binds_the_state(self):
        training = self.root / 'training.clab.yml'; training.write_bytes(BUILT.replace(b'name: built', b'name: training'))
        self.rows = {'training': [dict(name='clab-training-r1', lab_name='training', state='running', container_id='c1', absLabPath=str(training))]}
        for action in ('restart', 'stop', 'save', 'redeploy'):
            with self.subTest(action=action):
                self.rows['training'][0]['state'] = 'running'
                request = dict(action=action, name='training', path=str(training), options={}); review = self.host.plan(request)
                base = {k: v for k, v in review.items() if k not in ('digest', 'warnings')}
                self.assertEqual(review['digest'], digest(base))
                self.rows['training'][0]['state'] = 'exited'
                with self.assertRaisesRegex(ValueError, '^' + CHANGED + '$'): self.host.execute({**request, 'digest': review['digest']}, lambda _: None)

    # --- the option plumbing ----------------------------------------------------------------------------------
    def test_deployed_is_refused_on_every_other_action(self):
        self.assertEqual(host_operations.OPTION_ACTIONS['deployed'], ('revise',))
        requests = [dict(action='deploy', name='built', path=str(self.path), options={'deployed': True}),
                    dict(action='publish', name='fresh', options={'root': str(self.root), 'text': BUILT.decode(), 'deployed': True}),
                    dict(action='create', name='built', path=str(self.folder / 'new.clab.yml'), options={'text': BUILT.decode(), 'deployed': True})]
        requests += [dict(action=a, name='built', path=str(self.path), options={'deployed': True}) for a in (*LIFECYCLE, 'delete', 'inspect-all') if a != 'deploy']
        requests += [dict(action=a, name='built', path=str(self.path), options={'node': 'r1', 'container': 'clab-built-r1', 'deployed': True}) for a in NODE_ACTIONS]
        for request in requests:
            with self.subTest(action=request['action']):
                with self.assertRaises(ValueError) as caught: self.host.plan(request)
                self.assertEqual(str(caught.exception), 'Unsupported operation options.')
        self.assertFalse((self.folder / 'new.clab.yml').exists()); self.assertFalse((self.root / 'fresh').exists())

    def test_deployed_must_be_a_boolean(self):
        self.rows = {'built': [self.row('clab-built-r1')]}
        for value in ('yes', 1, 0, None, 'true', [True]):
            with self.subTest(value=value):
                with self.assertRaises(ValueError) as caught: self.host.plan(self.revise(deployed=value))
                self.assertEqual(str(caught.exception), 'Invalid boolean option.')

    # --- the warning ------------------------------------------------------------------------------------------
    def test_the_warning_counts_devices_by_state(self):
        cases = ((['running'] * 3 + ['exited', 'created'], 'This lab has 3 running and 2 stopped devices' + TAIL),
                 (['running'] * 5, 'This lab has 5 running devices' + TAIL),
                 (['exited'], 'This lab has 1 stopped device' + TAIL),
                 (['running'], 'This lab has 1 running device' + TAIL),
                 (['running', 'exited'], 'This lab has 1 running and 1 stopped devices' + TAIL))
        for states, sentence in cases:
            with self.subTest(states=states):
                self.rows = {'built': [self.row('clab-built-r%d' % i, state=s) for i, s in enumerate(states)]}
                self.assertEqual(self.host.plan(self.revise(deployed=True))['warnings'], [sentence])

    # --- capabilities and the no-container case ---------------------------------------------------------------
    def test_capabilities_offer_the_deployed_save(self):
        revise = self.host.capabilities()['actions']['revise']
        self.assertEqual(revise, {'available': True, 'deployed': True})
        self.assertIs(revise['deployed'], True)

    def test_the_flag_on_a_lab_without_containers_is_an_ordinary_revise(self):
        plain = self.host.plan(self.revise()); flagged = self.host.plan(self.revise(deployed=True))
        drop = lambda plan: {k: v for k, v in plan.items() if k not in ('options', 'digest')}
        self.assertEqual(drop(flagged), drop(plain))
        self.assertEqual(flagged['affected'], []); self.assertEqual(flagged['warnings'], [])
        self.assertEqual(flagged['options'], {**plain['options'], 'deployed': True})
        self.assertNotEqual(flagged['digest'], plain['digest'], 'the option itself is part of the reviewed request')
        with self.assertRaisesRegex(ValueError, '^' + CHANGED + '$'): self.run_plan(self.revise(), flagged['digest'])
        result = self.run_plan(self.revise(deployed=True), flagged['digest'])
        self.assertEqual(result['exit_code'], 0); self.assertEqual(self.path.read_text(), NEW_TEXT)

    def test_the_opened_versions_still_bind_a_deployed_save(self):
        self.rows = {'built': [self.row('clab-built-r1')]}
        with self.assertRaisesRegex(ValueError, 'changed on the VM'): self.host.plan(self.revise(deployed=True, base={'yaml': 'stale', 'annotations': sha(LAYOUT.encode())}))
        with self.assertRaisesRegex(ValueError, 'changed on the VM'): self.host.plan(self.revise(deployed=True, base={'yaml': sha(BUILT), 'annotations': ''}))
        request = self.revise(deployed=True); review = self.host.plan(request)
        self.path.write_bytes(BUILT + b'# edited on the VM\n')
        with self.assertRaisesRegex(ValueError, 'changed'): self.run_plan(request, review['digest'])
        self.assertEqual(self.side.read_text(), LAYOUT)


if __name__ == '__main__': unittest.main()
