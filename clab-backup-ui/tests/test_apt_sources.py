import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


spec = importlib.util.spec_from_file_location('apt_sources', Path(__file__).resolve().parents[2] / 'deploy/apt_sources.py')
apt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(apt)


class AptSourceRepairTests(unittest.TestCase):
    def test_list_repairs_only_active_media_and_preserves_mirrors_and_options(self):
        source = ('# deb file:/cdrom noble main\n'
                  'deb [arch=amd64 signed-by=/keyring] file:///cdrom/ noble main\n'
                  'deb cdrom:[Ubuntu Server 24.04]/ noble main\n'
                  'deb https://mirror.example/ubuntu noble main\n'
                  'deb file:/cdrom-cache noble main\n')
        result, count = apt.repair_text(source, '.list')
        self.assertEqual(count, 2)
        self.assertIn('# deb file:/cdrom noble main\n', result)
        self.assertIn('deb https://mirror.example/ubuntu noble main\n', result)
        self.assertIn('deb file:/cdrom-cache noble main\n', result)
        self.assertIn('signed-by=/keyring', result)
        self.assertEqual(apt.repair_text(result, '.list'), (result, 0))

    def test_deb822_mixed_uris_retains_every_network_mirror_and_comment(self):
        source = ('Types: deb deb-src\nURIs: file:/cdrom\n'
                  ' https://one.example/ubuntu\n# keep this comment\n'
                  ' https://two.example/ubuntu\nSuites: noble noble-updates\n'
                  'Components: main universe\nSigned-By: /usr/share/keyrings/ubuntu.gpg\n')
        result, count = apt.repair_text(source, '.sources')
        self.assertEqual(count, 1)
        self.assertIn('URIs: https://one.example/ubuntu https://two.example/ubuntu\n', result)
        self.assertIn('# keep this comment\n', result)
        self.assertIn('Signed-By: /usr/share/keyrings/ubuntu.gpg\n', result)
        self.assertNotIn('Enabled: no', result)

    def test_deb822_media_only_disabled_and_existing_disabled_untouched(self):
        source = ('Types: deb\r\nURIs: file:/cdrom\r\nSuites: noble\r\nEnabled: yes\r\n'
                  '\r\nTypes: deb\r\nURIs: file:/cdrom\r\nEnabled: no\r\n')
        result, count = apt.repair_text(source, '.sources')
        self.assertEqual(count, 1)
        self.assertEqual(result, source.replace('Enabled: yes', 'Enabled: no'))
        self.assertEqual(apt.repair_text(result, '.sources'), (result, 0))

    def test_deb822_missing_enabled_adds_it_without_touching_next_stanza(self):
        source = ('Types: deb\nURIs: file:/cdrom\nSuites: noble\n\n'
                  'Types: deb\nURIs: https://example.org/ubuntu\nSuites: noble')
        result, _ = apt.repair_text(source, '.sources')
        self.assertEqual(result, source.replace('Suites: noble\n\n', 'Suites: noble\nEnabled: no\n\n'))

    def test_ambiguous_deb822_fields_fail_without_guessing(self):
        for text in ('URIs: file:/cdrom\nURIs: https://mirror.example\n',
                     'URIs: file:/cdrom\nEnabled: yes\nEnabled: yes\n'):
            with self.subTest(text=text), self.assertRaisesRegex(ValueError, 'Ambiguous'):
                apt.repair_text(text, '.sources')

    def test_check_is_read_only_and_repair_has_exact_backup_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'apt'
            folder = root / 'sources.list.d'
            folder.mkdir(parents=True)
            source = root / 'sources.list'
            source.write_bytes(b'deb file:/cdrom noble main\ndeb https://mirror.example noble main\n')
            other = folder / 'ubuntu.sources'
            other.write_text('Types: deb\nURIs: https://mirror.example\nSuites: noble\n', encoding='utf-8')
            before = source.read_bytes()
            self.assertEqual(apt.scan_media_sources(root), [{'path': str(source), 'changes': 1}])
            self.assertEqual(source.read_bytes(), before)
            with patch.object(apt.os, 'chown', create=True):
                result = apt.repair_media_sources(root, Path(directory) / 'backups')
            self.assertEqual(result['changed'], [str(source)])
            self.assertEqual((Path(result['backup']) / 'sources.list').read_bytes(), before)
            self.assertEqual(apt.repair_media_sources(root, Path(directory) / 'backups'),
                             {'changed': [], 'backup': None})
            self.assertEqual(apt.scan_media_sources(root), [])

    def test_ambiguous_second_file_prevents_first_file_change(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            folder = root / 'sources.list.d'
            folder.mkdir()
            first = root / 'sources.list'
            first.write_text('deb file:/cdrom noble main\n', encoding='utf-8')
            (folder / 'bad.sources').write_text('URIs: file:/cdrom\nURIs: https://example.org\n', encoding='utf-8')
            with self.assertRaises(ValueError):
                apt.repair_media_sources(root, root / 'backups')
            self.assertEqual(first.read_text(), 'deb file:/cdrom noble main\n')
            self.assertFalse((root / 'backups').exists())

    def test_media_match_does_not_disable_unrelated_local_or_network_sources(self):
        for value in ('file:/mnt/repository', 'file:/cdrom-cache', 'https://cdrom.example/ubuntu', 'file://server/cdrom'):
            self.assertFalse(apt.media_uri(value))

    def test_root_required_before_any_cli_write(self):
        with patch.object(apt.os, 'geteuid', return_value=1000, create=True), \
                patch.object(apt, 'repair_media_sources') as repair:
            with self.assertRaisesRegex(ValueError, 'sudo/root'):
                apt.main(['--repair'])
        repair.assert_not_called()

    def test_source_changed_after_review_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'apt'
            root.mkdir()
            path = root / 'sources.list'
            original = b'deb file:/cdrom noble main\n'
            replacement = b'# edited by the administrator\n'
            path.write_bytes(original)
            plan = apt._plan(root)
            with patch.object(apt, '_plan', return_value=plan):
                path.write_bytes(replacement)
                with self.assertRaisesRegex(ValueError, 'changed during review'):
                    apt.repair_media_sources(root, Path(directory) / 'backups')
            self.assertEqual(path.read_bytes(), replacement)

    def test_docker_list_distinguishes_active_commented_and_source_only(self):
        source = 'deb [arch=amd64 signed-by=/keyring] https://download.docker.com/linux/ubuntu noble stable\n'
        self.assertEqual(apt._docker_states(source, '.list'), {'enabled'})
        self.assertEqual(apt._docker_states('# ' + source, '.list'), {'blocked'})
        self.assertEqual(apt._docker_states(source.replace('deb ', 'deb-src '), '.list'), {'blocked'})
        self.assertEqual(apt._docker_states('# Documentation: https://download.docker.com/linux/ubuntu\n', '.list'), set())

    def test_docker_deb822_requires_enabled_binary_source(self):
        source = ('Types: deb\nURIs: https://download.docker.com/linux/ubuntu\n'
                  'Suites: noble\nComponents: stable\nSigned-By: /keyring\n')
        self.assertEqual(apt._docker_states(source, '.sources'), {'enabled'})
        self.assertEqual(apt._docker_states(source + 'Enabled: no\n', '.sources'), {'blocked'})
        self.assertEqual(apt._docker_states(source.replace('Types: deb', 'Types: deb-src'), '.sources'), {'blocked'})
        commented = '\n'.join('# ' + line for line in source.splitlines())
        self.assertEqual(apt._docker_states(commented, '.sources'), {'blocked'})

    def test_disabled_docker_source_stops_without_modifying_sources(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            folder = root / 'sources.list.d'
            folder.mkdir()
            source = folder / 'docker.sources'
            text = 'Types: deb\nURIs: https://download.docker.com/linux/ubuntu\nEnabled: no\n'
            source.write_text(text, encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'disabled or source-only') as error:
                apt.docker_source_status(root)
            self.assertIn(str(source), str(error.exception))
            self.assertEqual(source.read_text(), text)
            self.assertEqual(list(folder.iterdir()), [source])

    def test_enabled_docker_source_can_coexist_with_a_disabled_old_entry(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / 'sources.list'
            self.assertEqual(apt.docker_source_status(root), 'absent')
            path.write_text('# deb https://download.docker.com/linux/ubuntu jammy stable\n'
                            'deb https://download.docker.com/linux/ubuntu noble stable\n', encoding='utf-8')
            self.assertEqual(apt.docker_source_status(root), 'enabled')


if __name__ == '__main__':
    unittest.main()
