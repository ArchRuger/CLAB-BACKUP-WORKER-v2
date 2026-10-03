"""Orchestration tests for deploy/scaffold-lab.py (the manager API is mocked)."""
import importlib.util
import json
import os
import threading
import unittest
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
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

    def test_snapshot_whose_save_cannot_start_rebinds_to_work(self):
        # The manager is busy (409) as the save starts: the lab was already pointed at the reference folder.
        real = scaffold.api

        def busy(manager, path, method='GET', body=None):
            if path.endswith('/git/save'):
                self.calls.append((method, path, body))
                return 409, {'detail': 'Another operation is running.'}
            return real(manager, path, method, body)
        real = scaffold.api
        patch.object(scaffold, 'api', busy).start()
        with self.assertRaises(SystemExit) as stop:
            scaffold.cmd_snapshot(args(slug='bgp-core', state='broken-01', yes=True))
        self.assertEqual(self.destinations(), ['bgp-core/reference/broken-01', 'bgp-core/work'])
        self.assertIn('save failed to start', str(stop.exception))
        self.assertIn('rebound to bgp-core/work', str(stop.exception))

    def test_snapshot_whose_poll_times_out_says_where_the_lab_saves_when_the_rebind_is_refused(self):
        # A save still pending refuses the folder change (the faithful fake), so the lab stays on the reference
        # folder; the person must be told, with the way out.
        def stuck(manager, job_id, timeout=300):
            self.job['status'] = 'push_pending'
            scaffold.die('timed out waiting for Git job %s.' % job_id)
        patch.object(scaffold, 'poll_git', stuck).start()
        with self.assertRaises(SystemExit) as stop:
            scaffold.cmd_snapshot(args(slug='bgp-core', state='broken-01', yes=True))
        text = str(stop.exception)
        self.assertIn('timed out waiting for Git job', text)
        self.assertIn('STILL SAVES TO bgp-core/reference/broken-01', text)
        self.assertIn('init bgp-core', text)

    def test_snapshot_stopped_at_the_question_with_ctrl_c_or_end_of_input_says_where_the_lab_saves(self):
        # The save waits for the review, so it blocks the folder change back: the person must be told.
        for interruption in (KeyboardInterrupt(), EOFError()):
            with self.subTest(interruption=type(interruption).__name__):
                self.calls.clear()
                self.job = None
                with patch.object(scaffold.sys.stdin, 'isatty', return_value=True), \
                        patch('builtins.input', side_effect=interruption), patch('builtins.print'), \
                        self.assertRaises(SystemExit) as stop:
                    scaffold.cmd_snapshot(args(slug='bgp-core', state='broken-01'))
                text = str(stop.exception)
                self.assertIn('stopped', text)
                self.assertIn('STILL SAVES TO bgp-core/reference/broken-01', text)
                self.assertIn('init bgp-core', text)
                self.assertFalse(any(path.endswith('/retry') for path in self.paths()))   # nothing was uploaded

    def test_snapshot_whose_dismiss_fails_reports_the_binding_and_rebinds_when_it_can(self):
        real = scaffold.api

        def refuse_dismiss(manager, path, method='GET', body=None):
            if path.endswith('/dismiss'):
                self.calls.append((method, path, body))
                return 500, {'detail': 'boom'}
            return real(manager, path, method, body)
        patch.object(scaffold, 'api', refuse_dismiss).start()
        with patch.object(scaffold.sys.stdin, 'isatty', return_value=True), patch('builtins.input', return_value='n'), \
                patch('builtins.print'), self.assertRaises(SystemExit) as stop:
            scaffold.cmd_snapshot(args(slug='bgp-core', state='broken-01'))
        text = str(stop.exception)
        self.assertIn('could not set the save aside', text)
        self.assertIn('STILL SAVES TO bgp-core/reference/broken-01', text)   # the save is still pending, so the rebind is refused

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


class ApiProxyTests(unittest.TestCase):
    """api() reaches the manager directly: an exported http_proxy never gets the loopback request."""

    def serve(self, reply):
        hits = []

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                hits.append(self.path)
                body = json.dumps(reply).encode()
                self.send_response(200)
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass
        server = HTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return server, hits

    def test_loopback_manager_url_ignores_the_proxy_environment(self):
        manager, manager_hits = self.serve({'labs': []})
        proxy, proxy_hits = self.serve({'proxy': 'answered'})
        # no_proxy is emptied too: a shell that exports no_proxy=127.0.0.1 would bypass the proxy by itself
        # and the test would prove nothing.
        env = {'http_proxy': 'http://127.0.0.1:%d' % proxy.server_port, 'HTTP_PROXY': 'http://127.0.0.1:%d' % proxy.server_port,
               'no_proxy': '', 'NO_PROXY': ''}
        with patch.dict(os.environ, env), patch.object(urllib.request, '_opener', None):
            status, body = scaffold.api('http://127.0.0.1:%d' % manager.server_port, '/state')
        self.assertEqual((status, body), (200, {'labs': []}))
        self.assertEqual(proxy_hits, [])
        self.assertEqual(manager_hits, ['/api/state'])


if __name__ == '__main__':
    unittest.main()
