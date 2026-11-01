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
`ufw show added` reports them, and its tuple files the way ufw writes /etc/ufw/user.rules and
user6.rules (one per address family: `show added` prints `from 0.0.0.0/0` and `from ::/0` as `any`, so
only the tuples say which family a rule covers). Standard library only: CI runs this before any
virtual environment.
"""
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / 'deploy/setup-firewall.sh'
ROOT_GUARD = "[[ $EUID -eq 0 ]] || { echo 'Run with sudo.' >&2; exit 1; }"
UFW_DEFAULTS_LINE = 'ufw_defaults=/etc/default/ufw'
UFW_RULES_DIR_LINE = 'ufw_rules_dir=/etc/ufw'
IPV6_PROC_LINE = 'ipv6_proc=/proc/sys/net/ipv6'
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
# ufw's tuple files, one per address family: `### tuple ### action proto dport dst sport src dir`.
families = {'4': (os.path.join(os.environ['UFW_DIR'], 'user.rules'), '0.0.0.0/0'),
            '6': (os.path.join(os.environ['UFW_DIR'], 'user6.rules'), '::/0')}
# A missing file stays missing (the script must notice it, not the fake).
tuples = {family: open(path).read().splitlines() if os.path.exists(path) else [] for family, (path, _) in families.items()}

def save():
    open(rules_path, 'w').write(''.join(line + '\n' for line in rules))
    json.dump(state, open(state_path, 'w'))
    for family, (path, _) in families.items():
        if os.path.exists(path):
            open(path, 'w').write(''.join(line + '\n' for line in tuples[family]))

def plain(action, port, every):
    return f'### tuple ### {action} tcp {port} {every} any {every} in'

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
    # Each family gets the rule unless it holds the same tuple already (ufw compares the tuple, not
    # the comment), as ufw adds a family that is missing while it skips the other.
    for family, (_, every) in families.items():
        tuple_line = plain(action, spec.split('/')[0], every)
        if not any(line.split(' comment=')[0] == tuple_line for line in tuples[family]):
            tuples[family].append(tuple_line + (f' comment={comment.encode().hex()}' if comment else ''))
elif args[:1] == ['delete']:
    action, spec = args[1], args[2]
    kept = [line for line in rules if not (RULE.match(line) and RULE.match(line).group(1) == action and RULE.match(line).group(2) == spec)]
    if len(kept) == len(rules):
        print('Could not delete non-existent rule')
    rules[:] = kept
    for family, (_, every) in families.items():
        tuples[family] = [line for line in tuples[family] if line.split(' comment=')[0] != plain(action, spec.split('/')[0], every)]
    print('Rule deleted')
elif args[:1] == ['default']:
    state[args[2]] = args[1]
    print(f'Default {args[2]} policy changed to {args[1]!r}')
elif args == ['--force', 'enable']:
    state['active'] = True
    print('Firewall is active and enabled on system startup')
elif args[:2] == ['app', 'info']:
    apps = json.loads(os.environ.get('UFW_APPS', '{}'))
    if args[2] not in apps:
        print(f"ERROR: Could not find profile '{args[2]}'", file=sys.stderr)
        sys.exit(1)
    print(f'Profile: {args[2]}\nTitle: fixture\nDescription: fixture\n')
    print('Ports:' if len(apps[args[2]]) > 1 else 'Port:')
    for spec in apps[args[2]]:
        print('  ' + spec)
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
  for address in ${SSHD_LISTEN-}; do echo "listenaddress $address"; done
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

# systemctl answers only the ssh.socket questions; SSH_SOCKET_LISTEN empty means the unit is neither
# enabled nor active, otherwise it is the Listen= values, one per line, as systemctl show prints them.
FAKE_SYSTEMCTL = r'''#!/usr/bin/env bash
echo "systemctl $*" >> "$OTHER_LOG"
case "$*" in
  'is-active --quiet ssh.socket'|'is-enabled --quiet ssh.socket') [[ -n "${SSH_SOCKET_LISTEN-}" ]]; exit;;
  'show ssh.socket --property=Listen --value') printf '%s\n' "${SSH_SOCKET_LISTEN-}"; exit 0;;
esac
echo "unexpected call to systemctl" >&2
exit 99
'''

FAKE_UNEXPECTED = r'''#!/usr/bin/env bash
echo "$(basename "$0") $*" >> "$OTHER_LOG"
echo "unexpected call to $(basename "$0")" >&2
exit 99
'''

LISTEN_22 = '0      4096         0.0.0.0:22        0.0.0.0:*\n0      4096            [::]:22           [::]:*\n'
SESSION_22 = '0      0       192.0.2.10:22     198.51.100.7:53422 users:(("sshd",pid=1234,fd=4),("sshd",pid=1200,fd=4))\n'


APPS = {'OpenSSH': ['22/tcp'], 'Open SSH': ['22']}


def tuples_of(line, families='46'):
    """The tuple lines ufw 0.36 writes for one `ufw show added` line, as {family: [tuple, ...]}: the
    forms of ufw's get_command(), checked against a real ufw (an app rule stores the profile's port and
    protocol next to the profile's name; `any` is 0.0.0.0/0 in user.rules and ::/0 in user6.rules; an
    address of one family puts the rule in that family's file only). `families` limits the result, for
    a rule an operator wrote with `from 0.0.0.0/0` or `from ::/0`, which `show added` prints as `any`."""
    match = re.match(r"^ufw (route )?(allow|deny|reject|limit) (.*?)(?: comment '(.*)')?$", line)
    route, action, rest, comment = match.groups()
    words = shlex.split(rest)
    i, direction, iface, log = 0, 'in', '', ''
    if words[:1] in (['in'], ['out']):
        direction, i = words[0], 1
        if words[1:2] == ['on']:
            iface, i = words[2], 3
    if words[i:i + 1] in (['log'], ['log-all']):
        log, i = '_' + words[i], i + 1
    src = dst = 'any'
    sport = dport = proto = 'any'
    sapp = dapp = '-'
    words = words[i:]
    if words and words[0] in ('from', 'to', 'proto'):
        while words:
            key, value, words = words[0], words[1], words[2:]
            if key == 'proto':
                proto = value
                continue
            if key == 'from':
                src = value
            else:
                dst = value
            if words[:1] in (['port'], ['app']):
                kind, name, words = words[0], words[1], words[2:]
                if kind == 'port':
                    if key == 'from':
                        sport = name
                    else:
                        dport = name
                elif key == 'from':
                    sapp = name
                else:
                    dapp = name
    elif words:
        spec = re.match(r'^([0-9][0-9,:]*)(?:/(\w+))?$', words[0])
        if spec:
            dport, proto = spec.group(1), spec.group(2) or 'any'
        else:
            dapp = words[0]
    for app, place in ((dapp, 'd'), (sapp, 's')):
        if app != '-':
            port, _, app_proto = APPS[app][0].partition('/')
            proto = app_proto or 'any'
            if place == 'd':
                dport = port
            else:
                sport = port
    for address in (src, dst):
        if '.' in address:
            families = ''.join(family for family in families if family == '4')
        elif ':' in address:
            families = ''.join(family for family in families if family == '6')
    every = {'4': '0.0.0.0/0', '6': '::/0'}
    result = {}
    for family in families:
        fields = [('route:' if route else '') + action + log, proto, dport,
                  every[family] if dst == 'any' else dst, sport, every[family] if src == 'any' else src]
        if dapp != '-' or sapp != '-':
            fields += [dapp.replace(' ', '%20'), sapp.replace(' ', '%20')]
        fields.append(direction + ('_' + iface if iface else ''))
        result[family] = ['### tuple ### ' + ' '.join(fields) + (f' comment={comment.encode().hex()}' if comment else '')]
    return result


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
        self.assertEqual(text.count(UFW_DEFAULTS_LINE + '\n'), 1, "the ufw defaults line changed; update this test")
        self.ufw_defaults = self.base / 'default-ufw'
        self.ufw_defaults.write_text('# /etc/default/ufw\nIPV6=yes\nDEFAULT_INPUT_POLICY="DROP"\n')
        self.assertEqual(text.count(UFW_RULES_DIR_LINE + '\n'), 1, "the ufw rules directory line changed; update this test")
        self.ufw_dir = self.base / 'etc-ufw'
        self.ufw_dir.mkdir()
        self.assertEqual(text.count(IPV6_PROC_LINE + '\n'), 1, "the kernel IPv6 line changed; update this test")
        self.ipv6_proc = self.base / 'proc-sys-net-ipv6'
        self.ipv6_proc.mkdir()
        self.script.write_text(text.replace(ROOT_GUARD, ': # root check removed for this unit test')
                               .replace(UFW_DEFAULTS_LINE + '\n', f'ufw_defaults={self.ufw_defaults}\n')
                               .replace(UFW_RULES_DIR_LINE + '\n', f'ufw_rules_dir={self.ufw_dir}\n')
                               .replace(IPV6_PROC_LINE + '\n', f'ipv6_proc={self.ipv6_proc}\n'))
        self.script.chmod(0o755)
        self.bin = self.base / 'bin'
        self.bin.mkdir()
        write_exe(self.bin / 'ufw', FAKE_UFW)
        write_exe(self.bin / 'sshd', FAKE_SSHD)
        write_exe(self.bin / 'ss', FAKE_SS)
        write_exe(self.bin / 'systemctl', FAKE_SYSTEMCTL)
        write_exe(self.bin / 'docker', FAKE_UNEXPECTED)
        self.ufw_log = self.base / 'ufw.log'
        self.other_log = self.base / 'other.log'
        self.rules = self.base / 'rules'
        self.set_rules()
        self.state = self.base / 'state.json'
        self.set_state(active=False, incoming='deny', outgoing='allow')
        self.env = {'PATH': f'{self.bin}{os.pathsep}{SYSTEM_PATH}', 'HOME': str(self.base), 'LC_ALL': 'C',
                    'UFW_LOG': str(self.ufw_log), 'OTHER_LOG': str(self.other_log),
                    'UFW_RULES': str(self.rules), 'UFW_STATE': str(self.state), 'UFW_DIR': str(self.ufw_dir),
                    'SSHD_PORTS': '22', 'SS_LISTENING': LISTEN_22, 'SS_ESTABLISHED': SESSION_22,
                    'SSH_CONNECTION': '198.51.100.7 53422 192.0.2.10 22'}

    def set_state(self, **state):
        self.state.write_text(json.dumps(state))

    def set_rules(self, *lines, families='46'):
        """The rules as `ufw show added` lists them, and the tuple files that hold them: in both
        address families, or only in those `families` names (a rule written with `from 0.0.0.0/0`
        or `from ::/0`, which `show added` prints exactly like `any`)."""
        self.rules.write_text(''.join(line + '\n' for line in lines))
        files = {'4': [], '6': []}
        for line in lines:
            for family, tuple_lines in tuples_of(line, families).items():
                files[family] += tuple_lines
        (self.ufw_dir / 'user.rules').write_text(''.join(line + '\n' for line in files['4']))
        (self.ufw_dir / 'user6.rules').write_text(''.join(line + '\n' for line in files['6']))

    def tuple_lines(self, family):
        return (self.ufw_dir / ('user.rules' if family == '4' else 'user6.rules')).read_text().splitlines()

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
        # `show added`, `status` and `app info` (an application profile's ports) only read.
        return [call for call in self.ufw_calls() if call[:1] not in (['show'], ['status']) and call[:2] != ['app', 'info']]

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

    def test_rules_of_other_directions_protocols_and_ports_do_not_count_as_the_operators_rule(self):
        # 'ufw allow 22' used to be listed here; it allows TCP 22 too (no protocol means both), so it
        # now counts as the operator's rule (the next test). A UDP-only rule takes its place.
        self.set_rules('ufw allow out 22/tcp', 'ufw allow 22/udp', 'ufw allow 2222/tcp', 'ufw route allow 22/tcp',
                       'ufw allow from 10.1.0.0/16', 'ufw deny from 203.0.113.9', 'ufw allow 2000:2100/tcp')
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(self.allow_calls()[0], ['allow', '22/tcp', 'comment', 'clab-manager'])

    def test_every_form_of_an_operators_allow_for_the_port_counts_as_their_rule(self):
        for own in ('ufw allow 22', 'ufw allow log 22/tcp', 'ufw allow 21,22/tcp', 'ufw allow 20:30/tcp',
                    'ufw allow to any port 22 proto tcp', 'ufw allow to any', 'ufw allow OpenSSH',
                    "ufw limit 22 comment 'ssh'"):
            with self.subTest(own=own):
                self.ufw_log.unlink(missing_ok=True)
                self.set_rules(own)
                result = self.run_script(UFW_APPS='{"OpenSSH": ["22/tcp"]}')
                self.assertEqual(result.returncode, 0, result.stdout)
                self.assertNotIn('22/tcp', [call[1] for call in self.allow_calls()])
                self.assertIn('Kept your own rule for 22/tcp', result.stdout)
                self.assertEqual(self.rule_lines()[0], own)

    def test_every_form_of_an_operators_deny_on_the_ssh_port_is_refused_before_any_change(self):
        for own in ('ufw deny 22', 'ufw reject 22', 'ufw deny log 22/tcp', 'ufw deny 21,22/tcp', 'ufw deny 20:30/tcp',
                    'ufw deny to any port 22', 'ufw deny from any to any port 22 proto tcp',
                    'ufw deny from 0.0.0.0/0 to any port 22 proto tcp', 'ufw deny to any', 'ufw deny OpenSSH',
                    "ufw deny 'Open SSH'"):
            with self.subTest(own=own):
                self.ufw_log.unlink(missing_ok=True)
                self.set_rules(own)
                result = self.run_script(UFW_APPS='{"OpenSSH": ["22/tcp"], "Open SSH": ["22"]}')
                self.assertEqual(result.returncode, 1, result.stdout)
                self.assertIn(own[4:], result.stdout)
                self.assertIn('Nothing was changed', result.stdout)
                self.assertEqual(self.mutating_calls(), [])

    def test_an_earlier_allow_of_the_operator_is_not_overruled_by_a_later_deny(self):
        self.set_rules('ufw allow 22/tcp', 'ufw deny 22')
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertNotIn('22/tcp', [call[1] for call in self.allow_calls()])

    def test_a_source_restricted_ssh_allow_is_kept_and_not_widened(self):
        for own in ('ufw allow from 10.0.0.0/8 to any port 22 proto tcp', 'ufw allow in on eth0 to any port 22',
                    'ufw limit from 192.0.2.0/24 to any port 22', 'ufw allow from 10.0.0.0/8 to 192.0.2.10 port 22'):
            with self.subTest(own=own):
                self.ufw_log.unlink(missing_ok=True)
                self.set_state(active=True, incoming='deny', outgoing='allow')
                self.set_rules(own)
                result = self.run_script()
                self.assertEqual(result.returncode, 0, result.stdout)
                self.assertNotIn('22/tcp', [call[1] for call in self.allow_calls()])
                self.assertEqual(self.rule_lines()[0], own)
                self.assertIn(f'Kept your own rule for 22/tcp: {own[4:]}', result.stdout)
                self.assertIn('no rule open to every address was added', result.stdout)

    def test_a_restricted_allow_ahead_of_a_general_deny_is_the_operators_restriction_not_a_lockout(self):
        # Accepted while ufw is active and denies other incoming traffic: the restriction is already in
        # effect and the operator reached the VM through it. (This test used to run on an inactive ufw
        # and expect the same acceptance; enabling ufw there blocked new logins from every address
        # outside 10.0.0.0/8, the session's own included. That case is now the refusal below.)
        self.set_state(active=True, incoming='deny', outgoing='allow')
        self.set_rules('ufw allow from 10.0.0.0/8 to any port 22 proto tcp', 'ufw deny 22/tcp')
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertNotIn('22/tcp', [call[1] for call in self.allow_calls()])
        self.assertIn('Kept your own rule for 22/tcp: allow from 10.0.0.0/8', result.stdout)

    def test_a_restricted_ssh_allow_that_is_not_in_effect_yet_is_refused_before_any_change(self):
        # Inactive ufw, or active with incoming allowed (this script would switch it to deny): enabling
        # the restriction blocks new logins from every other address, 198.51.100.7 (the session) included.
        for state in ({'active': False, 'incoming': 'deny'}, {'active': True, 'incoming': 'allow'}):
            for own in (('ufw allow from 10.0.0.0/8 to any port 22 proto tcp', 'ufw deny 22/tcp'),
                        ('ufw allow from 10.0.0.0/8 to any port 22 proto tcp',),
                        ('ufw allow in on eth0 to any port 22',), ('ufw limit from 192.0.2.0/24 to any port 22',)):
                with self.subTest(state=state, own=own):
                    self.ufw_log.unlink(missing_ok=True)
                    self.set_state(outgoing='allow', **state)
                    self.set_rules(*own)
                    result = self.run_script()
                    self.assertEqual(result.returncode, 1, result.stdout)
                    self.assertIn(f"Your ufw rule '{own[0][4:]}'", result.stdout)
                    self.assertIn('not in effect yet', result.stdout)
                    self.assertIn('Nothing was changed', result.stdout)
                    self.assertEqual(self.mutating_calls(), [])

    def test_a_restricted_allow_on_a_manager_port_is_kept_on_an_inactive_firewall(self):
        # Not a lockout: the operator chose who reaches the manager.
        self.set_rules('ufw allow from 10.0.0.0/8 to any port 8443 proto tcp')
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual([call[1] for call in self.allow_calls()], ['22/tcp', '8081/tcp'])
        self.assertIn('Kept your own rule for 8443/tcp', result.stdout)

    def test_an_ssh_allow_of_one_address_family_is_not_counted_as_every_address(self):
        # `ufw allow from ::/0 to any port 22 proto tcp` (IPv6 only) and its IPv4 mirror are listed by
        # `ufw show added` as `ufw allow 22/tcp`; only the tuple files show the family is missing.
        for families, missing in (('6', 'IPv4'), ('4', 'IPv6')):
            with self.subTest(families=families):
                self.ufw_log.unlink(missing_ok=True)
                self.set_rules('ufw allow 22/tcp', families=families)
                result = self.run_script()
                self.assertEqual(result.returncode, 1, result.stdout)
                self.assertIn("Your ufw rule 'allow 22/tcp'", result.stdout)
                self.assertIn(missing, result.stdout)
                self.assertIn('Nothing was changed', result.stdout)
                self.assertEqual(self.mutating_calls(), [])

    def test_an_ssh_allow_of_one_family_on_an_active_denying_firewall_is_kept(self):
        self.set_state(active=True, incoming='deny', outgoing='allow')
        self.set_rules('ufw allow 22/tcp', families='4')
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertNotIn('22/tcp', [call[1] for call in self.allow_calls()])
        self.assertIn('Kept your own rule for 22/tcp: allow 22/tcp.', result.stdout)
        self.assertIn('IPv6', result.stdout)
        self.assertIn('no rule open to every address was added', result.stdout)

    def test_an_ipv4_ssh_allow_counts_when_ufw_does_not_filter_ipv6(self):
        self.ufw_defaults.write_text('IPV6=no\n')
        self.set_rules('ufw allow 22/tcp', families='4')
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertNotIn('22/tcp', [call[1] for call in self.allow_calls()])
        self.assertIn('Kept your own rule for 22/tcp: allow 22/tcp.', result.stdout)

    def test_an_ssh_deny_of_one_family_behind_an_allow_of_the_other_is_not_every_address(self):
        # IPv4: allow, then deny (allowed). IPv6: only the deny. show added prints `allow 22/tcp` first.
        rules = ['ufw allow 22/tcp', 'ufw deny 22/tcp']
        self.rules.write_text(''.join(line + '\n' for line in rules))
        (self.ufw_dir / 'user.rules').write_text(tuples_of(rules[0])['4'][0] + '\n' + tuples_of(rules[1])['4'][0] + '\n')
        (self.ufw_dir / 'user6.rules').write_text(tuples_of(rules[1])['6'][0] + '\n')
        result = self.run_script()
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn('IPv6', result.stdout)
        self.assertEqual(self.mutating_calls(), [])

    def test_without_ipv6_in_the_kernel_only_the_ipv4_rules_count_and_no_ipv6_note_is_printed(self):
        # ufw filters IPv6 only with IPV6=yes and /proc/sys/net/ipv6 present (backend.use_ipv6); a
        # kernel booted with ipv6.disable=1 has no IPv6 table and no user6.rules rules apply.
        self.ipv6_proc.rmdir()
        self.set_rules('ufw allow 22/tcp', families='4')
        (self.ufw_dir / 'user6.rules').unlink()
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn('Kept your own rule for 22/tcp: allow 22/tcp.', result.stdout)
        self.assertNotIn('IPv6', result.stdout)

    def test_our_ssh_allow_missing_in_one_family_is_added_again(self):
        # Added while IPV6=no; now IPV6=yes. ufw adds the missing IPv6 copy and skips the IPv4 one.
        self.set_rules("ufw allow 22/tcp comment 'clab-manager'", families='4')
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(self.allow_calls()[0], ['allow', '22/tcp', 'comment', 'clab-manager'])
        self.assertEqual(len([line for line in self.tuple_lines('6') if ' 22 ' in line]), 1)
        self.assertEqual(self.rule_lines()[0], "ufw allow 22/tcp comment 'clab-manager'")

    def test_unreadable_ufw_rule_files_are_refused_before_any_change(self):
        (self.ufw_dir / 'user6.rules').unlink()
        self.set_rules('ufw allow 22/tcp')
        (self.ufw_dir / 'user6.rules').unlink()
        result = self.run_script()
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn('user6.rules', result.stdout)
        self.assertEqual(self.mutating_calls(), [])

    def test_a_deny_on_an_interface_or_address_ahead_of_our_ssh_allow_is_refused_while_ufw_is_inactive(self):
        # Our `allow 22/tcp` would sit behind it; ufw stops at the first match.
        for own in ('ufw deny in on eth0 to any port 22 proto tcp', 'ufw deny in on eth0', 'ufw deny to 192.0.2.10 port 22',
                    'ufw reject in on eth0 to any port 22', 'ufw deny from any port 5555 to any port 22'):
            with self.subTest(own=own):
                self.ufw_log.unlink(missing_ok=True)
                self.set_rules(own)
                result = self.run_script()
                self.assertEqual(result.returncode, 1, result.stdout)
                self.assertIn(f"Your ufw rule '{own[4:]}'", result.stdout)
                self.assertIn('Nothing was changed', result.stdout)
                self.assertEqual(self.mutating_calls(), [])

    def test_a_narrowed_deny_on_an_active_firewall_is_already_in_effect_and_ours_is_added(self):
        self.set_state(active=True, incoming='deny', outgoing='allow')
        self.set_rules('ufw deny in on eth0 to any port 22 proto tcp')
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(self.allow_calls()[0], ['allow', '22/tcp', 'comment', 'clab-manager'])

    def test_a_source_deny_that_covers_a_connected_session_is_refused_while_ufw_is_inactive(self):
        for own, session in (('ufw deny from 203.0.113.0/24 to any port 22 proto tcp', '203.0.113.5'),
                             ('ufw deny from 203.0.113.0/24', '203.0.113.5'),
                             ('ufw reject from 203.0.113.5 to any port 22', '203.0.113.5'),
                             ('ufw deny from 2001:db8::/32 to any port 22', '2001:db8::7')):
            with self.subTest(own=own):
                self.ufw_log.unlink(missing_ok=True)
                self.set_rules(own)
                result = self.run_script(SSH_CONNECTION=f'{session} 5555 198.51.100.10 22')
                self.assertEqual(result.returncode, 1, result.stdout)
                self.assertIn(f"Your ufw rule '{own[4:]}'", result.stdout)
                self.assertIn(session, result.stdout)
                self.assertEqual(self.mutating_calls(), [])

    def test_under_sudo_a_source_deny_that_covers_an_sshd_peer_is_refused(self):
        self.set_rules('ufw deny from 198.51.100.0/24 to any port 22 proto tcp')
        result = self.run_script(unset=('SSH_CONNECTION',))
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn('198.51.100.7', result.stdout)
        self.assertEqual(self.mutating_calls(), [])

    def test_under_sudo_an_ipv4_mapped_sshd_peer_is_matched_as_ipv4(self):
        session = '0      0       [::ffff:192.0.2.10]:22   [::ffff:203.0.113.5]:50000 users:(("sshd",pid=99,fd=4))\n'
        self.set_rules('ufw deny from 203.0.113.0/24 to any port 22 proto tcp')
        result = self.run_script(unset=('SSH_CONNECTION',), SS_ESTABLISHED=session)
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn('203.0.113.5', result.stdout)

    def test_a_source_deny_that_covers_no_session_is_the_operators_block_and_ours_is_added(self):
        self.set_rules('ufw deny from 203.0.113.0/24 to any port 22 proto tcp')
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(self.allow_calls()[0], ['allow', '22/tcp', 'comment', 'clab-manager'])
        self.assertEqual(self.rule_lines()[0], 'ufw deny from 203.0.113.0/24 to any port 22 proto tcp')

    def test_a_narrowed_deny_after_an_allow_for_every_address_changes_nothing(self):
        self.set_rules('ufw allow 22/tcp', 'ufw deny in on eth0 to any port 22 proto tcp')
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn('Kept your own rule for 22/tcp: allow 22/tcp.', result.stdout)

    def test_an_operators_deny_on_a_manager_port_in_any_form_is_kept_and_not_reported_as_allowed(self):
        self.set_rules('ufw deny 8443')
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertNotIn('8443/tcp', [call[1] for call in self.allow_calls()])
        self.assertNotIn('Allowed 8443/tcp', result.stdout)
        self.assertIn('The manager is not reachable on port 8443', result.stdout)

    def test_a_listenaddress_port_is_allowed(self):
        # sshd -T prints the Port default next to an explicit ListenAddress host:port.
        result = self.run_script(unset=('SSH_CONNECTION',), SS_ESTABLISHED='', SSHD_LISTEN='0.0.0.0:2222')
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn('2222/tcp', [call[1] for call in self.allow_calls()])

    def test_a_session_on_a_listenaddress_port_proceeds(self):
        result = self.run_script(SSHD_LISTEN='0.0.0.0:2222 [::]:2222',
                                 SSH_CONNECTION='198.51.100.7 53422 192.0.2.10 2222')
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn('2222/tcp', [call[1] for call in self.allow_calls()])

    def test_an_ssh_socket_listen_port_is_allowed(self):
        # An upgrade from Ubuntu 22.10 or 23.x can keep a ListenStream override of ssh.socket.
        result = self.run_script(SSH_SOCKET_LISTEN='0.0.0.0:2200 (Stream)\n[::]:2200 (Stream)',
                                 SSH_CONNECTION='198.51.100.7 53422 192.0.2.10 2200')
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual([call[1] for call in self.allow_calls()][:2], ['22/tcp', '2200/tcp'])

    def test_the_refusal_names_where_the_ssh_ports_come_from(self):
        result = self.run_script(SSH_CONNECTION='198.51.100.7 53422 192.0.2.10 2200')
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn('ListenAddress', result.stdout)
        self.assertIn('ssh.socket', result.stdout)

    def test_an_ipv6_session_is_refused_when_ufw_has_ipv6_disabled(self):
        for value in ('no', '"no"', 'No', ''):
            with self.subTest(value=value):
                self.ufw_log.unlink(missing_ok=True)
                self.ufw_defaults.write_text(f'IPV6={value}\n')
                result = self.run_script(SSH_CONNECTION='2001:db8::7 53422 2001:db8::10 22')
                self.assertEqual(result.returncode, 1, result.stdout)
                self.assertIn('IPV6', result.stdout)
                self.assertIn('Nothing was changed', result.stdout)
                self.assertEqual(self.mutating_calls(), [])

    def test_under_sudo_an_ipv6_sshd_session_is_refused_when_ufw_has_ipv6_disabled(self):
        self.ufw_defaults.write_text('IPV6=no\n')
        session = '0      0       [2001:db8::10]:22   [2001:db8::7]:50000 users:(("sshd-session",pid=99,fd=4))\n'
        result = self.run_script(unset=('SSH_CONNECTION',), SS_ESTABLISHED=session)
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn('IPV6', result.stdout)
        self.assertEqual(self.mutating_calls(), [])

    def test_a_missing_ufw_defaults_file_counts_as_ipv6_disabled(self):
        self.ufw_defaults.unlink()
        result = self.run_script(SSH_CONNECTION='2001:db8::7 53422 2001:db8::10 22')
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertEqual(self.mutating_calls(), [])

    def test_an_ipv4_mapped_session_is_ipv4(self):
        self.ufw_defaults.write_text('IPV6=no\n')
        session = '0      0       [::ffff:192.0.2.10]:22   [::ffff:198.51.100.7]:50000 users:(("sshd",pid=99,fd=4))\n'
        result = self.run_script(unset=('SSH_CONNECTION',), SS_ESTABLISHED=session)
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_an_ipv6_session_proceeds_when_ufw_handles_ipv6(self):
        result = self.run_script(SSH_CONNECTION='2001:db8::7 53422 2001:db8::10 22')
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertNotIn('IPV6=', result.stdout)

    def test_ipv6_disabled_without_an_ipv6_session_proceeds_with_a_warning(self):
        self.ufw_defaults.write_text('IPV6=no\n')
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn('IPV6=no', result.stdout)
        self.assertIn('IPv6', result.stdout)

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

    def test_the_hint_for_the_kept_ssh_allow_never_names_a_rule_that_ufw_merges_into_it(self):
        # ufw treats `allow 22/tcp` and `limit 22/tcp` as this same rule and takes it over in place, so
        # the hint's delete would then remove the only SSH allow. It names forms ufw keeps apart.
        self.set_state(active=True, incoming='deny', outgoing='allow')
        self.set_rules(*self.OURS)
        result = self.run_script('--remove')
        self.assertEqual(result.returncode, 0, result.stdout)
        for merged in ('ufw allow 22/tcp', 'ufw limit 22/tcp', 'ufw allow 22 ', 'ufw limit 22 '):
            self.assertNotIn('sudo ' + merged, result.stdout.replace('sudo ufw delete allow', ''))
        self.assertIn('sudo ufw allow from <your network> to any port 22 proto tcp', result.stdout)
        self.assertIn('sudo ufw allow OpenSSH', result.stdout)
        self.assertIn('sudo ufw show added', result.stdout)

    def test_the_hint_for_a_port_other_than_22_does_not_name_the_openssh_profile(self):
        self.set_state(active=True, incoming='deny', outgoing='allow')
        self.set_rules("ufw allow 2222/tcp comment 'clab-manager'")
        result = self.run_script('--remove', SSHD_PORTS='2222', SSH_CONNECTION='198.51.100.7 53422 192.0.2.10 2222')
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn('sudo ufw allow from <your network> to any port 2222 proto tcp', result.stdout)
        self.assertNotIn('OpenSSH', result.stdout)
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
