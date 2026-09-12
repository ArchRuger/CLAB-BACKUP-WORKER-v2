import json
from pathlib import Path
import subprocess
import sys
import unittest

from app import __version__


class HelperPreflightTests(unittest.TestCase):
    def verify(self, data):
        script = Path(__file__).resolve().parents[2] / 'deploy' / 'verify-helper.py'
        return subprocess.run([sys.executable, str(script), __version__], input=json.dumps(data).encode(), capture_output=True)

    def test_current_helper_with_no_deployed_labs_is_ready(self):
        result = self.verify(dict(protocol='clab-manager-files-v1', helper_version=__version__, inspect={}, sources={}))
        self.assertEqual(result.returncode, 0)
        self.assertIn(__version__.encode(), result.stdout)

    def test_old_wrong_and_malformed_helpers_fail_without_printing_contents(self):
        for data in ({}, [], dict(protocol='clab-manager-files-v1', helper_version='1.7.0', inspect={}, sources={}),
                     dict(protocol='clab-manager-files-v1', helper_version=__version__, inspect={}, sources='secret-password')):
            result = self.verify(data)
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn(b'secret-password', result.stdout + result.stderr)
            self.assertIn(b'has not been recreated', result.stderr)

    def test_version_mismatch_shows_expected_and_installed_versions(self):
        result = self.verify(dict(protocol='clab-manager-files-v1', helper_version='0.0.0', inspect={}, sources={}))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(('source VERSION expects ' + __version__).encode(), result.stderr)
        self.assertIn(b'installed helper reports 0.0.0', result.stderr)

    def test_invalid_version_and_inventory_content_are_never_printed(self):
        result = self.verify(dict(protocol='clab-manager-files-v1', helper_version='secret-token',
                                  inspect={'password': 'secret-password'}, sources={}))
        self.assertNotIn(b'secret-token', result.stderr)
        self.assertNotIn(b'secret-password', result.stderr)
