import copy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch


spec = importlib.util.spec_from_file_location('check_git', Path(__file__).resolve().parents[2] / 'deploy/check_git.py')
checks = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checks)


def response(stdout='', code=0, reason=''):
    return SimpleNamespace(stdout=stdout, stderr='PRIVATE STDERR TOKEN', code=code, reason=reason,
                           ok=code == 0 and not reason)


BINDING = dict(id='a' * 32, label='PRIVATE REPOSITORY LABEL', owner='archtop',
               path='/home/archtop/labs/my lab', remote='origin',
               push_url='https://github.com/example/lab.git', branch='main', prefix='labs/example', revision='b' * 64)
ACCOUNT = SimpleNamespace(pw_uid=1000, pw_gid=1000, pw_name='archtop', pw_dir='/home/archtop')


class Context:
    def __init__(self, repositories=None):
        self.owner = ACCOUNT
        self.source = Path('/source')
        self.version = '1.16.1'
        self.require_git = False
        self.git_remote = False
        self.repositories = [copy.deepcopy(BINDING)] if repositories is None else repositories
        self.rows = []
        self.calls = []
        self.path_problem = ''
        self.busy = False
        self.missing_identity = False
        self.staged = ''
        self.managed = ''
        self.remote_failure = False
        self.branch = 'main'
        self.destination = BINDING['push_url']
        self.rewrites = False
        self.registry_failure = False

    def add(self, id, status, title, detail, fix=''):
        self.rows.append(dict(id=id, status=status, title=title, detail=detail, fix=fix))

    def run(self, args, **kwargs):
        self.calls.append((args, kwargs))
        if str(self.source / 'deploy/git-registrations.py') in args:
            if self.registry_failure:
                return response('PRIVATE RAW REGISTRY', code=1)
            return response(json.dumps({'result': dict(protocol='clab-manager-git-v1',
                                                     version=self.version, repositories=self.repositories)}))
        if checks.CHECK_PATH in args:
            return response(json.dumps({'problem': self.path_problem, 'busy': self.busy}))
        offset = args.index('-C')
        path, command = args[offset + 1], args[offset + 2:]
        if command == ['rev-parse', '--show-toplevel']:
            return response(path + '\n')
        if command == ['rev-parse', '--is-bare-repository']:
            return response('false\n')
        if command == ['rev-parse', '--verify', 'HEAD']:
            return response('a' * 40 + '\n')
        if command[:2] == ['ls-files', '--stage']:
            return response('100644 ' + 'a' * 40 + ' 0\tREADME.md\n')
        if command[0] == 'var':
            return response('PRIVATE COMMIT IDENTITY', code=int(self.missing_identity))
        if command[0] == 'symbolic-ref':
            return response(self.branch + '\n')
        if command[0] == 'check-ref-format':
            return response(command[-1])
        if command[0] == 'remote':
            return response(self.destination + '\n')
        if command[0] == 'config':
            return response('PRIVATE REWRITE' if self.rewrites else '', code=0 if self.rewrites else 1)
        if command[0] == 'diff':
            return response(self.staged)
        if command[0] == 'status':
            return response(self.managed)
        if command[0] == 'ls-remote':
            return response('a' * 40 + '\trefs/heads/main\n', code=int(self.remote_failure))
        raise AssertionError('Unexpected command: ' + repr(command))

    def row(self, suffix):
        return next(item for item in self.rows if item['id'].endswith(suffix))


class GitCheckTests(unittest.TestCase):
    def run_checks(self, ctx):
        with patch.object(checks, 'account_for', return_value=ACCOUNT):
            checks.check_git(ctx)
        return ctx

    def test_repository_commands_run_as_owner_with_clean_home_and_no_optional_writes(self):
        ctx = self.run_checks(Context())
        for args, options in ctx.calls[1:]:
            self.assertEqual(args[:8], ['sudo', '-n', '-H', '-u', 'archtop', '--', '/usr/bin/env', '-i'])
            self.assertIn('HOME=/home/archtop', args)
            self.assertIn('GIT_TERMINAL_PROMPT=0', args)
            self.assertIn('GIT_OPTIONAL_LOCKS=0', args)
            self.assertTrue(options['privileged'])
            self.assertLessEqual(options['timeout'], 15)
            if '/usr/bin/git' in args:
                self.assertIn('--no-optional-locks', args)
                self.assertIn('core.fsmonitor=false', args)
                self.assertEqual(args[args.index('-C') + 1], '/home/archtop/labs/my lab')
                command = args[args.index('-C') + 2:]
                self.assertNotIn(command[0], ('fetch', 'commit', 'push', 'reset', 'checkout', 'add'))
        self.assertEqual(ctx.row('.working')['status'], 'PASS')
        self.assertFalse(any('ls-remote' in args for args, _ in ctx.calls))
        self.assertEqual(ctx.row('.remote')['status'], 'INFO')

    def test_identity_failure_is_distinct_and_secret_output_is_never_reported(self):
        ctx = Context()
        ctx.missing_identity = True
        self.run_checks(ctx)
        self.assertEqual(ctx.row('.identity')['status'], 'FAIL')
        self.assertIn('missing or invalid', ctx.row('.identity')['detail'])
        self.assertNotIn('PRIVATE', json.dumps(ctx.rows))
        self.assertNotIn(BINDING['push_url'], json.dumps(ctx.rows))

    def test_dirty_checkout_warns_with_counts_without_discard_instructions(self):
        ctx = Context()
        ctx.staged = 'PRIVATE FILE\0OTHER FILE\0'
        ctx.managed = ' M "PRIVATE FILE"\n?? OTHER\n'
        self.run_checks(ctx)
        row = ctx.row('.working')
        self.assertEqual(row['status'], 'WARN')
        self.assertIn('2 staged file(s); 2 changed', row['detail'])
        self.assertIn('retry that saved operation', row['fix'])
        self.assertNotIn('PRIVATE', json.dumps(ctx.rows))

    def test_existing_git_operation_is_not_reported_clean(self):
        ctx = Context()
        ctx.busy = True
        self.run_checks(ctx)
        self.assertEqual(ctx.row('.working')['status'], 'WARN')
        self.assertIn('merge, rebase or Git lock', ctx.row('.working')['detail'])

    def test_optional_and_required_missing_registration_have_distinct_results(self):
        for required, expected in [(False, 'WARN'), (True, 'FAIL')]:
            ctx = Context([])
            ctx.require_git = required
            self.run_checks(ctx)
            self.assertEqual(ctx.row('registry')['status'], expected)
            self.assertEqual(len(ctx.calls), 1)

    def test_malformed_or_secret_bearing_registration_does_not_run_owner_commands(self):
        for change in [dict(push_url='https://TOKEN@github.com/example/lab.git'),
                       dict(owner='root'), dict(path='/home/archtop/../root'), dict(prefix='../other')]:
            binding = {**BINDING, **change}
            ctx = self.run_checks(Context([binding]))
            self.assertEqual(ctx.row('.1')['status'], 'FAIL')
            self.assertEqual(len(ctx.calls), 1)
            self.assertNotIn('TOKEN', json.dumps(ctx.rows))

    def test_missing_owner_and_inaccessible_checkout_skip_git(self):
        ctx = Context()
        with patch.object(checks, 'account_for', side_effect=KeyError('PRIVATE')):
            checks.check_git(ctx)
        self.assertEqual(ctx.row('.owner')['status'], 'FAIL')
        self.assertEqual(len(ctx.calls), 1)
        for problem in ('missing', 'owner', 'symlink', 'unsupported'):
            ctx = Context()
            ctx.path_problem = problem
            self.run_checks(ctx)
            self.assertEqual(ctx.row('.checkout')['status'], 'FAIL')
            self.assertFalse(any('/usr/bin/git' in args for args, _ in ctx.calls))

    def test_registration_change_prevents_remote_request(self):
        for setting, value in [('branch', 'different'), ('destination', 'https://github.com/other/lab.git'), ('rewrites', True)]:
            ctx = Context()
            ctx.git_remote = True
            setattr(ctx, setting, value)
            self.run_checks(ctx)
            self.assertEqual(ctx.row('.binding')['status'], 'FAIL')
            self.assertEqual(ctx.row('.remote')['status'], 'SKIP')
            self.assertFalse(any('ls-remote' in args for args, _ in ctx.calls))

    def test_remote_read_does_not_claim_push_authentication(self):
        ctx = Context()
        ctx.git_remote = True
        self.run_checks(ctx)
        self.assertEqual(ctx.row('.remote')['status'], 'PASS')
        self.assertIn('anonymous', ctx.row('.remote')['detail'])
        self.assertIn('does not prove write permission', ctx.row('.push')['detail'])
        self.assertEqual(ctx.row('.push')['status'], 'INFO')
        self.assertEqual(sum('ls-remote' in args for args, _ in ctx.calls), 1)

    def test_remote_failure_reports_recovery_without_server_output(self):
        ctx = Context()
        ctx.git_remote = True
        ctx.remote_failure = True
        self.run_checks(ctx)
        self.assertEqual(ctx.row('.remote')['status'], 'FAIL')
        self.assertIn('noninteractive HTTPS login', ctx.row('.remote')['detail'])
        self.assertNotIn('PRIVATE', json.dumps(ctx.rows))

    def test_invalid_registry_stops_without_echoing_raw_data(self):
        ctx = Context()
        ctx.registry_failure = True
        self.run_checks(ctx)
        self.assertEqual(ctx.row('registry')['status'], 'FAIL')
        self.assertEqual(len(ctx.calls), 1)
        self.assertNotIn('PRIVATE', json.dumps(ctx.rows))

    def test_repository_limit_reports_unverified_remainder(self):
        ctx = self.run_checks(Context([{**BINDING, 'id': f'{number:032x}'} for number in range(21)]))
        self.assertEqual(ctx.row('limit')['status'], 'WARN')
        self.assertEqual(sum(item['id'].endswith('.checkout') for item in ctx.rows), 20)

    def test_duplicate_registration_ids_are_rejected_before_repository_access(self):
        ctx = self.run_checks(Context([copy.deepcopy(BINDING), copy.deepcopy(BINDING)]))
        self.assertEqual(len(ctx.calls), 1)
        self.assertEqual(sum(row['status'] == 'FAIL' for row in ctx.rows), 2)


if __name__ == '__main__':
    unittest.main()
