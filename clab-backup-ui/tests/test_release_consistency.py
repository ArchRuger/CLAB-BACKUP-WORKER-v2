import importlib.util
from pathlib import Path
import shutil
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('release_check', ROOT / 'deploy/verify-release.py')
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


class ReleaseConsistencyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name in ('clab-backup-ui/VERSION', *release.FIELDS):
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, path)

    def test_actual_repository_is_consistent(self):
        self.assertEqual(release.verify(ROOT), (ROOT / 'clab-backup-ui/VERSION').read_text().strip())

    def test_stale_version_file_identifies_mismatched_files(self):
        (self.root / 'clab-backup-ui/VERSION').write_text('0.0.0\n')
        with self.assertRaisesRegex(ValueError, 'VERSION expects 0.0.0') as error:
            release.verify(self.root)
        self.assertIn('app/host_files.py', str(error.exception))
        self.assertIn('Dockerfile', str(error.exception))

    def test_each_runtime_version_is_checked(self):
        version = release.verify(self.root)
        for name in release.FIELDS:
            with self.subTest(name=name):
                path = self.root / name
                original = path.read_text(encoding='utf-8')
                path.write_text(original.replace(version, '0.0.0'), encoding='utf-8')
                with self.assertRaisesRegex(ValueError, 'Mixed release files'):
                    release.verify(self.root)
                path.write_text(original, encoding='utf-8')

    def test_missing_metadata_is_not_silently_accepted(self):
        (self.root / 'clab-backup-ui/app/host_git.py').write_text('# VERSION removed\n')
        with self.assertRaisesRegex(ValueError, 'missing release metadata'):
            release.verify(self.root)

    def test_version_must_be_numeric(self):
        (self.root / 'clab-backup-ui/VERSION').write_text('1.15.1\nextra')
        with self.assertRaisesRegex(ValueError, 'one numeric release'):
            release.verify(self.root)

    def test_windows_line_endings_are_accepted(self):
        path = self.root / 'clab-backup-ui/VERSION'
        path.write_bytes(path.read_bytes().strip() + b'\r\n')
        self.assertEqual(release.verify(self.root), release.verify(ROOT))

    def test_source_check_precedes_host_setup(self):
        launcher = (ROOT / 'deploy/start-manager.sh').read_text()
        self.assertLess(launcher.index('verify-release.py'), launcher.index('bash "$script_dir/setup-discovery.sh"'))


if __name__ == '__main__':
    unittest.main()
