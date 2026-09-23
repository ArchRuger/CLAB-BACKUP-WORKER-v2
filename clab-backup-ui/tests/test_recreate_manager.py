"""deploy/recreate-manager.sh routing: source-build compose file vs. a detected
prepared-image installation (deploy/image.env + deploy/compose.image.yml), and the
"no container yet" message when nothing exists to recreate.

The real script requires EUID 0 (`sudo bash deploy/recreate-manager.sh`), and this
suite must never run as root or invoke sudo. Each test drives a copy of the actual
script with only that root guard's exact text replaced by a no-op, so the routing
logic under test is byte-identical to what ships; a fake `docker` on PATH stands in
for the real daemon. If the guard's text ever changes, `setUp` fails loudly instead
of silently testing stale logic.
"""
import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / 'deploy/recreate-manager.sh'
ROOT_GUARD = "[[ $EUID -eq 0 ]] || { echo 'Run with sudo.' >&2; exit 1; }"

FAKE_DOCKER = """#!/usr/bin/env bash
echo "$@" >> "$DOCKER_LOG"
case "$*" in
  *'ps --all --quiet backup-ui'*) printf '%s\\n' "$EXISTING_ID";;
  *'inspect --format {{.Config.Image}}'*) printf '%s\\n' "$RUNNING_IMAGE";;
  *'images --quiet '*) printf '%s\\n' "$LOCAL_SOURCE_IMAGE_ID";;
esac
exit 0
"""


class RecreateManagerRoutingTests(unittest.TestCase):
    def setUp(self):
        text = SCRIPT.read_text()
        self.assertIn(ROOT_GUARD, text,
                     "recreate-manager.sh's root guard text changed; update this test's neutralised copy")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        (self.base / 'deploy').mkdir()
        (self.base / 'clab-backup-ui').mkdir()
        neutralised = text.replace(ROOT_GUARD, ': # root check removed for this unit test')
        self.script = self.base / 'deploy/recreate-manager.sh'
        self.script.write_text(neutralised)
        self.script.chmod(0o755)
        (self.base / 'deploy/compose.image.yml').write_text('services: {}\n')
        (self.base / 'clab-backup-ui/compose.yml').write_text('services: {}\n')
        (self.base / 'clab-backup-ui/VERSION').write_text('9.9.9\n')
        bin_dir = self.base / 'bin'
        bin_dir.mkdir()
        docker = bin_dir / 'docker'
        docker.write_text(FAKE_DOCKER)
        docker.chmod(docker.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
        self.docker_log = self.base / 'docker.log'
        self.env = {**os.environ, 'PATH': str(bin_dir) + os.pathsep + os.environ.get('PATH', ''),
                   'DOCKER_LOG': str(self.docker_log), 'EXISTING_ID': '', 'RUNNING_IMAGE': '',
                   'LOCAL_SOURCE_IMAGE_ID': ''}

    def write_image_env(self, manager_image):
        (self.base / 'deploy/image.env').write_text(f'MANAGER_IMAGE={manager_image}\n')

    def run_script(self, **env_overrides):
        env = {**self.env, **env_overrides}
        return subprocess.run(['bash', str(self.script)], cwd=str(self.base), env=env,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=15)

    def docker_calls(self):
        return self.docker_log.read_text().splitlines() if self.docker_log.exists() else []

    def test_no_existing_container_prints_the_start_manager_hint_and_never_recreates(self):
        result = self.run_script(EXISTING_ID='')
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn('No manager container exists', result.stdout)
        self.assertIn('start-manager.sh', result.stdout)
        calls = self.docker_calls()
        self.assertEqual(len(calls), 1, calls)
        self.assertIn('ps --all --quiet backup-ui', calls[0])

    def test_no_image_env_uses_the_source_build_compose_file(self):
        result = self.run_script(EXISTING_ID='abc123')
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn('source-build installation', result.stdout)
        up_call = next(call for call in self.docker_calls() if 'up -d --no-build --no-deps backup-ui' in call)
        self.assertIn(str(self.base / 'clab-backup-ui/compose.yml'), up_call)
        self.assertNotIn('compose.image.yml', up_call)
        self.assertNotIn('--env-file', up_call)
        self.assertIn('Manager recreated', result.stdout)

    def test_image_env_present_but_running_image_differs_and_source_image_exists_stays_on_source(self):
        self.write_image_env('registry.example/clab-backup:9.9.9')
        result = self.run_script(EXISTING_ID='abc123', RUNNING_IMAGE='clab-backup:9.9.9',
                                 LOCAL_SOURCE_IMAGE_ID='sha256:localbuild')
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn('source-build installation', result.stdout)
        up_call = next(call for call in self.docker_calls() if 'up -d --no-build --no-deps backup-ui' in call)
        self.assertIn('clab-backup-ui/compose.yml', up_call)
        self.assertNotIn('compose.image.yml', up_call)

    def test_running_image_matches_manager_image_routes_to_the_prepared_image_compose_file(self):
        self.write_image_env('registry.example/clab-backup:9.9.9')
        result = self.run_script(EXISTING_ID='abc123', RUNNING_IMAGE='registry.example/clab-backup:9.9.9',
                                 LOCAL_SOURCE_IMAGE_ID='sha256:localbuild')
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn('prepared-image installation', result.stdout)
        up_call = next(call for call in self.docker_calls() if 'up -d --no-build --no-deps backup-ui' in call)
        self.assertIn(str(self.base / 'deploy/compose.image.yml'), up_call)
        self.assertIn(str(self.base / 'deploy/image.env'), up_call)

    def test_no_local_source_image_routes_to_the_prepared_image_compose_file_even_if_running_image_differs(self):
        self.write_image_env('registry.example/clab-backup:9.9.9')
        result = self.run_script(EXISTING_ID='abc123', RUNNING_IMAGE='registry.example/clab-backup:9.8.0',
                                 LOCAL_SOURCE_IMAGE_ID='')
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn('prepared-image installation', result.stdout)
        up_call = next(call for call in self.docker_calls() if 'up -d --no-build --no-deps backup-ui' in call)
        self.assertIn('compose.image.yml', up_call)

    def test_both_compose_invocations_use_the_same_chosen_route(self):
        self.write_image_env('registry.example/clab-backup:9.9.9')
        result = self.run_script(EXISTING_ID='abc123', RUNNING_IMAGE='registry.example/clab-backup:9.9.9',
                                 LOCAL_SOURCE_IMAGE_ID='')
        self.assertEqual(result.returncode, 0, result.stdout)
        calls = [call for call in self.docker_calls() if 'compose.image.yml' in call or 'compose.yml' in call]
        # The existing-container probe always uses the source compose file (project name is
        # shared across both files); the recreate and the closing status ps must both use the
        # chosen route, never a mix.
        recreate_calls = [call for call in calls if 'up -d' in call or call.rstrip().endswith(' ps')]
        self.assertTrue(recreate_calls)
        for call in recreate_calls:
            self.assertIn('compose.image.yml', call)

    def test_syntax(self):
        subprocess.run(['bash', '-n', str(SCRIPT)], check=True)


if __name__ == '__main__':
    unittest.main()
