"""Helper-side tests of the read-only diagnostics modes of host_operations.py (parity campaign C03,
docs/parity-campaign/C03-DESIGN.md section 2): the container binding, `logs`, `interfaces` with its
/proc counter sample, `netem-show`, `images` with `details`, `browse` with `files`, the hardened `read`,
`capabilities`, and the dispatch of all of it outside the host lock on the existing gateway request name.

Stdlib only, no VM, no Docker: the subprocess runners are stubs that record every argv, the same
harness shape as ImageModeTests in test_lab_operations.py."""
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import app.host_operations as host_operations
from app.host_operations import HostOperations

LAB = 'parity'; NODE = 'r1'; CONTAINER = 'clab-parity-r1'
ID = hashlib.sha256(b'clab-parity-r1').hexdigest()
OTHER_ID = hashlib.sha256(b'clab-parity-r2').hexdigest()
PORTS = '{"22/tcp":[{"HostIp":"0.0.0.0","HostPort":"2201"},{"HostIp":"::","HostPort":"2201"}],"830/tcp":null,"57400/tcp":[{"HostIp":"0.0.0.0","HostPort":"57401"}]}'
GATEWAY = Path(__file__).resolve().parents[2] / 'deploy/clab-manager-gateway'
# The gateway's case arms as test_gateway_whitelist.py pins them: this chunk adds no request name.
ARMS = ['clab-manager-git', 'clab-manager-operations',
        "'sudo -n /usr/local/sbin/clab-manager-inspect'|'containerlab inspect --all --format json'", '*']
NET_DEV = ('Inter-|   Receive                                                |  Transmit\n'
           ' face |bytes    packets errs drop fifo frame compressed multicast|bytes    packets errs drop fifo colls carrier compressed\n'
           '    lo:   10000     100    0    0    0     0          0         0    10000     100    0    0    0     0       0          0\n'
           '  eth0: 1234567    8901    2    3    0     0          0        12   7654321    1098    4    5    0     0       0          0\n'
           '  eth1:     512       4    0    1    0     0          0         0      1024       8    0    2    0     0       0          0\n')


def inspect_line(id=ID, pid=4242, status='running', started='2026-10-23T01:02:03.456789Z', health='healthy', lab=LAB, node=NODE, kind='ceos', topo='/srv/labs/parity/parity.clab.yml', ports=PORTS, network_mode='clab'):
    """The eleven tab-separated fields of INSPECT_FORMAT (C05 added `HostConfig.NetworkMode`; the read-only modes ignore it)."""
    return '\t'.join((id, str(pid), status, started, health, lab, node, kind, topo, ports, network_mode)) + '\n'


class DiagnosticsHarness(unittest.TestCase):
    """A helper on a temporary root with a stub Docker client; every runner records its argv and bounds."""
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)
        self.docker = self.root / 'docker'; self.docker.write_text('#!/bin/sh\n'); self.docker.chmod(0o755)
        self.clab = '/usr/bin/containerlab'
        self.calls = []; self.probes = []; self.merged = []
        self.topo = str(self.root / 'parity' / 'parity.clab.yml')
        self.containers = {CONTAINER: self.line()}
        self.interfaces_output = json.dumps([
            {'name': 'clab-parity-r2', 'interfaces': [{'name': 'eth0', 'alias': '', 'state': 'up', 'mac': '02:42:ac:14:14:03', 'mtu': 1500, 'ifindex': 2, 'type': 'veth'}]},
            {'name': CONTAINER, 'interfaces': [
                {'name': 'eth0', 'alias': '', 'state': 'up', 'mac': '02:42:ac:14:14:02', 'mtu': 1500, 'ifindex': 2, 'type': 'veth'},
                {'name': 'eth1', 'alias': 'Ethernet1', 'state': 'up', 'mac': '02:42:ac:14:14:12', 'mtu': 9500, 'ifindex': 7, 'type': 'veth'},
                {'name': 'cpu', 'alias': '', 'state': 'unknown', 'mac': '', 'mtu': 1500, 'ifindex': 3, 'type': 'dummy'}]}])
        self.netem_output = json.dumps({CONTAINER: None})
        self.listing = ('n24l/ceos:4.35.0F\tsha256:0a1b\t2.1GB\t2026-10-20 10:00:00 +0000 UTC\n'
                        'ghcr.io/srl-labs/network-multitool:latest\t3c4d5e6f\t60.2MB\t2026-09-01 08:30:00 +0000 UTC\n'
                        '<none>:<none>\t9999\t1GB\t2026-01-01 00:00:00 +0000 UTC\n'
                        'bad image name:x\t1111\t1GB\t2026-01-01 00:00:00 +0000 UTC\n'
                        'n24l/cisco_xrv9k:24.3.1\t7a7b\t4.53GB\t2026-10-23 02:03:42 +0000 UTC\n')
        self.log = b'2026-10-23T01:02:03.000000000Z boot: starting\n2026-10-23T01:02:04.000000000Z PASSWORD: hunter2\n'
        self.log_code = 0
        self.version_output = (0, '0.79.0\n')
        def run(argv, **bounds):
            self.calls.append((argv, bounds))
            if argv[:3] == [self.clab, 'inspect', 'interfaces']: return 0, self.interfaces_output
            if argv[:4] == [self.clab, 'tools', 'netem', 'show']: return 0, self.netem_output
            if argv == [self.clab, 'version', '--short']: return self.version_output
            if argv[:3] == [str(self.docker), 'image', 'ls']: return 0, self.listing
            if '--help' in argv: return 0, '--name --cleanup --graceful --node help'
            return 1, ''
        def probe(argv, timeout):
            self.probes.append((argv, timeout))
            if argv[1:5] == ['inspect', '--type', 'container', '--format']:
                line = self.containers.get(argv[-1])
                return (0, line, '') if line else (1, '', 'Error response from daemon: No such container: ' + argv[-1])
            raise AssertionError('unexpected probe ' + ' '.join(argv))
        def run_merged(argv, **bounds):
            self.merged.append((argv, bounds))
            return self.log_code, self.log
        self.patch = patch.object(host_operations, 'DOCKER', str(self.docker)); self.patch.start()
        self.host = HostOperations(dict(clab=self.clab, git='/usr/bin/git', roots=[str(self.root)], projects=str(self.root), network=False), run, probe, run_merged)
        self.host.proc = str(self.root / 'proc')
        self.options = {'node': NODE, 'container': CONTAINER}

    def tearDown(self): self.patch.stop(); self.tmp.cleanup()

    def line(self, **fields):
        """A docker inspect answer for a container of this lab deployed from a topology under the trusted root."""
        return inspect_line(**{'topo': self.topo, **fields})

    def proc_tree(self, pid=4242, cgroup='0::/system.slice/docker-' + ID + '.scope\n', dev=NET_DEV, host=False):
        """A fake /proc with the VM's own network namespace at 1/ns/net; `host` gives the task that same inode."""
        own = self.root / 'proc' / '1' / 'ns' / 'net'
        if not own.exists(): own.parent.mkdir(parents=True); own.write_text('net:[4026531840]')
        folder = self.root / 'proc' / str(pid); (folder / 'net').mkdir(parents=True); (folder / 'ns').mkdir()
        (folder / 'cgroup').write_text(cgroup); (folder / 'net' / 'dev').write_text(dev)
        if host: os.link(own, folder / 'ns' / 'net')
        else: (folder / 'ns' / 'net').write_text('net:[4026532555]')
        return folder

    def nothing_ran(self, message='a refused request runs nothing'):
        self.assertEqual((self.calls, self.probes, self.merged), ([], [], []), message)


class ContainerBindingTests(DiagnosticsHarness):
    """container_of(): one fixed `docker inspect --type container`, a 64-hex Id, labels naming this lab and node."""
    def test_binds_with_one_fixed_inspect_and_returns_bounded_facts(self):
        facts = self.host.container_of(self.options, LAB)
        self.assertEqual(self.probes, [([str(self.docker), 'inspect', '--type', 'container', '--format', host_operations.INSPECT_FORMAT, CONTAINER], host_operations.IMAGE_PROBE_TIMEOUT)])
        self.assertEqual(facts, {'present': True, 'id': ID, 'pid': 4242, 'status': 'running', 'health': 'healthy', 'started': '2026-10-23T01:02:03.456789Z', 'kind': 'ceos',
                                 'ports': [{'container': '22/tcp', 'host': '2201'}, {'container': '57400/tcp', 'host': '57401'}], 'network_mode': 'clab'})
        self.assertEqual(host_operations.INSPECT_FORMAT.count('\t'), 10, 'eleven fields: C05 added the network mode last')
        for piece in ('{{.Id}}', '{{.State.Pid}}', '{{index .Config.Labels "containerlab"}}', '{{index .Config.Labels "clab-node-name"}}', '{{index .Config.Labels "clab-topo-file"}}', '{{json .NetworkSettings.Ports}}', '{{.HostConfig.NetworkMode}}'):
            self.assertIn(piece, host_operations.INSPECT_FORMAT)
        self.assertEqual(self.calls, [], 'the binding runs no containerlab command')

    def test_health_is_read_with_index_so_a_container_without_a_healthcheck_binds(self):
        # Docker 27.5.1 evaluates this template against the raw JSON map (the `index .Config.Labels` pieces make it),
        # where a container without a HEALTHCHECK has no `State.Health` key: `{{with .State.Health}}` failed the whole
        # inspect for clab-parity-ceos and clab-parity-cjunos ("map has no entry for key Health"), so `interfaces` and
        # `logs` answered "did not answer about this container". `index` yields nil there and `with` skips it.
        self.assertIn('{{with index .State "Health"}}{{.Status}}{{end}}', host_operations.INSPECT_FORMAT)
        self.assertNotIn('.State.Health', host_operations.INSPECT_FORMAT)
        # Every template action may read only keys every container has (a missing key fails the whole inspect on Docker 27.5.1),
        # or reach an optional key through `index`; any other dotted .State.* or .Config.* access is the break that happened live.
        import re
        always = {'.Id', '.State.Pid', '.State.Status', '.State.StartedAt', '.HostConfig.NetworkMode', '.NetworkSettings.Ports'}
        actions = re.findall(r'\{\{(.*?)\}\}', host_operations.INSPECT_FORMAT)
        self.assertEqual(len(actions), 13, 'eleven fields; the health field is three actions (with, .Status, end)')
        for action in actions:
            words = action.split()
            indexed = words[0] == 'index' or words[:2] == ['with', 'index']   # `index .Config.Labels "key"`: nil, never an error
            for word in re.findall(r'\.(?:State|Config)\.\w+', action):
                if indexed and word == '.Config.Labels': continue
                self.assertIn(word, always, f'{word} may be absent in the raw JSON: read it with index')
        self.assertEqual(host_operations.INSPECT_FORMAT.split('\t')[4], '{{with index .State "Health"}}{{.Status}}{{end}}', 'the fifth field, as inspect_line() lays it out')
        self.containers[CONTAINER] = self.line(health='')
        facts = self.host.container_of(self.options, LAB)
        self.assertEqual((facts['present'], facts['health'], facts['status'], facts['id']), (True, '', 'running', ID))
        self.assertEqual(self.host.interfaces(LAB, self.options)['facts']['health'], '')
        self.assertEqual(self.host.logs(LAB, {**self.options, 'tail': 5})['facts']['health'], '')

    def test_an_absent_container_is_not_an_error(self):
        # Also the name of an image, a volume or a network: `--type container` makes Docker answer "No such container".
        self.containers = {}
        self.assertEqual(self.host.container_of(self.options, LAB), {'present': False})
        self.assertIn('--type', self.probes[0][0]); self.assertEqual(self.probes[0][0][self.probes[0][0].index('--type') + 1], 'container')
        self.assertEqual(self.host.logs(LAB, {**self.options, 'tail': 50}), {'facts': {'present': False}, 'text': '', 'truncated': False})
        self.assertEqual(self.host.interfaces(LAB, self.options), {'facts': {'present': False}, 'interfaces': []})
        self.assertEqual(self.host.netem_show(LAB, self.options), {'facts': {'present': False}, 'impairments': []})
        self.assertEqual((self.calls, self.merged), ([], []), 'nothing is asked about a container that is not there')

    def test_another_lab_s_container_and_a_node_label_mismatch_are_refused(self):
        self.containers[CONTAINER] = self.line(lab='other')
        with self.assertRaisesRegex(ValueError, 'does not belong to lab parity'): self.host.logs(LAB, {**self.options, 'tail': 10})
        self.containers[CONTAINER] = self.line(node='r2')
        with self.assertRaisesRegex(ValueError, 'does not belong to lab parity'): self.host.interfaces(LAB, self.options)
        self.containers[CONTAINER] = self.line(lab='', node='')
        with self.assertRaisesRegex(ValueError, 'does not belong'): self.host.netem_show(LAB, self.options)
        self.assertEqual((self.calls, self.merged), ([], []), 'a refused binding reads nothing')

    def test_an_unusable_id_is_refused(self):
        for bad in ('x' * 64, ID[:63], ID.upper(), '', ID + 'a', '-' + ID[1:]):
            self.containers[CONTAINER] = self.line(id=bad)
            with self.assertRaisesRegex(ValueError, 'unusable container identity', msg=bad): self.host.container_of(self.options, LAB)
        for short in ((ID, '1', 'running', 'x', '', LAB, NODE, 'ceos', self.topo), (ID, '1', 'running', 'x', '', LAB, NODE, 'ceos', self.topo, PORTS)):
            self.containers[CONTAINER] = '\t'.join(short) + '\n'   # nine fields; the pre-C05 ten-field line
            with self.assertRaisesRegex(ValueError, 'unusable container identity'): self.host.container_of(self.options, LAB)
        self.containers[CONTAINER] = self.line() + 'extra\tline\n'
        with self.assertRaisesRegex(ValueError, 'unusable container identity'): self.host.container_of(self.options, LAB)
        self.assertEqual(self.merged, [])

    def test_a_lab_deployed_from_outside_the_trusted_roots_is_refused(self):
        # The same binding every lifecycle action has: a lab name counts only with a topology path under a trusted root.
        for topo in ('/home/other/parity/parity.clab.yml', 'parity/parity.clab.yml', str(self.root) + '/../parity/parity.clab.yml', '', str(self.root), str(self.root) + 'x/parity.clab.yml', '/\x00'):
            self.containers[CONTAINER] = self.line(topo=topo)
            with self.assertRaisesRegex(ValueError, 'outside the trusted lab roots', msg=repr(topo)): self.host.logs(LAB, {**self.options, 'tail': 10})
        self.assertEqual((self.calls, self.merged), ([], []), 'nothing is read for such a lab')
        for topo in (self.topo, str(self.root / 'deep' / 'er' / 'lab.clab.yaml')):
            self.containers[CONTAINER] = self.line(topo=topo)
            self.assertTrue(self.host.container_of(self.options, LAB)['present'], topo)
        self.assertFalse(host_operations.HostOperations.trusted(self.host, 5))

    def test_the_selector_refuses_before_anything_runs(self):
        for options in ({'node': NODE, 'container': 'clab-other-r1'}, {'node': NODE}, {'container': CONTAINER}, {'node': [NODE], 'container': CONTAINER},
                        {'node': NODE, 'container': '--format={{.Id}}'}, {'node': 'r1,r2', 'container': CONTAINER}, {'node': NODE, 'container': 'vjunos-r1'}):
            with self.assertRaises(ValueError, msg=repr(options)): self.host.container_of(options, LAB)
        with self.assertRaisesRegex(ValueError, 'literal lab'): self.host.logs(None, {**self.options, 'tail': 10})
        with self.assertRaisesRegex(ValueError, 'literal lab'): self.host.interfaces('lab; id', self.options)
        self.nothing_ran()

    def test_docker_trouble_and_a_missing_client_are_sentences(self):
        self.host.probe = lambda argv, timeout: (1, '', 'permission denied while trying to connect to the Docker daemon socket')
        with self.assertRaisesRegex(ValueError, 'did not answer about this container'): self.host.container_of(self.options, LAB)
        self.host.probe = lambda argv, timeout: (1, '', 'Cannot connect to the Docker daemon at unix:///var/run/docker.sock: dial unix: no such file or directory')
        with self.assertRaisesRegex(ValueError, 'did not answer about this container'): self.host.container_of(self.options, LAB)
        self.host.probe = lambda argv, timeout: (1, '', 'Error: No such container: ' + CONTAINER)
        self.assertEqual(self.host.container_of(self.options, LAB), {'present': False}, 'a stopped daemon is not "not deployed"; only Docker\'s own absence answer is')
        self.docker.chmod(0o644)
        with self.assertRaisesRegex(ValueError, 'No Docker client'): self.host.container_of(self.options, LAB)

    def test_port_bindings_keep_digits_only(self):
        self.assertEqual(host_operations.port_bindings('null'), [])
        self.assertEqual(host_operations.port_bindings('not json'), [])
        self.assertEqual(host_operations.port_bindings('{"22/tcp":[{"HostPort":"22; id"}],"x/tcp":[{"HostPort":"1"}],"80/tcp":[{"HostPort":"8080"},{"HostPort":"8080"}]}'),
                         [{'container': '80/tcp', 'host': '8080'}])


class LogsModeTests(DiagnosticsHarness):
    def test_logs_argv_is_fixed_and_names_the_inspected_id_not_the_name(self):
        result = self.host.logs(LAB, {**self.options, 'tail': 200})
        self.assertEqual(self.merged, [([str(self.docker), 'logs', '--tail', '200', '--timestamps', ID], {'timeout': host_operations.LOGS_TIMEOUT, 'limit': host_operations.LOGS_LIMIT})])
        self.assertNotIn(CONTAINER, self.merged[0][0])
        self.assertEqual(result, {'facts': self.host.container_of(self.options, LAB), 'text': self.log.decode(), 'truncated': False})
        self.assertIn('PASSWORD: hunter2', result['text'], 'the helper returns the raw text; redaction is the manager\'s')
        self.merged.clear()
        self.host.logs(LAB, {**self.options, 'tail': 1, 'since': '2026-10-23T01:02:04.000000000Z'})
        self.assertEqual(self.merged[0][0], [str(self.docker), 'logs', '--tail', '1', '--timestamps', '--since', '2026-10-23T01:02:04.000000000Z', ID])
        self.assertEqual(host_operations.LOGS_TIMEOUT, 15); self.assertEqual(host_operations.LOGS_LIMIT, 512 * 1024); self.assertEqual(host_operations.LOGS_TAIL_LIMIT, 2000)
        self.assertEqual(self.calls, [], 'logs never runs containerlab')

    def test_tail_and_since_validation_table(self):
        for tail in (0, 2001, '10', True, False, None, 1.0, -1, 10 ** 9, [10]):
            with self.assertRaisesRegex(ValueError, 'Ask for 1 to 2000 log lines', msg=repr(tail)): self.host.logs(LAB, {**self.options, 'tail': tail})
        for since in ('2026-10-23T01:02:03Z\n', '\n2026-10-23T01:02:03Z', '２2026-10-23T01:02:03Z', '2026-10-23', '2026-10-23T01:02:03+00:00', '2026-10-23T01:02:03',
                      '2026-10-23T01:02:03.1234567890Z', '2026-10-23T01:02:03z', '2026-10-23 01:02:03Z', '10m', '', 5, b'2026-10-23T01:02:03Z', ' 2026-10-23T01:02:03Z'):
            with self.assertRaisesRegex(ValueError, 'UTC timestamp', msg=repr(since)): self.host.logs(LAB, {**self.options, 'tail': 10, 'since': since})
        with self.assertRaisesRegex(ValueError, 'Unsupported log options'): self.host.logs(LAB, {**self.options, 'tail': 10, 'follow': True})
        with self.assertRaisesRegex(ValueError, 'Unsupported log options'): self.host.logs(LAB, [NODE, CONTAINER])
        with self.assertRaisesRegex(ValueError, 'Unsupported log options'): self.host.logs(LAB, {**self.options, 'tail': 10, 'id': OTHER_ID})
        self.nothing_ran()
        for tail in (1, 2000):
            self.host.logs(LAB, {**self.options, 'tail': tail})
        for since in ('2026-10-23T01:02:03Z', '2026-10-23T01:02:03.1Z', '2026-10-23T01:02:03.123456789Z'):
            self.host.logs(LAB, {**self.options, 'tail': 10, 'since': since})
        self.assertEqual([argv[3] for argv, _ in self.merged[:2]], ['1', '2000'])
        self.assertEqual([argv[6] for argv, _ in self.merged[2:]], ['2026-10-23T01:02:03Z', '2026-10-23T01:02:03.1Z', '2026-10-23T01:02:03.123456789Z'])
        self.assertTrue(host_operations.LOGS_SINCE.flags & re.ASCII)

    def test_the_log_is_capped_at_512_kib_cut_at_a_line(self):
        lines = [('2026-10-23T01:%02d:%02d.000000000Z line %06d ' % (i // 3600 % 60, i % 60, i)).ljust(99, 'x') + '\n' for i in range(7000)]
        self.log = ''.join(lines).encode(); self.assertGreater(len(self.log), host_operations.LOGS_LIMIT)
        result = self.host.logs(LAB, {**self.options, 'tail': 2000})
        self.assertTrue(result['truncated'])
        self.assertLessEqual(len(result['text'].encode()), host_operations.LOGS_LIMIT)
        self.assertTrue(self.log.decode().endswith(result['text']), 'the newest text is kept')
        self.assertIn(result['text'].split('\n')[0] + '\n', lines, 'the cut lands on a line start')
        self.assertTrue(result['text'].endswith(lines[-1]))
        self.log = b'short\n'
        self.assertEqual(self.host.logs(LAB, {**self.options, 'tail': 5})['truncated'], False)

    def test_a_non_zero_exit_is_the_fixed_sentence_never_docker_s_text(self):
        self.log_code = 1; self.log = b'Error response from daemon: configured logging driver does not support reading\n'
        with self.assertRaises(ValueError) as caught: self.host.logs(LAB, {**self.options, 'tail': 10})
        self.assertEqual(str(caught.exception), "Docker on the VM did not return this container's log.")

    def test_capture_merged_keeps_both_streams_as_bytes_and_keeps_the_newest_over_the_limit(self):
        code, raw = host_operations.capture_merged([sys.executable, '-c', 'import sys; sys.stdout.write("out\\n"); sys.stdout.flush(); sys.stderr.write("err\\n")'])
        self.assertEqual(code, 0); self.assertIsInstance(raw, bytes); self.assertEqual(sorted(raw.split()), [b'err', b'out'])
        # A log far over the limit (the 4 MiB case) is not an error: the newest limit + 1 bytes come back, so logs() can cut at a line.
        code, raw = host_operations.capture_merged([sys.executable, '-c', 'import sys; sys.stdout.write("".join("%07d\\n" % i for i in range(600000)))'], limit=1024)
        self.assertEqual((code, len(raw)), (0, 1025)); self.assertTrue(raw.endswith(b'0599999\n')); self.assertTrue(raw.startswith(b'\n0599872\n'), raw[:20])
        code, raw = host_operations.capture_merged([sys.executable, '-c', 'import sys; sys.stdout.write("x" * 10)'], limit=1024)
        self.assertEqual(raw, b'x' * 10)


class InterfacesModeTests(DiagnosticsHarness):
    def test_argv_is_the_lab_wide_inspect_reduced_to_this_container(self):
        result = self.host.interfaces(LAB, self.options)
        self.assertEqual(self.calls, [([self.clab, 'inspect', 'interfaces', '--name', LAB, '-f', 'json'], {'timeout': host_operations.INSPECT_TIMEOUT, 'limit': host_operations.INSPECT_LIMIT})])
        self.assertEqual(result['facts']['id'], ID)
        self.assertEqual([r['name'] for r in result['interfaces']], ['eth0', 'eth1', 'cpu'], 'only this container\'s entry, in containerlab\'s order')
        self.assertEqual(result['interfaces'][1], {'name': 'eth1', 'alias': 'Ethernet1', 'state': 'up', 'mac': '02:42:ac:14:14:12', 'mtu': 9500, 'ifindex': 7, 'type': 'veth'})
        self.assertEqual(result.get('counters_reason'), 'pid', 'no /proc tree in this test: counters are left out with the reason')
        self.assertNotIn('counters', result); self.assertNotIn('sampled_at', result)
        self.assertEqual(self.merged, [])

    def test_counters_are_read_through_one_proc_directory_fd(self):
        folder = self.proc_tree()
        opened = []; real_open = os.open
        def recording_open(path, flags, *args, **kwargs):
            opened.append((str(path), flags, kwargs.get('dir_fd')))
            return real_open(path, flags, *args, **kwargs)
        before = time.time()
        with patch.object(host_operations.os, 'open', recording_open): result = self.host.interfaces(LAB, self.options)
        self.assertEqual(result['counters'], {
            'eth0': {'rx_bytes': 1234567, 'rx_packets': 8901, 'rx_errors': 2, 'rx_dropped': 3, 'tx_bytes': 7654321, 'tx_packets': 1098, 'tx_errors': 4, 'tx_dropped': 5},
            'eth1': {'rx_bytes': 512, 'rx_packets': 4, 'rx_errors': 0, 'rx_dropped': 1, 'tx_bytes': 1024, 'tx_packets': 8, 'tx_errors': 0, 'tx_dropped': 2}},
            'listed interfaces only: lo is not in the list, cpu has no counters')
        self.assertTrue(before <= result['sampled_at'] <= time.time())
        first = opened[0]
        self.assertEqual(first[0], str(folder)); self.assertTrue(first[1] & os.O_DIRECTORY); self.assertIsNone(first[2])
        self.assertEqual([(name, dir_fd is not None) for name, flags, dir_fd in opened[1:]], [('cgroup', True), ('net/dev', True)], 'both files are opened relative to the directory descriptor')
        for name, flags, dir_fd in opened[1:]:
            self.assertTrue(flags & os.O_NOFOLLOW); self.assertTrue(flags & os.O_NONBLOCK); self.assertFalse(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT))

    def test_counters_are_left_out_on_a_cgroup_mismatch_a_missing_task_or_no_pid(self):
        self.proc_tree(cgroup='0::/system.slice/docker-' + OTHER_ID + '.scope\n')
        result = self.host.interfaces(LAB, self.options)
        self.assertEqual((result.get('counters_reason'), 'counters' in result, len(result['interfaces'])), ('pid', False, 3))
        (self.root / 'proc' / '4242' / 'cgroup').write_text('0::/user.slice/docker-' + ID + 'ab.scope\n')
        self.assertEqual(self.host.interfaces(LAB, self.options).get('counters_reason'), 'pid', 'the Id must be a whole path segment, not a substring')
        (self.root / 'proc' / '4242' / 'cgroup').write_text('12:memory:/docker/' + ID + '\n1:name=systemd:/docker/' + ID + '\n')
        self.assertIn('counters', self.host.interfaces(LAB, self.options), 'the cgroup v1 form binds too')
        self.host.proc = str(self.root / 'no-proc')  # ESRCH on a real /proc: the task is gone
        self.assertEqual(self.host.interfaces(LAB, self.options).get('counters_reason'), 'pid')
        self.proc_tree(pid=7); self.containers[CONTAINER] = self.line(pid=0, status='created')
        self.assertEqual(self.host.interfaces(LAB, self.options).get('counters_reason'), 'pid')
        folder = self.proc_tree(pid=9); os.remove(folder / 'net' / 'dev'); os.symlink(folder / 'cgroup', folder / 'net' / 'dev')
        self.containers[CONTAINER] = self.line(pid=9)
        self.assertEqual(self.host.interfaces(LAB, self.options).get('counters_reason'), 'pid', 'a symlink where net/dev should be is not followed')

    def test_a_host_network_node_never_reports_the_vm_s_counters(self):
        self.proc_tree(host=True)
        result = self.host.interfaces(LAB, self.options)
        self.assertEqual(result.get('counters_reason'), 'host'); self.assertNotIn('counters', result); self.assertNotIn('sampled_at', result)
        self.assertEqual(len(result['interfaces']), 3, 'the interface list itself is still shown')

    def test_a_stopped_container_answers_an_empty_list_with_facts(self):
        self.containers[CONTAINER] = self.line(pid=0, status='exited', health=''); self.interfaces_output = '[]'
        result = self.host.interfaces(LAB, self.options)
        self.assertEqual(result, {'facts': {'present': True, 'id': ID, 'pid': 0, 'status': 'exited', 'health': '', 'started': '2026-10-23T01:02:03.456789Z', 'kind': 'ceos',
                                            'ports': [{'container': '22/tcp', 'host': '2201'}, {'container': '57400/tcp', 'host': '57401'}], 'network_mode': 'clab'}, 'interfaces': [], 'counters_reason': 'pid'})

    def test_text_output_is_an_empty_list_and_a_failed_command_is_a_sentence(self):
        self.interfaces_output = 'no containers found\n'
        self.assertEqual(self.host.interfaces(LAB, self.options)['interfaces'], [])
        self.interfaces_output = '{"not": "a list"}'
        self.assertEqual(self.host.interfaces(LAB, self.options)['interfaces'], [])
        self.host.run = lambda argv, **bounds: (1, 'Error: unknown command "interfaces" for "containerlab inspect"')
        with self.assertRaisesRegex(ValueError, 'did not list the interfaces'): self.host.interfaces(LAB, self.options)

    def test_reduction_is_bounded_and_typed(self):
        rows = [{'name': 'eth%d' % i, 'alias': 'a' * 100, 'state': 'up', 'mac': 7, 'mtu': '1500', 'ifindex': True, 'type': 'veth', 'extra': 'dropped'} for i in range(300)]
        rows.insert(0, {'name': 42}); rows.insert(0, 'junk'); rows.insert(0, {'alias': 'no name'})
        self.interfaces_output = json.dumps([{'name': CONTAINER, 'interfaces': rows}])
        found = self.host.interfaces(LAB, self.options)['interfaces']
        self.assertEqual(len(found), host_operations.INTERFACE_LIMIT)
        self.assertEqual(found[0], {'name': 'eth0', 'alias': 'a' * 64, 'state': 'up', 'mac': '', 'mtu': 0, 'ifindex': 0, 'type': 'veth'})
        self.assertEqual(set(found[0]), {'name', 'alias', 'state', 'mac', 'mtu', 'ifindex', 'type'})

    def test_option_whitelist(self):
        for options in ({**self.options, 'tail': 10}, {**self.options, 'pid': 1}, 'eth0', None):
            with self.assertRaisesRegex(ValueError, 'Unsupported interface options', msg=repr(options)): self.host.interfaces(LAB, options)
        self.nothing_ran()

    def test_net_dev_parser_ignores_headers_and_malformed_rows(self):
        text = NET_DEV + '  eth2: not numbers at all\n  eth3: 1 2 3\n  eth4: 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16\n'
        found = host_operations.net_dev(text, ['eth0', 'eth2', 'eth3', 'eth4', 'missing'])
        self.assertEqual(sorted(found), ['eth0', 'eth4'])
        self.assertEqual(found['eth4'], {'rx_bytes': 1, 'rx_packets': 2, 'rx_errors': 3, 'rx_dropped': 4, 'tx_bytes': 9, 'tx_packets': 10, 'tx_errors': 11, 'tx_dropped': 12})


class LinkStateModeTests(DiagnosticsHarness):
    """C06 S0: the `all` option of `interfaces` (docs/parity-campaign/C06-DESIGN.md §2.1). The lab is bound once per
    call by one fixed `containerlab inspect --name <lab> -f json` whose every row must name a topology inside the
    trusted roots; then the same lab-wide interface listing, reduced to {name, alias, state, type} per row."""
    def setUp(self):
        super().setUp()
        self.log = []
        self.bind_answer = (0, json.dumps({LAB: [self.bind_row(CONTAINER), self.bind_row('clab-parity-r2')]}))
        self.list_answer = None   # None: the harness's interfaces_output with exit 0
        def run(argv, **bounds):
            self.log.append((argv, bounds))
            if argv[:3] == [self.clab, 'inspect', '--name']: return self.bind_answer
            if argv[:3] == [self.clab, 'inspect', 'interfaces']: return self.list_answer or (0, self.interfaces_output)
            raise AssertionError('unexpected argv ' + ' '.join(argv))
        self.host.run = run

    def bind_row(self, name, path=None, key='labPath'):
        """One row of `containerlab inspect --name <lab> -f json` as containerlab 0.79 prints it (fact 0.3)."""
        row = {'lab_name': LAB, 'name': name, 'container_id': 'd9401619bc97', 'kind': 'ceos', 'state': 'running', 'owner': 'archtop'}
        row[key] = self.topo if path is None else path
        if key == 'labPath': row['absLabPath'] = row['labPath']
        return row

    def argvs(self): return [argv for argv, _ in self.log]

    def test_two_fixed_argvs_in_order_and_never_docker(self):
        result = self.host.interfaces(LAB, {'all': True})
        bounds = {'timeout': host_operations.INSPECT_TIMEOUT, 'limit': host_operations.INSPECT_LIMIT}
        self.assertEqual(self.log, [([self.clab, 'inspect', '--name', LAB, '-f', 'json'], bounds),
                                    ([self.clab, 'inspect', 'interfaces', '--name', LAB, '-f', 'json'], bounds)])
        self.assertEqual((self.probes, self.merged), ([], []), 'no docker inspect, no docker logs: nothing Docker runs')
        self.assertEqual(result, {'present': True, 'nodes': [
            {'name': 'clab-parity-r2', 'interfaces': [{'name': 'eth0', 'alias': '', 'state': 'up', 'type': 'veth'}]},
            {'name': CONTAINER, 'interfaces': [{'name': 'eth0', 'alias': '', 'state': 'up', 'type': 'veth'},
                                               {'name': 'eth1', 'alias': 'Ethernet1', 'state': 'up', 'type': 'veth'},
                                               {'name': 'cpu', 'alias': '', 'state': 'unknown', 'type': 'dummy'}]}]})
        self.assertNotIn('facts', result); self.assertNotIn('counters', result)
        source = Path(host_operations.__file__).read_text()
        start = source.index('    def lab_links(')
        body = source[start:source.index('\n    def ', start + 1)]
        for word in ('DOCKER', 'self.counters(', 'self.container_of(', 'self.probe(', 'self.run_merged(', "'set'", "'reset'"): self.assertNotIn(word, body, word)
        self.assertEqual(body.count('self.run('), 2, 'two fixed argvs, nothing else runs')

    def test_a_binding_row_outside_the_trusted_roots_stops_before_the_listing(self):
        sentence = 'This lab was deployed from outside the trusted lab roots. Add its project root during operations setup.'
        outside = [self.bind_row('clab-parity-r9', path='/tmp/elsewhere/parity.clab.yml'), self.bind_row('clab-parity-r9', path='relative/parity.clab.yml'),
                   self.bind_row('clab-parity-r9', path=str(self.root / '..' / 'x.clab.yml')), self.bind_row('clab-parity-r9', path=''),
                   {k: v for k, v in self.bind_row('clab-parity-r9').items() if k not in ('labPath', 'absLabPath')}, 'junk']
        for row in outside:
            for shape in (lambda rows: {LAB: rows}, lambda rows: rows):
                self.log.clear()
                self.bind_answer = (0, json.dumps(shape([self.bind_row(CONTAINER), row])))
                with self.assertRaises(ValueError, msg=repr(row)) as raised: self.host.interfaces(LAB, {'all': True})
                self.assertEqual(str(raised.exception), sentence)
                self.assertEqual(self.argvs(), [[self.clab, 'inspect', '--name', LAB, '-f', 'json']], 'the interfaces listing never runs')
        self.assertEqual(self.probes, [])

    def test_a_binding_that_is_not_json_empty_or_failed_is_not_present_and_runs_nothing_more(self):
        for answer in ((1, ''), (1, json.dumps({LAB: [self.bind_row(CONTAINER)]})), (0, 'no containers found'), (0, '{}'), (0, '[]'), (0, json.dumps({LAB: []})), (0, '"text"')):
            self.log.clear(); self.bind_answer = answer
            self.assertEqual(self.host.interfaces(LAB, {'all': True}), {'nodes': [], 'present': False}, repr(answer))
            self.assertEqual(len(self.log), 1, repr(answer))

    def test_the_listing_failing_is_the_existing_sentence_and_text_is_not_present(self):
        self.list_answer = (1, 'Error: unknown command "interfaces" for "containerlab inspect"')
        with self.assertRaisesRegex(ValueError, '^Containerlab on the VM did not list the interfaces of this lab.$'): self.host.interfaces(LAB, {'all': True})
        self.list_answer = (0, 'no containers found\n')
        self.assertEqual(self.host.interfaces(LAB, {'all': True}), {'nodes': [], 'present': False})
        self.list_answer = (0, '{"not": "a list"}')
        self.assertEqual(self.host.interfaces(LAB, {'all': True}), {'nodes': [], 'present': True})

    def test_only_containers_the_binding_listed_are_answered(self):
        self.bind_answer = (0, json.dumps({LAB: [self.bind_row(CONTAINER)]}))
        result = self.host.interfaces(LAB, {'all': True})
        self.assertEqual([n['name'] for n in result['nodes']], [CONTAINER], 'a container that appeared after the binding is not listed')
        self.bind_answer = (0, json.dumps([self.bind_row(CONTAINER, key='absLabPath'), self.bind_row('clab-parity-r2')]))
        self.assertEqual([n['name'] for n in self.host.interfaces(LAB, {'all': True})['nodes']], ['clab-parity-r2', CONTAINER], 'a list and absLabPath alone bind too')

    def test_rows_are_reduced_to_four_bounded_strings(self):
        rows = [{'name': 'e' * 100, 'alias': 'a' * 100, 'state': 's' * 100, 'type': 't' * 100, 'mac': '02:00:00:00:00:01', 'mtu': 1500, 'ifindex': 3, 'extra': 'x'},
                {'name': 'eth2', 'alias': None, 'state': 7, 'type': ['veth']}, {'name': 42}, {'name': ''}, 'junk', {'alias': 'no name'}]
        self.interfaces_output = json.dumps([{'name': CONTAINER, 'interfaces': rows, 'pid': 9}, {'name': 'x' * 254, 'interfaces': []}, 'junk', {'name': 7}])
        self.bind_answer = (0, json.dumps({LAB: [self.bind_row(CONTAINER), self.bind_row('x' * 254)]}))
        result = self.host.interfaces(LAB, {'all': True})
        self.assertEqual(result['nodes'], [{'name': CONTAINER, 'interfaces': [{'name': 'e' * 64, 'alias': 'a' * 64, 'state': 's' * 64, 'type': 't' * 64},
                                                                             {'name': 'eth2', 'alias': '', 'state': '', 'type': ''}]}],
                         'no mac, mtu or ifindex; a container name over 253 characters is left out')

    def test_513_containers_of_300_rows_are_cut_to_512_by_256_and_the_answer_is_smaller_than_the_listing(self):
        # S0 acceptance check (4): a fake runner that bypasses capture()'s 4 MiB bound; the reduction alone keeps the answer small.
        names = ['clab-parity-n%03d' % i for i in range(513)]
        row = {'alias': 'ge-0/0/0', 'state': 'up', 'mac': 'aa:c1:ab:00:00:01', 'mtu': 9500, 'ifindex': 1234, 'type': 'veth'}
        listing = json.dumps([{'name': n, 'interfaces': [dict(row, name='eth%d' % i) for i in range(300)]} for n in names])
        self.interfaces_output = listing
        self.bind_answer = (0, json.dumps({LAB: [self.bind_row(n) for n in names]}))
        result = self.host.interfaces(LAB, {'all': True})
        self.assertEqual(len(result['nodes']), 512)
        self.assertEqual({len(n['interfaces']) for n in result['nodes']}, {256})
        self.assertEqual({tuple(sorted(r)) for n in result['nodes'] for r in n['interfaces']}, {('alias', 'name', 'state', 'type')})
        self.assertLess(len(json.dumps({'result': result}, separators=(',', ':'))), len(listing))

    def test_the_option_whitelist_is_exact_and_refusals_run_nothing(self):
        for options in ({'all': 1}, {'all': True, 'node': 'x'}, {'all': True, 'container': CONTAINER}, {'all': False}, {'all': 'true'}, {'all': None},
                        {'all': True, 'node': NODE, 'container': CONTAINER}):
            with self.assertRaisesRegex(ValueError, '^Unsupported interface options.$', msg=repr(options)): self.host.interfaces(LAB, options)
        for name in (None, '', '../x', '-x', 'a b'):
            with self.assertRaisesRegex(ValueError, 'literal lab/project name', msg=repr(name)): self.host.interfaces(name, {'all': True})
        self.assertEqual((self.log, self.probes, self.merged), ([], [], []), 'a refused request runs nothing')

    def test_the_per_device_form_is_unchanged(self):
        result = self.host.interfaces(LAB, self.options)
        self.assertEqual(self.argvs(), [[self.clab, 'inspect', 'interfaces', '--name', LAB, '-f', 'json']], 'no binding listing on the per-device path')
        self.assertEqual(result['facts']['id'], ID); self.assertEqual(set(result['interfaces'][0]), {'name', 'alias', 'state', 'mac', 'type', 'mtu', 'ifindex'})

    def test_capabilities_report_link_state_from_containerlab_s_own_help(self):
        answers = {}
        def run(argv, **bounds):
            self.log.append((argv, bounds))
            if argv == [self.clab, 'inspect', 'interfaces', '--help']: return answers['help']
            if argv == [self.clab, 'version', '--short']: return 0, '0.79.0\n'
            if '--help' in argv: return 0, '--name --cleanup --graceful --node help'
            return 1, ''
        self.host.run = run
        answers['help'] = (0, 'USAGE\n  containerlab inspect interfaces [--flags]\n --name Lab/Topology name\n')
        self.assertIs(self.host.capabilities()['link_state'], True)
        self.assertIn([self.clab, 'inspect', 'interfaces', '--help'], self.argvs())
        # A containerlab before 0.64 has no `inspect interfaces`: an error, or cobra printing the help of `inspect` itself (exit 0).
        for answer in ((1, ''), (0, 'Error: unknown command "interfaces" for "containerlab inspect"'),
                       (0, 'Usage:\n  containerlab inspect [flags]\n\nFlags:\n  --name string   lab name\n')):
            answers['help'] = answer
            self.assertIs(self.host.capabilities()['link_state'], False, repr(answer))


class NetemShowModeTests(DiagnosticsHarness):
    def test_argv_is_fixed_and_null_means_no_impairments(self):
        result = self.host.netem_show(LAB, self.options)
        self.assertEqual(self.calls, [([self.clab, 'tools', 'netem', 'show', '-n', CONTAINER, '-f', 'json'], {'timeout': 15})])
        self.assertEqual(result, {'facts': self.host.container_of(self.options, LAB), 'impairments': []})
        self.netem_output = json.dumps({'clab-parity-r2': [{'interface': 'eth1', 'delay': '10ms'}]})
        self.assertEqual(self.host.netem_show(LAB, self.options)['impairments'], [], 'another container\'s entry is not this device\'s')

    def test_impairments_are_reduced_to_the_netem_set_keys(self):
        self.netem_output = json.dumps({CONTAINER: [
            {'interface': 'eth1', 'delay': '10ms', 'jitter': '2ms', 'packet_loss': 1.5, 'rate': 1000, 'corruption': 0, 'queue': 'dropped'},
            {'interface': 'eth2', 'loss': 2, 'delay': 'x' * 100}, {'delay': '1ms'}, 'junk', {'interface': ''}]})
        self.assertEqual(self.host.netem_show(LAB, self.options)['impairments'], [
            {'interface': 'eth1', 'delay': '10ms', 'jitter': '2ms', 'loss': 1.5, 'rate': 1000, 'corruption': 0},
            {'interface': 'eth2', 'loss': 2, 'delay': 'x' * 64}])

    def test_failures_are_a_sentence_and_options_are_whitelisted(self):
        self.host.run = lambda argv, **bounds: (1, '')
        with self.assertRaisesRegex(ValueError, 'did not show the impairments'): self.host.netem_show(LAB, self.options)
        self.host.run = lambda argv, **bounds: (0, 'not json')
        with self.assertRaisesRegex(ValueError, 'did not show the impairments'): self.host.netem_show(LAB, self.options)
        self.calls.clear(); self.probes.clear()
        for options in ({**self.options, 'interface': 'eth1'}, {**self.options, 'delay': '10ms'}, []):
            with self.assertRaisesRegex(ValueError, 'Unsupported impairment options', msg=repr(options)): self.host.netem_show(LAB, options)
        self.nothing_ran()


class ImagesContractTests(DiagnosticsHarness):
    """`images` keeps its `images` list exactly as before and adds `details` from the same one command."""
    def test_images_list_is_unchanged_and_details_are_added(self):
        found = self.host.images()
        self.assertEqual(self.calls, [([str(self.docker), 'image', 'ls', '--format', '{{.Repository}}:{{.Tag}}\t{{.ID}}\t{{.Size}}\t{{.CreatedAt}}'], {})])
        self.assertEqual(found['images'], ['ghcr.io/srl-labs/network-multitool:latest', 'n24l/ceos:4.35.0F', 'n24l/cisco_xrv9k:24.3.1'], 'the list the lab builder reads: sorted, dangling and invalid references left out')
        self.assertEqual(found['details'], [
            {'reference': 'ghcr.io/srl-labs/network-multitool:latest', 'id': '3c4d5e6f', 'size': '60.2MB', 'created': '2026-09-01 08:30:00 +0000 UTC'},
            {'reference': 'n24l/ceos:4.35.0F', 'id': 'sha256:0a1b', 'size': '2.1GB', 'created': '2026-10-20 10:00:00 +0000 UTC'},
            {'reference': 'n24l/cisco_xrv9k:24.3.1', 'id': '7a7b', 'size': '4.53GB', 'created': '2026-10-23 02:03:42 +0000 UTC'}])
        self.assertEqual(set(found), {'available', 'images', 'details'}); self.assertTrue(found['available'])
        self.assertEqual([d['reference'] for d in found['details']], found['images'], 'details follow the list, one per reference')

    def test_the_old_one_field_listing_still_yields_the_list(self):
        self.listing = 'n24l/ceos:4.35.0F\n<none>:<none>\nghcr.io/srl-labs/network-multitool:latest\n'
        found = self.host.images()
        self.assertEqual(found['images'], ['ghcr.io/srl-labs/network-multitool:latest', 'n24l/ceos:4.35.0F'])
        self.assertEqual(found['details'][0], {'reference': 'ghcr.io/srl-labs/network-multitool:latest', 'id': '', 'size': '', 'created': ''})

    def test_without_a_docker_client_the_answer_is_unchanged(self):
        self.docker.chmod(0o644)
        self.assertEqual(self.host.images(), {'available': False, 'images': []})
        self.assertFalse(self.host.capabilities()['images'])
        self.docker.chmod(0o755)
        self.host.run = lambda argv, **bounds: (1, '')
        with self.assertRaisesRegex(ValueError, 'did not list its images'): self.host.images()


class BrowseFilesModeTests(DiagnosticsHarness):
    def setUp(self):
        super().setUp()
        self.lab = self.root / 'parity'; node = self.lab / 'clab-parity' / 'r1'; node.mkdir(parents=True)
        (self.lab / 'parity.clab.yml').write_text('name: parity\n'); (self.lab / 'parity.clab.yml.annotations.json').write_text('{}')
        (self.lab / 'README.md').write_text('# lab\n'); (self.lab / 'notes.txt').write_text('n'); (self.lab / '.env').write_text('TOKEN=x')
        (self.lab / 'id_rsa').write_text('-----BEGIN OPENSSH PRIVATE KEY-----'); (self.lab / 'ca.pem').write_text('cert'); (self.lab / 'tool.bin').write_bytes(b'\x7fELF')
        (node / 'startup-config').write_text('hostname r1\n' * 10); (node / 'juniper.conf').write_text('system {}\n'); (node / 'r1.cfg').write_text('!\n')
        (node / 'tls').mkdir(); (node / 'tls' / 'node.key').write_text('key')
        os.symlink(node / 'startup-config', node / 'linked-config.cfg'); os.symlink(node / 'r1.cfg', self.lab / 'startup-config')

    def names(self, folder, options=None): return [e['name'] for e in self.host.browse(str(folder), options)['entries']]

    def test_without_the_option_the_listing_is_unchanged(self):
        entries = self.host.browse(str(self.lab))['entries']
        self.assertEqual([e['name'] for e in entries], ['clab-parity', 'parity.clab.yml'])
        self.assertEqual(entries, [{'name': 'clab-parity', 'path': str(self.lab / 'clab-parity'), 'directory': True}, {'name': 'parity.clab.yml', 'path': str(self.lab / 'parity.clab.yml'), 'directory': False}])
        self.assertEqual(self.names(self.lab, {'files': False}), ['clab-parity', 'parity.clab.yml'])
        self.assertEqual(self.host.browse('', {'files': True}), {'path': '', 'entries': [{'name': str(self.root), 'path': str(self.root), 'directory': True}]})

    def test_with_files_readable_text_files_are_listed_with_sizes_and_kinds(self):
        entries = self.host.browse(str(self.lab), {'files': True})['entries']
        self.assertEqual([(e['name'], e['kind']) for e in entries], [('clab-parity', 'directory'), ('notes.txt', 'file'), ('parity.clab.yml', 'topology'), ('parity.clab.yml.annotations.json', 'file'), ('README.md', 'file')])
        self.assertEqual(entries[0], {'name': 'clab-parity', 'path': str(self.lab / 'clab-parity'), 'directory': True, 'kind': 'directory'})
        self.assertEqual(entries[1], {'name': 'notes.txt', 'path': str(self.lab / 'notes.txt'), 'directory': False, 'kind': 'file', 'size': 1})
        for never in ('.env', 'id_rsa', 'ca.pem', 'tool.bin', 'startup-config'):
            self.assertNotIn(never, [e['name'] for e in entries], never + ' is a dot-file, a key, a certificate, a binary or a symlink')
        node = self.host.browse(str(self.lab / 'clab-parity' / 'r1'), {'files': True})['entries']
        self.assertEqual([(e['name'], e['kind'], e.get('size')) for e in node], [('tls', 'directory', None), ('juniper.conf', 'file', 10), ('r1.cfg', 'file', 2), ('startup-config', 'file', 120)])
        self.assertNotIn('linked-config.cfg', [e['name'] for e in node], 'a symlink is skipped, never followed')
        self.assertEqual(self.names(self.lab / 'clab-parity' / 'r1' / 'tls', {'files': True}), [], 'keys are never listed')

    def test_the_files_option_is_the_only_one_and_must_be_a_boolean(self):
        for options in ({'files': 'yes'}, {'files': 1}, {'files': None}, {'hidden': True}, {'files': True, 'keys': True}, ['files']):
            with self.assertRaisesRegex(ValueError, 'Unsupported browse options', msg=repr(options)): self.host.browse(str(self.lab), options)

    def test_the_entry_cap_holds_in_files_mode(self):
        for i in range(505): (self.lab / ('note-%03d.txt' % i)).write_text('x')
        entries = self.host.browse(str(self.lab), {'files': True})['entries']
        self.assertEqual(len(entries), 500); self.assertEqual(entries[0]['kind'], 'directory')


class ReadModeTests(DiagnosticsHarness):
    def setUp(self):
        super().setUp()
        self.node = self.root / 'clab-parity' / 'r1'; self.node.mkdir(parents=True)
        (self.node / 'startup-config').write_text('hostname r1\n'); (self.node / 'juniper.conf').write_text('system {}\n')
        (self.node / 'README.md').write_bytes(b'\xef\xbb\xbf# r1\n'); (self.node / 'id_rsa').write_text('key'); (self.node / 'ca.pem').write_text('cert')
        (self.node / '.env').write_text('x'); (self.node / 'node.key').write_text('k'); (self.node / 'tool.bin').write_bytes(b'\x7fELF')

    def test_reads_the_configuration_names_and_markdown_with_the_unchanged_shape(self):
        result = self.host.read(str(self.node / 'startup-config'))
        self.assertEqual(result, {'path': str(self.node / 'startup-config'), 'text': 'hostname r1\n', 'sha256': hashlib.sha256(b'hostname r1\n').hexdigest()})
        self.assertEqual(self.host.read(str(self.node / 'juniper.conf'))['text'], 'system {}\n')
        self.assertEqual(self.host.read(str(self.node / 'README.md'))['text'], '# r1\n', 'a BOM is stripped as before')

    def test_refuses_keys_certificates_dot_files_and_binaries(self):
        for name in ('id_rsa', 'ca.pem', '.env', 'node.key', 'tool.bin'):
            with self.assertRaisesRegex(ValueError, 'cannot be viewed', msg=name): self.host.read(str(self.node / name))

    def test_a_symlink_named_startup_config_is_refused_even_after_the_path_check(self):
        target = self.root / 'secret.cfg'; target.write_text('secret')
        link = self.node / 'startup-config'; link.unlink(); link.symlink_to(target)
        with self.assertRaisesRegex(ValueError, 'Symlink'): self.host.read(str(link))
        # The race the design closes: the by-path checks passed on a regular file and the symlink was planted
        # before the open. Simulated by a path() that no longer inspects: the dirfd O_NOFOLLOW open refuses it.
        with patch.object(HostOperations, 'path', lambda self, value, exists=True: Path(value)):
            with self.assertRaisesRegex(ValueError, 'Symlink'): self.host.read(str(link))
        self.assertTrue(target.read_text() == 'secret', 'nothing is written')

    def test_a_symlinked_parent_directory_is_refused_by_the_directory_open_and_a_missing_parent_has_its_sentence(self):
        real = self.root / 'real-dir'; real.mkdir(); (real / 'a.cfg').write_text('x\n')
        link = self.root / 'linked-dir'; link.symlink_to(real)
        # Past the by-path checks (the race): only O_NOFOLLOW on the parent stands between the link and a read.
        with patch.object(HostOperations, 'path', lambda self, value, exists=True: Path(value)):
            # Linux answers ENOTDIR (not ELOOP) for O_DIRECTORY | O_NOFOLLOW on a symlink, so the helper's
            # sentence here is the missing-path one; what is pinned is that the link is refused and nothing is read.
            with self.assertRaisesRegex(ValueError, 'Symlink|no longer exists'): self.host.read(str(link / 'a.cfg'))
            with patch.object(Path, 'is_file', lambda self: True), patch.object(Path, 'stat', lambda self, **kw: os.stat_result((0o100644, 0, 0, 1, 0, 0, 1, 0, 0, 0))):
                with self.assertRaisesRegex(ValueError, 'no longer exists'): self.host.read(str(self.root / 'gone-dir' / 'a.cfg'))

    def test_a_fifo_at_the_name_does_not_hang_and_is_refused(self):
        fifo = self.node / 'r1.cfg'; os.mkfifo(fifo)
        outcome = {}
        def attempt():
            try:
                # Simulate the race past the by-path type check: only the descriptor's fstat stands between the FIFO and a read.
                with patch.object(Path, 'is_file', lambda self: True): self.host.read(str(fifo))
            except ValueError as exc: outcome['error'] = str(exc)
        worker = threading.Thread(target=attempt, daemon=True); worker.start(); worker.join(5)
        self.assertFalse(worker.is_alive(), 'the open must not wait for a writer')
        self.assertIn('regular file', outcome.get('error', ''))
        with self.assertRaisesRegex(ValueError, 'regular file'): self.host.read(str(fifo))

    def test_size_limit_and_missing_file_keep_their_sentences(self):
        big = self.node / 'big.cfg'; big.write_bytes(b'x' * (host_operations.LIMIT + 1))
        with self.assertRaisesRegex(ValueError, 'regular file smaller'): self.host.read(str(big))
        with self.assertRaisesRegex(ValueError, 'no longer exists'): self.host.read(str(self.node / 'gone.cfg'))
        with self.assertRaisesRegex(ValueError, 'outside the trusted'): self.host.read('/etc/passwd')
        exact = self.node / 'exact.cfg'; exact.write_bytes(b'y' * host_operations.LIMIT)
        self.assertEqual(len(self.host.read(str(exact))['text']), host_operations.LIMIT)


class CapabilitiesModeTests(DiagnosticsHarness):
    def test_carries_the_containerlab_release_and_the_diagnostics_flag(self):
        found = self.host.capabilities()
        self.assertIn(([self.clab, 'version', '--short'], {}), self.calls)
        self.assertEqual((found['containerlab'], found['diagnostics']), ('0.79.0', True))
        for key in ('protocol', 'version', 'actions', 'roots', 'network', 'images'): self.assertIn(key, found)
        self.assertEqual(found['version'], host_operations.VERSION)

    def test_a_version_that_does_not_parse_is_left_out(self):
        for answer in ((0, 'fixture'), (1, '0.79.0'), (0, ''), (0, 'v0.79.0'), (0, 'containerlab version 0.79.0')):
            self.version_output = answer
            found = self.host.capabilities()
            self.assertNotIn('containerlab', found, repr(answer)); self.assertTrue(found['diagnostics'])
        self.version_output = (0, '0.79.0-rc1\nextra\n')
        self.assertEqual(self.host.capabilities()['containerlab'], '0.79.0-rc1')


class DispatchTests(unittest.TestCase):
    """main() dispatches the diagnostics modes outside the host lock, adds nothing wider, and the gateway is untouched."""
    def test_main_dispatches_the_diagnostics_modes_outside_the_lock(self):
        # Since C05 main() has one `elif` per mode and one shared locked() helper around the flock (test_host_lifecycle.py
        # pins which four modes go through it); the diagnostics lines are dispatched directly, never through locked().
        source = Path(host_operations.__file__).read_text()
        lines = ["elif mode == 'images': result = host.images()",
                 "elif mode == 'image-check': result = host.image_check(req.get('options') or {})",
                 "elif mode == 'browse': result = host.browse(req.get('path', ''), req.get('options') or {})",
                 "elif mode == 'logs': result = host.logs(req.get('name'), req.get('options') or {})",
                 "elif mode == 'interfaces': result = host.interfaces(req.get('name'), req.get('options') or {})",
                 "elif mode == 'netem-show': result = host.netem_show(req.get('name'), req.get('options') or {})"]
        for line in lines:
            self.assertEqual(source.count(line), 1, line)
            self.assertNotIn('locked(', line)
        self.assertEqual(source.count('fcntl.flock('), 1, 'one host lock')
        self.assertIn('fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)', source)
        modes = re.findall(r"^\s+elif mode == '([a-z-]+)'", source, re.MULTILINE)
        self.assertEqual(modes, ['read', 'browse', 'popular', 'images', 'image-check', 'logs', 'interfaces', 'netem-show', 'netem-show-all', 'apply-plan', 'netem-set', 'netem-reset', 'preview', 'run'])
        self.assertEqual(len(modes), len(set(modes)), 'one elif per mode')

    def run_main(self, request, **methods):
        """main() with the host lock held by someone else and a stub runner; returns (exit code, answer)."""
        import contextlib, fcntl, io
        from contextlib import redirect_stdout
        from types import SimpleNamespace
        root = Path(tempfile.mkdtemp()); self.addCleanup(lambda: __import__('shutil').rmtree(root, ignore_errors=True))
        config = dict(clab='/usr/bin/containerlab', docker=str(root / 'no-docker'), roots=[str(root)], projects=str(root))
        real_path, real_open = host_operations.Path, open
        class ConfigFile:
            def read_text(self): return json.dumps(config)
        def fake_path(value): return ConfigFile() if value == '/etc/clab-manager/operations.json' else real_path(value)
        lock_file = root / 'operations.lock'
        def fake_open(name, *args, **kwargs): return real_open(lock_file if name == '/run/clab-manager-operations.lock' else name, *args, **kwargs)
        stdin = SimpleNamespace(buffer=io.BytesIO(json.dumps(request).encode() + b'\n')); output = io.StringIO()
        with open(lock_file, 'a') as held:
            fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with patch.object(host_operations, 'Path', side_effect=fake_path), patch.object(host_operations, 'signal'), \
                 patch.object(host_operations.sys, 'stdin', stdin), patch.object(host_operations, 'open', fake_open, create=True), \
                 patch.object(host_operations.subprocess, 'Popen') as popen, redirect_stdout(output), \
                 (patch.multiple(HostOperations, **methods) if methods else contextlib.nullcontext()):
                code = host_operations.main()
        popen.assert_not_called()
        return code, json.loads(output.getvalue())

    def test_the_read_only_modes_answer_while_the_host_lock_is_held(self):
        code, answer = self.run_main({'mode': 'images'}, images=lambda self: {'available': False, 'images': []})
        self.assertEqual((code, answer), (0, {'result': {'available': False, 'images': []}}))
        code, answer = self.run_main({'mode': 'logs', 'name': 'parity', 'options': {}}, logs=lambda self, name, options: {'facts': {'present': False}})
        self.assertEqual((code, answer), (0, {'result': {'facts': {'present': False}}}))
        code, answer = self.run_main({'mode': 'preview', 'action': 'deploy', 'name': 'x', 'path': '/x', 'options': {}})
        self.assertEqual((code, answer), (1, {'error': 'Another host lab operation is running.'}), 'the lock really is held')

    def test_nothing_execs_follows_writes_or_contacts_a_device(self):
        source = Path(host_operations.__file__).read_text()
        for forbidden in ("DOCKER, 'exec'", "DOCKER, 'pull'", "DOCKER, 'rmi'", "DOCKER, 'run'],", "DOCKER, 'push'", "DOCKER, 'load'", "DOCKER, 'build'", "DOCKER, 'start'",
                          "DOCKER, 'stop'", "DOCKER, 'kill'", "DOCKER, 'cp'", "'logs', '-f'", "'--follow'", "'nsenter'", "'exec'", "'ssh'", "paramiko"):
            self.assertNotIn(forbidden, source, forbidden)
        # C05's two mutating netem commands exist exactly once each, in their own modes under the host lock; the
        # read-only modes of this chunk still build neither.
        self.assertEqual(source.count("'tools', 'netem', 'set', '-n'"), 1); self.assertEqual(source.count("'tools', 'netem', 'reset', '-n'"), 1)
        for method in ('def logs(', 'def interfaces(', 'def netem_show(', 'def netem_rows(', 'def counters('):
            body = source[source.index(method):source.index('\n    def ', source.index(method) + 1)]
            self.assertNotIn("'set'", body, method); self.assertNotIn("'reset'", body, method)
        self.assertNotIn("'--since', options", source, 'only the validated stamp reaches argv')
        self.assertIn("facts['id']]", source, 'docker logs reads the inspected Id')
        self.assertIn("'--type', 'container'", source)
        self.assertIn("os.O_RDONLY | os.O_DIRECTORY)", source, 'the /proc directory descriptor')

    def test_the_gateway_is_untouched_by_this_chunk(self):
        text = GATEWAY.read_text(encoding='utf-8')
        self.assertEqual(re.findall(r'^\s+(\S.*?)\) (?:exec|echo) ', text, re.MULTILINE), ARMS)
        self.assertIn('clab-manager-operations) exec sudo -n /usr/local/sbin/clab-manager-operate ;;', text, 'the new modes travel as request lines on this name')
        for mode in ('logs', 'interfaces', 'netem', 'browse', 'images', 'diagnostics'):
            self.assertNotIn(mode, text)

    def test_the_helper_compiles_and_still_refuses_an_unknown_mode(self):
        done = subprocess.run([sys.executable, '-m', 'py_compile', host_operations.__file__], capture_output=True)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("else: raise ValueError('Unknown request mode.')", Path(host_operations.__file__).read_text())


if __name__ == '__main__':
    unittest.main()
