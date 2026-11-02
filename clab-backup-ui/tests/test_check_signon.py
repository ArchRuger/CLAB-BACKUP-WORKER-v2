"""docs/sign-on/tools/check_signon.py: the parts of the sign-on browser check that need no browser (BUILD.md S11).

Standard library only: the module imports Playwright lazily, so this file runs with the system python3. What the
check asserts in a browser is run by the check itself against a fixture (see docs/sign-on/TOOLS.md); what is pinned
here is the machinery that decides pass or fail, so a regression in it cannot hide a product failure:

* which responses and console lines are expected and which fail the run (an unexpected 4xx, a console error, a
  request that failed to start),
* that nothing secret reaches a report or a log line,
* the sentences and addresses the check compares against, and the command line.
"""
import importlib.util
import json
import os
import re
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('check_signon', ROOT/'docs'/'sign-on'/'tools'/'check_signon.py')
check_signon = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check_signon)
Monitor, Report = check_signon.Monitor, check_signon.Report

LAB = '90881b5f090d4468a38ca18e74657f39'
LOG = f'''fixture manager ready on http://127.0.0.1:8871/  data=/tmp/x
  BGP_TheoryToPractice: {LAB}
  ospf-basics: 671afde9d3a547e59fcb38b90d90e2d2
  sign-on: requests are signed out; the fixture accounts (random for this run, scratch data only):
    admin    admin  password SECRET-ONE-aaaaaaaaaaaaaaaa
    operator student  password SECRET-TWO-bbbbbbbbbbbbbbbb
'''


class Foreign:
    """Some other HTTP server on a port: answers 200 `{}` to everything, like a real manager's /api/health would, and records
    what it was asked. Neither the fixture nor a regression run may take it for their own."""
    def __init__(self, fixture_shape=False):
        self.asked = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                outer.asked.append(self.path)
                raw = json.dumps({'requests': [], 'counts': {}} if fixture_shape and self.path == '/__fixture/requests' else {}).encode()
                self.send_response(200); self.send_header('Content-Type', 'application/json'); self.send_header('Content-Length', str(len(raw)))
                self.end_headers(); self.wfile.write(raw)
            def log_message(self, *args): pass

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def stop(self):
        self.server.shutdown(); self.server.server_close()


class OccupiedPortTests(unittest.TestCase):
    """A server that is already on the port must never be taken for the fixture (a typo such as 8081 on a VM points the
    regression, which deploys and saves, at a real manager)."""

    def setUp(self):
        self.foreign = Foreign()
        self.addCleanup(self.foreign.stop)

    def test_a_port_that_is_listening_is_in_use_and_a_free_one_is_not(self):
        self.assertTrue(check_signon.port_in_use(self.foreign.port))
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            free = sock.getsockname()[1]
        self.assertFalse(check_signon.port_in_use(free))

    def test_the_fixture_is_recognised_by_its_own_control_route_not_by_a_health_answer(self):
        self.assertFalse(check_signon.is_fixture('http://127.0.0.1:%d' % self.foreign.port), 'a server that answers 200 {} to everything')
        shaped = Foreign(fixture_shape=True)
        self.addCleanup(shaped.stop)
        self.assertTrue(check_signon.is_fixture('http://127.0.0.1:%d' % shaped.port))

    def test_check_signon_refuses_to_start_on_a_port_that_is_listening_and_starts_no_process(self):
        fixture = check_signon.Fixture(self.foreign.port)
        self.addCleanup(fixture.stop)
        with self.assertRaises(RuntimeError) as raised:
            fixture.start(5)
        self.assertIn('already', str(raised.exception))
        self.assertIsNone(fixture.process)
        self.assertEqual(self.foreign.asked, [], 'the refusal does not even talk to the other server')

    def test_run_regression_refuses_a_port_that_is_listening_and_runs_no_check(self):
        script = ROOT/'docs'/'sign-on'/'tools'/'run_regression.sh'
        done = subprocess.run(['bash', str(script), str(self.foreign.port)], capture_output=True, text=True, timeout=60,
                              env=dict(os.environ, CLAB_PYTHON=sys.executable))
        self.assertNotEqual(done.returncode, 0)
        self.assertIn('already', done.stderr)
        self.assertNotIn('verify_after', done.stdout + done.stderr)
        self.assertNotIn('fixture up', done.stdout)
        self.assertEqual(self.foreign.asked, [], 'nothing was sent to the other server')


class UntilTests(unittest.TestCase):
    def test_until_returns_true_as_soon_as_the_condition_holds_and_false_at_the_timeout(self):
        ticks = []
        original = check_signon.pause
        check_signon.pause = ticks.append
        try:
            calls = iter([False, False, True])
            self.assertTrue(check_signon.until(lambda: next(calls), timeout=5, step=0.5))
            self.assertEqual(ticks, [0.5, 0.5])
            ticks.clear()
            self.assertFalse(check_signon.until(lambda: False, timeout=1.0, step=0.5))
            self.assertEqual(ticks, [0.5, 0.5], 'it gives up when the time is up, not before')
        finally:
            check_signon.pause = original


class ScenarioListTests(unittest.TestCase):
    def test_every_row_of_the_ui_check_table_has_a_scenario(self):
        names = [name for name, _ in check_signon.SCENARIOS]
        for needed in ('sign-in and next', 'operator', 'throttle', 'people (administrator)', 'forced password change', 'cross-site arrival', 'sign-out',
                       'open redirect', 'session ends in a dialog', 'session ends in the save panel', 'session ends under a running operation',
                       'terminal pop-up', 'operator and the VM', 'student guide'):
            self.assertIn(needed, names)
        self.assertEqual(len(names), len(set(names)))


class MonitorTests(unittest.TestCase):
    def test_an_unlisted_error_response_fails_the_run(self):
        monitor = Monitor()
        monitor.response(500, 'GET', 'http://h/api/state')
        monitor.response(404, 'GET', 'http://h/static/missing.js')
        found = monitor.findings()
        self.assertEqual(len(found['failed_requests']), 2)
        self.assertTrue(monitor.failed())

    def test_a_listed_401_is_expected_and_its_console_line_goes_with_it(self):
        monitor = Monitor(allow=[(401, 'GET', r'/api/session$')])
        monitor.response(401, 'GET', 'http://h/api/session')
        monitor.console('error', 'Failed to load resource: the server responded with a status of 401 (Unauthorized)', 'http://h/api/session')
        found = monitor.findings()
        self.assertEqual(found['failed_requests'], [])
        self.assertEqual(found['console_errors'], [])
        self.assertEqual(len(found['expected']), 1)
        self.assertFalse(monitor.failed())

    def test_the_allowance_is_for_one_status_one_method_and_one_path(self):
        monitor = Monitor(allow=[(401, 'GET', r'/api/session$')])
        monitor.response(401, 'POST', 'http://h/api/session')      # another method
        monitor.response(403, 'GET', 'http://h/api/session')       # another status
        monitor.response(401, 'GET', 'http://h/api/state')         # another path
        self.assertEqual(len(monitor.findings()['failed_requests']), 3)

    def test_a_request_the_check_blocked_itself_is_expected_only_for_that_method_and_path(self):
        monitor = Monitor(blocked=[('DELETE', r'/api/session$')])
        monitor.request_failed('DELETE', 'http://h/api/session', 'net::ERR_FAILED')
        monitor.console('error', 'Failed to load resource: net::ERR_FAILED', 'http://h/api/session')
        found = monitor.findings()
        self.assertEqual((found['failed_requests'], found['console_errors']), ([], []))
        self.assertEqual(len(found['expected']), 1)
        other = Monitor(blocked=[('DELETE', r'/api/session$')])
        other.request_failed('GET', 'http://h/api/session', 'net::ERR_FAILED')          # another method
        other.request_failed('DELETE', 'http://h/api/state', 'net::ERR_FAILED')         # another path
        other.console('error', 'Failed to load resource: net::ERR_FAILED', 'http://h/api/state')
        self.assertEqual(len(other.findings()['failed_requests']), 2)
        self.assertEqual(len(other.findings()['console_errors']), 1)

    def test_the_query_string_does_not_hide_the_path(self):
        monitor = Monitor(allow=[(401, 'GET', r'/api/session$')])
        monitor.response(401, 'GET', 'http://h/api/session?x=1')
        self.assertEqual(monitor.findings()['failed_requests'], [])

    def test_the_console_line_of_an_unlisted_response_fails_even_when_the_response_event_came_late(self):
        monitor = Monitor(allow=[(401, 'GET', r'/api/session$')])
        monitor.console('error', 'Failed to load resource: the server responded with a status of 403 (Forbidden)', 'http://h/api/users')
        self.assertEqual(len(monitor.findings()['console_errors']), 1)

    def test_a_console_error_that_is_not_a_resource_line_always_fails(self):
        monitor = Monitor(allow=[(401, 'GET', r'.*')])
        monitor.console('error', 'Uncaught TypeError: x is not a function', 'http://h/static/app.js')
        monitor.page_error('ReferenceError: y is not defined')
        found = monitor.findings()
        self.assertEqual(len(found['console_errors']), 1)
        self.assertEqual(len(found['page_errors']), 1)
        self.assertTrue(monitor.failed())

    def test_warnings_and_info_are_not_errors(self):
        monitor = Monitor()
        monitor.console('warning', 'something', 'http://h/')
        monitor.console('log', 'something', 'http://h/')
        self.assertFalse(monitor.failed())

    def test_a_request_that_failed_to_start_fails_but_a_navigation_abort_does_not(self):
        monitor = Monitor()
        monitor.request_failed('GET', 'http://h/api/state', 'net::ERR_CONNECTION_REFUSED')
        monitor.request_failed('GET', 'http://h/api/state', 'net::ERR_ABORTED')
        found = monitor.findings()
        self.assertEqual(len(found['failed_requests']), 1)
        self.assertEqual(len(found['aborted']), 1)

    def test_the_same_failure_repeated_is_counted_each_time(self):
        monitor = Monitor()
        for _ in range(3):
            monitor.response(500, 'GET', 'http://h/api/state')
        self.assertEqual(len(monitor.findings()['failed_requests']), 3)

    def test_a_success_is_not_a_finding(self):
        monitor = Monitor()
        monitor.response(200, 'GET', 'http://h/api/state')
        monitor.response(302, 'GET', 'http://h/')
        self.assertFalse(monitor.failed())


class ScrubTests(unittest.TestCase):
    def test_known_secrets_cookie_values_and_bearer_words_are_replaced(self):
        text = 'Cookie: clab_session=abc123DEF; clab_capture_owner=zzz999 password=hunter2hunter2 token'
        out = check_signon.scrub(text, ['hunter2hunter2'])
        self.assertNotIn('abc123DEF', out)
        self.assertNotIn('zzz999', out)
        self.assertNotIn('hunter2hunter2', out)
        self.assertIn('***', out)

    def test_short_secrets_are_ignored_so_that_ordinary_words_survive(self):
        self.assertEqual(check_signon.scrub('the admin signed in', ['admin']), 'the admin signed in')

    def test_report_text_is_scrubbed_on_the_way_in(self):
        report = Report(secrets=['correct horse battery staple'])
        report.check('typed correct horse battery staple', False, 'detail correct horse battery staple')
        payload = json.dumps(report.as_dict())
        self.assertNotIn('correct horse battery staple', payload)
        self.assertIn('***', payload)


class ReportTests(unittest.TestCase):
    def test_a_failed_check_makes_the_report_fail_and_is_listed(self):
        report = Report()
        report.begin('1440x900')
        report.check('ok one', True)
        report.check('bad one', False, 'why')
        report.begin('390x844')
        report.check('ok two', True)
        self.assertFalse(report.passed())
        self.assertEqual([item['name'] for item in report.failures()], ['bad one'])
        self.assertEqual(report.failures()[0]['viewport'], '1440x900')

    def test_no_failure_and_no_crash_is_a_pass(self):
        report = Report()
        report.begin('1440x900')
        report.check('fine', True)
        self.assertTrue(report.passed())

    def test_a_crashed_scenario_is_a_failure_that_names_the_scenario(self):
        report = Report()
        report.begin('760x1024')
        report.crash('forced change', ValueError('boom'))
        self.assertFalse(report.passed())
        self.assertIn('forced change', report.failures()[0]['name'])
        self.assertIn('boom', report.failures()[0]['detail'])

    def test_monitor_findings_fail_the_report(self):
        report = Report()
        report.begin('1440x900')
        report.check('fine', True)
        monitor = Monitor()
        monitor.response(500, 'GET', 'http://h/api/state')
        report.absorb('scenario', monitor)
        self.assertFalse(report.passed())

    def test_the_report_names_what_it_ran_against(self):
        report = Report()
        report.environment(browser='Chromium 1', commit='abc1234', base='http://127.0.0.1:8871')
        data = report.as_dict()
        self.assertEqual(data['environment']['commit'], 'abc1234')
        self.assertIn('fixture', data['evidence'].lower())

    def test_write_makes_a_private_json_file(self):
        with tempfile.TemporaryDirectory() as directory:
            report = Report()
            report.begin('1440x900')
            report.check('fine', True)
            path = report.write(Path(directory))
            self.assertEqual(path.name, 'report.json')
            self.assertEqual(json.loads(path.read_text())['passed'], True)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)


class SentenceTests(unittest.TestCase):
    def test_the_throttle_sentence_is_the_one_the_design_names(self):
        self.assertTrue(check_signon.throttle_sentence('Too many sign-in attempts. Try again in 30 s.'))
        self.assertTrue(check_signon.throttle_sentence('Too many sign-in attempts. Try again in 7 s.'))
        for wrong in ('Too many sign-in attempts. Try again in  s.', 'Too many sign-in attempts. Try again in 30 s.30',
                      'Too many sign-in attempts. Try again in 3030 s. s.', 'Wrong username or password.', ''):
            self.assertFalse(check_signon.throttle_sentence(wrong), wrong)

    def test_the_sign_in_address_keeps_the_fragment_and_encodes_next(self):
        self.assertEqual(check_signon.login_address('http://h:1', LAB, 'devices'), f'http://h:1/login?next=%2F#lab={LAB}&view=devices')
        self.assertEqual(check_signon.lab_address('http://h:1', LAB, 'devices'), f'http://h:1/#lab={LAB}&view=devices')

    def test_the_lab_id_is_read_from_the_fixture_log_and_no_password_is(self):
        self.assertEqual(check_signon.lab_id_from_log(LOG, 'BGP_TheoryToPractice'), LAB)
        self.assertIsNone(check_signon.lab_id_from_log(LOG, 'missing-lab'))
        self.assertNotIn('SECRET', check_signon.scrub_log(LOG))
        self.assertIn('BGP_TheoryToPractice', check_signon.scrub_log(LOG))

    def test_the_viewports_are_the_four_of_the_design(self):
        self.assertEqual(check_signon.VIEWPORTS, [(1440, 900), (1280, 800), (760, 1024), (390, 844)])

    def test_the_account_chip_shows_at_wide_widths_only(self):
        self.assertTrue(check_signon.chip_expected(1440))
        self.assertTrue(check_signon.chip_expected(1280))
        self.assertFalse(check_signon.chip_expected(760))
        self.assertFalse(check_signon.chip_expected(390))


class CommandLineTests(unittest.TestCase):
    def test_defaults_are_port_8871_and_all_four_viewports(self):
        args = check_signon.parse_args([])
        self.assertEqual(args.port, 8871)
        self.assertEqual(check_signon.chosen_viewports(args), check_signon.VIEWPORTS)

    def test_a_viewport_can_be_chosen_by_width(self):
        args = check_signon.parse_args(['--port', '9001', '--viewport', '390', '--viewport', '1440'])
        self.assertEqual(args.port, 9001)
        self.assertEqual(check_signon.chosen_viewports(args), [(1440, 900), (390, 844)])

    def test_an_unknown_width_is_refused(self):
        with self.assertRaises(SystemExit):
            check_signon.parse_args(['--viewport', '1000'])

    def test_there_is_no_option_that_takes_a_password(self):
        parser = check_signon.argument_parser()
        flags = [flag for action in parser._actions for flag in action.option_strings]
        self.assertFalse([flag for flag in flags if re.search(r'pass|secret|token|cookie', flag)], flags)

    def test_the_evidence_directory_defaults_under_docs_sign_on_evidence(self):
        args = check_signon.parse_args([])
        self.assertIn(str(Path('docs')/'sign-on'/'evidence'), str(check_signon.evidence_dir(args)))
        args = check_signon.parse_args(['--out', '/tmp/somewhere'])
        self.assertEqual(check_signon.evidence_dir(args), Path('/tmp/somewhere'))


class SourceTests(unittest.TestCase):
    """The rules of clab-browser-qa, read from the source of the check."""
    source = (ROOT/'docs'/'sign-on'/'tools'/'check_signon.py').read_text()

    def test_no_networkidle_wait(self):
        self.assertNotIn('networkidle', self.source)

    def test_no_fixed_sleep(self):
        self.assertIsNone(re.search(r'\btime\.sleep\(', self.source))
        self.assertNotIn('wait_for_timeout', self.source)

    def test_playwright_is_imported_inside_main_so_the_helpers_load_without_it(self):
        head = self.source.split('def main', 1)[0]
        self.assertIsNone(re.search(r'^(from|import) playwright', head, re.M))

    def test_no_password_is_printed_or_given_on_a_command_line(self):
        self.assertNotRegex(self.source, r'print\([^)]*password')


if __name__ == '__main__':
    unittest.main()
