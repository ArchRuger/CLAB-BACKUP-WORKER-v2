"""Tests for the device review as a job (app/design_apply.py, docs/uiux-email-2026-10-03/DESIGN-CONTRACT.md):
POST .../design/generations/{gid}/review answers at once with a running job, the per-device work runs in the
background and records the stage each device is really at, GET .../design/review-jobs/{id} follows it and carries
the review payload (with its single-use token) only once the job is done.

The fixture is test_design_apply.py's (a scratch app, the fake cEOS driver, a fake connector); nothing here
touches a device, the VM or live data.
"""
import json
import threading
import time
import unittest
import uuid

import paramiko

from app import design_apply as da
from test_design_apply import (BASELINE, FRAGMENT, DesignApplyTestCase, add_generation, node_map, poll_job,
                               poll_review_job, set_credentials)

PASSWORD = 'never-in-a-job-7Q'


class ReviewJobTestCase(DesignApplyTestCase):
    def setUp(self):
        super().setUp()
        # A login password that must never show up in a job view.
        set_credentials(self.app, self.lab_id, 'ceos', password=PASSWORD)
        set_credentials(self.app, self.lab_id, 'ceos2', password=PASSWORD)

    def start(self, generation_id, targets=('ceos',), request_id=None, takeover=()):
        body = {'targets': list(targets), 'takeover': list(takeover)}
        if request_id is not None: body['request_id'] = request_id
        return self.client.post(f'/api/labs/{self.lab_id}/design/generations/{generation_id}/review', json=body)

    def get(self, job_id):
        return self.client.get(f'/api/labs/{self.lab_id}/design/review-jobs/{job_id}')

    def hold(self, method='snapshot'):
        """Make the fake driver wait inside `method` until the returned event is set; returns (entered, release)."""
        entered, release = threading.Event(), threading.Event()
        original = getattr(self.fake, method)

        def held(*args, **kwargs):
            entered.set()
            release.wait(10)
            return original(*args, **kwargs)
        setattr(self.fake, method, held)
        self.addCleanup(release.set)
        return entered, release


class ReviewJobShapeTests(ReviewJobTestCase):
    def test_post_answers_at_once_with_a_running_job(self):
        gen_id = self.default_generation()
        entered, release = self.hold()
        response = self.start(gen_id, request_id=uuid.uuid4().hex)
        self.assertEqual(response.status_code, 200, response.text)
        job = response.json()['review_job']
        self.assertEqual(job['status'], 'running')
        self.assertEqual(len(job['id']), 32)
        self.assertEqual(job['targets'][0]['name'], 'ceos')
        self.assertIn(job['targets'][0]['stage'], da.REVIEW_STAGES)
        self.assertIn('queued', job['targets'][0]['timeline'])
        self.assertTrue(job['started'])
        self.assertIsInstance(job['server_time'], float)
        self.assertNotIn('review', job)
        self.assertTrue(entered.wait(5))
        running = self.get(job['id']).json()
        self.assertEqual(running['status'], 'running')
        self.assertEqual(running['targets'][0]['stage'], 'reading_config')
        self.assertNotIn('review', running)   # no token while the devices are still being reviewed
        release.set()
        done = poll_review_job(self.client, self.lab_id, job['id'])
        self.assertEqual(done['status'], 'done')
        self.assertEqual(len(done['review']['token']), 32)
        self.assertEqual(done['review']['applicable'], ['ceos'])
        self.assertEqual(done['progress'], {'settled': 1, 'total': 1})
        self.assertTrue(done['finished'])

    def test_stages_are_recorded_in_the_order_the_device_went_through_them(self):
        gen_id = self.default_generation()
        job = self.start(gen_id).json()['review_job']
        done = poll_review_job(self.client, self.lab_id, job['id'])
        timeline = done['targets'][0]['timeline']
        order = [stage for stage, _ in sorted(timeline.items(), key=lambda item: item[1])]
        self.assertEqual([s for s in order if s != 'settled'],
                         ['queued', 'connecting', 'checking_pending', 'rendering', 'reading_config', 'staging', 'done'])
        self.assertEqual(done['targets'][0]['stage'], 'done')
        self.assertNotIn('restaging', timeline)   # only a take-over of an exclusive sibling stages twice

    def test_a_request_without_request_id_still_gets_a_job(self):
        gen_id = self.default_generation()
        response = self.start(gen_id)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(poll_review_job(self.client, self.lab_id, response.json()['review_job']['id'])['status'], 'done')

    def test_an_unknown_or_foreign_job_is_404(self):
        self.assertEqual(self.get(uuid.uuid4().hex).status_code, 404)
        gen_id = self.default_generation()
        job = self.start(gen_id).json()['review_job']
        poll_review_job(self.client, self.lab_id, job['id'])
        other = self.client.get(f'/api/labs/{uuid.uuid4().hex}/design/review-jobs/{job["id"]}')
        self.assertEqual(other.status_code, 404)

    def test_the_lab_listing_shows_the_job_without_the_token(self):
        gen_id = self.default_generation()
        job = self.start(gen_id).json()['review_job']
        poll_review_job(self.client, self.lab_id, job['id'])
        listed = self.client.get(f'/api/labs/{self.lab_id}/design/review-jobs').json()
        self.assertEqual([j['id'] for j in listed], [job['id']])
        self.assertNotIn('review', listed[0])

    def test_synchronous_guards_still_answer_at_once(self):
        gen_id = add_generation(self.app, self.lab_id, node_map('ceos'), {'ceos': [('initial', FRAGMENT)]}, status='failed')
        response = self.start(gen_id)
        self.assertEqual(response.status_code, 409)
        self.assertIn('Only a generated plan', response.json()['detail'])
        self.assertEqual(self.client.get(f'/api/labs/{self.lab_id}/design/review-jobs').json(), [])


class ReviewJobFailureTests(ReviewJobTestCase):
    def test_an_unreachable_device_is_reported_unreachable_and_the_job_finishes(self):
        gen_id = add_generation(self.app, self.lab_id, {**node_map('ceos'), **node_map('ceos2')},
                                {'ceos': [('initial', FRAGMENT)], 'ceos2': [('initial', FRAGMENT)]})

        def connect(client, node, creds):
            if node.get('definition_node') == 'ceos2': raise OSError('connection refused by 172.20.20.102 ' + PASSWORD)
        self.app.state.design_apply.connect = connect
        job = self.start(gen_id, targets=['ceos', 'ceos2']).json()['review_job']
        done = poll_review_job(self.client, self.lab_id, job['id'])
        self.assertEqual(done['status'], 'done')
        targets = {t['name']: t for t in done['targets']}
        self.assertEqual(targets['ceos']['stage'], 'done')
        self.assertEqual(targets['ceos2']['stage'], 'unreachable')
        self.assertEqual(targets['ceos2']['reason_code'], 'unreachable')
        self.assertEqual(targets['ceos2']['message'], da.REVIEW_REASONS['unreachable'])
        self.assertIn('connecting', targets['ceos2']['timeline'])
        self.assertEqual(done['review']['applicable'], ['ceos'])
        row = next(r for r in done['review']['targets'] if r['name'] == 'ceos2')
        self.assertFalse(row['reachable'])
        public = json.dumps({k: v for k, v in done.items() if k != 'review'})
        self.assertNotIn(PASSWORD, public)
        self.assertNotIn('172.20.20.102', public)

    def test_rejected_credentials_fail_the_device_with_the_auth_reason(self):
        gen_id = self.default_generation()

        def connect(client, node, creds):
            raise paramiko.AuthenticationException('denied')
        self.app.state.design_apply.connect = connect
        done = poll_review_job(self.client, self.lab_id, self.start(gen_id).json()['review_job']['id'])
        self.assertEqual(done['targets'][0]['stage'], 'failed')
        self.assertEqual(done['targets'][0]['reason_code'], 'auth')

    def test_an_exception_inside_the_worker_fails_that_device_and_the_job_still_finishes(self):
        gen_id = self.default_generation()

        def broken(*args, **kwargs):
            raise RuntimeError('render exploded: ' + BASELINE)
        self.fake.render_desired = broken
        done = poll_review_job(self.client, self.lab_id, self.start(gen_id).json()['review_job']['id'])
        self.assertEqual(done['status'], 'done')
        target = done['targets'][0]
        self.assertEqual(target['stage'], 'failed')
        self.assertEqual(target['reason_code'], 'internal')
        self.assertIn('rendering', target['timeline'])   # failed where it really was
        self.assertEqual(done['review']['applicable'], [])
        self.assertNotIn('hostname ceos', json.dumps({k: v for k, v in done.items() if k != 'review'}))

    def test_a_device_with_a_pending_change_is_failed_with_that_reason(self):
        gen_id = self.default_generation()
        self.fake.pending = lambda client, **o: 'someone-else'
        done = poll_review_job(self.client, self.lab_id, self.start(gen_id).json()['review_job']['id'])
        self.assertEqual(done['targets'][0]['reason_code'], 'pending_change')
        self.assertIn('checking_pending', done['targets'][0]['timeline'])
        self.assertNotIn('rendering', done['targets'][0]['timeline'])

    def test_a_device_that_overruns_the_budget_is_failed_with_timeout_and_the_job_finishes(self):
        gen_id = self.default_generation()
        entered, release = self.hold()
        self.app.state.design_apply.review_timeout = 0.3
        done = poll_review_job(self.client, self.lab_id, self.start(gen_id).json()['review_job']['id'])
        self.assertTrue(entered.is_set())
        self.assertEqual(done['status'], 'done')
        self.assertEqual(done['targets'][0]['stage'], 'failed')
        self.assertEqual(done['targets'][0]['reason_code'], 'timeout')
        release.set(); time.sleep(0.2)
        # The late worker does not move a settled device.
        self.assertEqual(self.get(done['id']).json()['targets'][0]['stage'], 'failed')

    def saturate_node_pool(self):
        """Occupy every node-pool worker (as another lab's apply or review would); returns the event that frees them."""
        service = self.app.state.design_apply; free = threading.Event(); busy = []
        for _ in range(service.node_pool._max_workers):
            started = threading.Event(); busy.append(started)
            service.node_pool.submit(lambda s=started: (s.set(), free.wait(10)))
        self.addCleanup(free.set)
        for started in busy: self.assertTrue(started.wait(5))
        return free

    def test_time_queued_for_a_slot_never_counts_against_the_device_deadline(self):
        gen_id = self.default_generation()
        service = self.app.state.design_apply
        service.review_timeout = 0.2; service.review_poll = 0.02
        free = self.saturate_node_pool()
        job = self.start(gen_id).json()['review_job']
        time.sleep(0.6)   # three device deadlines, all of it queued
        waiting = self.get(job['id']).json()
        self.assertEqual(waiting['status'], 'running')
        self.assertEqual(waiting['targets'][0]['stage'], 'queued')
        self.assertNotIn('connecting', waiting['targets'][0]['timeline'])
        free.set()
        done = poll_review_job(self.client, self.lab_id, job['id'])
        self.assertEqual(done['status'], 'done')
        self.assertEqual(done['targets'][0]['stage'], 'done')

    def test_a_device_still_waiting_at_the_job_limit_is_reported_as_never_contacted(self):
        gen_id = self.default_generation()
        service = self.app.state.design_apply
        service.review_limit = 0.3; service.review_poll = 0.02
        calls = []
        service.connect = lambda client, node, creds: calls.append(node)
        free = self.saturate_node_pool()
        done = poll_review_job(self.client, self.lab_id, self.start(gen_id).json()['review_job']['id'])
        self.assertEqual(done['status'], 'done')
        target = done['targets'][0]
        self.assertEqual((target['stage'], target['reason_code']), ('failed', 'queue_limit'))
        self.assertIn('not contacted', target['message'])
        self.assertNotIn('connecting', target['timeline'])
        free.set(); time.sleep(0.2)
        self.assertEqual(calls, [], 'the queued work was cancelled, the device never contacted')

    def test_each_review_job_waits_on_its_own_orchestrator_thread(self):
        """The orchestrator of a job only waits; it runs on a thread of its own (no shared orchestrator pool), so another
        lab's review is never stuck behind it; only the device work shares the node pool, where it shows `queued`."""
        gen_id = self.default_generation()
        entered, release = self.hold()
        job = self.start(gen_id).json()['review_job']
        self.assertTrue(entered.wait(5))
        self.assertIn('design-review-' + job['id'][:8], {t.name for t in threading.enumerate()})
        self.assertFalse(hasattr(self.app.state.design_apply, 'review_pool'))
        release.set()
        self.assertEqual(poll_review_job(self.client, self.lab_id, job['id'])['status'], 'done')

    def test_a_vm_connection_change_during_the_review_fails_the_job_without_a_token(self):
        gen_id = self.default_generation()
        entered, release = self.hold()
        job = self.start(gen_id).json()['review_job']
        self.assertTrue(entered.wait(5))
        with self.app.state.store.lock:
            self.app.state.store.state['host']['address'] = '10.0.0.99'
            self.app.state.store.save()
        release.set()
        done = poll_review_job(self.client, self.lab_id, job['id'])
        self.assertEqual(done['status'], 'failed')
        self.assertIn('VM connection changed', done['message'])
        self.assertNotIn('review', done)


class ReviewJobConcurrencyTests(ReviewJobTestCase):
    def test_a_second_review_of_the_lab_while_one_runs_is_409_naming_the_running_job(self):
        gen_id = self.default_generation()
        entered, release = self.hold()
        job = self.start(gen_id, request_id=uuid.uuid4().hex).json()['review_job']
        self.assertTrue(entered.wait(5))
        second = self.start(gen_id, request_id=uuid.uuid4().hex)
        self.assertEqual(second.status_code, 409)
        self.assertEqual(second.json()['detail']['review_job_id'], job['id'])
        self.assertTrue(second.json()['detail']['message'])
        release.set()
        poll_review_job(self.client, self.lab_id, job['id'])

    def test_the_same_request_id_returns_the_same_job(self):
        gen_id = self.default_generation()
        request_id = uuid.uuid4().hex
        entered, release = self.hold()
        first = self.start(gen_id, request_id=request_id).json()['review_job']
        again = self.start(gen_id, request_id=request_id)
        self.assertEqual(again.status_code, 200)
        self.assertEqual(again.json()['review_job']['id'], first['id'])
        release.set()
        poll_review_job(self.client, self.lab_id, first['id'])
        after = self.start(gen_id, request_id=request_id).json()['review_job']   # still the same job once finished
        self.assertEqual(after['id'], first['id'])
        self.assertEqual(len(self.client.get(f'/api/labs/{self.lab_id}/design/review-jobs').json()), 1)

    def test_closing_the_dialog_is_not_cancel_the_job_finishes_and_its_token_applies(self):
        """The page going away sends nothing (there is no cancel route); the job finishes on its own and a page that
        comes back reads the result and applies with the token."""
        gen_id = self.default_generation()
        entered, release = self.hold()
        job = self.start(gen_id).json()['review_job']
        self.assertTrue(entered.wait(5))
        self.assertIn(self.client.post(f'/api/labs/{self.lab_id}/design/review-jobs/{job["id"]}/cancel', json={}).status_code, (404, 405))
        release.set()
        done = poll_review_job(self.client, self.lab_id, job['id'])
        applied = self.submit_http(done['review']['token'])
        self.assertEqual(applied.status_code, 200, applied.text)
        self.assertEqual(poll_job(self.client, applied.json()['id'])['status'], 'succeeded')
        # The token stays single-use: the same review cannot be applied twice.
        self.assertEqual(self.submit_http(done['review']['token']).status_code, 409)

    def test_apply_waits_while_a_review_of_the_lab_runs(self):
        gen_id = self.default_generation()
        token = self.review(gen_id).json()['token']
        entered, release = self.hold()
        job = self.start(gen_id).json()['review_job']
        self.assertTrue(entered.wait(5))
        response = self.submit_http(token)
        self.assertEqual(response.status_code, 409)
        self.assertIn('being reviewed', response.json()['detail'])
        release.set()
        poll_review_job(self.client, self.lab_id, job['id'])

    def test_finished_jobs_expire_with_the_token_and_the_table_stays_bounded(self):
        gen_id = self.default_generation()
        job = self.start(gen_id).json()['review_job']
        poll_review_job(self.client, self.lab_id, job['id'])
        service = self.app.state.design_apply
        with service.review_lock:
            service.review_jobs[job['id']]['_expires'] = time.monotonic() - 1
        self.assertEqual(self.get(job['id']).status_code, 404)
        with service.review_lock:
            for _ in range(da.REVIEW_JOB_CAP + 10):
                fake_id = uuid.uuid4().hex
                service.review_jobs[fake_id] = {'id': fake_id, 'lab_id': 'x', 'generation_id': 'g', 'status': 'done', 'targets': [], '_expires': time.monotonic() + 600}
            service._prune_reviews()
            self.assertLess(len(service.review_jobs), da.REVIEW_JOB_CAP)


class PublicReviewJobTests(unittest.TestCase):
    def test_the_public_view_keeps_only_safe_fields(self):
        job = {'id': 'j', 'lab_id': 'l', 'generation_id': 'g', 'status': 'done', 'message': 'Review finished.', 'started': 's', 'finished': 'f',
               'request_id': 'r', 'progress': {'settled': 1, 'total': 1}, 'takeover': [], '_expires': 1.0,
               'targets': [{'name': 'ceos', 'kind': 'arista_ceos', 'stage': 'done', 'timeline': {'queued': 1.0}, '_secret': 'x'}],
               'review': {'token': 't' * 32}}
        public = da.public_review_job(job)
        self.assertNotIn('review', public)
        self.assertNotIn('_expires', public)
        self.assertNotIn('_secret', public['targets'][0])
        self.assertEqual(da.public_review_job(job, with_review=True)['review']['token'], 't' * 32)
        self.assertNotIn('review', da.public_review_job(dict(job, status='running'), with_review=True))


if __name__ == '__main__':
    unittest.main()
