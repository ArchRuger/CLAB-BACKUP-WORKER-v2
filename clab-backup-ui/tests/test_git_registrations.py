import contextlib
import importlib.util
import io
import json
from pathlib import Path
import stat
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch


spec = importlib.util.spec_from_file_location('git_registrations', Path(__file__).resolve().parents[2] / 'deploy/git-registrations.py')
listing = importlib.util.module_from_spec(spec)
spec.loader.exec_module(listing)


class GitRegistrationListingTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.helper = listing.host_helper()
        self.helper.REGISTRY = Path(self.folder.name) / 'git.json'
        self.helper.command = Mock(side_effect=AssertionError('Listing must not run Git'))
        self.helper.GitRepository = Mock(side_effect=AssertionError('Listing must not open a checkout'))
        self.helper.atomic_json = Mock(side_effect=AssertionError('Listing must not write'))
        # Windows tests cannot create Linux root-owned registry permissions.
        # Keep real bounded JSON parsing and test the ownership guards separately.
        self.root_file = patch.object(self.helper, 'root_file').start()
        self.parents = patch.object(listing, 'trusted_parents').start()
        self.addCleanup(patch.stopall)

    def binding(self):
        return dict(id='a' * 32, label='My lab', owner='engineer', path='/home/engineer/labs/bgp',
                    remote='lab-origin', push_url='https://github.com/owner/lab.git', branch='main',
                    prefix='labs/bgp', revision='b' * 64, uid=1001, gid=1001, home='/home/engineer',
                    anchor='c' * 40, password='never-output', token='never-output-either')

    def write(self, config):
        self.helper.REGISTRY.write_text(json.dumps(config), encoding='utf8')

    def test_absent_registry_is_empty_without_installed_helper_or_writes(self):
        result = listing.registrations(self.helper)
        self.assertEqual(result, {'result': {'protocol': self.helper.PROTOCOL,
                                            'version': self.helper.VERSION, 'repositories': []}})
        self.root_file.assert_not_called()
        self.parents.assert_called_once_with(self.helper.REGISTRY)
        self.helper.command.assert_not_called()
        self.helper.GitRepository.assert_not_called()
        self.helper.atomic_json.assert_not_called()
        self.assertFalse(self.helper.REGISTRY.exists())

    def test_only_public_fields_returned_and_custom_binding_is_preserved(self):
        original = self.binding()
        self.write({'repositories': [original]})
        before = self.helper.REGISTRY.read_bytes()
        result = listing.registrations(self.helper)
        self.assertEqual(result['result']['repositories'], [{key: original[key] for key in listing.FIELDS}])
        self.assertNotIn('never-output', json.dumps(result))
        self.assertEqual(before, self.helper.REGISTRY.read_bytes())
        self.root_file.assert_called_once_with(self.helper.REGISTRY)
        self.helper.command.assert_not_called()
        self.helper.GitRepository.assert_not_called()

    def test_oversized_registry_is_rejected_before_json_read(self):
        self.helper.REGISTRY.write_bytes(b' ' * (self.helper.MAX_FILE + 1))
        with self.assertRaisesRegex(ValueError, 'too large'):
            listing.registrations(self.helper)

    def test_registry_ownership_check_is_required(self):
        self.write({'repositories': [self.binding()]})
        self.root_file.side_effect = ValueError('Unsafe registry')
        with self.assertRaisesRegex(ValueError, 'Unsafe registry'):
            listing.registrations(self.helper)

    def test_symlink_guard_applies_even_when_registry_is_missing(self):
        with patch.object(self.helper, 'no_links', side_effect=ValueError('Symlink')) as guard:
            with self.assertRaisesRegex(ValueError, 'Symlink'):
                listing.registrations(self.helper)
            guard.assert_called_once_with(self.helper.REGISTRY, require=False)
        self.root_file.assert_not_called()

    def test_bad_descriptor_or_url_does_not_leak_registry_contents(self):
        for update in ({'label': ['never-output']}, {'push_url': 'https://never-output@github.com/owner/repo'}):
            binding = self.binding()
            binding.update(update)
            self.write({'repositories': [binding]})
            output = io.StringIO()
            with patch.object(listing, 'os', SimpleNamespace(name='posix', geteuid=lambda: 0)), \
                    patch.object(listing.sys, 'argv', ['git-registrations.py']), \
                    patch.object(listing, 'host_helper', return_value=self.helper), contextlib.redirect_stdout(output):
                self.assertEqual(listing.main(), 1)
            self.assertIn('error', json.loads(output.getvalue()))
            self.assertNotIn('never-output', output.getvalue())

    def test_nonroot_invocation_does_not_read_registry(self):
        with patch.object(listing, 'os', SimpleNamespace(name='posix', geteuid=lambda: 1000)), \
                patch.object(listing.sys, 'argv', ['git-registrations.py']), \
                patch.object(listing, 'host_helper') as helper, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(listing.main(), 1)
        helper.assert_not_called()


class GitRegistryParentTests(unittest.TestCase):
    def parent(self, *, exists=True, uid=0, mode=stat.S_IFDIR | 0o755):
        return SimpleNamespace(exists=lambda: exists, stat=lambda: SimpleNamespace(st_uid=uid, st_mode=mode))

    def test_absent_directory_is_allowed_only_with_trusted_existing_ancestors(self):
        listing.trusted_parents(SimpleNamespace(parents=[self.parent(exists=False), self.parent()]))

    def test_untrusted_owner_writable_or_nondirectory_parent_is_rejected(self):
        for parent in (self.parent(uid=1000), self.parent(mode=stat.S_IFDIR | 0o777),
                       self.parent(mode=stat.S_IFREG | 0o644)):
            with self.subTest(parent=parent), self.assertRaisesRegex(ValueError, 'root-owned'):
                listing.trusted_parents(SimpleNamespace(parents=[parent]))


if __name__ == '__main__':
    unittest.main()
