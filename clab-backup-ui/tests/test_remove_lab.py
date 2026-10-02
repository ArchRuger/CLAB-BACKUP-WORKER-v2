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


class HideLabTests(unittest.TestCase):
    """Hide from Home is a flag on the lab and nothing else: the lab keeps its devices, jobs, backups and
    Git binding, nothing on the VM changes, background discovery never clears it, and adding the lab again
    through the topology browser (POST /api/lab-definitions) shows it again."""
    setUp = vm_tests.VMFilesTests.setUp
    tearDown = vm_tests.VMFilesTests.tearDown
    host = vm_tests.VMFilesTests.host
    register = vm_tests.VMFilesTests.register
    poll = vm_tests.VMFilesTests.poll
    sync = vm_tests.VMFilesTests.sync
    confirm_import = vm_tests.VMFilesTests.confirm_import

    def imported(self):
        self.host(); self.poll()
        return self.store.state['labs'][0]

    def settings(self, lab, **body):
        return self.client.put('/api/labs/' + lab['id'] + '/operations-settings', headers=self.auth, json=body)

    def public(self, lab):
        return next(l for l in self.client.get('/api/state', headers=self.auth).json()['labs'] if l['id'] == lab['id'])

    def test_hide_changes_the_flag_only_and_the_poll_keeps_it(self):
        lab = self.imported()
        self.store.state['jobs'] = [dict(id='old', lab_id=lab['id'], status='succeeded', operation='backup', nodes=[])]
        lab['git_binding'] = {'binding_id': 'b1', 'revision': 'r1'}; lab['favorite'] = True; self.store.save()
        backup = Path(self.tmp.name) / 'backups' / lab['id'] / 'history' / 'config.cfg'
        backup.parent.mkdir(parents=True); backup.write_bytes(b'saved config')
        before = copy.deepcopy(self.store.lab(lab['id']))
        with patch('app.discovery.inspect_host') as remote, patch('app.node_services.connect') as ssh:
            response = self.settings(lab, hidden=True)
        self.assertEqual(response.status_code, 200, response.text)
        remote.assert_not_called(); ssh.assert_not_called()  # nothing on the VM is touched
        after = self.store.lab(lab['id'])
        self.assertTrue(after['hidden'])
        self.assertEqual({k: v for k, v in after.items() if k != 'hidden'}, before, 'hide sets the flag and nothing else')
        self.assertTrue(self.public(lab)['hidden'], 'Home reads the flag from /api/state')
        self.assertEqual([j['id'] for j in self.store.state['jobs']], ['old'])
        self.assertEqual(backup.read_bytes(), b'saved config')
        self.assertEqual(self.store.state['ignored_labs'], [], 'hiding is not an exclusion from discovery')
        self.poll(); self.poll()
        self.assertTrue(self.store.lab(lab['id'])['hidden'], 'the 30-second discovery keeps a hidden lab hidden')
        self.assertEqual(len(self.store.state['labs']), 1, 'and never re-creates it beside itself')
        self.assertTrue(Store(self.tmp.name).lab(lab['id'])['hidden'], 'the flag is persisted')
        events = (Path(self.tmp.name) / 'events.jsonl').read_text()
        self.assertIn('lab.hide', events)
        response = self.settings(lab, hidden=False)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertNotIn('hidden', self.store.lab(lab['id']), 'Show on Home removes the flag')
        self.assertIn('lab.show', (Path(self.tmp.name) / 'events.jsonl').read_text())

    def test_hidden_survives_a_sync_and_a_favourite_change(self):
        lab = self.imported(); self.settings(lab, hidden=True)
        self.sync(lab, vm_tests.envelope())
        self.assertTrue(self.store.lab(lab['id'])['hidden'], 'Sync topology from VM keeps the flag')
        self.settings(lab, favorite=True)
        self.assertTrue(self.store.lab(lab['id'])['hidden'])
        self.assertTrue(self.store.lab(lab['id'])['favorite'])

    def test_adding_the_lab_again_through_the_topology_browser_shows_it(self):
        lab = self.imported(); self.settings(lab, hidden=True)
        # Choose a file on the lab VM… › Add to My labs / Deploy lab: the same deployment name registers again.
        response = self.client.post('/api/lab-definitions', headers=self.auth, files={'definition': ('training.clab.yaml', YAML)})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['id'], lab['id'], 'the same lab, not a second workspace')
        self.assertNotIn('hidden', self.store.lab(lab['id']))
        self.assertEqual(len(self.store.state['labs']), 1)

    def test_unknown_settings_keys_and_missing_labs_are_refused(self):
        lab = self.imported()
        self.assertEqual(self.settings(lab, hide=True).status_code, 422)
        self.assertEqual(self.client.put('/api/labs/nope/operations-settings', headers=self.auth, json={'hidden': True}).status_code, 404)
