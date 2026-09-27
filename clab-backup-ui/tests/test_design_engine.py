import importlib.util
import os
import shutil
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch

import app.design_engine as design_engine
from app.design_engine import (ARGV, EngineError, engine_status, run_generation)

TOPOLOGY = {
    'name': 'engine-test', 'provider': 'external', 'module': ['ospf'],
    'nodes': {
        'r1': {'device': 'eos', 'id': 1, 'mgmt': {'ipv4': '172.20.20.11', 'ifname': 'Management0'}},
        'r2': {'device': 'vjunos-switch', 'id': 2, 'mgmt': {'ipv4': '172.20.20.12'}},
    },
    'links': [{'r1': {'ifname': 'Ethernet1'}, 'r2': {'ifname': 'ge-0/0/0'}, 'prefix': {'ipv4': '10.9.9.0/31'}}],
}


def has_real_netlab():
    return shutil.which('netlab') is not None


@unittest.skipUnless(has_real_netlab(), 'netlab is not on PATH for this test run')
class RealEngineTests(unittest.TestCase):
    """Runs the pinned engine for real; no mocks. Requires `netlab` on PATH, as CLAUDE.md's
    PATH="$PWD/.venv/bin:$PATH" prefix provides."""

    def setUp(self):
        self.work_root = tempfile.mkdtemp(prefix='design-engine-test-')
        self.addCleanup(shutil.rmtree, self.work_root, ignore_errors=True)

    def test_successful_run_artifacts_and_layout(self):
        result = run_generation(self.work_root, TOPOLOGY)
        try:
            self.assertTrue(result['ok'], result)
            self.assertEqual(result['exit_code'], 0)
            self.assertEqual(result['errors'], [])

            self.assertIn('r1', result['artifacts'])
            self.assertIn('r2', result['artifacts'])
            r1_modules = [module for module, _ in result['artifacts']['r1']]
            r2_modules = [module for module, _ in result['artifacts']['r2']]
            self.assertEqual(r1_modules, ['normalize', 'initial', 'ospf'])
            self.assertEqual(r2_modules, ['initial', 'ospf'])

            r1_initial = dict(result['artifacts']['r1'])['initial']
            self.assertIn('interface Management0', r1_initial)
            self.assertIn('ip address 10.9.9.0/31', r1_initial)

            self.assertEqual(result['transformed']['nodes']['r1']['id'], 1)

            # engine_version, from the transformed topology's _netlab_version.
            self.assertRegex(result['engine_version'], r'^\d+\.\d+$')

            self.assertGreaterEqual(result['duration'], 0.0)

            # Workdir layout: topology.yml, home/.netlab/, node_files/.
            workdir = result['workdir']
            self.assertTrue(os.path.isfile(os.path.join(workdir, 'topology.yml')))
            self.assertTrue(os.path.isdir(os.path.join(workdir, 'home', '.netlab')))
            self.assertTrue(os.path.isdir(os.path.join(workdir, 'node_files')))

            # The usage-statistics opt-out netlab itself supports: unchanged by a successful run.
            stats_path = os.path.join(workdir, 'home', '.netlab', 'stats.json')
            with open(stats_path, 'r', encoding='utf-8') as handle:
                stats_text = handle.read()
            self.assertIn('"_disabled": true', stats_text)
            self.assertNotIn('"cli"', stats_text)
        finally:
            shutil.rmtree(result['workdir'], ignore_errors=True)

    def test_unsupported_module_error(self):
        topology = {'name': 'engine-test', 'provider': 'external', 'module': ['eigrp'],
                    'nodes': {'r1': {'device': 'eos', 'id': 1,
                                     'mgmt': {'ipv4': '172.20.20.11', 'ifname': 'Management0'}}},
                    'links': []}
        result = run_generation(self.work_root, topology)
        try:
            self.assertFalse(result['ok'])
            self.assertNotEqual(result['exit_code'], 0)
            self.assertIsNotNone(result['exit_code'])
            self.assertTrue(any('does not support module eigrp' in line for line in result['errors']),
                             result['errors'])
            self.assertEqual(result['artifacts'], {})
            self.assertEqual(result['transformed'], {})
        finally:
            shutil.rmtree(result['workdir'], ignore_errors=True)

    def test_unknown_device_error(self):
        topology = {'name': 'engine-test', 'provider': 'external', 'module': ['ospf'],
                    'nodes': {'r1': {'device': 'nonexistent-device-xyz', 'id': 1,
                                     'mgmt': {'ipv4': '172.20.20.11'}}},
                    'links': []}
        result = run_generation(self.work_root, topology)
        try:
            self.assertFalse(result['ok'])
            self.assertIsNotNone(result['exit_code'])
            self.assertNotEqual(result['exit_code'], 0)
            self.assertTrue(result['errors'])
            self.assertTrue(any('device type' in line.lower() for line in result['errors']), result['errors'])
        finally:
            shutil.rmtree(result['workdir'], ignore_errors=True)

    def test_engine_status_reports_real_netlab(self):
        status = engine_status()
        self.assertTrue(status['available'], status)
        self.assertRegex(status['version'], r'^\d+\.\d+$')
        self.assertTrue(status['path'])
        self.assertEqual(status['diagnostic'], '')


class CallerErrorTests(unittest.TestCase):

    def test_topology_not_a_dict_raises(self):
        with tempfile.TemporaryDirectory() as work_root:
            with self.assertRaises(EngineError):
                run_generation(work_root, ['not', 'a', 'dict'])

    def test_missing_work_root_raises(self):
        with self.assertRaises(EngineError):
            run_generation('/nonexistent/path/for/design-engine-tests', TOPOLOGY)


class EngineStatusTests(unittest.TestCase):

    def test_available_false_when_not_on_path(self):
        empty_dir = tempfile.mkdtemp(prefix='design-engine-empty-path-')
        self.addCleanup(shutil.rmtree, empty_dir, ignore_errors=True)
        with patch.dict(os.environ, {'PATH': empty_dir}, clear=False):
            status = engine_status()
        self.assertFalse(status['available'])
        self.assertEqual(status['path'], '')
        self.assertIn('not installed', status['diagnostic'])


class EnvironmentAndArgvContractTests(unittest.TestCase):
    """Patches subprocess.Popen to inspect exactly what run_generation launches, without running the
    real engine."""

    def setUp(self):
        self.work_root = tempfile.mkdtemp(prefix='design-engine-contract-')
        self.addCleanup(shutil.rmtree, self.work_root, ignore_errors=True)

    def _fake_popen_success(self, captured):
        class FakeProcess:
            pid = 424242

            def __init__(self):
                self.stdout = _EmptyStream()
                self.stderr = _EmptyStream()

            def wait(self, timeout=None):
                return 0

        def fake_popen(argv, cwd=None, env=None, stdin=None, stdout=None, stderr=None,
                       start_new_session=None):
            captured['argv'] = argv
            captured['cwd'] = cwd
            captured['env'] = env
            captured['stdin'] = stdin
            captured['start_new_session'] = start_new_session
            return FakeProcess()

        return fake_popen

    def test_argv_env_cwd_stdin_and_session(self):
        captured = {}
        with patch.dict(os.environ, {'NETLAB_DEFAULTS_DEVICE': 'eos'}, clear=False):
            with patch('subprocess.Popen', side_effect=self._fake_popen_success(captured)):
                # yaml.safe_load('' ) is None: guard against the fake transformed.yaml not existing
                # by writing one ourselves, matching what a real successful run leaves behind.
                result = run_generation(self.work_root, TOPOLOGY)

        self.assertEqual(captured['argv'], list(ARGV))
        self.assertEqual(captured['cwd'], result['workdir'])
        self.assertIs(captured['stdin'], subprocess.DEVNULL)
        self.assertTrue(captured['start_new_session'])

        env = captured['env']
        self.assertEqual(set(env.keys()), {'PATH', 'HOME', 'LANG', 'PYTHONDONTWRITEBYTECODE'})
        self.assertEqual(env['LANG'], 'C.UTF-8')
        self.assertEqual(env['PYTHONDONTWRITEBYTECODE'], '1')
        self.assertEqual(env['PATH'], os.environ['PATH'])
        self.assertTrue(env['HOME'].startswith(result['workdir']))
        self.assertNotIn('NETLAB_DEFAULTS_DEVICE', env)
        for key in env:
            self.assertFalse(key.startswith('NETLAB_'))

    def test_only_create_is_ever_run_never_lifecycle_commands(self):
        captured = {}
        with patch('subprocess.Popen', side_effect=self._fake_popen_success(captured)) as popen:
            run_generation(self.work_root, TOPOLOGY)
        self.assertEqual(popen.call_count, 1)
        argv = captured['argv']
        self.assertIn('create', argv)
        for forbidden in ('up', 'down', 'connect', 'capture'):
            self.assertNotIn(forbidden, argv)


class _EmptyStream:
    def read(self, n=-1):
        return b''

    def close(self):
        pass


class TimeoutAndStoppingTests(unittest.TestCase):

    def setUp(self):
        self.work_root = tempfile.mkdtemp(prefix='design-engine-timeout-')
        self.addCleanup(shutil.rmtree, self.work_root, ignore_errors=True)

    class _NeverExitsProcess:
        pid = 999999

        def __init__(self):
            self.stdout = _EmptyStream()
            self.stderr = _EmptyStream()
            self.killed_with = []

        def wait(self, timeout=None):
            raise subprocess.TimeoutExpired(cmd='netlab', timeout=timeout or 0)

    def test_timeout_kills_group_and_reports_error(self):
        process = self._NeverExitsProcess()
        killed = []

        def fake_killpg(pid, sig):
            killed.append((pid, sig))
            if sig.name == 'SIGKILL':
                # Simulate the process finally dying so the final wait() succeeds.
                process.wait = lambda timeout=None: 0

        with patch('subprocess.Popen', return_value=process):
            with patch('os.killpg', side_effect=fake_killpg):
                result = run_generation(self.work_root, TOPOLOGY, timeout=0.3)

        self.assertFalse(result['ok'])
        self.assertIsNone(result['exit_code'])
        self.assertIn(design_engine.TIMED_OUT, result['errors'])
        self.assertTrue(killed)

    def test_stopping_event_set_before_run_aborts(self):
        process = self._NeverExitsProcess()

        def fake_killpg(pid, sig):
            if sig.name == 'SIGKILL':
                process.wait = lambda timeout=None: 0

        stopping = threading.Event()
        stopping.set()

        with patch('subprocess.Popen', return_value=process):
            with patch('os.killpg', side_effect=fake_killpg):
                result = run_generation(self.work_root, TOPOLOGY, timeout=120, stopping=stopping)

        self.assertFalse(result['ok'])
        self.assertIsNone(result['exit_code'])
        self.assertIn(design_engine.TIMED_OUT, result['errors'])


class StatsModuleHasNoNetworkCodeTests(unittest.TestCase):
    """Contract test: netlab's usage-statistics module (netsim/utils/stats.py) never opens a socket
    or makes an HTTP request; the only thing our opt-out relies on is that write_stats() checks the
    _disabled flag before touching the file, and that no code path here reaches the network."""

    def test_stats_module_has_no_network_primitives(self):
        spec = importlib.util.find_spec('netsim.utils.stats')
        self.assertIsNotNone(spec, 'netsim is not installed in this venv')
        self.assertIsNotNone(spec.origin)
        with open(spec.origin, 'r', encoding='utf-8') as handle:
            source = handle.read()
        for forbidden in ('requests', 'urllib', 'socket', 'http'):
            self.assertNotIn(forbidden, source,
                              f'netsim/utils/stats.py unexpectedly mentions {forbidden!r}')




class EngineStatusBoundaryTests(unittest.TestCase):
    """engine_status() answers from metadata: no child process, nothing written into HOME."""

    def test_engine_status_starts_no_process_and_writes_nothing_into_home(self):
        home = tempfile.mkdtemp(prefix='design-engine-status-home-')
        self.addCleanup(shutil.rmtree, home, ignore_errors=True)
        with patch.dict(os.environ, {'HOME': home}), \
             patch('subprocess.run', side_effect=AssertionError('engine_status must not start a process')), \
             patch('subprocess.Popen', side_effect=AssertionError('engine_status must not start a process')):
            status = engine_status()
        self.assertEqual(os.listdir(home), [], 'nothing may be written into the caller HOME')
        if shutil.which('netlab'):
            self.assertTrue(status['available'])
            self.assertRegex(status['version'], r'^\d+(\.\d+)+$')


class CrashContractTests(unittest.TestCase):

    def test_a_traceback_becomes_one_controlled_line_without_paths(self):
        from app.design_engine import _error_lines, UNEXPECTED_FAILURE
        text = 'Traceback (most recent call last):\n  File "/usr/local/lib/python3.12/site-packages/netsim/x.py", line 5, in f\n    raise BoxTypeError("bad")\nbox.exceptions.BoxTypeError: bad value at /data/network-design/work/abc\n'
        self.assertEqual(_error_lines(text), [UNEXPECTED_FAILURE + ' (box.exceptions.BoxTypeError).'])
        self.assertEqual(_error_lines('IncorrectValue in modules: x\nFatal error in netlab: y\n'), ['IncorrectValue in modules: x', 'Fatal error in netlab: y'])
        self.assertEqual(_error_lines(''), [])

if __name__ == '__main__':
    unittest.main()
