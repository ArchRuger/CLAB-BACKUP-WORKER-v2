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
FAKE_SETUP_TLS = """#!/usr/bin/env bash
echo "$@" >> "$TLS_LOG"
exit "$TLS_EXIT"
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
        # setup-tls.sh --prepare settles the ports and checks the TLS files of the chosen route before `up`;
        # its own logic is test_setup_tls.py's, so a fake records the call here.
        setup_tls = self.base / 'deploy/setup-tls.sh'
        setup_tls.write_text(FAKE_SETUP_TLS)
        setup_tls.chmod(0o755)
        self.tls_log = self.base / 'tls.log'
        self.env = {**os.environ, 'PATH': str(bin_dir) + os.pathsep + os.environ.get('PATH', ''),
                   'DOCKER_LOG': str(self.docker_log), 'EXISTING_ID': '', 'RUNNING_IMAGE': '',
                   'LOCAL_SOURCE_IMAGE_ID': '', 'TLS_LOG': str(self.tls_log), 'TLS_EXIT': '0'}

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
        up_call = next(call for call in self.docker_calls() if 'up -d --no-build --no-deps --force-recreate backup-ui' in call)
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
        up_call = next(call for call in self.docker_calls() if 'up -d --no-build --no-deps --force-recreate backup-ui' in call)
        self.assertIn('clab-backup-ui/compose.yml', up_call)
        self.assertNotIn('compose.image.yml', up_call)

    def test_running_image_matches_manager_image_routes_to_the_prepared_image_compose_file(self):
        self.write_image_env('registry.example/clab-backup:9.9.9')
        result = self.run_script(EXISTING_ID='abc123', RUNNING_IMAGE='registry.example/clab-backup:9.9.9',
                                 LOCAL_SOURCE_IMAGE_ID='sha256:localbuild')
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn('prepared-image installation', result.stdout)
        up_call = next(call for call in self.docker_calls() if 'up -d --no-build --no-deps --force-recreate backup-ui' in call)
        self.assertIn(str(self.base / 'deploy/compose.image.yml'), up_call)
        self.assertIn(str(self.base / 'deploy/image.env'), up_call)

    def test_no_local_source_image_routes_to_the_prepared_image_compose_file_even_if_running_image_differs(self):
        self.write_image_env('registry.example/clab-backup:9.9.9')
        result = self.run_script(EXISTING_ID='abc123', RUNNING_IMAGE='registry.example/clab-backup:9.8.0',
                                 LOCAL_SOURCE_IMAGE_ID='')
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn('prepared-image installation', result.stdout)
        up_call = next(call for call in self.docker_calls() if 'up -d --no-build --no-deps --force-recreate backup-ui' in call)
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

    def tls_calls(self):
        return self.tls_log.read_text().splitlines() if self.tls_log.exists() else []

    def test_the_tls_step_runs_for_the_chosen_route_before_up_and_a_failure_stops_the_recreate(self):
        # A pre-TLS installation after `git pull`, or an operator who set UI_PORT=8081 by hand and recreates: the
        # ports are settled and the TLS files checked for the route that `up` will use, never for the other one.
        result = self.run_script(EXISTING_ID='abc123')
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(self.tls_calls(), ['--prepare --route source'])
        self.assertLess(result.stdout.index('source-build installation'), result.stdout.index('Manager recreated'))
        self.write_image_env('registry.example/clab-backup:9.9.9')
        self.tls_log.unlink()
        result = self.run_script(EXISTING_ID='abc123', RUNNING_IMAGE='registry.example/clab-backup:9.9.9', LOCAL_SOURCE_IMAGE_ID='')
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(self.tls_calls(), ['--prepare --route image'])
        self.docker_log.unlink()
        self.tls_log.unlink()
        (self.base / 'deploy/image.env').unlink()
        result = self.run_script(EXISTING_ID='abc123', TLS_EXIT='1')
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertEqual(self.tls_calls(), ['--prepare --route source'])
        self.assertFalse([call for call in self.docker_calls() if 'up -d' in call], 'nothing is recreated when the TLS step refuses')
        self.assertNotIn('Manager recreated', result.stdout)

    def test_no_existing_container_never_runs_the_tls_step(self):
        result = self.run_script(EXISTING_ID='')
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(self.tls_calls(), [])

    def test_both_services_are_force_recreated_so_a_new_certificate_is_loaded(self):
        # A certificate change (setup-tls.sh --renew, --name, --cert, --self-signed) only changes files inside the
        # bind-mounted tls directory: without --force-recreate compose answers "Running" and leaves uvicorn serving
        # the certificate it loaded at start while the script still says the manager was recreated.
        for route in ('source', 'image'):
            with self.subTest(route=route):
                self.docker_log.unlink(missing_ok=True)
                if route == 'image':
                    self.write_image_env('registry.example/clab-backup:9.9.9')
                result = self.run_script(EXISTING_ID='abc123', RUNNING_IMAGE='registry.example/clab-backup:9.9.9')
                self.assertEqual(result.returncode, 0, result.stdout)
                ups = [call for call in self.docker_calls() if ' up ' in call]
                self.assertEqual(len(ups), 1, ups)
                words = ups[0].split()
                services = words[words.index('--no-deps') + 1:]
                self.assertIn('--force-recreate', words, ups[0])
                self.assertEqual([w for w in services if not w.startswith('-')], ['backup-ui', 'http-redirect'], ups[0])
                self.assertIn('--no-build', words)

    def test_syntax(self):
        subprocess.run(['bash', '-n', str(SCRIPT)], check=True)


if __name__ == '__main__':
    unittest.main()
