import json
import unittest
from unittest.mock import patch

from app.discovery import parse_snapshot
from app.store import Store
import test_vm_files as vm_tests
from test_vm_files import envelope
from test_discovery import YAML


class ImportConfirmationTests(unittest.TestCase):
    setUp = vm_tests.VMFilesTests.setUp
    tearDown = vm_tests.VMFilesTests.tearDown
    host = vm_tests.VMFilesTests.host

    def remote(self, value=None):
        return patch('app.discovery.inspect_host', return_value=(parse_snapshot(json.dumps(value or envelope()).encode()), 'SHA256:fixture'))

    def preview(self):
        response = self.client.post('/api/discovery/import-preview', headers=self.auth, json={'name': 'training'})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def confirm(self, preview):
        return self.client.post('/api/discovery/import', headers=self.auth,
                                json={'name': 'training', 'token': preview['token']})

    def test_poll_preview_and_cancel_do_not_save_lab_or_credentials(self):
        self.host()
        with self.remote():
            for _ in range(3): self.service.refresh()
            self.assertIn('training', self.service.public()['pending_imports'])
            preview = self.preview()
            self.service.refresh()  # Cancelling means no confirm request.
        self.assertEqual(self.store.state['labs'], [])
        self.assertEqual(Store(self.tmp.name).state['labs'], [])
        self.assertNotIn('fixture-device-secret', json.dumps(preview))
        self.assertNotIn('token', json.dumps(self.service.public()))
        self.assertEqual((preview['nodes'], preview['links']), (2, 1))

    def test_confirmation_saves_once_and_requires_preview_token(self):
        self.host()
        with self.remote():
            missing = self.client.post('/api/discovery/import', headers=self.auth, json={'name': 'training'})
            self.assertEqual(missing.status_code, 422)
            preview = self.preview()
            result = self.confirm(preview)
            self.assertEqual(result.status_code, 200, result.text)
            self.assertEqual(self.confirm(preview).status_code, 409)
        self.assertEqual(len(Store(self.tmp.name).state['labs']), 1)
        self.assertEqual(self.store.state['labs'][0]['nodes'][0]['password'], 'fixture-device-secret')

    def test_changed_files_require_new_confirmation(self):
        self.host()
        with self.remote(): preview = self.preview()
        with self.remote(envelope(definition=YAML + b'\n# changed')):
            response = self.confirm(preview)
        self.assertEqual(response.status_code, 409)
        self.assertIn('changed', response.text)
        self.assertEqual(self.store.state['labs'], [])

    def test_changed_host_or_expired_preview_cannot_import(self):
        self.host()
        with self.remote():
            preview = self.preview()
            self.store.state['host']['revision'] = 'replacement'
            self.assertEqual(self.confirm(preview).status_code, 409)
            preview = self.preview()
            self.service.import_previews[preview['token']]['expires'] = 0
            self.assertEqual(self.confirm(preview).status_code, 409)
        self.assertEqual(self.store.state['labs'], [])

    def test_excluded_lab_cancel_retains_exclusion_then_confirmation_restores(self):
        self.host(); self.store.state['ignored_labs'] = ['training']; self.store.save()
        with self.remote():
            preview = self.preview()
            self.assertTrue(preview['excluded'])
            self.service.refresh()
            self.assertEqual(self.store.state['ignored_labs'], ['training'])
            self.assertEqual(self.store.state['labs'], [])
            old = self.client.post('/api/discovery/allow-import', headers=self.auth, json={'name': 'training'})
            self.assertEqual(old.status_code, 409)
            self.assertEqual(self.store.state['ignored_labs'], ['training'])
            self.assertEqual(self.confirm(preview).status_code, 200)
        self.assertEqual(Store(self.tmp.name).state['ignored_labs'], [])

    def test_save_failure_leaves_storage_unchanged_and_allows_retry(self):
        self.host(); self.store.state['ignored_labs'] = ['training']; self.store.save()
        with self.remote():
            preview = self.preview()
            original_save = self.store.save
            def fail_workspace_save():
                if self.store.state['labs']: raise OSError('fixture write failure')
                return original_save()
            with patch.object(self.store, 'save', side_effect=fail_workspace_save):
                self.assertEqual(self.confirm(preview).status_code, 500)
            self.assertEqual(self.store.state['labs'], [])
            self.assertEqual(self.store.state['ignored_labs'], ['training'])
            self.assertEqual(self.confirm(preview).status_code, 200)

    def test_offline_confirmation_and_cross_name_token_are_rejected(self):
        self.host()
        with self.remote():
            preview = self.preview()
            wrong = self.client.post('/api/discovery/import', headers=self.auth, json={'name': 'other', 'token': preview['token']})
            self.assertEqual(wrong.status_code, 409)
        with patch('app.discovery.inspect_host', side_effect=OSError()):
            self.assertEqual(self.confirm(preview).status_code, 409)
        self.assertEqual(self.store.state['labs'], [])

    def test_both_import_endpoints_require_authentication(self):
        for route in ('import-preview', 'import'):
            self.assertEqual(self.client.post('/api/discovery/' + route, json={'name': 'training', 'token': 'x'*32}).status_code, 401)
