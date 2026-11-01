"""deploy/setup-ssh-hardening.sh (docs/sign-on/EXPOSURE.md 5.4): a conservative sshd drop-in.

What must hold: the drop-in `sshd_config.d/40-clab-manager.conf` carries only directives whose
effective value (`sshd -T`, evaluated without the script's own earlier drop-in) is still OpenSSH's
default, so an operator's own choice is never overridden; it never writes PasswordAuthentication,
AllowTcpForwarding or AllowUsers; the candidate is checked with `sshd -t -f`, the applied
configuration with `sshd -t`, and any failure restores the previous state and reloads it; `--remove`
deletes the drop-in and reloads.

PermitRootLogin is not written while root can log in with a key (a key in root's AuthorizedKeysFile
other than cloud-init's "Please login as" stub, or an AuthorizedKeysCommand or TrustedUserCAKeys that
could admit one): `no` would refuse the very login the operator may depend on.

The script must run as root and this suite never touches /etc/ssh or /root: each test drives a copy
of the shipped script with exactly three lines replaced, the root guard (a no-op), the SSH directory
and root's home (temporary ones); the texts are asserted, so a change fails loudly instead of testing
stale logic. The fake sshd emulates the include order of Ubuntu (drop-ins first, then the rest of
sshd_config, the first value wins) over a base of OpenSSH defaults the test chooses; with `-C`
(`sshd -T -C user=root,...`) it applies the `Match User` and `Match all` blocks that name the user over
that, as sshd does for one connection. Standard library only.
"""
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / 'deploy/setup-ssh-hardening.sh'
ROOT_GUARD = "[[ $EUID -eq 0 ]] || { echo 'Run with sudo.' >&2; exit 1; }"
SSH_DIR_LINE = 'ssh_dir=/etc/ssh'
ROOT_HOME_LINE = 'root_home=$(getent passwd root | cut -d: -f6)'
SYSTEM_PATH = '/usr/bin:/bin'
DROPIN = 'sshd_config.d/40-clab-manager.conf'

DEFAULTS = {'port': '22', 'permitrootlogin': 'without-password', 'maxauthtries': '6', 'logingracetime': '120',
            'persourcemaxstartups': 'none', 'x11forwarding': 'no', 'passwordauthentication': 'yes',
            'allowtcpforwarding': 'yes', 'maxstartups': '10:30:100',
            'authorizedkeysfile': '.ssh/authorized_keys .ssh/authorized_keys2', 'authorizedkeyscommand': 'none',
            'trustedusercakeys': 'none'}
# The stock Ubuntu 24.04 sshd_config, apart from its comments.
UBUNTU_SSHD_CONFIG = ('Include /etc/ssh/sshd_config.d/*.conf\n\nKbdInteractiveAuthentication no\nUsePAM yes\n'
                      'X11Forwarding yes\nPrintMotd no\nAcceptEnv LANG LC_*\nSubsystem sftp /usr/lib/openssh/sftp-server\n')
CLOUD_INIT_STUB = ('no-port-forwarding,no-agent-forwarding,no-X11-forwarding,command="echo \'Please login as the user '
                   '\\"ubuntu\\" rather than the user \\"root\\".\';echo;sleep 10;exit 142" ssh-ed25519 AAAAC3fixture root@x\n')

FAKE_SSHD = r'''#!PYTHON
import os, sys
from pathlib import Path
args = sys.argv[1:]
with open(os.environ['CALL_LOG'], 'a') as log:
    log.write('sshd ' + ' '.join(args) + '\n')
ssh_dir = Path(os.environ['SSH_DIR'])
dropin = ssh_dir / 'sshd_config.d/40-clab-manager.conf'

def lines(path):
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith('#'):
            key, _, value = line.partition(' ')
            yield key.lower(), value.strip()

if args[:1] == ['-T']:
    if os.environ.get('SSHD_T_STATUS', '0') != '0':
        sys.exit(int(os.environ['SSHD_T_STATUS']))
    connection = {}
    if args[1:2] == ['-C']:
        if os.environ.get('SSHD_TC_STATUS', '0') != '0':
            sys.exit(int(os.environ['SSHD_TC_STATUS']))
        connection = dict(item.split('=', 1) for item in args[2].split(','))
    files = sorted((ssh_dir / 'sshd_config.d').glob('*.conf')) + [ssh_dir / 'sshd_config']
    seen, matched = {}, {}
    for path in files:
        block = None  # None: global; True or False: inside a Match block that does or does not apply
        for key, value in lines(path):
            if key == 'match':
                words = value.split()
                block = words == ['all'] or (words[0].lower() == 'user' and connection.get('user') in words[1].split(','))
            elif key == 'include':
                continue
            elif block is None:
                seen.setdefault(key, value)
            elif block:
                matched.setdefault(key, value)
    for key, value in lines(Path(os.environ['SSHD_BASE'])):
        seen.setdefault(key, value)
    seen.update(matched)
    for key, value in seen.items():
        print(key, value.lower() if key in ('permitrootlogin', 'x11forwarding') else value)
    sys.exit(0)
if args[:1] == ['-t']:
    if len(args) == 3 and args[1] == '-f':
        if os.environ.get('SSHD_FAIL_CANDIDATE'):
            print('sshd: bad candidate', file=sys.stderr)
            sys.exit(255)
        sys.exit(0)
    if os.environ.get('SSHD_FAIL_ALWAYS'):
        print('sshd: bad configuration', file=sys.stderr)
        sys.exit(255)
    if os.environ.get('SSHD_FAIL_WITHOUT_DROPIN') and not dropin.exists():
        print('sshd: bad configuration', file=sys.stderr)
        sys.exit(255)
    if os.environ.get('SSHD_FAIL_WITH_NEW_DROPIN') and dropin.exists() and 'MaxAuthTries 4' in dropin.read_text():
        print('sshd: bad configuration', file=sys.stderr)
        sys.exit(255)
    sys.exit(0)
sys.exit(0)
'''

FAKE_SYSTEMCTL = r'''#!/usr/bin/env bash
echo "systemctl $*" >> "$CALL_LOG"
case "$1" in
  is-active) [[ " $ACTIVE_UNITS " == *" ${!#} "* ]]; exit;;
  reload) [[ -z "${RELOAD_FAIL:-}" ]] || exit 1; exit 0;;
esac
echo "unexpected call to systemctl" >&2
exit 99
'''

FAKE_UNEXPECTED = r'''#!/usr/bin/env bash
echo "$(basename "$0") $*" >> "$CALL_LOG"
echo "unexpected call to $(basename "$0")" >&2
exit 99
'''


def write_exe(path, text):
    path.write_text(text.replace('#!PYTHON', '#!' + sys.executable))
    path.chmod(0o755)


class SshHardeningTests(unittest.TestCase):
    def setUp(self):
        text = SCRIPT.read_text()
        self.assertIn(ROOT_GUARD, text, "the root guard text changed; update this test's neutralised copy")
        self.assertEqual(text.count(SSH_DIR_LINE + '\n'), 1, 'the SSH directory line changed; update this test')
        self.assertEqual(text.count(ROOT_HOME_LINE + '\n'), 1, "the root home line changed; update this test")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.ssh_dir = self.base / 'etc-ssh'
        (self.ssh_dir / 'sshd_config.d').mkdir(parents=True)
        self.config = self.ssh_dir / 'sshd_config'
        # Without Ubuntu's X11Forwarding yes, so that every directive starts at OpenSSH's default (the
        # fake sshd reads this file; it used to ignore it and contradict the line). The stock file is
        # UBUNTU_SSHD_CONFIG, used by its own test.
        self.config.write_text('Include /etc/ssh/sshd_config.d/*.conf\n\nKbdInteractiveAuthentication no\nUsePAM yes\n'
                               'Subsystem sftp /usr/lib/openssh/sftp-server\n')
        self.dropin = self.ssh_dir / DROPIN
        self.root_home = self.base / 'root-home'
        self.root_home.mkdir()
        (self.base / 'deploy').mkdir()
        self.script = self.base / 'deploy/setup-ssh-hardening.sh'
        self.script.write_text(text.replace(ROOT_GUARD, ': # root check removed for this unit test')
                               .replace(SSH_DIR_LINE + '\n', f'ssh_dir={self.ssh_dir}\n')
                               .replace(ROOT_HOME_LINE + '\n', f'root_home={self.root_home}\n'))
        self.bin = self.base / 'bin'
        self.bin.mkdir()
        write_exe(self.bin / 'sshd', FAKE_SSHD)
        write_exe(self.bin / 'systemctl', FAKE_SYSTEMCTL)
        for name in ('ufw', 'docker', 'ss'):
            write_exe(self.bin / name, FAKE_UNEXPECTED)
        self.call_log = self.base / 'calls.log'
        self.sshd_base = self.base / 'effective'
        self.set_base()
        self.env = {'PATH': f'{self.bin}{os.pathsep}{SYSTEM_PATH}', 'HOME': str(self.base), 'LC_ALL': 'C',
                    'CALL_LOG': str(self.call_log), 'SSH_DIR': str(self.ssh_dir), 'SSHD_BASE': str(self.sshd_base),
                    'ACTIVE_UNITS': 'ssh'}

    def set_base(self, **changes):
        values = {**DEFAULTS, **changes}
        self.sshd_base.write_text(''.join(f'{key} {value}\n' for key, value in values.items() if value is not None))

    def run_script(self, *args, **overrides):
        result = subprocess.run(['bash', str(self.script), *args], cwd=str(self.base), env={**self.env, **overrides},
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=30)
        self.assertNotIn('unexpected call', result.stdout)
        return result

    def calls(self):
        return self.call_log.read_text().splitlines() if self.call_log.exists() else []

    def directives(self):
        return [line for line in self.dropin.read_text().splitlines() if line and not line.startswith('#')]

    def leftovers(self):
        return sorted(path.name for path in (self.ssh_dir / 'sshd_config.d').iterdir() if path.name != '40-clab-manager.conf')

    def test_directives_at_the_openssh_default_are_all_written(self):
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(self.directives(), ['PermitRootLogin no', 'MaxAuthTries 4', 'LoginGraceTime 30',
                                             'PerSourceMaxStartups 8', 'X11Forwarding no'])
        self.assertEqual(stat.S_IMODE(self.dropin.stat().st_mode), 0o644)
        self.assertEqual(self.leftovers(), [])
        self.assertIn('systemctl reload ssh', self.calls())

    def test_the_candidate_is_checked_alone_then_the_applied_configuration_then_reloaded(self):
        self.assertEqual(self.run_script().returncode, 0)
        calls = self.calls()
        candidate = next(index for index, call in enumerate(calls) if call.startswith('sshd -t -f '))
        full = [index for index, call in enumerate(calls) if call == 'sshd -t']
        reload = calls.index('systemctl reload ssh')
        self.assertTrue(full and full[0] < candidate, calls)  # the current configuration is valid first
        self.assertTrue(any(candidate < index < reload for index in full), calls)
        self.assertNotIn(str(self.ssh_dir), calls[candidate])  # the candidate is not yet in sshd_config.d

    def test_prohibit_password_is_the_same_default_as_without_password(self):
        self.set_base(permitrootlogin='prohibit-password')
        self.assertEqual(self.run_script().returncode, 0)
        self.assertIn('PermitRootLogin no', self.directives())

    def test_an_operators_own_value_is_never_overridden(self):
        self.set_base(permitrootlogin='yes', maxauthtries='3', x11forwarding='yes', logingracetime='60')
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(self.directives(), ['PerSourceMaxStartups 8'])
        self.assertIn('MaxAuthTries 3', result.stdout)

    def test_a_directive_this_sshd_does_not_know_is_not_written(self):
        self.set_base(persourcemaxstartups=None)
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertNotIn('PerSourceMaxStartups 8', self.directives())

    def root_keys(self, text, name='.ssh/authorized_keys'):
        path = self.root_home / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def test_stock_ubuntu_x11forwarding_yes_is_kept_and_not_called_the_operators_own(self):
        self.config.write_text(UBUNTU_SSHD_CONFIG)
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(self.directives(), ['PermitRootLogin no', 'MaxAuthTries 4', 'LoginGraceTime 30',
                                             'PerSourceMaxStartups 8'])
        self.assertIn('Kept X11Forwarding yes', result.stdout)
        self.assertNotIn('your own', result.stdout)

    def test_root_with_an_authorized_key_keeps_its_login_and_the_rest_is_written(self):
        for name in ('.ssh/authorized_keys', '.ssh/authorized_keys2'):
            with self.subTest(name=name):
                shutil.rmtree(self.root_home / '.ssh', ignore_errors=True)
                self.dropin.unlink(missing_ok=True)
                path = self.root_keys('# operator key\nssh-ed25519 AAAAC3fixture admin@laptop\n', name)
                result = self.run_script()
                self.assertEqual(result.returncode, 0, result.stdout)
                self.assertEqual(self.directives(), ['MaxAuthTries 4', 'LoginGraceTime 30', 'PerSourceMaxStartups 8',
                                                     'X11Forwarding no'])
                self.assertIn('Not written: PermitRootLogin', result.stdout)
                self.assertIn(str(path), result.stdout)

    def test_a_root_key_with_options_or_a_forced_command_still_counts(self):
        self.root_keys('command="/usr/local/bin/backup",no-pty ssh-ed25519 AAAAC3fixture backup@host\n')
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertNotIn('PermitRootLogin no', self.directives())

    def test_an_absolute_authorized_keys_file_with_tokens_is_read_for_root(self):
        keys = self.base / 'keys'
        keys.mkdir()
        (keys / 'root').write_text('ssh-ed25519 AAAAC3fixture admin@laptop\n')
        self.set_base(authorizedkeysfile=f'{keys}/%u')
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertNotIn('PermitRootLogin no', self.directives())
        self.assertIn(f'{keys}/root', result.stdout)

    def test_a_home_token_in_the_authorized_keys_file_is_roots_home(self):
        self.root_keys('ssh-ed25519 AAAAC3fixture admin@laptop\n', 'keys/authorized')
        self.set_base(authorizedkeysfile='%h/keys/authorized')
        self.assertEqual(self.run_script().returncode, 0)
        self.assertNotIn('PermitRootLogin no', self.directives())

    def test_the_cloud_init_stub_comments_and_blank_lines_are_not_a_root_login(self):
        self.root_keys('\n# nothing here\n   \n' + CLOUD_INIT_STUB)
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn('PermitRootLogin no', self.directives())

    def test_a_root_key_that_only_a_match_user_root_block_admits_keeps_permitrootlogin(self):
        # The global AuthorizedKeysFile is the default (.ssh/authorized_keys, absent for root); a Match
        # block at the end of sshd_config points root at a file of its own, which holds root's key.
        keys = self.base / 'rootkeys'
        keys.mkdir()
        (keys / 'root').write_text('ssh-ed25519 AAAAC3fixture admin@laptop\n')
        self.config.write_text(self.config.read_text() + f'Match User root\n    AuthorizedKeysFile {keys}/%u\n')
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertNotIn('PermitRootLogin no', self.directives())
        self.assertIn('Not written: PermitRootLogin', result.stdout)
        self.assertIn(f'{keys}/root', result.stdout)
        self.assertIn('sshd -T -C user=root,host=localhost,addr=127.0.0.1', self.calls())

    def test_a_match_block_for_other_users_does_not_give_root_a_key(self):
        keys = self.base / 'rootkeys'
        keys.mkdir()
        (keys / 'root').write_text('ssh-ed25519 AAAAC3fixture admin@laptop\n')
        self.config.write_text(self.config.read_text() + f'Match User deploy\n    AuthorizedKeysFile {keys}/%u\n')
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn('PermitRootLogin no', self.directives())

    def test_root_settings_that_cannot_be_read_keep_permitrootlogin(self):
        result = self.run_script(SSHD_TC_STATUS='255')
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertNotIn('PermitRootLogin no', self.directives())
        self.assertIn('Not written: PermitRootLogin', result.stdout)
        self.assertIn('MaxAuthTries 4', self.directives())

    def test_keys_sshd_finds_elsewhere_keep_permitrootlogin(self):
        for change in ({'authorizedkeyscommand': '/usr/bin/sss_ssh_authorizedkeys'},
                       {'trustedusercakeys': '/etc/ssh/user_ca.pub'}):
            with self.subTest(change=change):
                self.dropin.unlink(missing_ok=True)
                self.set_base(**change)
                result = self.run_script()
                self.assertEqual(result.returncode, 0, result.stdout)
                self.assertNotIn('PermitRootLogin no', self.directives())
                self.assertIn('Not written: PermitRootLogin', result.stdout)

    def test_working_as_root_without_any_root_key_still_writes_permitrootlogin(self):
        # With prohibit-password and no key, root has no SSH login that `no` could take away; running
        # the script from root's console or `sudo -i` changes nothing about that.
        result = self.run_script(USER='root', LOGNAME='root')
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn('PermitRootLogin no', self.directives())

    def test_password_forwarding_and_user_directives_are_never_written(self):
        self.assertEqual(self.run_script().returncode, 0)
        text = self.dropin.read_text().lower()
        for directive in ('passwordauthentication', 'allowtcpforwarding', 'allowusers', 'match'):
            self.assertNotIn(directive + ' ', text)

    def test_a_second_run_writes_the_same_drop_in_because_its_own_values_are_set_aside(self):
        self.assertEqual(self.run_script().returncode, 0)
        first = self.dropin.read_text()
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(self.dropin.read_text(), first)

    def test_an_operator_change_after_the_first_run_is_released_on_the_next(self):
        self.assertEqual(self.run_script().returncode, 0)
        self.set_base(maxauthtries='3')
        self.assertEqual(self.run_script().returncode, 0)
        self.assertNotIn('MaxAuthTries 4', self.directives())

    def test_failing_sshd_t_after_applying_restores_no_drop_in_and_reloads(self):
        result = self.run_script(SSHD_FAIL_WITH_NEW_DROPIN='1')
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertFalse(self.dropin.exists())
        self.assertEqual(self.leftovers(), [])
        self.assertIn('restored', result.stdout)
        calls = self.calls()
        self.assertEqual(calls[-2:], ['sshd -t', 'systemctl reload ssh'])

    def test_failing_sshd_t_after_applying_restores_the_previous_drop_in(self):
        previous = '# earlier\nPermitRootLogin no\n'
        self.dropin.write_text(previous)
        self.dropin.chmod(0o644)
        result = self.run_script(SSHD_FAIL_WITH_NEW_DROPIN='1')
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertEqual(self.dropin.read_text(), previous)
        self.assertEqual(stat.S_IMODE(self.dropin.stat().st_mode), 0o644)

    def test_a_reload_failure_restores_the_previous_state(self):
        result = self.run_script(RELOAD_FAIL='1')
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertFalse(self.dropin.exists())

    def test_a_bad_candidate_changes_nothing_and_never_reloads(self):
        result = self.run_script(SSHD_FAIL_CANDIDATE='1')
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertFalse(self.dropin.exists())
        self.assertNotIn('systemctl reload ssh', self.calls())

    def test_a_bad_candidate_keeps_the_previous_drop_in(self):
        self.dropin.write_text('PermitRootLogin no\n')
        result = self.run_script(SSHD_FAIL_CANDIDATE='1')
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertEqual(self.dropin.read_text(), 'PermitRootLogin no\n')

    def test_sshd_T_failure_restores_the_previous_drop_in(self):
        self.dropin.write_text('PermitRootLogin no\n')
        result = self.run_script(SSHD_T_STATUS='255')
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertEqual(self.dropin.read_text(), 'PermitRootLogin no\n')

    def test_an_invalid_current_configuration_is_refused_before_any_change(self):
        result = self.run_script(SSHD_FAIL_ALWAYS='1')
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn('Nothing was changed', result.stdout)
        self.assertFalse(self.dropin.exists())
        self.assertNotIn('systemctl reload ssh', self.calls())

    def test_no_directive_at_the_default_writes_no_drop_in_and_removes_an_old_one(self):
        self.set_base(permitrootlogin='no', maxauthtries='3', logingracetime='60', persourcemaxstartups='4',
                      x11forwarding='yes')
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertFalse(self.dropin.exists())
        self.assertNotIn('systemctl reload ssh', self.calls())
        self.assertNotIn('your own', result.stdout)
        self.dropin.write_text('PermitRootLogin no\n')
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertFalse(self.dropin.exists())
        self.assertIn('systemctl reload ssh', self.calls())
        self.assertNotIn('your own', result.stdout)

    def test_nothing_to_write_because_root_keeps_its_key_is_not_called_a_value_of_your_own(self):
        # PermitRootLogin stays at the default (root has a key) and every other directive is set:
        # "every directive already has a value of your own" would be false for PermitRootLogin.
        self.root_keys('ssh-ed25519 AAAAC3fixture admin@laptop\n')
        self.set_base(maxauthtries='3', logingracetime='60', persourcemaxstartups='4', x11forwarding='yes')
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertFalse(self.dropin.exists())
        self.assertNotIn('your own', result.stdout)
        self.assertIn('no drop-in was written', result.stdout)

    def test_a_directive_an_earlier_drop_in_sets_is_reported_as_not_in_effect(self):
        (self.ssh_dir / 'sshd_config.d/10-operator.conf').write_text('MaxAuthTries 6\n')
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn('MaxAuthTries 4', self.directives())
        self.assertIn('Not in effect: MaxAuthTries', result.stdout)
        self.assertIn('In effect: PermitRootLogin no', result.stdout)

    def test_a_service_that_is_not_running_gets_the_drop_in_without_a_reload(self):
        result = self.run_script(ACTIVE_UNITS='')
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertTrue(self.dropin.exists())
        self.assertFalse([call for call in self.calls() if call.startswith('systemctl reload')])

    def test_the_sshd_unit_name_is_used_when_ssh_is_not_active(self):
        self.assertEqual(self.run_script(ACTIVE_UNITS='sshd').returncode, 0)
        self.assertIn('systemctl reload sshd', self.calls())

    def test_a_configuration_without_the_drop_in_include_is_refused(self):
        self.config.write_text('UsePAM yes\n')
        result = self.run_script()
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn('sshd_config.d', result.stdout)
        self.assertFalse(self.dropin.exists())

    def test_symlinks_are_refused(self):
        target = self.base / 'elsewhere.conf'
        target.write_text('PermitRootLogin no\n')
        self.dropin.symlink_to(target)
        result = self.run_script()
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn('symlink', result.stdout)
        self.assertEqual(target.read_text(), 'PermitRootLogin no\n')
        self.assertTrue(self.dropin.is_symlink())

    def test_remove_deletes_the_drop_in_validates_and_reloads(self):
        self.assertEqual(self.run_script().returncode, 0)
        self.call_log.unlink()
        result = self.run_script('--remove')
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertFalse(self.dropin.exists())
        self.assertEqual(self.calls()[-2:], ['sshd -t', 'systemctl reload ssh'])

    def test_remove_without_a_drop_in_changes_nothing(self):
        result = self.run_script('--remove')
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn('No clab-manager SSH drop-in', result.stdout)
        self.assertNotIn('systemctl reload ssh', self.calls())

    def test_remove_restores_the_drop_in_when_the_result_fails_sshd_t(self):
        self.dropin.write_text('MaxAuthTries 4\n')
        result = self.run_script('--remove', SSHD_FAIL_WITHOUT_DROPIN='1')
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertEqual(self.dropin.read_text(), 'MaxAuthTries 4\n')
        self.assertIn('restored', result.stdout)
        self.assertEqual(self.calls()[-2:], ['sshd -t', 'systemctl reload ssh'])

    def test_other_files_are_never_changed(self):
        other = self.ssh_dir / 'sshd_config.d/50-cloud-init.conf'
        other.write_text('PasswordAuthentication yes\n')
        config = self.config.read_text()
        self.assertEqual(self.run_script().returncode, 0)
        self.assertEqual(self.run_script('--remove').returncode, 0)
        self.assertEqual(other.read_text(), 'PasswordAuthentication yes\n')
        self.assertEqual(self.config.read_text(), config)

    def test_unknown_options_are_refused(self):
        for args in (['--force'], ['--remove', 'x']):
            with self.subTest(args=args):
                self.assertEqual(self.run_script(*args).returncode, 64)
                self.assertFalse(self.dropin.exists())

    def test_shipped_script_has_the_root_guard_and_valid_syntax(self):
        subprocess.run(['bash', '-n', str(SCRIPT)], check=True)
        self.assertIn(ROOT_GUARD, SCRIPT.read_text())


if __name__ == '__main__':
    unittest.main()
