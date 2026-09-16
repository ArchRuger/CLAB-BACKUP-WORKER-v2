"""Orchestration tests for deploy/scaffold-lab.py (the manager API is mocked)."""
import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('scaffold_lab', Path(__file__).resolve().parents[2] / 'deploy/scaffold-lab.py')
scaffold = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scaffold)


def args(**kwargs):
    base = {'manager': 'http://m', 'lab': ''}
    base.update(kwargs)
    return type('Args', (), base)()


class ScaffoldLabTests(unittest.TestCase):
    def setUp(self):
        self.calls = []

        def fake_api(manager, path, method='GET', body=None):
            self.calls.append((method, path, body))
            if path == '/state':
                return 200, {'labs': [{'id': 'lab1', 'name': 'bgp-core'}]}
            if path == '/labs/lab1/git':
                return 200, {'binding': {'binding_id': 'bid'}}
            if path.endswith('/folders'):
                return 200, {'repository': {'id': 'x', 'prefix': (body or {}).get('prefix')}}
            if path.endswith('/git/destination'):
                return 200, {'binding': {}, 'job': None}
            if path.endswith('/git/save'):
                return 200, {'id': 'job1', 'status': 'queued'}
            if path.startswith('/git/jobs/'):
                return 200, {'status': 'synced', 'commit': 'a' * 40}
            raise AssertionError(path)

        patch.object(scaffold, 'api', fake_api).start()
        self.addCleanup(patch.stopall)

    def folders(self):
        return [body['prefix'] for method, path, body in self.calls if path.endswith('/folders')]

    def destinations(self):
        return [body['prefix'] for method, path, body in self.calls if path.endswith('/git/destination')]

    def test_init_creates_reference_and_work_then_binds_to_work(self):
        scaffold.cmd_init(args(slug='bgp-core', states='start,solution,broken-01'))
        self.assertEqual(self.folders(), ['bgp-core/reference/start', 'bgp-core/reference/solution',
                                          'bgp-core/reference/broken-01', 'bgp-core/work'])
        self.assertEqual(self.destinations(), ['bgp-core/work'])

    def test_snapshot_saves_into_reference_then_rebinds_to_work(self):
        scaffold.cmd_snapshot(args(slug='bgp-core', state='broken-01'))
        self.assertEqual(self.destinations(), ['bgp-core/reference/broken-01', 'bgp-core/work'])
        self.assertTrue(any(path.endswith('/git/save') for method, path, body in self.calls))

    def test_rejects_unsafe_names(self):
        with self.assertRaises(SystemExit):
            scaffold.cmd_init(args(slug='BGP Core', states='start'))
        with self.assertRaises(SystemExit):
            scaffold.cmd_snapshot(args(slug='bgp-core', state='../etc'))

    def test_init_tolerates_lab_already_bound_to_work(self):
        def bound(manager, path, method='GET', body=None):
            if path == '/state':
                return 200, {'labs': [{'id': 'lab1', 'name': 'bgp-core'}]}
            if path == '/labs/lab1/git':
                return 200, {'binding': {'binding_id': 'bid'}}
            if path.endswith('/folders'):
                return 200, {'repository': {'prefix': (body or {}).get('prefix')}}
            if path.endswith('/git/destination'):
                return 409, {'detail': 'This lab already saves to that folder.'}
            raise AssertionError(path)
        patch.object(scaffold, 'api', bound).start()
        scaffold.cmd_init(args(slug='bgp-core', states='start'))  # must not raise

    def test_init_is_re_runnable_when_folders_exist(self):
        def existing(manager, path, method='GET', body=None):
            if path == '/state':
                return 200, {'labs': [{'id': 'lab1', 'name': 'bgp-core'}]}
            if path == '/labs/lab1/git':
                return 200, {'binding': {'binding_id': 'bid'}}
            if path.endswith('/folders'):
                return 409, {'detail': 'This folder is already registered.'}
            if path.endswith('/git/destination'):
                return 200, {'binding': {}, 'job': None}
            raise AssertionError(path)
        patch.object(scaffold, 'api', existing).start()
        scaffold.cmd_init(args(slug='bgp-core', states='start'))  # must not raise


if __name__ == '__main__':
    unittest.main()
