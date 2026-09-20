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
        # A faithful manager: a save a person starts never uploads by itself, it ends waiting for the
        # review; a waiting save refuses a folder change; an upload must state the review.
        self.job = None
        self.after_upload = 'synced'
        pending = ('review_pending', 'committed', 'push_pending', 'export_pending')

        def fake_api(manager, path, method='GET', body=None):
            self.calls.append((method, path, body))
            if path == '/state':
                return 200, {'labs': [{'id': 'lab1', 'name': 'bgp-core'}]}
            if path == '/labs/lab1/git':
                return 200, {'binding': {'binding_id': 'bid'}}
            if path.endswith('/folders'):
                return 200, {'repository': {'id': 'x', 'prefix': (body or {}).get('prefix')}}
            if path.endswith('/git/destination'):
                if self.job and self.job['status'] in pending:
                    return 409, {'detail': 'Finish pending Git saves, or choose Keep snapshot only, before changing this lab.'}
                return 200, {'binding': {}, 'job': None}
            if path.endswith('/git/save'):
                self.job = {'id': 'job1', 'status': 'review_pending', 'commit': 'a' * 40, 'pushed': False,
                            'changed_files': ['bgp-core/reference/broken-01/latest/r1.cfg']}
                return 200, {'id': 'job1', 'status': 'queued'}
            if path.endswith('/retry'):
                if not (body or {}).get('reviewed'):
                    return 409, {'detail': 'Review the changes of this save before uploading it.'}
                self.job.update(status=self.after_upload, pushed=self.after_upload == 'synced')
                return 200, dict(self.job, status='queued')
            if path.endswith('/dismiss'):
                if not (body or {}).get('acknowledge'):
                    return 400, {'detail': 'Confirm keeping the snapshot without tracking its pending Git save.'}
                self.job['status'] = 'dismissed'
                return 200, dict(self.job)
            if path.startswith('/git/jobs/'):
                return 200, dict(self.job)
            raise AssertionError(path)

        patch.object(scaffold, 'api', fake_api).start()
        self.addCleanup(patch.stopall)

    def paths(self):
        return [path for method, path, body in self.calls]

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
        scaffold.cmd_snapshot(args(slug='bgp-core', state='broken-01', yes=True))
        self.assertEqual(self.destinations(), ['bgp-core/reference/broken-01', 'bgp-core/work'])
        self.assertTrue(any(path.endswith('/git/save') for method, path, body in self.calls))

    def test_snapshot_states_the_review_and_uploads_before_it_rebinds(self):
        scaffold.cmd_snapshot(args(slug='bgp-core', state='broken-01', yes=True))
        retry = [(path, body) for method, path, body in self.calls if path.endswith('/retry')]
        self.assertEqual(retry, [('/git/jobs/job1/retry', {'push': True, 'reviewed': True})])
        paths = self.paths()
        self.assertLess(paths.index('/git/jobs/job1/retry'), len(paths) - 1 - paths[::-1].index('/labs/lab1/git/destination'))
        self.assertEqual(self.job['status'], 'synced')

    def test_snapshot_asks_and_a_no_keeps_the_state_on_the_vm_and_still_rebinds(self):
        with patch.object(scaffold.sys.stdin, 'isatty', return_value=True), patch('builtins.input', return_value='n'), \
                patch('builtins.print') as shown:
            scaffold.cmd_snapshot(args(slug='bgp-core', state='broken-01'))
        self.assertFalse(any(path.endswith('/retry') for path in self.paths()))
        self.assertIn('/git/jobs/job1/dismiss', self.paths())
        self.assertEqual(self.destinations(), ['bgp-core/reference/broken-01', 'bgp-core/work'])
        text = ' '.join(str(call.args[0]) for call in shown.call_args_list if call.args)
        self.assertIn('r1.cfg', text)                       # the changed files are shown before the question
        self.assertIn('kept on the lab VM only', text)

    def test_snapshot_without_a_terminal_needs_yes_and_changes_nothing(self):
        with patch.object(scaffold.sys.stdin, 'isatty', return_value=False), self.assertRaises(SystemExit) as stop:
            scaffold.cmd_snapshot(args(slug='bgp-core', state='broken-01'))
        self.assertIn('--yes', str(stop.exception))
        self.assertEqual(self.destinations(), [])
        self.assertFalse(any(path.endswith('/git/save') for path in self.paths()))

    def test_snapshot_whose_upload_fails_says_the_lab_still_saves_to_the_reference_folder(self):
        self.after_upload = 'push_pending'
        with self.assertRaises(SystemExit) as stop:
            scaffold.cmd_snapshot(args(slug='bgp-core', state='broken-01', yes=True))
        self.assertIn('STILL SAVES TO bgp-core/reference/broken-01', str(stop.exception))
        self.assertIn('init bgp-core', str(stop.exception))
        self.assertEqual(self.destinations(), ['bgp-core/reference/broken-01'])   # no rebind was attempted

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
