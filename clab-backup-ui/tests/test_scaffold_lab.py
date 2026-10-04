"""Orchestration tests for deploy/scaffold-lab.py (the manager API is mocked)."""
import http.client
import importlib.util
import io
import json
import os
import threading
import unittest
import urllib.error
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
        # A faithful manager: a save a person starts never uploads by itself, it ends waiting for the review; a
        # waiting save does not stop a folder change; an upload must state the review and carry the HEAD the review
        # showed, and goes through the save at HEAD.
        self.job = None
        self.after_upload = 'synced'
        self.head = 'a' * 40                 # the HEAD of the repository on the VM
        self.also = []                       # what the review says the upload also sends
        self.upload_job = 'job1'
        self.lands = 0                       # how many more saves land between a review and its upload
        self.busy = False                    # the manager refuses a folder change (other work is running)

        def fake_api(manager, path, method='GET', body=None):
            self.calls.append((method, path, body))
            if path == '/state':
                return 200, {'labs': [{'id': 'lab1', 'name': 'bgp-core'}]}
            if path == '/labs/lab1/git':
                return 200, {'binding': {'binding_id': 'bid'}}
            if path.endswith('/folders'):
                return 200, {'repository': {'id': 'x', 'prefix': (body or {}).get('prefix')}}
            if path.endswith('/git/destination'):
                if self.busy:
                    return 409, {'detail': 'Wait for the active backup, Git save or lab operation to finish.'}
                return 200, {'saved': True, 'binding': {}, 'job': None}
            if path.endswith('/git/save'):
                self.job = {'id': 'job1', 'status': 'review_pending', 'commit': 'a' * 40, 'pushed': False,
                            'changed_files': ['bgp-core/reference/broken-01/latest/r1.cfg']}
                return 200, {'id': 'job1', 'status': 'queued'}
            if path.endswith('/git/compare'):
                return 200, {'files': [], 'summary': None, 'head': self.head, 'upload_job': self.upload_job, 'also_sends': list(self.also)}
            if path.endswith('/retry'):
                if not (body or {}).get('reviewed') or not (body or {}).get('head'):
                    return 409, {'detail': 'Review the changes of this save before uploading it.'}
                if self.lands:
                    self.lands -= 1; self.head = chr(ord(self.head[0]) + 1) * 40
                    self.also = self.also + [{'job_id': 'late%d' % self.lands, 'lab': 'other-lab', 'name': 'Landed meanwhile', 'kind': 'save', 'target': 'latest'}]
                if body['head'] != self.head:
                    return 409, {'detail': 'Another save was made in this repository. Look at the changes again.'}
                self.job.update(status=self.after_upload, pushed=self.after_upload == 'synced')
                return 200, dict(self.job, id=path.split('/')[3], status='queued')
            if path.startswith('/git/jobs/'):
                return 200, dict(self.job, id=path.split('/')[3])
            raise AssertionError(path)

        self.real_api, self.fake_api = scaffold.api, fake_api
        patch.object(scaffold, 'api', fake_api).start()
        self.addCleanup(patch.stopall)

    def printed(self, shown):
        return [str(call.args[0]) for call in shown.call_args_list if call.args]

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
        # The upload carries the HEAD the review showed (was: {'push': True, 'reviewed': True} without it, which the
        # manager now refuses) and goes to the save the review names.
        scaffold.cmd_snapshot(args(slug='bgp-core', state='broken-01', yes=True))
        retry = [(path, body) for method, path, body in self.calls if path.endswith('/retry')]
        self.assertEqual(retry, [('/git/jobs/job1/retry', {'push': True, 'reviewed': True, 'head': 'a' * 40})])
        paths = self.paths()
        self.assertLess(paths.index('/labs/lab1/git/compare'), paths.index('/git/jobs/job1/retry'), 'the review comes before the upload')
        self.assertLess(paths.index('/git/jobs/job1/retry'), len(paths) - 1 - paths[::-1].index('/labs/lab1/git/destination'))
        self.assertEqual(self.job['status'], 'synced')

    def test_snapshot_asks_the_manager_for_the_review_and_names_every_save_the_upload_also_sends(self):
        self.also = [{'job_id': 'j2', 'lab': 'other-lab', 'name': 'OSPF done', 'kind': 'save', 'target': 'latest'},
                     {'job_id': 'j3', 'lab': 'bgp-core', 'name': '', 'kind': 'save', 'target': 'latest'},
                     {'commit': 'c' * 40, 'name': 'Save removed-lab progress', 'files': ['x/latest/r1.cfg']}]
        with patch.object(scaffold.sys.stdin, 'isatty', return_value=True), patch('builtins.input', return_value='y') as asked, \
                patch('builtins.print') as shown:
            scaffold.cmd_snapshot(args(slug='bgp-core', state='broken-01'))
        lines = self.printed(shown)
        self.assertEqual([line for line in lines if line.startswith('This upload also sends')],
                         ['This upload also sends: other-lab: OSPF done', 'This upload also sends: bgp-core: a save without a name',
                          'This upload also sends: Save removed-lab progress'])
        self.assertIn('  bgp-core/reference/broken-01/latest/r1.cfg', lines)
        compare = [body for method, path, body in self.calls if path.endswith('/git/compare')]
        self.assertEqual(compare, [{'job_id': 'job1'}])
        asked.assert_called_once()
        self.assertTrue(any(line.endswith('and uploaded. Lab rebound to bgp-core/work.') for line in lines), lines)

    def test_snapshot_uploads_through_the_save_the_review_names(self):
        # A newer save of the repository is at HEAD: the upload goes through it and carries this state.
        self.upload_job = 'job9'
        scaffold.cmd_snapshot(args(slug='bgp-core', state='broken-01', yes=True))
        self.assertEqual([path for path in self.paths() if path.endswith('/retry')], ['/git/jobs/job9/retry'])
        self.assertEqual(self.job['status'], 'synced')

    def test_snapshot_shows_the_review_again_when_another_save_was_made_meanwhile(self):
        self.lands = 1
        with patch.object(scaffold.sys.stdin, 'isatty', return_value=True), patch('builtins.input', return_value='y') as asked, \
                patch('builtins.print') as shown:
            scaffold.cmd_snapshot(args(slug='bgp-core', state='broken-01'))
        lines = self.printed(shown)
        heads = [body['head'] for method, path, body in self.calls if path.endswith('/retry')]
        self.assertEqual(heads, ['a' * 40, 'b' * 40], 'the second upload carries the HEAD of the second review')
        self.assertEqual(len([path for path in self.paths() if path.endswith('/git/compare')]), 2)
        self.assertEqual(asked.call_count, 2, 'asked again after the review changed')
        self.assertIn('Another save was made in this repository meanwhile. This is what an upload sends now:', lines)
        self.assertEqual(lines.count('This upload also sends: other-lab: Landed meanwhile'), 1, 'only the second review names it')
        self.assertEqual(self.job['status'], 'synced')

    def test_snapshot_with_yes_tries_once_more_then_leaves_the_state_on_the_vm(self):
        self.lands = 5
        with patch('builtins.print') as shown:
            scaffold.cmd_snapshot(args(slug='bgp-core', state='broken-01', yes=True))
        self.assertEqual(len([path for path in self.paths() if path.endswith('/retry')]), 2, 'one more try, not a loop')
        self.assertEqual(self.job['status'], 'review_pending', 'nothing was uploaded')
        text = ' '.join(self.printed(shown))
        self.assertIn('kept on the lab VM only: other saves kept being made in this repository', text)
        self.assertIn('Lab rebound to bgp-core/work', text)
        self.assertEqual(self.destinations(), ['bgp-core/reference/broken-01', 'bgp-core/work'])
        self.lands = 1; self.calls.clear()
        scaffold.cmd_snapshot(args(slug='bgp-core', state='broken-01', yes=True))
        self.assertEqual(self.job['status'], 'synced', 'with one save in between the second try uploads')

    def test_snapshot_asks_and_a_no_keeps_the_state_on_the_vm_and_still_rebinds(self):
        # The state waits on the lab VM as a save to upload (was: set aside with Keep snapshot only so that the folder
        # change back was not refused; a waiting save no longer stops a folder change).
        with patch.object(scaffold.sys.stdin, 'isatty', return_value=True), patch('builtins.input', return_value='n'), \
                patch('builtins.print') as shown:
            scaffold.cmd_snapshot(args(slug='bgp-core', state='broken-01'))
        self.assertFalse(any(path.endswith('/retry') for path in self.paths()))
        self.assertFalse(any(path.endswith('/dismiss') for path in self.paths()))
        self.assertEqual(self.job['status'], 'review_pending')
        self.assertEqual(self.destinations(), ['bgp-core/reference/broken-01', 'bgp-core/work'])
        text = ' '.join(self.printed(shown))
        self.assertIn('r1.cfg', text)                       # the changed files are shown before the question
        self.assertIn('kept on the lab VM only', text)
        self.assertIn('goes up with the next upload of this repository', text)

    def test_snapshot_without_a_terminal_needs_yes_and_changes_nothing(self):
        with patch.object(scaffold.sys.stdin, 'isatty', return_value=False), self.assertRaises(SystemExit) as stop:
            scaffold.cmd_snapshot(args(slug='bgp-core', state='broken-01'))
        self.assertIn('--yes', str(stop.exception))
        self.assertEqual(self.destinations(), [])
        self.assertFalse(any(path.endswith('/git/save') for path in self.paths()))

    def test_snapshot_whose_upload_fails_says_so_and_rebinds_to_work(self):
        # Was: "says the lab still saves to the reference folder". A save that waits no longer refuses the folder change.
        self.after_upload = 'push_pending'
        with self.assertRaises(SystemExit) as stop:
            scaffold.cmd_snapshot(args(slug='bgp-core', state='broken-01', yes=True))
        text = str(stop.exception)
        self.assertIn('saved on the lab VM but was not uploaded: push_pending', text)
        self.assertIn('upload it from the save status in the lab header', text)
        self.assertIn('rebound to bgp-core/work', text); self.assertNotIn('STILL SAVES TO', text)
        self.assertEqual(self.destinations(), ['bgp-core/reference/broken-01', 'bgp-core/work'])

    def test_snapshot_whose_upload_is_refused_says_the_managers_reason_and_rebinds(self):
        self.head = ''   # the manager cannot name a HEAD: the upload is refused, nothing is uploaded
        with self.assertRaises(SystemExit) as stop:
            scaffold.cmd_snapshot(args(slug='bgp-core', state='broken-01', yes=True))
        text = str(stop.exception)
        self.assertIn('was not uploaded: refused (Review the changes of this save before uploading it.)', text)
        self.assertIn('rebound to bgp-core/work', text)

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
        # The manager refuses the folder change back (other work is still running), so the lab stays on the
        # reference folder; the person must be told, with the way out. (A waiting save alone no longer refuses it.)
        def stuck(manager, job_id, timeout=300):
            self.job['status'] = 'push_pending'; self.busy = True
            scaffold.die('timed out waiting for Git job %s.' % job_id)
        patch.object(scaffold, 'poll_git', stuck).start()
        with self.assertRaises(SystemExit) as stop:
            scaffold.cmd_snapshot(args(slug='bgp-core', state='broken-01', yes=True))
        text = str(stop.exception)
        self.assertIn('timed out waiting for Git job', text)
        self.assertIn('Wait for the active backup, Git save or lab operation to finish.', text)
        self.assertIn('STILL SAVES TO bgp-core/reference/broken-01', text)
        self.assertIn('init bgp-core', text)

    def test_snapshot_whose_poll_times_out_rebinds_to_work_when_nothing_else_runs(self):
        def stuck(manager, job_id, timeout=300):
            self.job['status'] = 'push_pending'
            scaffold.die('timed out waiting for Git job %s.' % job_id)
        patch.object(scaffold, 'poll_git', stuck).start()
        with self.assertRaises(SystemExit) as stop:
            scaffold.cmd_snapshot(args(slug='bgp-core', state='broken-01', yes=True))
        self.assertIn('timed out waiting for Git job', str(stop.exception)); self.assertIn('rebound to bgp-core/work', str(stop.exception))

    def test_snapshot_stopped_at_the_question_with_ctrl_c_or_end_of_input_says_where_the_lab_saves(self):
        # The save waits on the lab VM; that does not stop the folder change back (was: STILL SAVES TO).
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
                self.assertIn('rebound to bgp-core/work', text)
                self.assertEqual(self.destinations(), ['bgp-core/reference/broken-01', 'bgp-core/work'])
                self.assertFalse(any(path.endswith('/retry') for path in self.paths()))   # nothing was uploaded

    def interrupted_bind(self, refuse_rebind):
        # The destination change to the reference folder returns a job; Ctrl+C arrives while it is polled.
        inner = scaffold.api
        polls = []

        def api(manager, path, method='GET', body=None):
            if path.endswith('/git/destination') and body['prefix'].endswith('/reference/broken-01'):
                self.calls.append((method, path, body))
                return 200, {'binding': {}, 'job': {'id': 'bind1'}}
            if path.endswith('/git/destination') and refuse_rebind:
                self.calls.append((method, path, body))
                return 409, {'detail': 'Wait for the active backup, Git save or lab operation to finish.'}
            return inner(manager, path, method, body)

        def poll(manager, job_id, timeout=300):
            polls.append(job_id)
            raise KeyboardInterrupt

        patch.object(scaffold, 'api', api).start()
        patch.object(scaffold, 'poll_git', poll).start()
        with self.assertRaises(SystemExit) as stop:
            scaffold.cmd_snapshot(args(slug='bgp-core', state='broken-01', yes=True))
        self.assertEqual(polls, ['bind1'])
        self.assertFalse(any(path.endswith('/git/save') for path in self.paths()))   # nothing was captured
        return str(stop.exception)

    def test_snapshot_stopped_with_ctrl_c_while_the_lab_is_pointed_at_the_reference_folder_rebinds(self):
        text = self.interrupted_bind(refuse_rebind=False)
        self.assertIn('stopped', text)
        self.assertIn('rebound to bgp-core/work', text)
        self.assertEqual(self.destinations(), ['bgp-core/reference/broken-01', 'bgp-core/work'])

    def test_snapshot_stopped_with_ctrl_c_while_pointing_at_the_reference_says_where_the_lab_may_save(self):
        text = self.interrupted_bind(refuse_rebind=True)
        self.assertIn('stopped', text)
        self.assertIn('MAY STILL SAVE TO bgp-core/reference/broken-01', text)
        self.assertIn('init bgp-core', text)

    def test_snapshot_whose_review_cannot_be_read_reports_it_and_rebinds_when_it_can(self):
        # Was: "whose dismiss fails". Nothing is set aside any more; the step between the save and the question is the
        # review, and a review that cannot be read uploads nothing.
        real = scaffold.api

        def refuse_review(manager, path, method='GET', body=None):
            if path.endswith('/git/compare'):
                self.calls.append((method, path, body))
                return 409, {'detail': 'Cannot reach the VM Git helper.'}
            return real(manager, path, method, body)
        patch.object(scaffold, 'api', refuse_review).start()
        with patch.object(scaffold.sys.stdin, 'isatty', return_value=True), patch('builtins.input', return_value='y') as asked, \
                patch('builtins.print'), self.assertRaises(SystemExit) as stop:
            scaffold.cmd_snapshot(args(slug='bgp-core', state='broken-01'))
        text = str(stop.exception)
        self.assertIn('could not read what an upload would send: Cannot reach the VM Git helper.', text)
        self.assertIn('rebound to bgp-core/work', text)
        asked.assert_not_called(); self.assertFalse(any(path.endswith('/retry') for path in self.paths()))

    def over_http(self, lose):
        """Run the real api() against the faithful fake: `lose(method, path, body, n)` says how request n ends,
        None for a normal answer, 'before' when the connection breaks before the manager acted, 'after' when the
        manager acted and the answer was lost (RemoteDisconnected, as when it restarts mid-request)."""
        seen = []
        broken = http.client.RemoteDisconnected('Remote end closed connection without response')

        class Answer(io.BytesIO):
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        class Transport:
            def open(transport, request, timeout=None):
                path = request.full_url.split('/api', 1)[1]
                body = json.loads(request.data) if request.data else None
                seen.append((request.get_method(), path, body))
                how = lose(request.get_method(), path, body, len(seen))
                if how == 'before':
                    raise broken
                status, reply = self.fake_api('http://m', path, request.get_method(), body)
                if how == 'after':
                    raise broken
                if status != 200:
                    raise urllib.error.HTTPError(request.full_url, status, 'x', {}, io.BytesIO(json.dumps(reply).encode()))
                return Answer(json.dumps(reply).encode())
        patch.object(scaffold, 'api', self.real_api).start()
        patch.object(scaffold, 'DIRECT', Transport()).start()
        return seen

    def snapshot_text(self):
        with self.assertRaises(SystemExit) as stop:
            scaffold.cmd_snapshot(args(slug='bgp-core', state='broken-01', yes=True))
        return str(stop.exception)

    def test_api_turns_an_error_raised_while_the_answer_is_read_into_a_clean_exit(self):
        # urllib wraps only the connect: these come out of http.client's getresponse() as they are.
        for error in (http.client.RemoteDisconnected('Remote end closed connection without response'),
                      TimeoutError('timed out'), ConnectionResetError(104, 'Connection reset by peer'),
                      http.client.IncompleteRead(b'x'), urllib.error.URLError('refused')):
            with self.subTest(error=type(error).__name__):
                class Transport:
                    def open(transport, request, timeout=None, error=error):
                        raise error
                patch.object(scaffold, 'DIRECT', Transport()).start()
                with self.assertRaises(SystemExit) as stop:
                    self.real_api('http://m', '/state')
                self.assertTrue(str(stop.exception).startswith('Cannot reach the manager at http://m ('), str(stop.exception))
                self.assertIn('Is it running?', str(stop.exception))

    def test_snapshot_whose_save_answer_is_lost_before_the_manager_acted_rebinds_to_work(self):
        self.over_http(lambda method, path, body, n: 'before' if path.endswith('/git/save') else None)
        text = self.snapshot_text()
        self.assertIn('Cannot reach the manager', text)
        self.assertIn('rebound to bgp-core/work', text)
        self.assertEqual(self.destinations(), ['bgp-core/reference/broken-01', 'bgp-core/work'])

    def test_snapshot_whose_save_answer_is_lost_after_the_manager_acted_says_where_the_lab_saves(self):
        # The save started and waits on the lab VM; the folder change back still works (was: refused, STILL SAVES TO).
        self.over_http(lambda method, path, body, n: 'after' if path.endswith('/git/save') else None)
        text = self.snapshot_text()
        self.assertIn('Cannot reach the manager', text)
        self.assertIn('rebound to bgp-core/work', text)
        self.assertEqual(self.destinations(), ['bgp-core/reference/broken-01', 'bgp-core/work'])

    def test_snapshot_whose_bind_answer_is_lost_rebinds_when_the_manager_is_back(self):
        self.over_http(lambda method, path, body, n: 'after' if n == 2 and path.endswith('/git/destination') else None)
        text = self.snapshot_text()
        self.assertIn('rebound to bgp-core/work', text)
        self.assertEqual(self.destinations(), ['bgp-core/reference/broken-01', 'bgp-core/work'])
        self.assertFalse(any(path.endswith('/git/save') for path in self.paths()))   # nothing was captured

    def test_snapshot_whose_bind_answer_is_lost_while_the_manager_stays_away_says_the_lab_may_still_save_there(self):
        seen = self.over_http(lambda method, path, body, n: 'after' if path.endswith('/git/destination') else None)
        text = self.snapshot_text()
        self.assertIn('Cannot reach the manager', text)
        self.assertIn('MAY STILL SAVE TO bgp-core/reference/broken-01', text)
        self.assertIn('init bgp-core', text)
        self.assertEqual([body['prefix'] for method, path, body in seen if path.endswith('/git/destination')],
                         ['bgp-core/reference/broken-01', 'bgp-core/work'])      # the rebind was tried

    def test_snapshot_whose_rebind_answer_is_lost_does_not_claim_the_lab_still_saves_there(self):
        # The rebind may have been done: the stop after a failed save must not state the opposite as a fact.
        self.over_http(lambda method, path, body, n: 'before' if path.endswith('/git/save') else (
            'after' if path.endswith('/git/destination') and body['prefix'].endswith('/work') else None))
        text = self.snapshot_text()
        self.assertIn('MAY STILL SAVE TO bgp-core/reference/broken-01', text)
        self.assertNotIn('STILL SAVES TO', text)

    def test_snapshot_whose_final_rebind_answer_is_lost_says_where_the_lab_saves_and_that_the_save_is_done(self):
        self.over_http(lambda method, path, body, n: 'after' if path.endswith('/git/destination') and body['prefix'].endswith('/work') else None)
        text = self.snapshot_text()
        self.assertIn('Cannot reach the manager', text)
        self.assertIn('MAY STILL SAVE TO bgp-core/reference/broken-01', text)
        self.assertIn('uploaded', text)

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
                # The folder the lab saves to already is the one meant (was: 409 "This lab already saves to that folder.").
                return 200, {'saved': True, 'binding': {'binding_id': 'bid'}, 'job': None}
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
