"""Helper-side tests of the C05 modes of host_operations.py (docs/parity-campaign/C05-DESIGN.md section 2): the
mutating impairment modes `netem-set` and `netem-reset` under the one host lock, the lab-wide read `netem-show-all`,
the dry-run plan inside the apply review and the read-only `apply-plan`, the node actions `start-node` and
`stop-node`, the `nodes` option and the extra run flags, `capabilities`, and main()'s dispatch through one shared
locked() helper for exactly preview, run, netem-set and netem-reset.

Stdlib plus the manager module for one equality (LOCK_SENTENCE); no VM, no Docker: the subprocess runners are stubs
that record every argv, the shape of test_host_diagnostics.py's DiagnosticsHarness with a fake /proc tree."""
import contextlib
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import time
import unittest
from unittest.mock import patch

import app.host_operations as host_operations
from app.host_operations import HostOperations, digest

LAB = 'parity'; NODE = 'r1'; CONTAINER = 'clab-parity-r1'; OTHER = 'clab-parity-r2'
ID = hashlib.sha256(b'clab-parity-r1').hexdigest()
OTHER_ID = hashlib.sha256(b'clab-parity-r2').hexdigest()
PORTS = '{"22/tcp":[{"HostIp":"0.0.0.0","HostPort":"2201"}]}'
VALUES = json.loads((Path(__file__).parent / 'fixtures' / 'impairment_values.json').read_text())
BASE = VALUES['base']
# Fact F8: the dry run of a deployed lab with changes, in containerlab's own order.
DRY_RUN_DEPLOYED = {'dry-run': True, 'deployed-lab': False, 'added-nodes': ['r3'], 'deleted-nodes': None, 'recreated-nodes': ['r2'], 'started-nodes': None,
                    'added-links': ['r1:eth1 -- r2:eth1'], 'deleted-endpoints': None, 'restarted-nodes': ['r2', 'r1'], 'node-change-reasons': {'r2': 'config drift: Env', 'r1': 'added link'}}
DRY_RUN_UNDEPLOYED = {'dry-run': True, 'deployed-lab': True, 'lab-name': LAB, 'added-nodes': None, 'deleted-nodes': None, 'recreated-nodes': None, 'started-nodes': None,
                      'added-links': None, 'deleted-endpoints': None, 'restarted-nodes': None, 'node-change-reasons': None}
DRY_RUN_EMPTY = {'dry-run': True, 'deployed-lab': False, 'added-nodes': None, 'deleted-nodes': None, 'recreated-nodes': None, 'started-nodes': None,
                 'added-links': None, 'deleted-endpoints': None, 'restarted-nodes': None, 'node-change-reasons': None}
# Fact F13, captured live on this VM (containerlab 0.79.0, NO_COLOR=1): the INFO banner, a boxed ERROR, the sentence, the generic last line.
F13_STDERR = ('05:45:53 INFO Containerlab started version=0.79.0\n'
              '          \n'
              '   ERROR  \n'
              '          \n'
              '  Failed to read topology file: yaml: line 3: did not find expected node content                                      \n'
              '  Consult with release notes to see if any fields were changed/removed.                                               \n'
              '\n')
EMPTY_PLAN = {'deploys_lab': False, 'added': [], 'removed': [], 'recreated': [], 'started': [], 'restarted': [], 'links_added': [], 'endpoints_removed': [], 'reasons': {}}
HELP = {'deploy': '--name --cleanup --graceful --node-filter --max-workers --skip-post-deploy --dry-run --format help',
        'apply': '--name --cleanup --graceful --node-filter --max-workers --skip-post-deploy --dry-run --format help',
        'redeploy': '--name --cleanup --graceful --max-workers --skip-post-deploy --keep-mgmt-net help',
        'destroy': '--name --cleanup --graceful --node-filter --max-workers --keep-mgmt-net help',
        'save': '--name --node-filter help', 'inspect': '--name --format help',
        'start': '--name --node help', 'stop': '--name --node help', 'restart': '--name --node help', 'tools': '--delay --jitter --loss --rate --corruption help'}


def inspect_line(id=ID, pid=4242, status='running', health='healthy', lab=LAB, node=NODE, kind='ceos', topo='', ports=PORTS, network_mode='clab'):
    return '\t'.join((id, str(pid), status, '2026-10-23T01:02:03.456789Z', health, lab, node, kind, topo, ports, network_mode)) + '\n'


class LifecycleHarness(unittest.TestCase):
    """A helper on a temporary trusted root with a stub Docker client, two deployed devices of lab `parity`, a
    bindable /proc task for r1 and recorded argv of every runner."""
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)
        self.docker = self.root / 'docker'; self.docker.write_text('#!/bin/sh\n'); self.docker.chmod(0o755)
        self.clab = '/usr/bin/containerlab'
        self.calls = []; self.probes = []; self.merged = []
        self.lab_dir = self.root / LAB; self.lab_dir.mkdir(); self.topo = self.lab_dir / 'parity.clab.yml'
        self.topo.write_text('name: parity\ntopology:\n  nodes:\n    r1: {kind: ceos}\n    r2: {kind: ceos}\n  links:\n    - endpoints: [r1:eth1, r2:eth1]\n')
        self.help_texts = dict(HELP); self.missing = set()
        self.rows = {LAB: [dict(name=CONTAINER, lab_name=LAB, state='running', container_id=ID, absLabPath=str(self.topo)),
                           dict(name=OTHER, lab_name=LAB, state='running', container_id=OTHER_ID, absLabPath=str(self.topo))]}
        self.containers = {CONTAINER: self.line(), OTHER: self.line(id=OTHER_ID, pid=4343, node='r2')}
        self.netem = {CONTAINER: None, OTHER: [{'interface': 'eth1', 'delay': '20ms', 'jitter': '5ms', 'packet_loss': 1.5, 'rate': 1000, 'corruption': 0.5}]}
        self.netem_answer = (0, '', ''); self.dry_run_answer = (0, json.dumps(DRY_RUN_DEPLOYED), '05:45:53 INFO Containerlab started version=0.79.0\n')
        self.version_output = (0, '0.79.0\n')
        def run(argv, **bounds):
            self.calls.append((argv, bounds))
            if '--help' in argv: return (1, '') if argv[1] in self.missing else (0, self.help_texts.get(argv[1], ''))
            if argv[:4] == [self.clab, 'tools', 'netem', 'show']: return 0, json.dumps({argv[5]: self.netem.get(argv[5])})
            if argv[1:2] == ['inspect']: return 0, json.dumps(self.rows)
            if argv == [self.clab, 'version', '--short']: return self.version_output
            return 1, ''
        def probe(argv, timeout):
            self.probes.append((argv, timeout))
            if argv[1:5] == ['inspect', '--type', 'container', '--format']:
                line = self.containers.get(argv[-1])
                return (0, line, '') if line else (1, '', 'Error response from daemon: No such container: ' + argv[-1])
            if argv[:4] == [self.clab, 'tools', 'netem', 'set'] or argv[:4] == [self.clab, 'tools', 'netem', 'reset']: return self.netem_answer
            if argv[:3] == [self.clab, 'deploy', '--dry-run']: return self.dry_run_answer
            raise AssertionError('unexpected probe ' + ' '.join(argv))
        def run_merged(argv, **bounds):
            self.merged.append((argv, bounds)); return 0, b''
        self.patch = patch.object(host_operations, 'DOCKER', str(self.docker)); self.patch.start()
        self.host = HostOperations(dict(clab=self.clab, git='/usr/bin/git', roots=[str(self.root)], projects=str(self.root), network=False), run, probe, run_merged)
        self.host.proc = str(self.root / 'proc')
        self.proc_tree()

    def tearDown(self): self.patch.stop(); self.tmp.cleanup()

    def line(self, **fields): return inspect_line(**{'topo': str(self.topo), **fields})

    def proc_tree(self, pid=4242, cgroup='0::/system.slice/docker-' + ID + '.scope\n', host=False):
        own = self.root / 'proc' / '1' / 'ns' / 'net'
        if not own.exists(): own.parent.mkdir(parents=True); own.write_text('net:[4026531840]')
        folder = self.root / 'proc' / str(pid)
        if folder.exists(): shutil.rmtree(folder)
        (folder / 'net').mkdir(parents=True); (folder / 'ns').mkdir()
        (folder / 'cgroup').write_text(cgroup); (folder / 'net' / 'dev').write_text('')
        if host: os.link(own, folder / 'ns' / 'net')
        else: (folder / 'ns' / 'net').write_text('net:[4026532555]')
        return folder

    def netem_request(self, mode='netem-set', values=None, expected_id=ID, **selector):
        options = {'node': NODE, 'container': CONTAINER, 'interface': 'eth1', **selector}
        if mode == 'netem-set': options.update(BASE); options.update(values or {})
        req = {'mode': mode, 'name': LAB, 'options': options, 'expected_id': expected_id}
        return {**req, 'digest': digest(req)}

    def lifecycle(self, action, **options): return dict(action=action, name=LAB, path=str(self.topo), options=options)

    def containerlab_calls(self):
        """Every containerlab command that ran (help and version probes left out): the stub `run` and `probe` argv."""
        return [argv for argv, _ in self.calls if '--help' not in argv and argv != [self.clab, 'version', '--short']] + [argv for argv, _ in self.probes if argv[0] == self.clab]

    def nothing_ran(self, message='a refused request runs nothing'):
        self.assertEqual((self.containerlab_calls(), self.merged), ([], []), message)


class NetemSetTests(LifecycleHarness):
    def test_argv_carries_the_bound_container_the_interface_and_all_five_flags(self):
        result = self.host.netem_set(self.netem_request())
        argv, timeout = self.probes[-1]
        self.assertEqual(argv, [self.clab, 'tools', 'netem', 'set', '-n', CONTAINER, '-i', 'eth1', '--delay', '20ms', '--jitter', '5ms', '--loss', '1.5', '--rate', '1000', '--corruption', '0.5'])
        self.assertEqual(timeout, host_operations.NETEM_TIMEOUT); self.assertEqual(host_operations.NETEM_TIMEOUT, 15)
        self.assertEqual(argv[:5], [self.clab, 'tools', 'netem', 'set', '-n'], 'nothing variable at argv[0..4]')
        self.assertEqual([a for a, _ in self.calls if a[:4] == [self.clab, 'tools', 'netem', 'show']], [[self.clab, 'tools', 'netem', 'show', '-n', CONTAINER, '-f', 'json']], 'one show after the set')
        self.assertEqual(result, {'facts': self.host.container_of({'node': NODE, 'container': CONTAINER}, LAB), 'impairments': []})
        self.netem[CONTAINER] = [{'interface': 'eth1', 'delay': '20ms', 'jitter': '5ms', 'packet_loss': 1.5, 'rate': 1000, 'corruption': 0.5}]
        self.assertEqual(self.host.netem_set(self.netem_request())['impairments'], [{'interface': 'eth1', 'delay': '20ms', 'jitter': '5ms', 'loss': 1.5, 'rate': 1000, 'corruption': 0.5}], 'the rows after the change')

    def test_every_accepted_row_of_the_shared_table_renders_its_argv_text(self):
        for case in VALUES['accepted']:
            with self.subTest(case=case['name']):
                self.probes.clear()
                self.host.netem_set(self.netem_request(values=case['values']))
                argv = self.probes[-1][0]
                self.assertEqual(dict(zip(argv[8::2], argv[9::2])), {'--' + k: v for k, v in case['argv'].items()})
                for value in (argv[13], argv[15], argv[17]): self.assertNotIn('e', value, 'a percentage or a rate is plain decimal text, never an exponent')

    def test_every_refused_row_of_the_shared_table_is_the_sentence_and_runs_nothing(self):
        for case in VALUES['refused']:
            with self.subTest(case=case['name']):
                with self.assertRaises(ValueError) as caught: self.host.netem_set(self.netem_request(values=case['values']))
                self.assertEqual(str(caught.exception), VALUES['sentences'][case['problem']])
        self.nothing_ran()
        self.assertEqual(set(VALUES['sentences']), {'time', 'jitter', 'percent', 'rate', 'zero'})
        self.assertTrue(any(c['values'] == {'delay': '61s'} for c in VALUES['refused']) and any(c['values'] == {'jitter': '61s'} for c in VALUES['refused']), 'both durations are limited')

    def test_the_request_shape_and_the_digest_are_checked_before_anything_runs(self):
        good = self.netem_request()
        bad = [{**good, 'options': {k: v for k, v in good['options'].items() if k != 'rate'}},            # a missing key
               {**good, 'options': {**good['options'], 'queue': 'pfifo'}},                                   # a ninth key
               {**good, 'options': [NODE, CONTAINER]}, {**good, 'options': None},
               {k: v for k, v in good.items() if k != 'digest'}, {**good, 'digest': ''}, {**good, 'digest': 'x' * 64}, {**good, 'digest': None},
               {**good, 'options': {**good['options'], 'delay': '30ms'}},                                   # a digest over different options
               {**good, 'name': 'other'}, {**good, 'mode': 'netem-reset'},                                   # mode and name are bound too
               {**good, 'extra': True},                                                                      # a key the digest does not cover
               {k: v for k, v in good.items() if k != 'expected_id'}, {**good, 'expected_id': ID[:63]}, {**good, 'expected_id': ID.upper()},
               {**good, 'expected_id': None}, {**good, 'expected_id': OTHER_ID}]
        for req in bad:
            with self.assertRaises(ValueError, msg=json.dumps(req)[:200]): self.host.netem_set(req)
        self.nothing_ran()
        with self.assertRaisesRegex(ValueError, 'Unsupported impairment options'): self.host.netem_set(bad[0])
        with self.assertRaisesRegex(ValueError, 'Unsupported impairment options'): self.host.netem_set(bad[1])
        with self.assertRaisesRegex(ValueError, 'Review the impairment again'): self.host.netem_set(bad[4])
        with self.assertRaisesRegex(ValueError, 'Review the impairment again'): self.host.netem_set(bad[8])
        with self.assertRaisesRegex(ValueError, 'Review the impairment again'): self.host.netem_set(bad[11])
        with self.assertRaisesRegex(ValueError, 'container changed since you opened'): self.host.netem_set(bad[12])
        with self.assertRaisesRegex(ValueError, 'container changed since you opened'): self.host.netem_set(bad[13])
        self.assertEqual(self.probes, [], 'not even the container is inspected for a malformed request')
        # The digest the manager must compute: the helper's own digest() over exactly these four keys.
        self.assertEqual(good['digest'], digest({'mode': 'netem-set', 'name': LAB, 'options': good['options'], 'expected_id': ID}))

    def test_an_expected_id_that_is_not_the_inspected_id_is_the_reopen_sentence(self):
        # The drawer showed one container; a redeploy since then recreated it: the change never reaches the new one.
        with self.assertRaises(ValueError) as caught: self.host.netem_set(self.netem_request(expected_id=OTHER_ID))
        self.assertEqual(str(caught.exception), "The device's container changed since you opened this section; reopen it and apply again.")
        self.assertEqual(len(self.probes), 1, 'the one docker inspect'); self.nothing_ran()

    def test_management_and_malformed_interfaces_are_refused_before_the_container_is_inspected(self):
        for interface, sentence in (('eth0', 'The management interface eth0 cannot be impaired: the manager reaches the device through it.'), ('lo', 'lo cannot be impaired.'),
                                    ('e' * 16, 'Choose an interface by its literal name.'), ('eth1;x', 'Choose an interface by its literal name.'), ('', 'Choose an interface by its literal name.'),
                                    ('-i', 'Choose an interface by its literal name.'), ('eth 1', 'Choose an interface by its literal name.'), (None, 'Choose an interface by its literal name.'), (['eth1'], 'Choose an interface by its literal name.')):
            with self.assertRaises(ValueError, msg=repr(interface)) as caught: self.host.netem_set(self.netem_request(interface=interface))
            self.assertEqual(str(caught.exception), sentence)
            with self.assertRaises(ValueError, msg=repr(interface)): self.host.netem_reset(self.netem_request('netem-reset', interface=interface))
        self.assertEqual(self.probes, []); self.nothing_ran()
        for interface in ('e' * 15, 'Ethernet1', 'eth1.100', 'ge-0_0_0', 'et_0.0'):
            self.host.netem_set(self.netem_request(interface=interface))

    def test_a_device_that_is_not_running_or_not_there_is_refused(self):
        for status in ('exited', 'created', 'paused', 'restarting', 'dead', ''):
            self.containers[CONTAINER] = self.line(status=status)
            with self.assertRaisesRegex(ValueError, 'is not running; impairments exist only on a running device', msg=status): self.host.netem_set(self.netem_request())
        del self.containers[CONTAINER]
        with self.assertRaisesRegex(ValueError, 'is not running; impairments exist only on a running device'): self.host.netem_set(self.netem_request())
        with self.assertRaisesRegex(ValueError, 'is not running; impairments exist only on a running device'): self.host.netem_reset(self.netem_request('netem-reset'))
        self.nothing_ran()

    def test_another_lab_s_container_and_a_label_mismatch_are_refused(self):
        self.containers[CONTAINER] = self.line(lab='other')
        with self.assertRaisesRegex(ValueError, 'does not belong to lab parity'): self.host.netem_set(self.netem_request())
        self.containers[CONTAINER] = self.line(node='r2')
        with self.assertRaisesRegex(ValueError, 'does not belong to lab parity'): self.host.netem_reset(self.netem_request('netem-reset'))
        self.containers[CONTAINER] = self.line(topo='/home/other/parity.clab.yml')
        with self.assertRaisesRegex(ValueError, 'outside the trusted lab roots'): self.host.netem_set(self.netem_request())
        with self.assertRaises(ValueError): self.host.netem_set(self.netem_request(container='clab-other-r1'))
        self.nothing_ran()

    def test_host_and_shared_network_modes_and_an_unreadable_mode_refuse(self):
        cases = ((self.line(network_mode='host'), "This device shares the VM's own network; its interfaces are the VM's and cannot be impaired."),
                 (self.line(network_mode='container:abc'), "This device shares another container's network; its interfaces are not its own and cannot be impaired."),
                 (self.line(network_mode='container:' + OTHER_ID), "This device shares another container's network; its interfaces are not its own and cannot be impaired."),
                 (self.line(network_mode=''), "The manager could not read this device's network mode; try again in a moment."),
                 (self.line().rstrip('\n').rsplit('\t', 1)[0] + '\n', 'Docker on the VM returned an unusable container identity.'))   # the field missing: a ten-field line
        for line, sentence in cases:
            self.containers[CONTAINER] = line
            with self.assertRaises(ValueError, msg=sentence) as caught: self.host.netem_set(self.netem_request())
            self.assertEqual(str(caught.exception), sentence)
        self.nothing_ran()
        for mode in ('clab', 'bridge', 'none', 'my-mgmt', 'host-like'):   # a Docker network name, however it is spelled, is the device's own
            self.containers[CONTAINER] = self.line(network_mode=mode); self.host.netem_set(self.netem_request())

    def test_the_namespace_check_is_tri_state_and_unknown_refuses(self):
        self.proc_tree(host=True)
        with self.assertRaisesRegex(ValueError, "shares the VM's own network"): self.host.netem_set(self.netem_request())
        self.proc_tree(cgroup='0::/system.slice/docker-' + OTHER_ID + '.scope\n')
        with self.assertRaisesRegex(ValueError, "could not bind this device's network namespace"): self.host.netem_set(self.netem_request())
        self.proc_tree(); self.containers[CONTAINER] = self.line(pid=0)
        with self.assertRaisesRegex(ValueError, "could not bind this device's network namespace"): self.host.netem_set(self.netem_request())
        self.containers[CONTAINER] = self.line(pid=9999)   # no such task
        with self.assertRaisesRegex(ValueError, "could not bind this device's network namespace"): self.host.netem_set(self.netem_request())
        self.containers[CONTAINER] = self.line()
        with patch.object(host_operations.os, 'stat', side_effect=OSError(13, 'denied')):
            self.assertIsNone(self.host.in_host_network(os.open(self.root / 'proc' / '4242', os.O_RDONLY | os.O_DIRECTORY)), 'an OSError is unknown, not "not host"')
            with self.assertRaisesRegex(ValueError, "could not bind this device's network namespace"): self.host.netem_set(self.netem_request())
        self.nothing_ran()
        self.assertIs(self.host.network_separate(self.host.container_of({'node': NODE, 'container': CONTAINER}, LAB)), True)
        self.proc_tree(host=True); self.assertIs(self.host.network_separate(self.host.container_of({'node': NODE, 'container': CONTAINER}, LAB)), False)
        self.proc_tree(cgroup='x\n'); self.assertIsNone(self.host.network_separate(self.host.container_of({'node': NODE, 'container': CONTAINER}, LAB)))
        # The C03 counter sample keeps its own answers on the same binding.
        self.proc_tree(); self.assertIsInstance(self.host.counters({'pid': 4242, 'id': ID}, ['eth0']), dict)
        self.proc_tree(host=True); self.assertEqual(self.host.counters({'pid': 4242, 'id': ID}, ['eth0']), 'host')

    def test_containerlab_s_refusal_becomes_the_sentence(self):
        self.netem_answer = (1, '', '05:50:00 ERRO Link not found.\n')
        with self.assertRaises(ValueError) as caught: self.host.netem_set(self.netem_request(interface='eth7'))
        self.assertEqual(str(caught.exception), 'eth7 is not an interface of this device right now.')
        self.netem_answer = (1, '', 'Jitter cannot be set without setting delay.\n')
        with self.assertRaises(ValueError) as caught: self.host.netem_set(self.netem_request())
        self.assertEqual(str(caught.exception), 'Containerlab on the VM refused the impairment: Jitter cannot be set without setting delay.')
        self.netem_answer = (1, '', F13_STDERR.replace('Failed to read topology file: yaml: line 3: did not find expected node content', 'Packet loss must be in the range between 0 and 100.'))
        with self.assertRaisesRegex(ValueError, 'refused the impairment: Packet loss must be in the range'): self.host.netem_set(self.netem_request())
        self.netem_answer = (1, '', 'x' * 500)
        with self.assertRaises(ValueError) as caught: self.host.netem_set(self.netem_request())
        self.assertEqual(len(str(caught.exception)), len('Containerlab on the VM refused the impairment: ') + 200)
        self.assertEqual([a for a, _ in self.calls if a[:4] == [self.clab, 'tools', 'netem', 'show']], [], 'no read-back after a refusal')


class NetemResetTests(LifecycleHarness):
    def test_reset_runs_only_when_the_interface_has_a_row(self):
        result = self.host.netem_reset(self.netem_request('netem-reset'))
        self.assertEqual(result, {'facts': self.host.container_of({'node': NODE, 'container': CONTAINER}, LAB), 'changed': False, 'impairments': []})
        self.assertEqual([a for a, _ in self.probes if a[0] == self.clab], [], 'no reset argv for an interface without a row (fact F7)')
        self.netem[CONTAINER] = [{'interface': 'eth2', 'delay': '1ms'}]
        self.assertEqual(self.host.netem_reset(self.netem_request('netem-reset'))['changed'], False, 'another interface\'s row is not this one')
        self.netem[CONTAINER] = [{'interface': 'eth1', 'delay': '20ms', 'jitter': '5ms', 'packet_loss': 1.5, 'rate': 1000, 'corruption': 0.5}]
        self.calls.clear(); self.probes.clear()
        result = self.host.netem_reset(self.netem_request('netem-reset'))
        self.assertEqual([a for a, _ in self.probes if a[0] == self.clab], [[self.clab, 'tools', 'netem', 'reset', '-n', CONTAINER, '-i', 'eth1']])
        self.assertEqual(self.probes[-1][1], host_operations.NETEM_TIMEOUT)
        self.assertEqual([a for a, _ in self.calls if a[:4] == [self.clab, 'tools', 'netem', 'show']], [[self.clab, 'tools', 'netem', 'show', '-n', CONTAINER, '-f', 'json']] * 2, 'one show before and one after the reset')
        self.assertEqual((result['changed'], result['impairments'], result['facts']['id']), (True, [{'interface': 'eth1', 'delay': '20ms', 'jitter': '5ms', 'loss': 1.5, 'rate': 1000, 'corruption': 0.5}], ID))

    def test_reset_takes_exactly_three_option_keys_and_a_failure_is_the_sentence(self):
        for options in ({'node': NODE, 'container': CONTAINER}, {'node': NODE, 'container': CONTAINER, 'interface': 'eth1', 'delay': '0ms'}):
            req = {'mode': 'netem-reset', 'name': LAB, 'options': options, 'expected_id': ID}; req['digest'] = digest(req)
            with self.assertRaisesRegex(ValueError, 'Unsupported impairment options', msg=repr(options)): self.host.netem_reset(req)
        with self.assertRaisesRegex(ValueError, 'Review the impairment again'): self.host.netem_reset({**self.netem_request('netem-reset'), 'digest': 'x' * 64})
        with self.assertRaisesRegex(ValueError, 'container changed since you opened'): self.host.netem_reset(self.netem_request('netem-reset', expected_id=OTHER_ID))
        self.nothing_ran()
        self.netem[CONTAINER] = [{'interface': 'eth1', 'delay': '20ms'}]; self.netem_answer = (1, '', 'Netlink receive: invalid argument.\n')
        with self.assertRaises(ValueError) as caught: self.host.netem_reset(self.netem_request('netem-reset'))
        self.assertEqual(str(caught.exception), 'Containerlab on the VM could not reset the impairment on eth1.')
        self.host.run = lambda argv, **bounds: (0, 'not json')
        with self.assertRaisesRegex(ValueError, 'did not show the impairments'): self.host.netem_reset(self.netem_request('netem-reset'))


class ImpairmentRowAliasTests(unittest.TestCase):
    def test_a_vm_interface_printed_with_its_nos_name_is_split_into_interface_and_alias(self):
        rows = host_operations.impairment_rows([
            {'interface': 'eth1 (ge-0/0/0)', 'delay': '20ms', 'jitter': '0s', 'packet_loss': 0, 'rate': 0, 'corruption': 0},
            {'interface': 'eth2 (ge-0/0/1)'}, {'interface': 'eth3', 'delay': '1ms'}, {'interface': 'odd (name'}, {'interface': ' (x)'}])
        self.assertEqual([(r['interface'], r.get('alias')) for r in rows],
                         [('eth1', 'ge-0/0/0'), ('eth2', 'ge-0/0/1'), ('eth3', None), ('odd (name', None)])
        self.assertEqual(rows[0]['delay'], '20ms'); self.assertEqual(rows[0]['loss'], 0)


class NetemShowAllTests(LifecycleHarness):
    def pairs(self, count):
        pairs = [{'node': 'r%d' % i, 'container': 'clab-parity-r%d' % i} for i in range(1, count + 1)]
        for pair in pairs:
            self.containers.setdefault(pair['container'], self.line(id=hashlib.sha256(pair['container'].encode()).hexdigest(), node=pair['node']))
        return pairs

    def test_reads_each_bound_pair_and_answers_rows_per_device(self):
        result = self.host.netem_show_all(LAB, {'nodes': [{'node': NODE, 'container': CONTAINER}, {'node': 'r2', 'container': OTHER}]})
        self.assertEqual(result, {'complete': True, 'devices': [
            {'node': NODE, 'container': CONTAINER, 'present': True, 'id': ID, 'impairments': []},
            {'node': 'r2', 'container': OTHER, 'present': True, 'id': OTHER_ID, 'impairments': [{'interface': 'eth1', 'delay': '20ms', 'jitter': '5ms', 'loss': 1.5, 'rate': 1000, 'corruption': 0.5}]}]})
        self.assertEqual([a[-1] for a, _ in self.probes], [CONTAINER, OTHER], 'one docker inspect per pair')
        self.assertEqual([a for a, _ in self.calls if a[:4] == [self.clab, 'tools', 'netem', 'show']], [[self.clab, 'tools', 'netem', 'show', '-n', c, '-f', 'json'] for c in (CONTAINER, OTHER)])

    def test_stopped_and_absent_devices_answer_an_empty_list_without_a_show(self):
        self.containers[CONTAINER] = self.line(status='exited', pid=0); del self.containers[OTHER]
        result = self.host.netem_show_all(LAB, {'nodes': [{'node': NODE, 'container': CONTAINER}, {'node': 'r2', 'container': OTHER}]})
        self.assertEqual(result['devices'], [{'node': NODE, 'container': CONTAINER, 'present': True, 'id': ID, 'impairments': []}, {'node': 'r2', 'container': OTHER, 'present': False, 'id': '', 'impairments': []}])
        self.assertEqual([a for a, _ in self.calls if a[:4] == [self.clab, 'tools', 'netem', 'show']], [])

    def test_one_to_sixty_four_pairs_each_well_formed(self):
        self.assertEqual(len(self.host.netem_show_all(LAB, {'nodes': self.pairs(64)})['devices']), 64)
        self.calls.clear(); self.probes.clear()
        for options in ({'nodes': self.pairs(65)}, {'nodes': []}, {'nodes': 'r1'}, {'nodes': None}):
            with self.assertRaisesRegex(ValueError, 'Name 1 to 64 devices', msg=repr(options)[:60]): self.host.netem_show_all(LAB, options)
        for options in ({}, {'nodes': [{'node': NODE, 'container': CONTAINER}], 'interface': 'eth1'}, {'pairs': []}, [], None):
            with self.assertRaisesRegex(ValueError, 'Unsupported impairment options', msg=repr(options)[:60]): self.host.netem_show_all(LAB, options)
        for pair in ({'node': NODE}, {'node': NODE, 'container': CONTAINER, 'id': ID}, [NODE, CONTAINER], 'r1', {'node': 'r1,r2', 'container': CONTAINER}, {'node': NODE, 'container': 'clab-other-r1'}):
            with self.assertRaises(ValueError, msg=repr(pair)): self.host.netem_show_all(LAB, {'nodes': [{'node': 'r2', 'container': OTHER}, pair]})
        with self.assertRaisesRegex(ValueError, 'literal lab'): self.host.netem_show_all('lab;id', {'nodes': [{'node': NODE, 'container': CONTAINER}]})
        self.assertEqual(self.probes, [], 'a bad pair anywhere in the list fails the call before any device is read'); self.nothing_ran()

    def test_a_pair_whose_binding_fails_fails_the_whole_call(self):
        self.containers[OTHER] = self.line(id=OTHER_ID, node='r2', lab='other')
        with self.assertRaisesRegex(ValueError, 'does not belong to lab parity'):
            self.host.netem_show_all(LAB, {'nodes': [{'node': NODE, 'container': CONTAINER}, {'node': 'r2', 'container': OTHER}]})

    def test_one_devices_failed_show_comes_back_unread_and_the_rest_are_read(self):
        real = self.host.netem_rows
        def rows(container):
            if container == OTHER: raise ValueError('Containerlab on the VM refused the impairment: boom')
            return real(container)
        with patch.object(self.host, 'netem_rows', rows):
            result = self.host.netem_show_all(LAB, {'nodes': [{'node': 'r2', 'container': OTHER}, {'node': NODE, 'container': CONTAINER}]})
        self.assertEqual(result['complete'], False)
        self.assertEqual(result['devices'], [{'node': 'r2', 'container': OTHER, 'present': True, 'unread': True},
                                             {'node': NODE, 'container': CONTAINER, 'present': True, 'id': ID, 'impairments': []}])
        self.assertEqual([a[-1] for a, _ in self.probes], [OTHER, CONTAINER], 'both pairs were bound; only the failed show is unread')

    def test_the_deadline_returns_the_rest_as_unread(self):
        clock = iter([100.0, 100.0, 170.0, 170.0])   # started, r1 checked in time, r2 and r3 past the deadline
        with patch.object(host_operations.time, 'monotonic', lambda: next(clock)):
            result = self.host.netem_show_all(LAB, {'nodes': [{'node': NODE, 'container': CONTAINER}, {'node': 'r2', 'container': OTHER}, {'node': 'r3', 'container': 'clab-parity-r3'}]})
        self.assertEqual(result['complete'], False)
        self.assertEqual(result['devices'][0]['impairments'], [])
        self.assertEqual(result['devices'][1:], [{'node': 'r2', 'container': OTHER, 'unread': True}, {'node': 'r3', 'container': 'clab-parity-r3', 'unread': True}])
        self.assertEqual([a[-1] for a, _ in self.probes], [CONTAINER], 'unread pairs are not inspected')
        self.assertEqual(host_operations.SHOW_ALL_DEADLINE, 60)


class ApplyPlanTests(LifecycleHarness):
    def test_apply_plan_reduces_the_three_live_shapes_sorted_and_bounded(self):
        self.assertEqual(host_operations.apply_plan(DRY_RUN_DEPLOYED), {'deploys_lab': False, 'added': ['r3'], 'removed': [], 'recreated': ['r2'], 'started': [], 'restarted': ['r1', 'r2'],
                                                                           'links_added': ['r1:eth1 -- r2:eth1'], 'endpoints_removed': [], 'reasons': {'r1': 'added link', 'r2': 'config drift: Env'}})
        self.assertEqual(host_operations.apply_plan(DRY_RUN_UNDEPLOYED), {**EMPTY_PLAN, 'deploys_lab': True})
        self.assertEqual(host_operations.apply_plan(DRY_RUN_EMPTY), EMPTY_PLAN)
        self.assertEqual(host_operations.apply_plan({}), EMPTY_PLAN); self.assertEqual(host_operations.apply_plan([]), EMPTY_PLAN); self.assertEqual(host_operations.apply_plan(None), EMPTY_PLAN)
        junk = {'deployed-lab': 'true', 'added-nodes': ['b', 'a', 5, '', None, 'x' * 300], 'started-nodes': 'r1', 'node-change-reasons': {'z': 'r' * 300, 'a': 1, 3: 'x', 'b': 'why'}, 'extra': ['dropped']}
        plan = host_operations.apply_plan(junk)
        self.assertEqual((plan['deploys_lab'], plan['added'], plan['started'], set(plan)), (False, ['a', 'b', 'x' * 120], [], set(EMPTY_PLAN)))
        self.assertEqual(plan['reasons'], {'b': 'why', 'z': 'r' * 200}); self.assertEqual(list(plan['reasons']), ['b', 'z'])
        self.assertEqual(len(host_operations.apply_plan({'added-nodes': ['n%04d' % i for i in range(300)]})['added']), host_operations.PLAN_LIST_LIMIT)
        shuffled = {**DRY_RUN_DEPLOYED, 'restarted-nodes': ['r1', 'r2'], 'node-change-reasons': {'r1': 'added link', 'r2': 'config drift: Env'}}
        self.assertEqual(digest(host_operations.apply_plan(shuffled)), digest(host_operations.apply_plan(DRY_RUN_DEPLOYED)), 'order alone never changes the digest')
        self.assertTrue(host_operations.plan_changes(host_operations.apply_plan(DRY_RUN_DEPLOYED))); self.assertTrue(host_operations.plan_changes({**EMPTY_PLAN, 'deploys_lab': True}))
        self.assertFalse(host_operations.plan_changes(EMPTY_PLAN)); self.assertFalse(host_operations.plan_changes(None))

    def test_error_line_takes_the_sentence_after_the_boxed_error_never_the_banner(self):
        self.assertEqual(host_operations.error_line(F13_STDERR), 'Failed to read topology file: yaml: line 3: did not find expected node content')
        self.assertEqual(host_operations.error_line('05:45:53 INFO Containerlab started version=0.79.0\nERRO[0001] Link not found.\n'), 'ERRO[0001] Link not found.')
        self.assertEqual(host_operations.error_line('INFO banner\nsomething odd\n'), 'something odd', 'never the first line')
        self.assertEqual(host_operations.error_line('INFO banner\nConsult with release notes to see if any fields were changed/removed.\n'), 'Consult with release notes to see if any fields were changed/removed.', 'only when nothing better exists')
        self.assertEqual(host_operations.error_line('one line only\n'), 'one line only'); self.assertEqual(host_operations.error_line(''), ''); self.assertEqual(host_operations.error_line(None), '')
        self.assertEqual(host_operations.error_line('│ ERROR │\n\nboxed sentence\n'), 'boxed sentence')
        self.assertEqual(len(host_operations.error_line('INFO\nERROR\n' + 'x' * 400)), 300)

    def test_the_dry_run_argv_is_one_builder_and_always_carries_dry_run(self):
        argv = self.host.dry_run_argv(self.topo, LAB, self.help_texts['deploy'])
        self.assertEqual(argv, [self.clab, 'deploy', '--dry-run', '--format', 'json', '-t', str(self.topo), '--name', LAB])
        self.assertEqual(self.host.dry_run_argv(self.topo, LAB, '--dry-run only'), [self.clab, 'deploy', '--dry-run', '--format', 'json', '-t', str(self.topo)], '--name only when the deploy help has it')
        self.host.pending_plan(LAB, str(self.topo)); self.host.plan(self.lifecycle('apply'))
        dry_runs = [a for a, _ in self.probes if a[0] == self.clab]
        self.assertEqual(len(dry_runs), 2); self.assertEqual([a[:5] for a in dry_runs], [[self.clab, 'deploy', '--dry-run', '--format', 'json']] * 2)
        self.assertEqual([t for a, t in self.probes if a[0] == self.clab], [host_operations.APPLY_PLAN_TIMEOUT] * 2); self.assertEqual(host_operations.APPLY_PLAN_TIMEOUT, 60)
        source = Path(host_operations.__file__).read_text()
        self.assertEqual(source.count("'deploy', '--dry-run', '--format', 'json'"), 1, 'the one argv builder')
        self.assertEqual(source.count("'--dry-run'"), 3, "the builder, the help probe and the capability")
        self.assertNotIn("'--reconfigure'", source)

    def test_apply_plan_mode_is_read_only_and_answers_the_three_outcomes(self):
        self.assertEqual(self.host.pending_plan(LAB, str(self.topo)), {'plan': host_operations.apply_plan(DRY_RUN_DEPLOYED), 'failed': '', 'error': ''})
        self.assertEqual([a[1] for a, _ in self.calls], ['deploy'], 'the deploy help probe only: no inspect --all')
        self.assertEqual(self.probes, [([self.clab, 'deploy', '--dry-run', '--format', 'json', '-t', str(self.topo), '--name', LAB], 60)])
        self.dry_run_answer = (1, '', F13_STDERR)
        self.assertEqual(self.host.pending_plan(LAB, str(self.topo)), {'plan': None, 'failed': 'error', 'error': 'Failed to read topology file: yaml: line 3: did not find expected node content'})
        self.dry_run_answer = (0, 'a table, not json', '')
        self.assertEqual(self.host.pending_plan(LAB, str(self.topo))['failed'], 'error')
        self.dry_run_answer = (0, json.dumps(DRY_RUN_UNDEPLOYED), '')
        self.assertEqual(self.host.pending_plan(LAB, str(self.topo))['plan']['deploys_lab'], True)
        self.help_texts['deploy'] = '--name --format help'
        self.probes.clear()
        self.assertEqual(self.host.pending_plan(LAB, str(self.topo)), {'plan': None, 'failed': 'unsupported', 'error': ''})
        self.missing.add('deploy'); self.assertEqual(self.host.pending_plan(LAB, str(self.topo))['failed'], 'unsupported')
        self.assertEqual(self.probes, [], 'without --dry-run nothing is run')
        with self.assertRaisesRegex(ValueError, 'literal lab'): self.host.pending_plan('a b', str(self.topo))
        with self.assertRaisesRegex(ValueError, 'outside the trusted lab roots'): self.host.pending_plan(LAB, '/etc/containerlab/x.clab.yml')
        (self.lab_dir / 'notes.txt').write_text('x')
        with self.assertRaisesRegex(ValueError, 'Select the original lab YAML'): self.host.pending_plan(LAB, str(self.lab_dir / 'notes.txt'))
        with self.assertRaisesRegex(ValueError, 'no longer exists'): self.host.pending_plan(LAB, str(self.lab_dir / 'gone.clab.yml'))
        with self.assertRaisesRegex(ValueError, 'Invalid project path'): self.host.pending_plan(LAB, None)

    def test_the_plan_inside_the_apply_review_is_bound_into_the_digest(self):
        plan = self.host.plan(self.lifecycle('apply'))
        self.assertEqual((plan['plan'], plan['plan_failed']), (host_operations.apply_plan(DRY_RUN_DEPLOYED), ''))
        self.assertEqual(plan['argv'], [self.clab, 'apply', '-t', str(self.topo), '--name', LAB], 'the run itself is still apply')
        self.assertEqual([w for w in plan['warnings'] if 'could not plan' in w], [])
        self.dry_run_answer = (0, json.dumps(DRY_RUN_EMPTY), '')
        other = self.host.plan(self.lifecycle('apply'))
        self.assertEqual(other['argv'], plan['argv']); self.assertNotEqual(other['digest'], plan['digest'], 'a different live plan, the same argv: a different review')
        self.assertEqual(other['plan'], EMPTY_PLAN)
        # Run time: the plan is recomputed; a change since the review is the existing refusal, and nothing runs.
        req = {**self.lifecycle('apply'), 'digest': plan['digest']}
        with patch('app.host_operations.stream') as stream:
            with self.assertRaisesRegex(ValueError, 'The topology or deployment changed. Preview the operation again.'): self.host.execute(req, lambda _: None)
            stream.assert_not_called()
        self.dry_run_answer = (0, json.dumps(DRY_RUN_DEPLOYED), '')
        with patch('app.host_operations.stream', return_value=0) as stream:
            self.assertEqual(self.host.execute(req, lambda _: None)['exit_code'], 0)
            self.assertEqual(stream.call_args.args[0], plan['argv'])
        # Failure and absence of the dry run are inside the digest too; the warning carries the sentence.
        self.dry_run_answer = (1, '', F13_STDERR)
        failed = self.host.plan(self.lifecycle('apply'))
        self.assertEqual((failed['plan'], failed['plan_failed']), (None, 'error'))
        self.assertIn('containerlab could not plan this change: Failed to read topology file: yaml: line 3: did not find expected node content', failed['warnings'])
        self.help_texts['deploy'] = '--name help'
        unsupported = self.host.plan(self.lifecycle('apply'))
        self.assertEqual((unsupported['plan'], unsupported['plan_failed']), (None, 'unsupported')); self.assertEqual([w for w in unsupported['warnings'] if 'could not plan' in w], [])
        self.assertEqual(len({plan['digest'], other['digest'], failed['digest'], unsupported['digest']}), 4)
        # No other lifecycle action runs the dry run.
        self.probes.clear()
        for action in ('deploy', 'redeploy', 'destroy', 'start', 'stop', 'restart', 'save', 'inspect'):
            found = self.host.plan(self.lifecycle(action)); self.assertNotIn('plan', found, action); self.assertNotIn('plan_failed', found, action)
        self.assertEqual([a for a, _ in self.probes if a[0] == self.clab], [])


class NodeActionTests(LifecycleHarness):
    def selector(self, action, node=NODE, container=CONTAINER): return self.lifecycle(action, node=node, container=container)

    def test_start_and_stop_argv_follow_restart_with_the_command_of_the_action(self):
        self.rows[LAB][0]['state'] = 'exited'
        plan = self.host.plan(self.selector('start-node'))
        self.assertEqual(plan['argv'], [self.clab, 'start', '-t', str(self.topo), '--name', LAB, '--node', NODE]); self.assertEqual(plan['steps'], [])
        self.assertEqual(plan['affected'], [{'name': CONTAINER, 'id': ID, 'state': 'exited'}]); self.assertEqual((plan['node'], plan['container']), (NODE, CONTAINER))
        self.assertEqual(plan['warnings'], [], 'the start/restore warning belongs to restart alone')
        self.assertEqual([a for a, _ in self.calls if '--help' in a], [[self.clab, 'start', '--help']], 'the --node probe is on the start command')
        self.rows[LAB][0]['state'] = 'running'; self.calls.clear()
        plan = self.host.plan(self.selector('stop-node'))
        self.assertEqual(plan['argv'], [self.clab, 'stop', '-t', str(self.topo), '--name', LAB, '--node', NODE])
        self.assertEqual(plan['affected'], [{'name': CONTAINER, 'id': ID, 'state': 'running'}]); self.assertEqual(plan['warnings'], [])
        self.assertEqual([a for a, _ in self.calls if '--help' in a], [[self.clab, 'stop', '--help']])
        self.assertEqual(self.host.plan(self.selector('restart-node'))['argv'][1], 'restart')
        self.assertEqual(host_operations.NODE_ACTIONS, ('restart-node', 'start-node', 'stop-node'))
        with patch('app.host_operations.stream', return_value=0) as stream:
            req = {**self.selector('stop-node'), 'digest': plan['digest']}
            self.assertEqual(self.host.execute(req, lambda _: None)['exit_code'], 0)
            self.assertEqual(stream.call_args.args[0], plan['argv']); self.assertEqual(stream.call_args.args[1], str(self.lab_dir))

    def test_stop_of_a_stopped_device_and_start_of_a_running_one_are_refused(self):
        with self.assertRaises(ValueError) as caught: self.host.plan(self.selector('start-node'))
        self.assertEqual(str(caught.exception), 'Device clab-parity-r1 is already running.')
        for state in ('exited', 'created', 'paused', ''):
            self.rows[LAB][0]['state'] = state
            with self.assertRaises(ValueError, msg=state) as caught: self.host.plan(self.selector('stop-node'))
            self.assertEqual(str(caught.exception), 'Device clab-parity-r1 is ' + (state or 'not running') + '; there is nothing to stop.')
            self.assertEqual(self.host.plan(self.selector('start-node'))['argv'][1], 'start')
        with patch('app.host_operations.stream') as stream:
            with self.assertRaises(ValueError): self.host.execute({**self.selector('stop-node'), 'digest': 'x'}, lambda _: None)
            stream.assert_not_called()

    def test_the_digest_binds_the_state_so_a_change_between_review_and_run_is_refused(self):
        req = self.selector('stop-node'); req['digest'] = self.host.plan(req)['digest']
        for change in ({'container_id': 'recreated'}, {'state': 'exited'}, {'name': CONTAINER + '-x'}):
            original = dict(self.rows[LAB][0]); self.rows[LAB][0].update(change)
            with patch('app.host_operations.stream') as stream:
                with self.assertRaises(ValueError, msg=repr(change)): self.host.execute(req, lambda _: None)
                stream.assert_not_called()
            self.rows[LAB][0] = original
        self.rows[LAB][0]['state'] = 'exited'
        start = self.host.plan(self.selector('start-node')); self.rows[LAB][0]['state'] = 'paused'
        self.assertNotEqual(self.host.plan(self.selector('start-node'))['digest'], start['digest'])

    def test_the_node_probe_and_the_missing_command_per_action(self):
        for action in host_operations.NODE_ACTIONS:
            command = action[:-5]
            if action == 'start-node': self.rows[LAB][0]['state'] = 'exited'
            self.help_texts[command] = '--name help'
            with self.assertRaises(ValueError, msg=action) as caught: self.host.plan(self.selector(action))
            self.assertEqual(str(caught.exception), 'The installed Containerlab cannot ' + command + ' one device: its ' + command + ' command has no --node option. Upgrade containerlab on the VM.')
            self.assertFalse(self.host.capabilities()['actions'][action]['available'])
            self.assertTrue(self.host.capabilities()['actions'][command]['available'], 'the lab-wide command is still there')
            self.missing.add(command)
            with self.assertRaises(ValueError, msg=action) as caught: self.host.plan(self.selector(action))
            self.assertEqual(str(caught.exception), 'This Containerlab version does not support ' + command + '.')
            self.assertFalse(self.host.capabilities()['actions'][action]['available'])
            self.missing.discard(command); self.help_texts[command] = HELP[command]; self.rows[LAB][0]['state'] = 'running'
        self.assertEqual({k: v for k, v in self.host.capabilities()['actions'].items() if k.endswith('-node')}, {a: {'available': True} for a in host_operations.NODE_ACTIONS})

    def test_every_node_action_fails_closed_on_every_bad_selector_and_never_widens(self):
        bad = [{}, {'node': NODE}, {'container': CONTAINER}, {'node': '', 'container': CONTAINER}, {'node': None, 'container': CONTAINER}, {'node': [NODE], 'container': CONTAINER},
               {'node': 'r1,r2', 'container': CONTAINER}, {'node': '--node', 'container': CONTAINER}, {'node': '-r1', 'container': CONTAINER}, {'node': 'r1 r2', 'container': CONTAINER},
               {'node': NODE, 'container': OTHER}, {'node': NODE, 'container': [CONTAINER]}, {'node': NODE, 'container': CONTAINER, 'cleanup': True},
               {'node': NODE, 'container': CONTAINER, 'graceful': True}, {'node': NODE, 'container': CONTAINER, 'nodes': [NODE]}, {'node': NODE, 'container': CONTAINER, 'max_workers': 1},
               {'node': 'r9', 'container': 'clab-parity-r9'}, {'node': NODE, 'container': 'clab-other-r1'}, {'node': NODE, 'container': CONTAINER, 'extra': 1},
               {'node': 'switch', 'container': 'clab-parity-vjunos-switch'}, {'node': NODE, 'container': 'x-r1'}]
        self.rows[LAB][0]['state'] = 'exited'; self.rows[LAB][1]['state'] = 'exited'   # so start-node's own state check never masks a selector refusal
        with patch('app.host_operations.stream') as stream:
            for action in host_operations.NODE_ACTIONS:
                if action == 'stop-node': self.rows[LAB][0]['state'] = self.rows[LAB][1]['state'] = 'running'
                for options in bad:
                    with self.assertRaises(ValueError, msg=action + ' ' + repr(options)): self.host.plan(self.lifecycle(action, **options))
                    with self.assertRaises(ValueError, msg=action + ' ' + repr(options)): self.host.execute({**self.lifecycle(action, **options), 'digest': 'x'}, lambda _: None)
            stream.assert_not_called()
        for action in (*host_operations.LIFECYCLE, 'delete', 'inspect-all'):
            with self.assertRaisesRegex(ValueError, 'options'): self.host.plan(self.lifecycle(action, node=NODE, container=CONTAINER))
        self.assertEqual([a for a, _ in self.probes if a[0] == self.clab], [])


class OptionTests(LifecycleHarness):
    # `deployed` (campaign 2, the deployed save): revise only; its own contract is in test_revise_deployed.py.
    TABLE = {'nodes': ('deploy', 'destroy', 'save'), 'max_workers': ('deploy', 'redeploy', 'destroy'), 'skip_post_deploy': ('deploy', 'redeploy'), 'keep_mgmt_net': ('redeploy', 'destroy'), 'deployed': ('revise',)}
    SAMPLE = {'nodes': ['r1'], 'max_workers': 4, 'skip_post_deploy': True, 'keep_mgmt_net': True, 'deployed': True}

    def test_every_new_key_against_every_action_is_the_table(self):
        self.assertEqual(host_operations.OPTION_ACTIONS, self.TABLE)
        for key, value in self.SAMPLE.items():
            for action in (*host_operations.LIFECYCLE, *host_operations.NODE_ACTIONS, 'delete', 'inspect-all'):
                with self.subTest(key=key, action=action):
                    if action == 'deploy': self.rows = {}   # a partial deploy is only for a lab that is not deployed
                    else: self.rows = {LAB: [dict(name=CONTAINER, lab_name=LAB, state='running', container_id=ID, absLabPath=str(self.topo))]}
                    if action in self.TABLE[key]:
                        self.assertIn('--node-filter' if key == 'nodes' else '--' + key.replace('_', '-'), ' '.join(self.host.plan(self.lifecycle(action, **{key: value}))['argv']))
                    else:
                        with self.assertRaisesRegex(ValueError, 'Unsupported operation options'): self.host.plan(self.lifecycle(action, **{key: value}))
        # The old union is unchanged: cleanup and graceful are refused where they always were, accepted where they always were.
        self.rows = {LAB: [dict(name=CONTAINER, lab_name=LAB, state='running', container_id=ID, absLabPath=str(self.topo))]}
        with self.assertRaisesRegex(ValueError, 'Cleanup is only available'): self.host.plan(self.lifecycle('save', cleanup=True))
        self.assertIn('--cleanup', self.host.plan(self.lifecycle('destroy', cleanup=True))['argv'])

    def test_nodes_shapes_are_refused_before_anything_runs(self):
        for nodes in ('r1', ['r1,r2'], [], ['r%d' % i for i in range(65)], ['r1', 'r1'], ['eth0 '], [''], ['-r1'], [1], [None], ['r1', ['r2']], {'r1': True}, ['r' * 121], [' r1'], ['r1\n'], None, True):
            with self.assertRaises(ValueError, msg=repr(nodes)[:60]) as caught: self.host.plan(self.lifecycle('destroy', nodes=nodes))
            self.assertEqual(str(caught.exception), 'Choose devices by their literal topology node names.')
        self.nothing_ran()
        self.assertEqual(host_operations.NODE_FILTER_LIMIT, 64)
        self.rows[LAB].append(dict(name='clab-parity-r_1.a-b', lab_name=LAB, state='running', container_id='x', absLabPath=str(self.topo)))
        self.rows[LAB].append(dict(name='clab-parity-R1', lab_name=LAB, state='running', container_id='y', absLabPath=str(self.topo)))
        for nodes in (['r1'], ['r1', 'r2'], ['r_1.a-b'], ['R1']):
            self.assertEqual(self.host.plan(self.lifecycle('destroy', nodes=nodes))['argv'][-1], ','.join(nodes))

    def test_a_partial_deploy_is_only_for_a_lab_that_is_not_deployed(self):
        with self.assertRaises(ValueError) as caught: self.host.plan(self.lifecycle('deploy', nodes=['r1']))
        self.assertEqual(str(caught.exception), 'This lab is already deployed, so a deploy limited to chosen devices is not possible (containerlab would remove the devices left out). Use Apply topology changes to add the missing devices.')
        self.rows = {LAB: [dict(name=CONTAINER, lab_name=LAB, state='exited', container_id=ID, absLabPath=str(self.topo))]}
        with self.assertRaisesRegex(ValueError, 'already deployed'): self.host.plan(self.lifecycle('deploy', nodes=['r2']))
        self.rows = {'other': [dict(name='clab-other-r1', lab_name='other', state='running', container_id='o', absLabPath=str(self.root / 'o.clab.yml'))]}
        plan = self.host.plan(self.lifecycle('deploy', nodes=['r1', 'r2'], max_workers=1, skip_post_deploy=True))
        self.assertEqual(plan['argv'], [self.clab, 'deploy', '-t', str(self.topo), '--name', LAB, '--node-filter', 'r1,r2', '--max-workers', '1', '--skip-post-deploy'])
        self.assertEqual((plan['affected'], plan.get('kept')), ([], None), 'no deployed rows: nothing to split; membership is the manager\'s and containerlab\'s check (fact F10)')
        with self.assertRaisesRegex(ValueError, 'Clean up cannot be combined with chosen devices'): self.host.plan(self.lifecycle('deploy', nodes=['r1'], cleanup=True))
        self.help_texts['deploy'] = '--name --cleanup help'
        with self.assertRaisesRegex(ValueError, 'Installed command lacks --node-filter'): self.host.plan(self.lifecycle('deploy', nodes=['r1']))

    def test_nodes_on_destroy_and_save_must_name_deployed_devices_and_split_affected_from_kept(self):
        plan = self.host.plan(self.lifecycle('destroy', nodes=['r2']))
        self.assertEqual(plan['argv'], [self.clab, 'destroy', '-t', str(self.topo), '--name', LAB, '--node-filter', 'r2'])
        self.assertEqual(plan['affected'], [{'name': OTHER, 'id': OTHER_ID, 'state': 'running'}]); self.assertEqual(plan['kept'], [CONTAINER])
        whole = self.host.plan(self.lifecycle('destroy'))
        self.assertEqual(len(whole['affected']), 2); self.assertNotIn('kept', whole); self.assertNotEqual(whole['digest'], plan['digest'])
        save = self.host.plan(self.lifecycle('save', nodes=['r1', 'r2']))
        self.assertEqual(save['argv'][-2:], ['--node-filter', 'r1,r2']); self.assertEqual(len(save['affected']), 2); self.assertEqual(save['kept'], [])
        for action in ('destroy', 'save'):
            with self.assertRaises(ValueError, msg=action) as caught: self.host.plan(self.lifecycle(action, nodes=['r1', 'r9']))
            self.assertEqual(str(caught.exception), 'Device r9 is not deployed in lab parity. Refresh the lab list and review again.')
        with self.assertRaises(ValueError) as caught: self.host.plan(self.lifecycle('destroy', nodes=['r1'], cleanup=True))
        self.assertEqual(str(caught.exception), 'Clean up cannot be combined with chosen devices: containerlab would delete the whole lab folder, which the devices left running still use.')
        with patch('app.host_operations.stream') as stream:
            with self.assertRaises(ValueError): self.host.execute({**self.lifecycle('destroy', nodes=['r1'], cleanup=True), 'digest': 'x'}, lambda _: None)
            stream.assert_not_called()
        # `kept` is bound: a device that appears between review and run changes the review.
        req = {**self.lifecycle('destroy', nodes=['r2']), 'digest': plan['digest']}
        self.rows[LAB].append(dict(name='clab-parity-r3', lab_name=LAB, state='running', container_id='third', absLabPath=str(self.topo)))
        with patch('app.host_operations.stream') as stream:
            with self.assertRaisesRegex(ValueError, 'Preview the operation again'): self.host.execute(req, lambda _: None)
            stream.assert_not_called()
        self.help_texts['save'] = '--name help'
        with self.assertRaisesRegex(ValueError, 'Installed command lacks --node-filter'): self.host.plan(self.lifecycle('save', nodes=['r1']))

    def test_membership_uses_container_matches_in_an_empty_prefix_and_a_custom_prefix_lab(self):
        self.assertTrue(host_operations.container_matches('r1', LAB, 'r1')); self.assertTrue(host_operations.container_matches('parity-r1', LAB, 'r1'))
        self.assertTrue(host_operations.container_matches('clab-parity-r1', LAB, 'r1')); self.assertTrue(host_operations.container_matches('lab-parity-r1', LAB, 'r1'))
        for container in ('clab-parity-r10', 'clab-parity-vjunos-r1', 'xr1', 'clab-other-r1', 'r1 ', 'clab-parity-r1x', 'parity-vjunos-r1'):
            self.assertFalse(host_operations.container_matches(container, LAB, 'r1'), container)
        source = Path(host_operations.__file__).read_text()
        self.assertEqual(source.count('def container_matches('), 1); self.assertEqual(source.count('container_matches('), 3, 'the definition, node_selector and the nodes membership check')
        for prefix in ('', 'lab-parity-', 'parity-'):
            self.rows = {LAB: [dict(name=prefix + 'r1', lab_name=LAB, state='running', container_id='a', absLabPath=str(self.topo)),
                               dict(name=prefix + 'r2', lab_name=LAB, state='running', container_id='b', absLabPath=str(self.topo)),
                               dict(name=prefix + 'vjunos-r1', lab_name=LAB, state='running', container_id='c', absLabPath=str(self.topo))]}
            plan = self.host.plan(self.lifecycle('destroy', nodes=['r1']))
            self.assertEqual([a['id'] for a in plan['affected']], ['a'], prefix or 'empty prefix'); self.assertEqual(plan['kept'], [prefix + 'r2', prefix + 'vjunos-r1'])
            self.assertEqual([a['id'] for a in self.host.plan(self.lifecycle('save', nodes=['vjunos-r1']))['affected']], ['c'])
        self.rows = {LAB: [dict(name='r1', lab_name=LAB, state='running', container_id='a', absLabPath=str(self.topo)), dict(name='clab-parity-r1', lab_name=LAB, state='running', container_id='b', absLabPath=str(self.topo))]}
        with self.assertRaisesRegex(ValueError, 'Device r1 is not deployed'): self.host.plan(self.lifecycle('destroy', nodes=['r1']))   # two matches are not one

    def test_flags_follow_one_fixed_order_and_each_needs_its_help_flag(self):
        plan = self.host.plan(self.lifecycle('destroy', nodes=['r1'], keep_mgmt_net=True, graceful=True, max_workers=64))
        self.assertEqual(plan['argv'], [self.clab, 'destroy', '-t', str(self.topo), '--name', LAB, '--node-filter', 'r1', '--max-workers', '64', '--graceful', '--keep-mgmt-net'])
        plan = self.host.plan(self.lifecycle('redeploy', keep_mgmt_net=True, graceful=True, cleanup=True, skip_post_deploy=True, max_workers=2))
        self.assertEqual(plan['argv'], [self.clab, 'redeploy', '-t', str(self.topo), '--name', LAB, '--max-workers', '2', '--skip-post-deploy', '--cleanup', '--graceful', '--keep-mgmt-net'])
        self.assertEqual(self.host.plan(self.lifecycle('inspect'))['argv'], [self.clab, 'inspect', '-t', str(self.topo), '--name', LAB, '--format', 'json'])
        for flag, action in (('keep_mgmt_net', 'destroy'), ('max_workers', 'destroy'), ('skip_post_deploy', 'deploy'), ('max_workers', 'deploy'), ('keep_mgmt_net', 'redeploy'), ('skip_post_deploy', 'redeploy')):
            self.help_texts[action] = '--name --cleanup --graceful help'
            if action == 'deploy': self.rows = {}
            with self.assertRaisesRegex(ValueError, 'Installed command lacks --' + flag.replace('_', '-'), msg=flag + ' ' + action): self.host.plan(self.lifecycle(action, **{flag: self.SAMPLE[flag]}))
            self.help_texts[action] = HELP[action]
        for flag in ('skip_post_deploy', 'keep_mgmt_net'):
            for value in (1, 'yes', None, 'true'):
                with self.assertRaisesRegex(ValueError, 'Invalid boolean option', msg=flag + repr(value)): self.host.plan(self.lifecycle('redeploy', **{flag: value}))
        self.assertNotIn('--skip-post-deploy', self.host.plan(self.lifecycle('redeploy', skip_post_deploy=False))['argv'])

    def test_max_workers_is_a_whole_number_from_one_to_sixty_four(self):
        for value in (0, 65, -1, True, False, '4', 4.0, None, [4]):
            with self.assertRaises(ValueError, msg=repr(value)) as caught: self.host.plan(self.lifecycle('destroy', max_workers=value))
            self.assertEqual(str(caught.exception), 'Max workers must be a whole number from 1 to 64.')
        self.nothing_ran()
        self.assertEqual(host_operations.MAX_WORKERS_LIMIT, 64)
        for value in (1, 64):
            self.assertEqual(self.host.plan(self.lifecycle('destroy', max_workers=value))['argv'][-2:], ['--max-workers', str(value)])

    def test_the_redeploy_fallback_distributes_the_flags_over_its_two_steps(self):
        self.missing.add('redeploy')
        plan = self.host.plan(self.lifecycle('redeploy', keep_mgmt_net=True, graceful=True, cleanup=True, skip_post_deploy=True, max_workers=3))
        self.assertEqual(plan['steps'], [[self.clab, 'destroy', '-t', str(self.topo), '--name', LAB, '--max-workers', '3', '--cleanup', '--graceful', '--keep-mgmt-net'],
                                         [self.clab, 'deploy', '-t', str(self.topo), '--name', LAB, '--max-workers', '3', '--skip-post-deploy']])
        self.assertEqual(plan['argv'], [])
        caps = self.host.capabilities()['actions']['redeploy']
        self.assertEqual({k: caps[k] for k in ('fallback', 'node_filter', 'dry_run', 'skip_post_deploy', 'keep_mgmt_net', 'max_workers', 'cleanup', 'graceful')},
                         {'fallback': True, 'node_filter': False, 'dry_run': False, 'skip_post_deploy': True, 'keep_mgmt_net': True, 'max_workers': True, 'cleanup': True, 'graceful': True})
        self.help_texts['destroy'] = '--name --cleanup --graceful help'
        with self.assertRaisesRegex(ValueError, 'Installed destroy command lacks this option'): self.host.plan(self.lifecycle('redeploy', keep_mgmt_net=True))
        with self.assertRaisesRegex(ValueError, 'Installed destroy command lacks this option'): self.host.plan(self.lifecycle('redeploy', max_workers=3))
        self.help_texts['destroy'] = HELP['destroy']; self.help_texts['deploy'] = '--name --cleanup help'
        with self.assertRaisesRegex(ValueError, 'Installed deploy command lacks this option'): self.host.plan(self.lifecycle('redeploy', skip_post_deploy=True))
        with self.assertRaisesRegex(ValueError, 'Installed deploy command lacks this option'): self.host.plan(self.lifecycle('redeploy', max_workers=3))
        with self.assertRaisesRegex(ValueError, 'Unsupported operation options'): self.host.plan(self.lifecycle('redeploy', nodes=['r1']))

    def test_capabilities_carry_the_per_action_flags_the_node_actions_and_impairments(self):
        found = self.host.capabilities()
        actions = found['actions']
        self.assertEqual(actions['deploy'], {'available': True, 'cleanup': True, 'graceful': True, 'node_filter': True, 'max_workers': True, 'skip_post_deploy': True, 'keep_mgmt_net': False, 'dry_run': True})
        self.assertEqual(actions['destroy'], {'available': True, 'cleanup': True, 'graceful': True, 'node_filter': True, 'max_workers': True, 'skip_post_deploy': False, 'keep_mgmt_net': True, 'dry_run': False})
        self.assertEqual(actions['save'], {'available': True, 'cleanup': False, 'graceful': False, 'node_filter': True, 'max_workers': False, 'skip_post_deploy': False, 'keep_mgmt_net': False, 'dry_run': False})
        self.assertEqual((actions['start-node'], actions['stop-node'], actions['restart-node'], actions['impairments']), ({'available': True}, {'available': True}, {'available': True}, {'available': True}))
        self.assertEqual((found['lifecycle_options'], found['diagnostics'], found['containerlab']), (True, True, '0.79.0'))
        self.assertIn([self.clab, 'tools', 'netem', 'set', '--help'], [a for a, _ in self.calls])
        self.missing.add('tools')
        self.assertEqual(self.host.capabilities()['actions']['impairments'], {'available': False})
        self.assertEqual([a[1] for a, _ in self.calls if '--help' in a].count('tools'), 2, 'one netem probe per capabilities call')


def run_main(test, request, hold=True, **methods):
    """main() with a stub configuration and lock file; `hold` keeps the host lock in another descriptor. Returns
    (exit code, answer, the modes' flock calls). Popen is patched, so nothing can run."""
    from contextlib import redirect_stdout
    from types import SimpleNamespace
    root = Path(tempfile.mkdtemp()); test.addCleanup(lambda: shutil.rmtree(root, ignore_errors=True))
    config = dict(clab='/usr/bin/containerlab', roots=[str(root)], projects=str(root))
    real_path, real_open, real_flock = host_operations.Path, open, fcntl.flock
    class ConfigFile:
        def read_text(self): return json.dumps(config)
    def fake_path(value): return ConfigFile() if value == '/etc/clab-manager/operations.json' else real_path(value)
    lock_file = root / 'operations.lock'
    def fake_open(name, *args, **kwargs): return real_open(lock_file if name == host_operations.LOCK_PATH else name, *args, **kwargs)
    flocks = []
    def recording_flock(fd, flags): flocks.append(flags); return real_flock(fd, flags)
    stdin = SimpleNamespace(buffer=io.BytesIO(json.dumps(request).encode() + b'\n')); output = io.StringIO()
    with (open(lock_file, 'a') if hold else contextlib.nullcontext()) as held:
        if hold: fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with patch.object(host_operations, 'Path', side_effect=fake_path), patch.object(host_operations, 'signal'), \
             patch.object(host_operations.sys, 'stdin', stdin), patch.object(host_operations, 'open', fake_open, create=True), \
             patch.object(fcntl, 'flock', recording_flock), patch.object(host_operations.subprocess, 'Popen') as popen, redirect_stdout(output), \
             (patch.multiple(HostOperations, **methods) if methods else contextlib.nullcontext()):
            code = host_operations.main()
    popen.assert_not_called()
    return code, json.loads(output.getvalue()), flocks


class DispatchTests(unittest.TestCase):
    """main(): one elif per mode; the one host lock through one shared locked() helper for exactly four modes."""
    def never(self, *args, **kwargs): raise AssertionError('must not run under a held lock')

    def test_netem_set_and_reset_under_a_held_lock_answer_the_lock_sentence_and_run_nothing(self):
        for mode in ('netem-set', 'netem-reset'):
            code, answer, flocks = run_main(self, {'mode': mode, 'name': LAB, 'options': {}, 'expected_id': ID, 'digest': 'x'}, netem_set=self.never, netem_reset=self.never)
            self.assertEqual((code, answer), (1, {'error': host_operations.LOCK_SENTENCE}), mode)
            self.assertEqual(flocks, [fcntl.LOCK_EX | fcntl.LOCK_NB], 'one non-blocking attempt, no wait, no retry')
        for mode in ('preview', 'run'):
            code, answer, flocks = run_main(self, {'mode': mode, 'action': 'deploy', 'name': LAB, 'path': '/x', 'options': {}}, plan=self.never, execute=self.never)
            self.assertEqual((code, answer), (1, {'error': host_operations.LOCK_SENTENCE}), mode)
        self.assertEqual(host_operations.LOCK_SENTENCE, 'Another host lab operation is running.')

    def test_the_read_only_modes_answer_while_the_lock_is_held(self):
        code, answer, flocks = run_main(self, {'mode': 'netem-show-all', 'name': LAB, 'options': {'nodes': []}}, netem_show_all=lambda self, name, options: {'devices': [], 'complete': True})
        self.assertEqual((code, answer, flocks), (0, {'result': {'devices': [], 'complete': True}}, []))
        code, answer, flocks = run_main(self, {'mode': 'apply-plan', 'name': LAB, 'path': '/x'}, pending_plan=lambda self, name, path: {'plan': None, 'failed': 'unsupported', 'error': ''})
        self.assertEqual((code, answer, flocks), (0, {'result': {'plan': None, 'failed': 'unsupported', 'error': ''}}, []))
        code, answer, flocks = run_main(self, {'mode': 'netem-show', 'name': LAB, 'options': {}}, netem_show=lambda self, name, options: {'facts': {'present': False}, 'impairments': []})
        self.assertEqual((code, flocks), (0, []))

    def test_exactly_four_modes_take_the_lock_through_one_shared_helper(self):
        stubs = dict(netem_set=lambda self, req: {'set': True}, netem_reset=lambda self, req: {'reset': True}, plan=lambda self, req: {'options': {}, 'planned': True},
                     execute=lambda self, req, emit: {'exit_code': 0}, netem_show_all=lambda self, name, options: {}, pending_plan=lambda self, name, path: {},
                     netem_show=lambda self, name, options: {}, logs=lambda self, name, options: {}, interfaces=lambda self, name, options: {}, images=lambda self: {},
                     image_check=lambda self, options: {}, browse=lambda self, path, options: {}, read=lambda self, path: {}, capabilities=lambda self: {})
        locked = {}
        for mode in ('netem-set', 'netem-reset', 'preview', 'run', 'netem-show-all', 'apply-plan', 'netem-show', 'logs', 'interfaces', 'images', 'image-check', 'browse', 'read', 'capabilities'):
            code, answer, flocks = run_main(self, {'mode': mode, 'name': LAB, 'path': '/x', 'options': {}}, hold=False, **stubs)
            self.assertEqual(code, 0, mode); locked[mode] = flocks
        self.assertEqual({m for m, f in locked.items() if f}, {'netem-set', 'netem-reset', 'preview', 'run'})
        self.assertTrue(all(f == [fcntl.LOCK_EX | fcntl.LOCK_NB] for f in locked.values() if f))
        code, answer, flocks = run_main(self, {'mode': 'preview', 'name': LAB, 'path': '/x', 'options': {}}, hold=False, **stubs)
        self.assertEqual(answer, {'result': {'planned': True}}, 'a preview answer drops the options as before')
        source = Path(host_operations.__file__).read_text()
        self.assertEqual(source.count('def locked('), 1); self.assertEqual(source.count('fcntl.flock('), 1)
        self.assertEqual(re.findall(r"elif mode == '([a-z-]+)': result = locked\(", source), ['netem-set', 'netem-reset', 'preview', 'run'])
        self.assertIn("with open(LOCK_PATH, 'a') as lock:", source); self.assertEqual(host_operations.LOCK_PATH, '/run/clab-manager-operations.lock')
        self.assertIn("raise ValueError('" + host_operations.LOCK_SENTENCE + "') from None", source, 'the literal the C02 test pins is the constant')
        self.assertIn("else: raise ValueError('Unknown request mode.')", source)

    def test_the_lock_sentence_equals_the_manager_s_constant(self):
        import app.lab_operations as lab_operations
        self.assertEqual(lab_operations.LOCK_SENTENCE, host_operations.LOCK_SENTENCE)

    def test_the_gateway_names_none_of_the_new_modes(self):
        text = (Path(__file__).resolve().parents[2] / 'deploy/clab-manager-gateway').read_text(encoding='utf-8')
        for mode in ('netem', 'apply-plan', 'start-node', 'stop-node', 'impairment', 'lifecycle'):
            self.assertNotIn(mode, text)
        self.assertIn('clab-manager-operations) exec sudo -n /usr/local/sbin/clab-manager-operate ;;', text)


if __name__ == '__main__':
    unittest.main()
