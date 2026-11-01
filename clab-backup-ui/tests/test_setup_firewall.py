"""deploy/setup-firewall.sh (docs/sign-on/EXPOSURE.md 5.2): ufw allows the SSH port(s), the
manager's TLS port and its redirect port, then denies other incoming traffic.

What must hold: the current SSH session's port is never locked out (the script refuses before any
change when that port is not one sshd listens on, whether it learns the port from SSH_CONNECTION or,
under sudo, which drops that variable, from the established sshd connections `ss` lists); `ufw reset`
and `ufw disable` are never run; only rules carrying the comment `clab-manager` are added, an
operator's own rule for a port is kept untouched, and `--remove` deletes only the clab-manager rules
(keeping the SSH one while an active firewall denies other incoming traffic).

The script must run as root and this suite never does anything as root: each test drives a copy of
the shipped script with only its root guard replaced by a no-op (the exact text is asserted, so a
changed guard fails loudly instead of testing stale logic). Fakes for ufw, sshd, ss, systemctl and
docker on PATH record their argv; the ufw fake keeps its rules in a temporary file the way
`ufw show added` reports them. Standard library only: CI runs this before any virtual environment.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / 'deploy/setup-firewall.sh'
ROOT_GUARD = "[[ $EUID -eq 0 ]] || { echo 'Run with sudo.' >&2; exit 1; }"
SYSTEM_PATH = '/usr/bin:/bin'

FAKE_UFW = r'''#!PYTHON
import json, os, re, sys
args = sys.argv[1:]
with open(os.environ['UFW_LOG'], 'a') as log:
    log.write(json.dumps(args) + '\n')
fail = os.environ.get('UFW_FAIL_ON', '')
if fail and fail in ' '.join(args):
    print('ERROR: injected failure', file=sys.stderr)
    sys.exit(1)
rules_path = os.environ['UFW_RULES']
state_path = os.environ['UFW_STATE']
rules = [line for line in open(rules_path).read().splitlines() if line.strip()]
state = json.load(open(state_path))
RULE = re.compile(r"^ufw (allow|deny|reject|limit)(?: in)? (\d+/tcp)(?: comment '(.*)')?$")

def save():
    open(rules_path, 'w').write(''.join(line + '\n' for line in rules))
    json.dump(state, open(state_path, 'w'))

if args[:2] == ['show', 'added']:
    print("Added user rules (see 'ufw status' for running firewall):")
    print('\n'.join(rules) if rules else '(None)')
elif args and args[0] in ('allow', 'deny', 'reject', 'limit'):
    action, spec, rest = args[0], args[1], args[2:]
    comment = rest[1] if rest[:1] == ['comment'] else None
    if any(RULE.match(line) and RULE.match(line).group(2) == spec for line in rules):
        print('Skipping adding existing rule')
    else:
        rules.append(f'ufw {action} {spec}' + (f" comment '{comment}'" if comment else ''))
        print('Rule added')
elif args[:1] == ['delete']:
    action, spec = args[1], args[2]
    kept = [line for line in rules if not (RULE.match(line) and RULE.match(line).group(1) == action and RULE.match(line).group(2) == spec)]
    if len(kept) == len(rules):
        print('Could not delete non-existent rule')
    rules[:] = kept
    print('Rule deleted')
elif args[:1] == ['default']:
    state[args[2]] = args[1]
    print(f'Default {args[2]} policy changed to {args[1]!r}')
elif args == ['--force', 'enable']:
    state['active'] = True
    print('Firewall is active and enabled on system startup')
elif args[:1] == ['status']:
    print('Status: ' + ('active' if state['active'] else 'inactive'))
    if 'verbose' in args:
        print(f"Default: {state['incoming']} (incoming), {state['outgoing']} (outgoing), disabled (routed)")
    if state['active'] and 'numbered' in args:
        for number, line in enumerate(rules, 1):
            print(f'[{number:2}] {line[4:]}')
save()
'''

FAKE_SSHD = r'''#!/usr/bin/env bash
echo "sshd $*" >> "$OTHER_LOG"
if [[ "$1" == -T ]]; then
  [[ "${SSHD_T_STATUS:-0}" == 0 ]] || { echo 'sshd: injected failure' >&2; exit "$SSHD_T_STATUS"; }
  for port in $SSHD_PORTS; do echo "port $port"; done
  echo 'addressfamily any'
  echo 'permitrootlogin without-password'
  exit 0
fi
exit 0
'''

FAKE_SS = r'''#!/usr/bin/env bash
echo "ss $*" >> "$OTHER_LOG"
[[ "${SS_STATUS:-0}" == 0 ]] || exit "$SS_STATUS"
case "$*" in
  *established*) printf '%s' "$SS_ESTABLISHED";;
  *listening*) printf '%s' "$SS_LISTENING";;
esac
exit 0
'''

FAKE_UNEXPECTED = r'''#!/usr/bin/env bash
echo "$(basename "$0") $*" >> "$OTHER_LOG"
echo "unexpected call to $(basename "$0")" >&2
exit 99
'''

LISTEN_22 = '0      4096         0.0.0.0:22        0.0.0.0:*\n0      4096            [::]:22           [::]:*\n'
SESSION_22 = '0      0       192.0.2.10:22     198.51.100.7:53422 users:(("sshd",pid=1234,fd=4),("sshd",pid=1200,fd=4))\n'


def write_exe(path, text):
    path.write_text(text.replace('#!PYTHON', '#!' + sys.executable))
    path.chmod(0o755)


class FirewallCase(unittest.TestCase):
    def setUp(self):
        text = SCRIPT.read_text()
        self.assertIn(ROOT_GUARD, text,
                      "setup-firewall.sh's root guard text changed; update this test's neutralised copy")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        (self.base / 'deploy').mkdir()
        (self.base / 'clab-backup-ui').mkdir()
        self.script = self.base / 'deploy/setup-firewall.sh'
        self.script.write_text(text.replace(ROOT_GUARD, ': # root check removed for this unit test'))
        self.script.chmod(0o755)
        self.bin = self.base / 'bin'
        self.bin.mkdir()
        write_exe(self.bin / 'ufw', FAKE_UFW)
        write_exe(self.bin / 'sshd', FAKE_SSHD)
        write_exe(self.bin / 'ss', FAKE_SS)
        write_exe(self.bin / 'systemctl', FAKE_UNEXPECTED)
        write_exe(self.bin / 'docker', FAKE_UNEXPECTED)
        self.ufw_log = self.base / 'ufw.log'
        self.other_log = self.base / 'other.log'
        self.rules = self.base / 'rules'
        self.rules.write_text('')
        self.state = self.base / 'state.json'
        self.set_state(active=False, incoming='deny', outgoing='allow')
        self.env = {'PATH': f'{self.bin}{os.pathsep}{SYSTEM_PATH}', 'HOME': str(self.base), 'LC_ALL': 'C',
                    'UFW_LOG': str(self.ufw_log), 'OTHER_LOG': str(self.other_log),
                    'UFW_RULES': str(self.rules), 'UFW_STATE': str(self.state),
                    'SSHD_PORTS': '22', 'SS_LISTENING': LISTEN_22, 'SS_ESTABLISHED': SESSION_22,
                    'SSH_CONNECTION': '198.51.100.7 53422 192.0.2.10 22'}

    def set_state(self, **state):
        self.state.write_text(json.dumps(state))

    def set_rules(self, *lines):
        self.rules.write_text(''.join(line + '\n' for line in lines))

    def rule_lines(self):
        return [line for line in self.rules.read_text().splitlines() if line]

    def write_env(self, name, text):
        (self.base / name).write_text(text)

    def run_script(self, *args, unset=(), **overrides):
        env = {**self.env, **overrides}
        for key in unset:
            env.pop(key, None)
        result = subprocess.run(['bash', str(self.script), *args], cwd=str(self.base), env=env,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=30)
        for call in self.ufw_calls():
            self.assertNotIn('reset', call, result.stdout)
            self.assertNotIn('disable', call, result.stdout)
        self.assertNotIn('unexpected call', result.stdout)
        return result

    def ufw_calls(self):
        if not self.ufw_log.exists():
            return []
        return [json.loads(line) for line in self.ufw_log.read_text().splitlines()]

    def mutating_calls(self):
        return [call for call in self.ufw_calls() if call[:1] not in (['show'], ['status'])]

    def allow_calls(self):
        return [call for call in self.ufw_calls() if call[:1] == ['allow']]


class SetupTests(FirewallCase):
    def test_fresh_host_allows_ssh_then_the_manager_ports_then_denies_and_enables_in_that_order(self):
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(self.mutating_calls(), [
            ['allow', '22/tcp', 'comment', 'clab-manager'],
            ['allow', '8443/tcp', 'comment', 'clab-manager'],
            ['allow', '8081/tcp', 'comment', 'clab-manager'],
            ['default', 'deny', 'incoming'],
            ['default', 'allow', 'outgoing'],
            ['--force', 'enable'],
        ])
        self.assertEqual(self.ufw_calls()[-1], ['status', 'numbered'])
        self.assertIn('Docker-published ports bypass this firewall; the health check lists them.', result.stdout)
        self.assertEqual(self.rule_lines(), ["ufw allow 22/tcp comment 'clab-manager'",
                                             "ufw allow 8443/tcp comment 'clab-manager'",
                                             "ufw allow 8081/tcp comment 'clab-manager'"])

    def test_every_port_sshd_listens_on_is_allowed_before_the_manager_ports(self):
        result = self.run_script(SSHD_PORTS='2222 22')
        self.assertEqual(result.returncode, 0, result.stdout)
        allowed = [call[1] for call in self.allow_calls()]
        self.assertEqual(allowed, ['22/tcp', '2222/tcp', '8443/tcp', '8081/tcp'])

    def test_session_port_not_listed_by_sshd_is_refused_before_any_change(self):
        result = self.run_script(SSH_CONNECTION='198.51.100.7 53422 192.0.2.10 2200')
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn('2200', result.stdout)
        self.assertIn('Nothing was changed', result.stdout)
        self.assertEqual(self.mutating_calls(), [])

    def test_malformed_ssh_connection_is_refused_because_the_session_port_is_unknown(self):
        result = self.run_script(SSH_CONNECTION='garbage')
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn('Nothing was changed', result.stdout)
        self.assertEqual(self.mutating_calls(), [])

    def test_under_sudo_without_ssh_connection_an_sshd_session_on_an_unlisted_port_is_refused(self):
        # sudo's env_reset drops SSH_CONNECTION; the established sshd connections are the evidence.
        listening = LISTEN_22 + '0      128          0.0.0.0:2200      0.0.0.0:*\n'
        session = '0      0       192.0.2.10:2200   198.51.100.7:50000 users:(("sshd-session",pid=99,fd=4))\n'
        result = self.run_script(unset=('SSH_CONNECTION',), SS_LISTENING=listening, SS_ESTABLISHED=session)
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn('2200', result.stdout)
        self.assertEqual(self.mutating_calls(), [])

    def test_an_sshd_forwarding_socket_on_an_ephemeral_port_is_not_mistaken_for_a_session(self):
        # VS Code Remote-SSH: sshd holds an outgoing connection to the forwarded server port.
        forwarded = SESSION_22 + '0      0        127.0.0.1:51234    127.0.0.1:34567 users:(("sshd",pid=1234,fd=9))\n'
        result = self.run_script(unset=('SSH_CONNECTION',), SS_ESTABLISHED=forwarded)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertNotIn('51234', ' '.join(' '.join(call) for call in self.ufw_calls()))

    def test_a_console_session_without_ssh_proceeds(self):
        result = self.run_script(unset=('SSH_CONNECTION',), SS_ESTABLISHED='')
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(self.ufw_calls()[-2], ['--force', 'enable'])

    def test_ss_failure_is_refused_because_the_sessions_cannot_be_seen(self):
        result = self.run_script(SS_STATUS='1')
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertEqual(self.mutating_calls(), [])

    def test_sshd_t_failure_is_refused_before_any_change(self):
        result = self.run_script(SSHD_T_STATUS='255')
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn('sshd -T', result.stdout)
        self.assertEqual(self.mutating_calls(), [])

    def test_missing_ufw_is_refused_with_the_install_command(self):
        if shutil.which('ufw', path=SYSTEM_PATH):
            self.skipTest('a real ufw is on the system PATH')
        (self.bin / 'ufw').unlink()
        result = self.run_script()
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn('apt-get install -y ufw', result.stdout)

    def test_env_ports_are_used_and_a_zero_redirect_port_is_not_opened(self):
        self.write_env('clab-backup-ui/.env', 'UI_BIND=0.0.0.0\nUI_PORT=9443\nUI_HTTP_PORT=0\n')
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual([call[1] for call in self.allow_calls()], ['22/tcp', '9443/tcp'])

    def test_the_last_value_in_env_wins_as_start_manager_reads_it_and_empty_means_default(self):
        self.write_env('clab-backup-ui/.env', 'UI_PORT=9000\nUI_PORT=9443\nUI_HTTP_PORT=\n')
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual([call[1] for call in self.allow_calls()], ['22/tcp', '9443/tcp', '8081/tcp'])

    def test_a_prepared_image_installation_also_opens_the_ports_of_image_env(self):
        self.write_env('deploy/image.env', 'MANAGER_IMAGE=registry.example/clab-backup:9.9.9\nUI_PORT=8555\nUI_HTTP_PORT=0\n')
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual([call[1] for call in self.allow_calls()], ['22/tcp', '8443/tcp', '8555/tcp', '8081/tcp'])

    def test_image_env_without_manager_image_is_ignored(self):
        self.write_env('deploy/image.env', 'UI_PORT=8555\n')
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertNotIn('8555/tcp', [call[1] for call in self.allow_calls()])

    def test_a_port_value_that_is_not_a_port_is_refused_before_any_change(self):
        for value in ('84x3', '0', '70000', '"8443"'):
            with self.subTest(value=value):
                self.ufw_log.unlink(missing_ok=True)
                self.write_env('clab-backup-ui/.env', f'UI_PORT={value}\n')
                result = self.run_script()
                self.assertEqual(result.returncode, 1, result.stdout)
                self.assertIn('UI_PORT', result.stdout)
                self.assertEqual(self.mutating_calls(), [])

    def test_a_manager_port_equal_to_the_ssh_port_is_allowed_once(self):
        self.write_env('clab-backup-ui/.env', 'UI_PORT=22\n')
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual([call[1] for call in self.allow_calls()], ['22/tcp', '8081/tcp'])

    def test_an_operators_own_rule_for_a_port_is_kept_and_not_taken_over(self):
        for own in ('ufw allow 22/tcp', 'ufw limit 22/tcp', "ufw allow 22/tcp comment 'admin ssh'"):
            with self.subTest(own=own):
                self.ufw_log.unlink(missing_ok=True)
                self.set_rules(own, 'ufw allow 80/tcp')
                result = self.run_script()
                self.assertEqual(result.returncode, 0, result.stdout)
                self.assertNotIn('22/tcp', [call[1] for call in self.allow_calls()])
                self.assertIn('Kept your own rule for 22/tcp', result.stdout)
                self.assertEqual(self.rule_lines()[:2], [own, 'ufw allow 80/tcp'])

    def test_an_operators_deny_on_the_ssh_port_is_refused_before_any_change(self):
        for own in ('ufw deny 22/tcp', 'ufw reject 22/tcp'):
            with self.subTest(own=own):
                self.ufw_log.unlink(missing_ok=True)
                self.set_rules(own)
                result = self.run_script()
                self.assertEqual(result.returncode, 1, result.stdout)
                self.assertIn(own[4:], result.stdout)
                self.assertEqual(self.mutating_calls(), [])

    def test_an_operators_deny_on_a_manager_port_is_kept_and_named(self):
        self.set_rules('ufw deny 8081/tcp')
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertNotIn('8081/tcp', [call[1] for call in self.allow_calls()])
        self.assertIn('deny 8081/tcp', result.stdout)
        self.assertIn('ufw deny 8081/tcp', self.rule_lines())

    def test_rules_of_other_directions_and_ports_do_not_count_as_the_operators_rule(self):
        self.set_rules('ufw allow out 22/tcp', 'ufw allow 22', 'ufw allow 2222/tcp')
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(self.allow_calls()[0], ['allow', '22/tcp', 'comment', 'clab-manager'])

    def test_a_second_run_adds_nothing_and_keeps_the_rules(self):
        self.assertEqual(self.run_script().returncode, 0)
        before = self.rule_lines()
        self.ufw_log.unlink()
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(self.allow_calls(), [])
        self.assertEqual(self.rule_lines(), before)
        self.assertIn('Already allowed 22/tcp', result.stdout)

    def test_an_active_firewall_keeps_the_operators_rules(self):
        self.set_state(active=True, incoming='allow', outgoing='allow')
        self.set_rules('ufw allow 80/tcp', "ufw allow 9000/tcp comment 'lab'")
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(self.rule_lines()[:2], ['ufw allow 80/tcp', "ufw allow 9000/tcp comment 'lab'"])
        self.assertEqual(json.loads(self.state.read_text())['incoming'], 'deny')

    def test_a_ufw_failure_before_enable_leaves_ufw_not_enabled(self):
        result = self.run_script(UFW_FAIL_ON='allow 8081/tcp')
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertNotIn(['--force', 'enable'], self.ufw_calls())
        self.assertFalse(json.loads(self.state.read_text())['active'])

    def test_unknown_options_are_refused(self):
        for args in (['--reset'], ['--remove', 'extra'], ['-y']):
            with self.subTest(args=args):
                result = self.run_script(*args)
                self.assertEqual(result.returncode, 64, result.stdout)
                self.assertEqual(self.mutating_calls(), [])

    def test_shipped_script_has_the_root_guard_and_valid_syntax(self):
        subprocess.run(['bash', '-n', str(SCRIPT)], check=True)
        self.assertIn(ROOT_GUARD, SCRIPT.read_text())
        self.assertNotIn('ufw reset', SCRIPT.read_text())


class RemoveTests(FirewallCase):
    OURS = ["ufw allow 22/tcp comment 'clab-manager'", "ufw allow 8443/tcp comment 'clab-manager'",
            "ufw allow 8081/tcp comment 'clab-manager'"]
    THEIRS = ['ufw allow 80/tcp', "ufw allow 9000/tcp comment 'other'", "ufw allow 8082/tcp comment 'clab-manager-old'"]

    def test_remove_on_an_active_denying_firewall_deletes_the_manager_ports_and_keeps_the_ssh_allow(self):
        self.set_state(active=True, incoming='deny', outgoing='allow')
        self.set_rules(*self.OURS, *self.THEIRS)
        result = self.run_script('--remove')
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(self.mutating_calls(), [['delete', 'allow', '8443/tcp'], ['delete', 'allow', '8081/tcp']])
        self.assertEqual(self.rule_lines(), [self.OURS[0], *self.THEIRS])
        self.assertIn('Kept the SSH allow on 22/tcp', result.stdout)
        self.assertIn('sudo ufw delete allow 22/tcp', result.stdout)
        self.assertTrue(json.loads(self.state.read_text())['active'])

    def test_remove_on_an_inactive_firewall_deletes_all_three(self):
        self.set_rules(*self.OURS, *self.THEIRS)
        result = self.run_script('--remove')
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(self.mutating_calls(), [['delete', 'allow', '22/tcp'], ['delete', 'allow', '8443/tcp'],
                                                 ['delete', 'allow', '8081/tcp']])
        self.assertEqual(self.rule_lines(), self.THEIRS)

    def test_remove_on_an_active_allowing_firewall_deletes_all_three(self):
        self.set_state(active=True, incoming='allow', outgoing='allow')
        self.set_rules(*self.OURS)
        result = self.run_script('--remove')
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(self.rule_lines(), [])

    def test_remove_keeps_an_allow_on_a_port_a_session_is_connected_on(self):
        self.set_state(active=True, incoming='deny', outgoing='allow')
        self.set_rules("ufw allow 2200/tcp comment 'clab-manager'")
        listening = LISTEN_22 + '0      128          0.0.0.0:2200      0.0.0.0:*\n'
        session = '0      0       192.0.2.10:2200   198.51.100.7:50000 users:(("sshd",pid=99,fd=4))\n'
        result = self.run_script('--remove', unset=('SSH_CONNECTION',), SS_LISTENING=listening, SS_ESTABLISHED=session)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(self.mutating_calls(), [])

    def test_remove_with_no_rules_of_its_own_changes_nothing(self):
        self.set_rules(*self.THEIRS)
        result = self.run_script('--remove')
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(self.mutating_calls(), [])
        self.assertIn('No clab-manager rules', result.stdout)

    def test_remove_never_changes_defaults_or_enables(self):
        self.set_rules(*self.OURS)
        self.run_script('--remove')
        for call in self.ufw_calls():
            self.assertNotIn(call[:1], (['default'], ['--force'], ['enable']))

    def test_remove_refuses_when_sshd_t_fails(self):
        self.set_state(active=True, incoming='deny', outgoing='allow')
        self.set_rules(*self.OURS)
        result = self.run_script('--remove', SSHD_T_STATUS='255')
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertEqual(self.mutating_calls(), [])

    def test_setup_then_remove_on_an_inactive_firewall_round_trips_to_the_operators_rules(self):
        self.set_rules(*self.THEIRS)
        self.assertEqual(self.run_script().returncode, 0)
        self.set_state(active=False, incoming='deny', outgoing='allow')
        self.assertEqual(self.run_script('--remove').returncode, 0)
        self.assertEqual(self.rule_lines(), self.THEIRS)


if __name__ == '__main__':
    unittest.main()
