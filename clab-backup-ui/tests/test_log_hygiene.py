import logging
import unittest

from app import log_hygiene


def record(message, level=logging.INFO, args=None):
    return logging.LogRecord('uvicorn.error', level, __file__, 1, message, args, None)


class LogHygieneTests(unittest.TestCase):
    def setUp(self):
        self.logger = logging.getLogger('uvicorn.error')
        self.before = list(self.logger.filters)

    def tearDown(self):
        self.logger.filters[:] = self.before

    def test_websocket_handshake_lines_are_dropped(self):
        for message in ('203.0.113.9:4444 - "WebSocket /api/terminal?ticket=x" 403',
                        '203.0.113.9:4444 - "WebSocket /api/terminal?ticket=x" [accepted]'):
            self.assertFalse(log_hygiene.keep(record(message)), message)
        # uvicorn formats these with %-arguments; the filter judges the formatted text
        self.assertFalse(log_hygiene.keep(record('%s - "WebSocket %s" %d', args=('1.2.3.4:5', '/x?y=z', 403))))

    def test_websockets_library_connection_lines_are_dropped(self):
        for message in ('connection rejected (403 Forbidden)', 'connection open', 'connection closed',
                        'connection failed (400 Bad Request)'):
            self.assertFalse(log_hygiene.keep(record(message)), message)
        self.assertFalse(log_hygiene.keep(record('connection open', level=logging.DEBUG)))

    def test_startup_lines_stay(self):
        for message in ('Started server process [1]', 'Waiting for application startup.', 'Application startup complete.',
                        'Uvicorn running on https://0.0.0.0:8443 (Press CTRL+C to quit)'):
            self.assertTrue(log_hygiene.keep(record(message)), message)

    def test_warning_and_above_pass_untouched(self):
        self.assertTrue(log_hygiene.keep(record('Invalid HTTP request received.', level=logging.WARNING)))
        self.assertTrue(log_hygiene.keep(record('connection closed', level=logging.WARNING)))
        self.assertTrue(log_hygiene.keep(record('"WebSocket /x" 403', level=logging.ERROR)))

    def test_install_is_idempotent_and_filters_the_logger(self):
        log_hygiene.install()
        log_hygiene.install()
        self.assertEqual(sum(1 for f in self.logger.filters if getattr(f, 'clab_log_hygiene', False)), 1)
        self.assertFalse(self.logger.filter(record('connection rejected (403 Forbidden)')))
        self.assertTrue(self.logger.filter(record('Started server process [1]')))

    def test_debug_records_are_dropped(self):
        # At DEBUG the websockets library writes every request header, the Cookie among them.
        self.assertFalse(log_hygiene.keep(record('< Cookie: clab_session=abc', level=logging.DEBUG)))
        self.assertFalse(log_hygiene.keep(record('= connection is OPEN', level=logging.DEBUG)))

    def test_create_app_installs_the_filter(self):
        import tempfile
        from app import main
        for item in [f for f in self.logger.filters if getattr(f, 'clab_log_hygiene', False)]:
            self.logger.removeFilter(item)
        with tempfile.TemporaryDirectory() as data:
            main.create_app(data)
        self.assertEqual(sum(1 for f in self.logger.filters if getattr(f, 'clab_log_hygiene', False)), 1)


if __name__ == '__main__':
    unittest.main()
