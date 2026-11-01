"""deploy/manager-recover-admin.sh (docs/sign-on/DESIGN.md 9.5, EXPOSURE.md 7.1, REVIEW R11).

What must hold: the script takes no options, finds the manager container exactly as
recreate-manager.sh does (source build or prepared image), runs `docker exec <id> python -m
app.recover`, passes its output through unchanged and exits with its status. Only when that status is
0 does it print one line of its own, last: the recovery address
`https://<primary>:<UI_PORT>/setup?recover=1`, with `<primary>` from `setup-tls.sh --primary` and
`UI_PORT` read from the env file of the chosen route (default 8443, the port omitted at 443). Apart
from that line it prints only the route it chose.

The script must run as root and this suite never does anything as root: a copy of the shipped
script with only its root guard replaced, a fake `docker` on PATH and a fake `setup-tls.sh` beside the
copy. The recovery output below is a fixture, not a real code. Standard library only.
"""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / 'deploy/manager-recover-admin.sh'
ROOT_GUARD = "[[ $EUID -eq 0 ]] || { echo 'Run with sudo.' >&2; exit 1; }"
SYSTEM_PATH = '/usr/bin:/bin'
RECOVER_OUTPUT = ('Recovery code: fixture-fixture-fixture-fixture\n'
                  'Valid for 15 minutes. Create one new administrator on the setup page; existing accounts are not changed.\n')
SETUP_MODE_OUTPUT = 'The manager is in setup mode: use the setup code in /data/setup-code.\n'

FAKE_DOCKER = r'''#!/usr/bin/env bash
echo "$@" >> "$DOCKER_LOG"
case "$*" in
  *'ps --all --quiet backup-ui'*) [[ -z "$EXISTING_ID" ]] || printf '%s\n' "$EXISTING_ID";;
  *'inspect --format {{.Config.Image}}'*) printf '%s\n' "$RUNNING_IMAGE";;
  *'images --quiet '*) [[ -z "$LOCAL_SOURCE_IMAGE_ID" ]] || printf '%s\n' "$LOCAL_SOURCE_IMAGE_ID";;
  exec\ *) printf '%s' "$RECOVER_OUTPUT"; exit "$RECOVER_STATUS";;
esac
exit 0
'''

FAKE_SETUP_TLS = r'''#!/usr/bin/env bash
echo "$*" >> "$TLS_LOG"
[[ "${TLS_STATUS:-0}" == 0 ]] || { echo 'setup-tls: no certificate' >&2; exit "$TLS_STATUS"; }
printf '%s\n' "$PRIMARY"
'''

FAKE_UNEXPECTED = r'''#!/usr/bin/env bash
echo "unexpected call to $(basename "$0")" >&2
exit 99
'''


class RecoverAdminTests(unittest.TestCase):
    def setUp(self):
        text = SCRIPT.read_text()
        self.assertIn(ROOT_GUARD, text, "the root guard text changed; update this test's neutralised copy")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        (self.base / 'deploy').mkdir()
        (self.base / 'clab-backup-ui').mkdir()
        self.script = self.base / 'deploy/manager-recover-admin.sh'
        self.script.write_text(text.replace(ROOT_GUARD, ': # root check removed for this unit test'))
        (self.base / 'deploy/setup-tls.sh').write_text(FAKE_SETUP_TLS)
        (self.base / 'deploy/compose.image.yml').write_text('services: {}\n')
        (self.base / 'clab-backup-ui/compose.yml').write_text('services: {}\n')
        (self.base / 'clab-backup-ui/VERSION').write_text('9.9.9\n')
        bin_dir = self.base / 'bin'
        bin_dir.mkdir()
        for name, body in (('docker', FAKE_DOCKER), ('systemctl', FAKE_UNEXPECTED), ('ufw', FAKE_UNEXPECTED),
                           ('sshd', FAKE_UNEXPECTED)):
            (bin_dir / name).write_text(body)
            (bin_dir / name).chmod(0o755)
        self.docker_log = self.base / 'docker.log'
        self.tls_log = self.base / 'tls.log'
        self.env = {'PATH': f'{bin_dir}{os.pathsep}{SYSTEM_PATH}', 'HOME': str(self.base), 'LC_ALL': 'C',
                    'DOCKER_LOG': str(self.docker_log), 'TLS_LOG': str(self.tls_log), 'EXISTING_ID': 'abc123',
                    'RUNNING_IMAGE': 'clab-backup:9.9.9', 'LOCAL_SOURCE_IMAGE_ID': 'sha256:local',
                    'RECOVER_OUTPUT': RECOVER_OUTPUT, 'RECOVER_STATUS': '0', 'PRIMARY': 'vm.example.org'}

    def run_script(self, *args, **overrides):
        result = subprocess.run(['bash', str(self.script), *args], cwd=str(self.base), env={**self.env, **overrides},
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=15)
        self.assertNotIn('unexpected call', result.stderr)
        return result

    def docker_calls(self):
        return self.docker_log.read_text().splitlines() if self.docker_log.exists() else []

    def url_line(self, authority):
        return f'Open https://{authority}/setup?recover=1 within 15 minutes and create one new administrator.'

    def write_image_env(self, *lines):
        (self.base / 'deploy/image.env').write_text(''.join(line + '\n' for line in lines))

    def test_source_route_passes_the_output_through_and_prints_the_recovery_address_last(self):
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        lines = result.stdout.splitlines()
        self.assertEqual(len(lines), 4, lines)
        self.assertIn('source-build installation', lines[0])
        self.assertEqual('\n'.join(lines[1:3]) + '\n', RECOVER_OUTPUT)
        self.assertEqual(lines[3], self.url_line('vm.example.org:8443'))
        self.assertEqual(result.stderr, '')
        self.assertIn('exec abc123 python -m app.recover', self.docker_calls())
        self.assertEqual(self.tls_log.read_text().splitlines(), ['--primary'])

    def test_the_port_comes_from_the_source_env_with_the_last_value_winning(self):
        (self.base / 'clab-backup-ui/.env').write_text('UI_PORT=9000\nUI_HTTP_PORT=8081\nUI_PORT=9443\n')
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines()[-1], self.url_line('vm.example.org:9443'))

    def test_an_empty_ui_port_means_the_default(self):
        (self.base / 'clab-backup-ui/.env').write_text('UI_PORT=\n')
        result = self.run_script()
        self.assertEqual(result.stdout.splitlines()[-1], self.url_line('vm.example.org:8443'))

    def test_port_443_is_omitted_from_the_address(self):
        (self.base / 'clab-backup-ui/.env').write_text('UI_PORT=443\n')
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines()[-1], self.url_line('vm.example.org'))

    def test_prepared_image_route_reads_image_env_and_not_the_source_env(self):
        (self.base / 'clab-backup-ui/.env').write_text('UI_PORT=9443\n')
        self.write_image_env('MANAGER_IMAGE=registry.example/clab-backup:9.9.9', 'UI_PORT=8555')
        result = self.run_script(RUNNING_IMAGE='registry.example/clab-backup:9.9.9')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('prepared-image installation', result.stdout.splitlines()[0])
        self.assertEqual(result.stdout.splitlines()[-1], self.url_line('vm.example.org:8555'))

    def test_prepared_image_route_without_ui_port_uses_the_default_not_the_source_env(self):
        (self.base / 'clab-backup-ui/.env').write_text('UI_PORT=9443\n')
        self.write_image_env('MANAGER_IMAGE=registry.example/clab-backup:9.9.9')
        result = self.run_script(LOCAL_SOURCE_IMAGE_ID='')
        self.assertIn('prepared-image installation', result.stdout.splitlines()[0])
        self.assertEqual(result.stdout.splitlines()[-1], self.url_line('vm.example.org:8443'))

    def test_image_env_with_a_source_built_container_stays_on_the_source_route(self):
        (self.base / 'clab-backup-ui/.env').write_text('UI_PORT=9443\n')
        self.write_image_env('MANAGER_IMAGE=registry.example/clab-backup:9.9.9', 'UI_PORT=8555')
        result = self.run_script()
        self.assertIn('source-build installation', result.stdout.splitlines()[0])
        self.assertEqual(result.stdout.splitlines()[-1], self.url_line('vm.example.org:9443'))

    def test_a_refusal_of_app_recover_is_passed_through_without_an_address(self):
        result = self.run_script(RECOVER_OUTPUT=SETUP_MODE_OUTPUT, RECOVER_STATUS='1')
        self.assertEqual(result.returncode, 1)
        lines = result.stdout.splitlines()
        self.assertEqual(lines[1:], [SETUP_MODE_OUTPUT.rstrip('\n')])
        self.assertNotIn('https://', result.stdout)
        self.assertFalse(self.tls_log.exists())

    def test_the_exit_status_of_app_recover_is_passed_through(self):
        for status in ('2', '3', '125'):
            with self.subTest(status=status):
                result = self.run_script(RECOVER_OUTPUT='', RECOVER_STATUS=status)
                self.assertEqual(result.returncode, int(status))
                self.assertNotIn('https://', result.stdout)

    def test_no_container_is_refused_without_running_anything(self):
        result = self.run_script(EXISTING_ID='')
        self.assertEqual(result.returncode, 1)
        self.assertIn('start-manager.sh', result.stderr)
        self.assertFalse([call for call in self.docker_calls() if call.startswith('exec')])

    def test_the_first_container_id_is_used(self):
        result = self.run_script(EXISTING_ID='abc123\ndef456')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('exec abc123 python -m app.recover', self.docker_calls())

    def test_a_failing_primary_reader_still_prints_an_address_with_a_placeholder(self):
        result = self.run_script(TLS_STATUS='1')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines()[-1], self.url_line('<VM address>:8443'))

    def test_a_primary_name_with_unexpected_characters_is_not_printed(self):
        for primary in ('', 'vm example', 'vm.example/evil', '\x1b[31mred'):
            with self.subTest(primary=primary):
                result = self.run_script(PRIMARY=primary)
                self.assertEqual(result.stdout.splitlines()[-1], self.url_line('<VM address>:8443'))

    def test_an_ipv6_primary_is_bracketed(self):
        result = self.run_script(PRIMARY='2001:db8::10')
        self.assertEqual(result.stdout.splitlines()[-1], self.url_line('[2001:db8::10]:8443'))

    def test_a_ui_port_that_is_not_a_port_falls_back_to_the_default_with_a_note(self):
        (self.base / 'clab-backup-ui/.env').write_text('UI_PORT=84x3\n')
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines()[-1], self.url_line('vm.example.org:8443'))
        self.assertIn('UI_PORT', result.stderr)

    def test_options_are_refused(self):
        for args in (['--force'], ['admin'], ['-h']):
            with self.subTest(args=args):
                result = self.run_script(*args)
                self.assertEqual(result.returncode, 64)
                self.assertEqual(self.docker_calls(), [])

    def test_shipped_script_has_the_root_guard_and_valid_syntax(self):
        subprocess.run(['bash', '-n', str(SCRIPT)], check=True)
        self.assertIn(ROOT_GUARD, SCRIPT.read_text())


if __name__ == '__main__':
    unittest.main()
