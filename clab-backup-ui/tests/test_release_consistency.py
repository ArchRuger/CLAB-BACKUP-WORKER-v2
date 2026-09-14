import importlib.util
from pathlib import Path
import shutil
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'deploy' / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


release = load('release_check', 'verify-release.py')
set_release = load('set_release', 'set-release.py')


def docs_fixture(root, version):
    """A minimal living-documentation tree that passes verify_docs for `version`."""
    files = {
        'README.md': f'# Manager\n\nCurrent release: **{version}** · changelog\n\nClone into ~/projects/clab-manager.\n',
        'docs/INSTALL.md': '# Guided installation\n\nLabs saved since 1.19.3 keep their login. '
                           'The Flow panel (`andrewbmchugh-flow-panel` 1.20.1) draws the map.\n',
        'docs/archive/OLD.md': '# Old guide — 1.12.0\n\ncd ~/projects/v1.12.0 && docker build -t clab-backup:1.12.0 .\n',
        'docs/CHANGELOG.md': f'# Changelog\n\n## Changes in {version}\n\n- x\n\n## Changes in 1.19.2\n\n- y\n',
        'clab-backup-ui/VALIDATION.md': f'# Audit — {version}\n\nevidence\n\n# Older — 1.19.2\n',
        'agent instructions.md': f'# Audit — {version}\n\nnotes\n\n# Older — 1.19.2\n',
        'clab-backup-ui/README.md': 'Run the tests.\n',
        'clab-backup-ui/NODE-FEATURES.md': 'Node actions.\n',
        'deploy/NOTICES.md': '| Flow panel (`andrewbmchugh-flow-panel` 1.20.1) | Apache-2.0 |\n',
    }
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')


class ReleaseConsistencyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name in ('clab-backup-ui/VERSION', *release.FIELDS):
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, path)
        self.version = release.read_version(self.root)

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

    def test_capture_and_grafana_stacks_follow_storage_and_precede_the_image_build(self):
        launcher = (ROOT / 'deploy/start-manager.sh').read_text()
        order = [launcher.index(step) for step in ('setup-vm.sh', 'setup-capture.sh" --no-recreate',
                                                    'setup-telemetry.sh" --no-recreate', 'compose.yml build')]
        self.assertEqual(order, sorted(order), 'stacks need the data directory and must precede the manager build')
        self.assertIn('--manager-only', launcher)
        # A pending documentation section must never block a VM install: the VM scripts check the runtime set only.
        for script in ('start-manager.sh', 'setup-capture.sh', 'setup-telemetry.sh'):
            with self.subTest(script=script):
                self.assertIn('verify-release.py" --runtime', (ROOT / 'deploy' / script).read_text())
        for script in ('setup-capture.sh', 'setup-telemetry.sh'):
            with self.subTest(script=script):
                text = (ROOT / 'deploy' / script).read_text()
                self.assertIn('recreate-manager.sh', text)
                self.assertIn('--no-recreate', text)
                self.assertIn('--remove', text)

    # ---- documentation ------------------------------------------------------------------

    def test_documentation_names_only_the_current_release(self):
        self.assertEqual(release.verify_docs(ROOT), release.verify(ROOT))

    def test_stale_releases_versioned_folders_and_image_tags_are_reported_with_lines(self):
        docs_fixture(self.root, self.version)
        (self.root / 'docs/INSTALL.md').write_text('# Guided installation — 1.19.2\n\nThis guide targets 1.19.2.\n'
                                                   'Clone into ~/projects/v1.19.2 and build clab-backup:1.19.2.\n', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'disagrees') as error:
            release.verify_docs(self.root)
        message = str(error.exception)
        self.assertIn('docs/INSTALL.md:1: names release 1.19.2', message)
        self.assertIn('docs/INSTALL.md:3: names release 1.19.2', message)
        self.assertIn('docs/INSTALL.md:4: versioned source folder', message)
        self.assertIn('docs/INSTALL.md:4: versioned image tag', message)
        self.assertNotIn('archive', message, 'superseded guides may name their release')
        self.assertNotIn('CHANGELOG', message)

    def test_history_phrases_third_party_versions_and_history_files_are_allowed(self):
        docs_fixture(self.root, self.version)
        (self.root / 'docs/GUIDE.md').write_text(
            'Works on 1.22.0 or later. Introduced in 1.23.0; upgrading from 1.19.4. Since **1.19.3** the wizard asks.\n'
            'Prometheus v3.14.0, Grafana 13.0.2, cEOS 4.35.0F at 172.20.20.2, plugin v0.24.0 and xterm.js 1.5.0.\n'
            'See the [UI refinement](archive/UI-UPDATE-1.12.1.md) and [the audit](archive/REPOSITORY-AUDIT-1.15.1.md).\n', encoding='utf-8')
        self.assertEqual(release.verify_docs(self.root), self.version)

    def test_release_sections_must_lead_the_history_files_and_the_readme(self):
        docs_fixture(self.root, self.version)
        (self.root / 'docs/CHANGELOG.md').write_text('# Changelog\n\n## Changes in 1.19.2\n', encoding='utf-8')
        (self.root / 'README.md').write_text('# Manager\n\nCurrent release: **1.19.2**\n', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'disagrees') as error:
            release.verify_docs(self.root)
        self.assertIn('docs/CHANGELOG.md: leads with 1.19.2', str(error.exception))
        self.assertIn('README.md:3: names release 1.19.2', str(error.exception))

    def test_set_release_moves_every_marker_but_not_history_or_third_party_versions(self):
        docs_fixture(self.root, self.version)
        guide = self.root / 'docs/GUIDE.md'
        guide.write_text(f'The installer ends with `Manager {self.version}: running`. Labs saved since {self.version} keep it. '
                         f'Flow panel 1.20.1.\n', encoding='utf-8')
        previous, changed = set_release.set_release(self.root, '9.9.9')
        self.assertEqual(previous, self.version)
        self.assertEqual(release.verify(self.root), '9.9.9')
        text = guide.read_text(encoding='utf-8')
        self.assertIn('Manager 9.9.9: running', text)
        self.assertIn(f'since {self.version}', text, 'a history phrase keeps the release it names')
        self.assertIn('Flow panel 1.20.1', text)
        self.assertIn('Current release: **9.9.9**', (self.root / 'README.md').read_text(encoding='utf-8'))
        self.assertIn('docs/GUIDE.md', changed)
        self.assertIn('clab-backup-ui/VERSION', changed)
        self.assertIn('clab-backup-ui/app/static/index.html', changed)
        with self.assertRaisesRegex(ValueError, 'CHANGELOG.md: leads with'):
            release.verify_docs(self.root)   # the history sections are written by hand
        with self.assertRaisesRegex(ValueError, 'already contains'):
            set_release.set_release(self.root, '9.9.9')


if __name__ == '__main__':
    unittest.main()
