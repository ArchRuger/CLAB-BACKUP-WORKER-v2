import contextlib
import importlib.util
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('retire_telemetry', Path(__file__).resolve().parents[2] / 'deploy/retire_telemetry.py')
retire_telemetry = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = retire_telemetry
spec.loader.exec_module(retire_telemetry)

PROJECT = retire_telemetry.PROJECT
PROMETHEUS_IMAGE = retire_telemetry.IMAGES[0]
GRAFANA_IMAGE = retire_telemetry.IMAGES[1]


def completed(returncode=0, stdout='', stderr=''):
    return subprocess.CompletedProcess([], returncode, stdout=stdout, stderr=stderr)


def container(cid, name, service, project=PROJECT):
    return (cid, name, service, project)


def volume(name, project=PROJECT):
    return (name, project)


class FakeDocker:
    """A docker double keyed on the exact argv shapes retire_telemetry.py issues.

    Containers, volumes and networks carry their own Compose project label; `--filter
    label=...` is actually honoured here (never a name match), so a container that is
    merely named clab-manager-grafana, or one that belongs to a foreign project, is
    correctly excluded from discovery exactly as a real dockerd would exclude it.
    """

    def __init__(self, containers=None, volumes=None, networks=None, images_in_use=None, images_present=None, fail=None):
        self.containers = list(containers or [])  # [(id, name, service, project)]
        self.volumes = list(volumes or [])  # [(name, project)]
        self.networks = list(networks or [])  # [(name, project)]
        self.images_in_use = images_in_use or {}  # image ref -> [other container ids]
        # Images actually present on this host; a fresh/never-installed host has none, so
        # `docker image rm` behaves exactly as it would for real: "no such image".
        self.images_present = set(images_present) if images_present is not None else set()
        self.fail = fail or {}  # keyword -> stderr text, to make that command fail once
        self.calls = []

    @staticmethod
    def _label_value(args):
        for arg in args:
            if arg.startswith('label=com.docker.compose.project='):
                return arg.split('=', 2)[2]
        return None

    def __call__(self, args, **kwargs):
        self.calls.append(list(args))
        if args[:2] == ['docker', 'ps'] and '-q' in args:
            if 'image-ps' in self.fail:
                return completed(1, stderr=self.fail.pop('image-ps'))
            image = next(a.split('=', 1)[1] for a in args if a.startswith('ancestor='))
            return completed(0, stdout='\n'.join(self.images_in_use.get(image, [])))
        if args[:2] == ['docker', 'ps']:
            if 'ps' in self.fail:
                return completed(1, stderr=self.fail.pop('ps'))
            wanted = self._label_value(args)
            matched = [c for c in self.containers if c[3] == wanted]
            return completed(0, stdout='\n'.join(f'{cid} {name} {service}' for cid, name, service, _project in matched))
        if args[:3] == ['docker', 'volume', 'ls']:
            if 'volume-ls' in self.fail:
                return completed(1, stderr=self.fail.pop('volume-ls'))
            wanted = self._label_value(args)
            matched = [name for name, project in self.volumes if project == wanted]
            return completed(0, stdout='\n'.join(matched))
        if args[:3] == ['docker', 'network', 'ls']:
            if 'network-ls' in self.fail:
                return completed(1, stderr=self.fail.pop('network-ls'))
            wanted = self._label_value(args)
            matched = [name for name, project in self.networks if project == wanted]
            return completed(0, stdout='\n'.join(matched))
        if args[:2] == ['docker', 'rm']:
            cid = args[-1]
            if self.fail.get('rm') == cid:
                return completed(1, stderr='boom')
            self.containers = [c for c in self.containers if c[0] != cid]
            return completed(0)
        if args[:3] == ['docker', 'volume', 'rm']:
            name = args[-1]
            if self.fail.get('volume-rm') == name:
                return completed(1, stderr='boom')
            self.volumes = [v for v in self.volumes if v[0] != name]
            return completed(0)
        if args[:3] == ['docker', 'network', 'rm']:
            name = args[-1]
            self.networks = [n for n in self.networks if n[0] != name]
            return completed(0)
        if args[:3] == ['docker', 'image', 'rm']:
            image = args[-1]
            message = self.fail.get('image-rm-' + image)
            if message:
                return completed(1, stderr=message)
            if image not in self.images_present:
                return completed(1, stderr='Error: No such image: ' + image)
            self.images_present.discard(image)
            return completed(0)
        raise AssertionError('unexpected docker call: ' + ' '.join(args))


class RetireTelemetryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'srv' / 'containerlab-node-manager'
        self.root.mkdir(parents=True)
        self.source = Path(self.temp.name) / 'source'
        (self.source / 'deploy').mkdir(parents=True)
        self.env_path = self.source / 'clab-backup-ui' / '.env'
        self.env_path.parent.mkdir(parents=True)
        patcher = patch.object(retire_telemetry, 'DATA_ROOT', str(self.root))
        patcher.start()
        self.addCleanup(patcher.stop)

    def write_env(self, extra=''):
        self.env_path.write_text('UI_PORT=8081\nCAPTURE_PROVIDER=edgeshark\n' + extra, encoding='utf-8')

    def write_env_bytes(self, data):
        self.env_path.write_bytes(data)

    def retire(self, docker, **kwargs):
        kwargs.setdefault('archive_stamp', 'TESTSTAMP')
        return retire_telemetry.retire(env_path=self.env_path, runner=docker, source=self.source, **kwargs)

    # ---- never installed / already retired --------------------------------------------------

    def test_never_installed_reports_nothing_and_env_is_untouched(self):
        self.write_env()
        before = self.env_path.read_bytes()
        docker = FakeDocker()
        found = self.retire(docker)
        self.assertFalse(found)
        self.assertEqual(self.env_path.read_bytes(), before)
        self.assertFalse((self.root / 'telemetry-retired-TESTSTAMP').exists())

    def test_missing_env_file_is_a_no_op(self):
        docker = FakeDocker()
        found = self.retire(docker)
        self.assertFalse(found)
        self.assertFalse(self.env_path.exists())

    def test_repeated_run_after_retirement_is_a_no_op(self):
        self.write_env('TELEMETRY_STACK=disabled\n')
        docker = FakeDocker(containers=[container('a' * 12, 'clab-manager-telemetry-prometheus-1', 'prometheus'),
                                        container('b' * 12, 'clab-manager-grafana', 'grafana')],
                            volumes=[volume('clab-manager-telemetry_prometheus-data'),
                                     volume('clab-manager-telemetry_grafana-data')],
                            images_present={PROMETHEUS_IMAGE, GRAFANA_IMAGE})
        self.assertTrue(self.retire(docker, archive_stamp='FIRST'))
        docker.calls.clear()
        found_again = self.retire(docker, archive_stamp='SECOND')
        self.assertFalse(found_again)
        self.assertNotIn('TELEMETRY_STACK', self.env_path.read_text())

    # ---- a running stack: containers, volumes, images, files, .env ---------------------------

    def test_running_stack_is_fully_removed_and_archived(self):
        config_dir = self.root / 'telemetry'
        (config_dir / 'plugins').mkdir(parents=True)
        (config_dir / 'prometheus.yml').write_text('scrape_configs: []\n')
        maps_dir = self.root / 'data' / 'telemetry' / 'dashboards'
        maps_dir.mkdir(parents=True)
        (maps_dir / 'lab1.json').write_text('{}')
        self.write_env('TELEMETRY_STACK=grafana\nTELEMETRY_GRAFANA_PORT=3000\n'
                       f'TELEMETRY_CONFIG_DIR={config_dir}\nTELEMETRY_MAPS_DIR={maps_dir}\n')
        docker = FakeDocker(containers=[container('a' * 12, 'clab-manager-telemetry-prometheus-1', 'prometheus'),
                                        container('b' * 12, 'clab-manager-grafana', 'grafana')],
                            volumes=[volume('clab-manager-telemetry_prometheus-data'),
                                     volume('clab-manager-telemetry_grafana-data')],
                            images_present={PROMETHEUS_IMAGE, GRAFANA_IMAGE})
        found = self.retire(docker)
        self.assertTrue(found)
        self.assertEqual(docker.containers, [])
        self.assertEqual(docker.volumes, [])
        rm_calls = [c for c in docker.calls if c[:2] == ['docker', 'rm']]
        self.assertEqual([c[-1] for c in rm_calls], ['a' * 12, 'b' * 12])
        image_rm_calls = [c for c in docker.calls if c[:3] == ['docker', 'image', 'rm']]
        self.assertEqual({c[-1] for c in image_rm_calls}, set(retire_telemetry.IMAGES))
        archive = self.root / 'telemetry-retired-TESTSTAMP'
        self.assertFalse(config_dir.exists())
        self.assertFalse(maps_dir.parent.exists())
        self.assertTrue((archive / 'config' / 'prometheus.yml').is_file())
        self.assertTrue((archive / 'dashboards' / 'dashboards' / 'lab1.json').is_file())
        env_text = self.env_path.read_text()
        self.assertNotIn('TELEMETRY_', env_text)
        self.assertIn('UI_PORT=8081', env_text)
        self.assertIn('CAPTURE_PROVIDER=edgeshark', env_text)
        archived_env = (archive / 'env-telemetry.txt').read_text()
        self.assertIn('TELEMETRY_STACK=grafana', archived_env)
        self.assertIn('TELEMETRY_GRAFANA_PORT=3000', archived_env)

    def test_stopped_or_partial_stack_handles_a_single_container_and_a_missing_volume(self):
        self.write_env('TELEMETRY_STACK=disabled\n')
        docker = FakeDocker(containers=[container('c' * 12, 'clab-manager-grafana', 'grafana')], volumes=[])
        found = self.retire(docker)
        self.assertTrue(found)
        self.assertEqual(docker.containers, [])

    def test_unlabelled_grafana_named_container_is_left_alone(self):
        self.write_env()
        # Same name as the real Grafana container, but no Compose project label: a real
        # `docker ps --filter label=...` would never return it, and neither may we.
        docker = FakeDocker(containers=[container('z' * 12, 'clab-manager-grafana', 'grafana', project=None)])
        found = self.retire(docker)
        self.assertFalse(found)
        self.assertEqual(len(docker.containers), 1, 'the unlabelled container is left alone, not removed')
        rm_calls = [c for c in docker.calls if c[:2] == ['docker', 'rm']]
        self.assertEqual(rm_calls, [])

    def test_foreign_compose_project_is_never_matched(self):
        self.write_env()
        docker = FakeDocker(containers=[container('f' * 12, 'other-app-db-1', 'db', project='other-app')],
                            volumes=[volume('other-app_data', project='other-app')])
        found = self.retire(docker)
        self.assertFalse(found)
        self.assertEqual(len(docker.containers), 1, 'a foreign project is left alone')
        self.assertEqual(len(docker.volumes), 1, 'a foreign project volume is left alone')

    # ---- images -------------------------------------------------------------------------------

    def test_image_still_used_by_another_container_is_left_in_place(self):
        self.write_env('TELEMETRY_STACK=disabled\n')
        docker = FakeDocker(containers=[container('a' * 12, 'clab-manager-telemetry-prometheus-1', 'prometheus')],
                            images_in_use={PROMETHEUS_IMAGE: ['other-container-id']})
        self.retire(docker)
        image_rm_calls = [c for c in docker.calls if c[:3] == ['docker', 'image', 'rm']]
        self.assertFalse(any(c[-1] == PROMETHEUS_IMAGE for c in image_rm_calls))

    def test_image_rm_no_such_image_is_ignored(self):
        self.write_env('TELEMETRY_STACK=disabled\n')
        docker = FakeDocker(containers=[container('a' * 12, 'clab-manager-telemetry-prometheus-1', 'prometheus')],
                            fail={'image-rm-' + PROMETHEUS_IMAGE: 'Error: No such image: ' + PROMETHEUS_IMAGE})
        # Must not raise.
        self.retire(docker)

    # ---- purge / dry-run ------------------------------------------------------------------------

    def test_purge_deletes_instead_of_archiving(self):
        config_dir = self.root / 'telemetry'
        config_dir.mkdir(parents=True)
        (config_dir / 'prometheus.yml').write_text('x')
        self.write_env(f'TELEMETRY_CONFIG_DIR={config_dir}\n')
        docker = FakeDocker()
        found = self.retire(docker, purge=True)
        self.assertTrue(found)
        self.assertFalse(config_dir.exists())
        self.assertFalse((self.root / 'telemetry-retired-TESTSTAMP').exists())
        self.assertNotIn('TELEMETRY_', self.env_path.read_text())

    def test_dry_run_changes_nothing_on_disk_or_in_env(self):
        config_dir = self.root / 'telemetry'
        config_dir.mkdir(parents=True)
        (config_dir / 'prometheus.yml').write_text('x')
        self.write_env(f'TELEMETRY_CONFIG_DIR={config_dir}\nTELEMETRY_STACK=grafana\n')
        before_env = self.env_path.read_bytes()
        docker = FakeDocker(containers=[container('a' * 12, 'clab-manager-telemetry-prometheus-1', 'prometheus')],
                            volumes=[volume('clab-manager-telemetry_prometheus-data')])
        found = self.retire(docker, dry_run=True)
        self.assertTrue(found)
        self.assertTrue(config_dir.is_dir())
        self.assertTrue((config_dir / 'prometheus.yml').is_file())
        self.assertEqual(self.env_path.read_bytes(), before_env)
        self.assertFalse((self.root / 'telemetry-retired-TESTSTAMP').exists())
        mutating = [c for c in docker.calls if c[:2] == ['docker', 'rm']
                   or c[:3] in (['docker', 'volume', 'rm'], ['docker', 'network', 'rm'], ['docker', 'image', 'rm'])]
        self.assertEqual(mutating, [])

    # ---- failures -------------------------------------------------------------------------------

    def test_docker_failure_stops_with_a_non_zero_exit_and_a_clear_message(self):
        self.write_env()
        docker = FakeDocker(fail={'ps': 'permission denied'})
        with self.assertRaisesRegex(retire_telemetry.RetireError, 'docker ps failed'):
            self.retire(docker)

    def test_container_removal_failure_raises_and_stops(self):
        self.write_env()
        docker = FakeDocker(containers=[container('a' * 12, 'clab-manager-grafana', 'grafana')], fail={'rm': 'a' * 12})
        with self.assertRaises(retire_telemetry.RetireError):
            self.retire(docker)

    def test_mixed_tree_with_the_old_compose_file_still_present_is_refused(self):
        (self.source / 'deploy' / 'compose.telemetry.yml').write_text('name: clab-manager-telemetry\n')
        self.write_env()
        docker = FakeDocker()
        with self.assertRaisesRegex(retire_telemetry.RetireError, 'mixed checkout'):
            self.retire(docker)

    # ---- path safety: only the two fixed paths are ever touched -----------------------------

    def test_path_is_plain_accepts_an_ordinary_directory(self):
        plain = self.root / 'telemetry'
        plain.mkdir()
        self.assertTrue(retire_telemetry.path_is_plain(plain))

    def test_path_is_plain_rejects_the_leaf_itself_being_a_symlink(self):
        real = self.root / 'real-telemetry'
        real.mkdir()
        leaf = self.root / 'telemetry'
        os.symlink(real, leaf)
        self.assertFalse(retire_telemetry.path_is_plain(leaf))

    def test_path_is_plain_rejects_a_symlinked_middle_component(self):
        real_root = self.root / 'real-root'
        real_root.mkdir()
        linked = self.root / 'linked'
        os.symlink(real_root, linked)
        leaf = linked / 'telemetry'
        leaf.mkdir()
        # `leaf` itself is a plain directory; the symlink is one level up, between it and DATA_ROOT.
        self.assertFalse(retire_telemetry.path_is_plain(leaf))

    def test_symlinked_config_dir_is_reported_and_never_followed(self):
        real = self.root / 'elsewhere'
        real.mkdir()
        (real / 'marker.txt').write_text('do not touch')
        linked = self.root / 'telemetry'
        os.symlink(real, linked)
        self.write_env()
        docker = FakeDocker()
        self.retire(docker, purge=True)
        self.assertTrue(linked.is_symlink(), 'the symlink itself is left in place, never followed or removed')
        self.assertTrue((real / 'marker.txt').is_file(), 'the real target must never be touched')

    def test_env_value_naming_the_backups_folder_is_reported_and_never_touched(self):
        # The old bug: TELEMETRY_MAPS_DIR's *parent* was taken as the folder to remove; a value
        # of <root>/data/backups/x made that parent <root>/data/backups. Only the two fixed
        # paths (DATA_ROOT/telemetry and DATA_ROOT/data/telemetry) are ever touched now, so a
        # different TELEMETRY_MAPS_DIR is reported and left completely alone, even with --purge.
        backups = self.root / 'data' / 'backups'
        backups.mkdir(parents=True)
        (backups / 'important.tar').write_text('do not delete')
        self.write_env(f'TELEMETRY_MAPS_DIR={backups / "x"}\n')
        docker = FakeDocker()
        self.retire(docker, purge=True)
        self.assertTrue(backups.is_dir())
        self.assertTrue((backups / 'important.tar').is_file())

    def test_env_value_naming_a_sibling_folder_is_reported_and_never_touched(self):
        sibling = self.root / 'projects'
        sibling.mkdir()
        (sibling / 'marker.txt').write_text('do not touch')
        self.write_env(f'TELEMETRY_CONFIG_DIR={sibling}\n')
        docker = FakeDocker()
        self.retire(docker)
        self.assertTrue(sibling.is_dir())
        self.assertTrue((sibling / 'marker.txt').is_file())

    def test_env_value_naming_a_data_pre_restore_sibling_is_reported_and_never_touched(self):
        sibling = self.root / 'data.pre-restore-20260101T000000Z'
        sibling.mkdir()
        (sibling / 'marker.txt').write_text('do not touch')
        self.write_env(f'TELEMETRY_CONFIG_DIR={sibling}\n')
        docker = FakeDocker()
        self.retire(docker, purge=True)
        self.assertTrue(sibling.is_dir())
        self.assertTrue((sibling / 'marker.txt').is_file())

    def test_env_override_is_printed_and_the_fixed_default_is_still_processed(self):
        sibling = self.root / 'projects'
        sibling.mkdir()
        fixed = self.root / 'telemetry'
        fixed.mkdir()
        (fixed / 'prometheus.yml').write_text('x')
        self.write_env(f'TELEMETRY_CONFIG_DIR={sibling}\n')
        docker = FakeDocker()
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            found = self.retire(docker)
        self.assertTrue(found)
        self.assertIn(str(sibling), buffer.getvalue())
        self.assertIn('always used', buffer.getvalue())
        self.assertTrue(sibling.is_dir(), 'the named override is never touched')
        self.assertFalse(fixed.exists(), 'the fixed default is still processed regardless of the override')

    # ---- .env byte preservation and mode/owner --------------------------------------------------

    def test_env_unrelated_lines_are_preserved_byte_for_byte_and_order_kept(self):
        self.write_env('# a comment\nTELEMETRY_STACK=grafana\nCAPTURE_SESSION_TOKEN=deadbeef\nTELEMETRY_GRAFANA_PORT=3000\n')
        original_order = [line for line in self.env_path.read_text().splitlines() if not line.startswith('TELEMETRY_')]
        docker = FakeDocker()
        self.retire(docker)
        new_lines = self.env_path.read_text().splitlines()
        self.assertEqual(new_lines, original_order)

    def test_env_mode_and_owner_are_preserved(self):
        self.write_env('TELEMETRY_STACK=grafana\n')
        os.chmod(self.env_path, 0o600)
        mode_before = self.env_path.stat().st_mode
        uid_before, gid_before = self.env_path.stat().st_uid, self.env_path.stat().st_gid
        docker = FakeDocker()
        self.retire(docker)
        self.assertEqual(self.env_path.stat().st_mode, mode_before)
        if os.geteuid() == 0:
            self.assertEqual(self.env_path.stat().st_uid, uid_before)
            self.assertEqual(self.env_path.stat().st_gid, gid_before)

    def test_crlf_env_file_keeps_crlf_on_every_kept_line(self):
        self.write_env_bytes(b'UI_PORT=8081\r\nCAPTURE_PROVIDER=edgeshark\r\nTELEMETRY_STACK=grafana\r\n')
        docker = FakeDocker()
        self.retire(docker)
        self.assertEqual(self.env_path.read_bytes(), b'UI_PORT=8081\r\nCAPTURE_PROVIDER=edgeshark\r\n')

    def test_value_containing_a_vt_character_survives(self):
        # str.splitlines()/bytes.splitlines() treat \x0b (VT) as a line break; a byte-exact
        # rewrite must not, or this line would be corrupted even though it is kept untouched.
        raw = b'UI_PORT=8081\nCAPTURE_SESSION_TOKEN=abc\x0bdef\nTELEMETRY_STACK=grafana\n'
        self.write_env_bytes(raw)
        docker = FakeDocker()
        self.retire(docker)
        self.assertEqual(self.env_path.read_bytes(), b'UI_PORT=8081\nCAPTURE_SESSION_TOKEN=abc\x0bdef\n')

    def test_capture_bytes_are_identical_before_and_after(self):
        capture_line = b'CAPTURE_SESSION_TOKEN=' + b'a' * 64
        raw = b'UI_PORT=8081\n' + capture_line + b'\nTELEMETRY_STACK=grafana\nTELEMETRY_GRAFANA_PORT=3000\n'
        self.write_env_bytes(raw)
        docker = FakeDocker()
        self.retire(docker)
        data = self.env_path.read_bytes()
        self.assertIn(capture_line + b'\n', data)
        self.assertNotIn(b'TELEMETRY_', data)

    # ---- stop before anything is removed ------------------------------------------------------

    def test_non_utf8_env_stops_before_any_docker_query_or_removal(self):
        broken = b'UI_PORT=8081\nTELEMETRY_STACK=\xff\xfe\n'
        self.write_env_bytes(broken)
        docker = FakeDocker(containers=[container('a' * 12, 'clab-manager-grafana', 'grafana')])
        with self.assertRaisesRegex(retire_telemetry.RetireError, 'not valid UTF-8') as error:
            self.retire(docker)
        self.assertIn(str(self.env_path), str(error.exception))
        self.assertIn('Next:', str(error.exception))
        self.assertEqual(docker.calls, [], 'nothing was queried before the bad .env was detected')
        self.assertEqual(self.env_path.read_bytes(), broken)

    def test_unreadable_env_stops_before_any_docker_query_or_removal(self):
        if os.geteuid() == 0:
            self.skipTest('root bypasses file permission checks')
        self.write_env('TELEMETRY_STACK=grafana\n')
        os.chmod(self.env_path, 0o000)
        self.addCleanup(os.chmod, self.env_path, 0o600)
        docker = FakeDocker(containers=[container('a' * 12, 'clab-manager-grafana', 'grafana')])
        with self.assertRaisesRegex(retire_telemetry.RetireError, 'could not be read') as error:
            self.retire(docker)
        self.assertIn(str(self.env_path), str(error.exception))
        self.assertIn('Next:', str(error.exception))
        self.assertEqual(docker.calls, [])

    def test_failed_archive_write_leaves_env_completely_unchanged(self):
        self.write_env('TELEMETRY_STACK=grafana\n')
        before = self.env_path.read_bytes()
        # Block the archive folder with a plain file where retire() needs to create a directory.
        (self.root / 'telemetry-retired-TESTSTAMP').write_text('blocker')
        docker = FakeDocker()
        with self.assertRaises(retire_telemetry.RetireError):
            self.retire(docker)
        self.assertEqual(self.env_path.read_bytes(), before, '.env must be untouched when the archive write fails')

    # ---- CLI (main) -------------------------------------------------------------------------------

    def test_main_rejects_unknown_option_with_usage_and_exit_64(self):
        stderr = io.StringIO()
        with patch.object(sys, 'stderr', stderr):
            code = retire_telemetry.main(['--bogus'])
        self.assertEqual(code, 64)
        self.assertIn('Usage', stderr.getvalue())

    def test_main_forwards_purge_and_dry_run_to_retire(self):
        calls = []
        with patch.object(retire_telemetry, 'retire', side_effect=lambda **kwargs: calls.append(kwargs)):
            self.assertEqual(retire_telemetry.main([]), 0)
            self.assertEqual(retire_telemetry.main(['--purge']), 0)
            self.assertEqual(retire_telemetry.main(['--dry-run']), 0)
        self.assertEqual([c['purge'] for c in calls], [False, True, False])
        self.assertEqual([c['dry_run'] for c in calls], [False, False, True])

    def test_main_reports_a_retire_error_and_returns_1(self):
        stderr = io.StringIO()
        with patch.object(retire_telemetry, 'retire', side_effect=retire_telemetry.RetireError('boom')), \
                patch.object(sys, 'stderr', stderr):
            code = retire_telemetry.main([])
        self.assertEqual(code, 1)
        self.assertIn('boom', stderr.getvalue())


if __name__ == '__main__':
    unittest.main()
