from pathlib import Path
import re
import subprocess
import tempfile
import unittest

# Stdlib only: CI runs this with the system python3 before the virtual environment exists.
GATEWAY = Path(__file__).resolve().parents[2] / 'deploy/clab-manager-gateway'
HELPERS = {
    'clab-manager-git': ['/usr/local/sbin/clab-manager-git'],
    'clab-manager-operations': ['/usr/local/sbin/clab-manager-operate'],
    'sudo -n /usr/local/sbin/clab-manager-inspect': ['/usr/local/sbin/clab-manager-inspect'],
    'containerlab inspect --all --format json': ['/usr/local/sbin/clab-manager-inspect'],
}
ARMS = ['clab-manager-git', 'clab-manager-operations',
        "'sudo -n /usr/local/sbin/clab-manager-inspect'|'containerlab inspect --all --format json'", '*']
REFUSED = ['', ' ', 'clab-manager-git ', ' clab-manager-git', 'clab-manager-git\n', 'clab-manager-git;id', 'clab-manager-git extra',
           'clab-manager-git && id', 'clab-manager-*', 'clab-manager-g*', 'clab-manager-?it', 'clab-manager-GIT', 'clab-manager-inspect',
           'clab-manager-operate', 'clab-manager', '/usr/local/sbin/clab-manager-git', 'sudo -n /usr/local/sbin/clab-manager-git',
           'sudo -n /usr/local/sbin/clab-manager-inspect extra', 'sudo -n /usr/local/sbin/clab-manager-inspect;id',
           'sudo /usr/local/sbin/clab-manager-inspect', 'containerlab inspect --all', 'containerlab inspect --all --format json;id',
           'containerlab inspect --all --format json extra', 'containerlab  inspect --all --format json', 'containerlab inspect --all --format table',
           'clab-manager-shell', 'clab-manager-write', '$(id)', '`id`', 'id', 'sh', 'bash -c id', 'scp -t /tmp', 'sftp', 'clab-manager-git\nid']


def run_gateway(script, original, args=()):
    """Run the forced command with a recording stub `sudo` first on PATH; return (code, stderr, recorded argv lists)."""
    with tempfile.TemporaryDirectory() as temp:
        stubs = Path(temp) / 'bin'
        stubs.mkdir()
        log = Path(temp) / 'sudo.log'
        stub = stubs / 'sudo'
        stub.write_text('#!/bin/sh\nprintf \'%s\\0\' "$@" >> "' + str(log) + '"\nprintf \'\\n\' >> "' + str(log) + '"\nexit 0\n', encoding='utf-8')
        stub.chmod(0o755)
        # Only the stub is on PATH, so even a widened gateway under test cannot run a real command.
        env = {'PATH': str(stubs), 'LC_ALL': 'C'}
        if original is not None:
            env['SSH_ORIGINAL_COMMAND'] = original
        done = subprocess.run(['/bin/sh', str(script), *args], env=env, capture_output=True, text=True, timeout=30)
        calls = []
        if log.exists():
            calls = [[part for part in line.split('\0') if part] for line in log.read_text(encoding='utf-8').split('\n') if line]
    return done.returncode, done.stderr, calls


def violations(script):
    """Every way `script` departs from the exact whitelist; empty for the shipped gateway."""
    found = []
    for original, helper in HELPERS.items():
        code, _stderr, calls = run_gateway(script, original)
        if code != 0 or calls != [['-n', *helper]]:
            found.append(('allowed', original, code, calls))
    for original in REFUSED + [None]:
        code, _stderr, calls = run_gateway(script, original)
        if code != 64 or calls:
            found.append(('refused', original, code, calls))
    arms = re.findall(r'^\s+(\S.*?)\) (?:exec|echo) ', Path(script).read_text(encoding='utf-8'), re.MULTILINE)
    if arms != ARMS:
        found.append(('case arms', arms))
    code, _stderr, calls = run_gateway(script, 'clab-manager-git', ['extra'])
    if code != 64 or calls:
        found.append(('argument', 'clab-manager-git', code, calls))
    return found


class GatewayWhitelistTests(unittest.TestCase):
    def test_script_has_valid_sh_syntax(self):
        done = subprocess.run(['/bin/sh', '-n', str(GATEWAY)], capture_output=True, text=True, timeout=30)
        self.assertEqual((done.returncode, done.stderr), (0, ''))
        self.assertEqual(GATEWAY.read_text(encoding='utf-8').splitlines()[0], '#!/bin/sh')

    def test_each_request_name_runs_exactly_its_helper_through_sudo_n(self):
        for original, helper in HELPERS.items():
            with self.subTest(original=original):
                code, stderr, calls = run_gateway(GATEWAY, original)
                self.assertEqual((code, stderr, calls), (0, '', [['-n', *helper]]))

    def test_anything_else_is_refused_with_64_and_nothing_executes(self):
        for original in REFUSED + [None]:
            with self.subTest(original=original):
                code, stderr, calls = run_gateway(GATEWAY, original)
                self.assertEqual(code, 64)
                self.assertEqual(calls, [])
                self.assertIn('Only manager discovery', stderr)

    def test_any_command_line_argument_is_refused_even_with_an_allowed_name(self):
        for original in HELPERS:
            for args in (['x'], [''], ['-c', 'id']):
                with self.subTest(original=original, args=args):
                    code, _stderr, calls = run_gateway(GATEWAY, original, args)
                    self.assertEqual((code, calls), (64, []))

    def test_the_request_text_is_never_executed_or_passed_on(self):
        text = GATEWAY.read_text(encoding='utf-8')
        for word in ('eval', 'bash', 'sh -c', '"$@"', '$*'):
            self.assertNotIn(word, text)
        self.assertEqual(text.count('SSH_ORIGINAL_COMMAND'), 1)
        self.assertEqual(sorted(set(re.findall(r'/usr/local/sbin/[\w-]+', text))),
                         sorted({'/usr/local/sbin/clab-manager-git', '/usr/local/sbin/clab-manager-operate', '/usr/local/sbin/clab-manager-inspect'}))

    def test_shipped_gateway_has_no_violations(self):
        self.assertEqual(violations(GATEWAY), [])

    def test_the_check_detects_a_widened_gateway(self):
        original = GATEWAY.read_text(encoding='utf-8')
        mutants = {
            'glob arm': original.replace("  clab-manager-git)", "  clab-manager-*)", 1),
            'extra name': original.replace("  *) echo", "  'clab-manager-shell') exec sudo -n /usr/local/sbin/clab-manager-git ;;\n  *) echo", 1),
            'pass-through': original.replace("  *) echo", "  *) exec $SSH_ORIGINAL_COMMAND ;;\n  *) echo", 1),
            'argument check removed': original.replace('[ "$#" -eq 0 ] || exit 64\n', '', 1),
            'wrong helper': original.replace('clab-manager-operate', 'clab-manager-git', 1),
            'no sudo -n': original.replace('exec sudo -n /usr/local/sbin/clab-manager-git', 'exec /usr/local/sbin/clab-manager-git', 1),
            'refusal exits 0': original.replace('exit 64 ;;', 'exit 0 ;;', 1),
        }
        for label, mutated in mutants.items():
            with self.subTest(mutant=label), tempfile.TemporaryDirectory() as temp:
                self.assertNotEqual(mutated, original)
                script = Path(temp) / 'clab-manager-gateway'
                script.write_text(mutated, encoding='utf-8')
                self.assertTrue(violations(script), label)


if __name__ == '__main__':
    unittest.main()
