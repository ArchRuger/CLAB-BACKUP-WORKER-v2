import copy
from pathlib import Path
import unittest
from unittest.mock import patch

from app.store import Store
import test_vm_files as vm_tests
from test_discovery import YAML


class RemoveLabTests(unittest.TestCase):
    setUp = vm_tests.VMFilesTests.setUp
    tearDown = vm_tests.VMFilesTests.tearDown
    host = vm_tests.VMFilesTests.host
    register = vm_tests.VMFilesTests.register
    poll = vm_tests.VMFilesTests.poll
    confirm_import = vm_tests.VMFilesTests.confirm_import

    def imported(self):
        self.host(); self.poll()
        return self.store.state['labs'][0]

    def remove(self, lab, **options):
        return self.client.request('DELETE', '/api/labs/' + lab['id'], headers=self.auth,
                                   json={'name': lab['name'], **options})

    def test_remove_only_manager_workspace_and_history(self):
        lab = self.imported()
        other = self.register(YAML.replace(b'training', b'other'))
        self.store.state['jobs'] = [dict(id='old', lab_id=lab['id'], status='succeeded'),
                                    dict(id='other-job', lab_id=other['id'], status='running')]
        saved_host = copy.deepcopy(self.store.state['host'])
        saved_other = copy.deepcopy(self.store.lab(other['id']))
        backup = Path(self.tmp.name) / 'backups' / lab['id'] / 'history' / 'config.cfg'
        backup.parent.mkdir(parents=True); backup.write_bytes(b'saved config')
        self.app.state.node_services.checks[(lab['id'], 'r1')] = {'status': 'reachable'}
        self.app.state.node_services.tickets['ticket'] = (123, lab['id'], 'r1')
        with patch('app.discovery.inspect_host') as remote, patch('app.node_services.connect') as ssh:
            response = self.remove(lab)
        self.assertEqual(response.status_code, 200, response.text)
        remote.assert_not_called(); ssh.assert_not_called()
        self.assertIsNone(self.store.lab(lab['id']))
        self.assertEqual(self.store.state['host'], saved_host)
        self.assertEqual(self.store.lab(other['id']), saved_other)
        self.assertEqual([j['id'] for j in self.store.state['jobs']], ['other-job'])
        self.assertEqual(backup.read_bytes(), b'saved config')
        self.assertNotIn(lab['deployment_name'], self.service.sources)
        self.assertEqual(self.app.state.node_services.checks, {})
        self.assertEqual(self.app.state.node_services.tickets, {})
        self.assertIn('lab.remove', (Path(self.tmp.name) / 'events.jsonl').read_text())

    def test_exclusion_survives_restart_and_later_discovery(self):
        lab = self.imported(); self.remove(lab)
        self.poll(); self.poll()
        self.assertEqual(self.store.state['labs'], [])
        persisted = Store(self.tmp.name)
        self.assertEqual(persisted.state['ignored_labs'], ['training'])
        from app.discovery import Discovery
        restarted = Discovery(persisted)
        try:
            with patch('app.discovery.inspect_host', return_value=(vm_tests.parse_snapshot(vm_tests.json.dumps(vm_tests.envelope()).encode()), 'SHA256:fixture')):
                restarted.refresh()
            self.assertEqual(persisted.state['labs'], [])
            self.assertTrue(restarted.public()['discovered'][0]['excluded'])
        finally: restarted.close()

    def test_allow_import_creates_a_fresh_workspace(self):
        lab = self.imported(); old_id = lab['id']; self.remove(lab)
        from app.discovery import parse_snapshot
        import json
        with patch('app.discovery.inspect_host', return_value=(parse_snapshot(json.dumps(vm_tests.envelope()).encode()), 'SHA256:fixture')):
            self.confirm_import()
        self.assertEqual(self.store.state['ignored_labs'], [])
        self.assertEqual(len(self.store.state['labs']), 1)
        self.assertNotEqual(self.store.state['labs'][0]['id'], old_id)

    def test_remove_without_excluding_allows_next_poll(self):
        lab = self.imported(); old_id = lab['id']
        self.assertEqual(self.remove(lab, prevent_reimport=False).status_code, 200)
        self.assertEqual(self.store.state['labs'], [])
        self.poll(confirm=False)
        self.assertEqual(self.store.state['labs'], [])
        self.poll()
        self.assertNotEqual(self.store.state['labs'][0]['id'], old_id)

    def test_inflight_discovery_does_not_undo_removal(self):
        lab = self.imported()
        def arriving(*args):
            self.assertEqual(self.remove(lab).status_code, 200)
            return vm_tests.parse_snapshot(vm_tests.json.dumps(vm_tests.envelope()).encode()), 'SHA256:fixture'
        with patch('app.discovery.inspect_host', side_effect=arriving): self.service.refresh()
        self.assertEqual(self.store.state['labs'], [])
        self.assertEqual(self.store.state['ignored_labs'], ['training'])

    def test_busy_lab_and_stale_confirmation_are_rejected(self):
        lab = self.imported()
        self.store.state['jobs'] = [dict(id='active', lab_id=lab['id'], status='queued')]
        self.assertEqual(self.remove(lab).status_code, 409)
        self.store.state['jobs'] = []
        self.assertEqual(self.remove(lab, name='wrong').status_code, 409)
        self.assertIsNotNone(self.store.lab(lab['id']))
        self.assertEqual(self.remove(lab).status_code, 200)
        self.assertEqual(self.remove(lab).status_code, 404)

    def test_failed_save_preserves_workspace_and_exclusion(self):
        lab = self.imported(); previous = copy.deepcopy(self.store.state)
        with patch.object(self.store, 'save', side_effect=OSError('disk unavailable')):
            result = self.remove(lab)
        self.assertEqual(result.status_code, 500)
        self.assertEqual(self.store.state, previous)
        self.assertIsNotNone(Store(self.tmp.name).lab(lab['id']))

    def test_authentication_required_and_manual_reimport_clears_exclusion(self):
        lab = self.imported()
        result = self.client.request('DELETE', '/api/labs/' + lab['id'], headers={'Origin':'https://other.example'}, json={'name': lab['name']})
        self.assertEqual(result.status_code, 403)
        self.assertEqual(self.client.post('/api/discovery/allow-import', headers={'Origin':'https://other.example'}, json={'name': 'training'}).status_code, 403)
        self.remove(lab)
        self.register()
        self.assertEqual(self.store.state['ignored_labs'], [])
        self.poll()
        self.assertEqual(len(self.store.state['labs']), 1)


if __name__ == '__main__': unittest.main()
