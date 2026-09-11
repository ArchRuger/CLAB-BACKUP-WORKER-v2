"""Bounded Git readiness checks without export, fetch, commit or push.

All repository commands run as the registered ordinary Linux owner. The existing
Git helper's status mode is intentionally avoided: it creates progress storage.
"""
import json
from pathlib import PurePosixPath
import re
import shlex
from urllib.parse import urlsplit


MAX_REPOSITORIES = 20
FIELDS = ('id', 'label', 'owner', 'path', 'remote', 'push_url', 'branch', 'prefix', 'revision')
PATH_PART = re.compile(r'[A-Za-z0-9_][A-Za-z0-9_.-]{0,180}\Z')
HEX = re.compile(r'(?:[0-9a-f]{40}|[0-9a-f]{64})\Z')
CHECK_PATH = """import json, os, pathlib, sys
p = pathlib.Path(sys.argv[1]); control = p / '.git'
problem = ''
if any(q.is_symlink() for q in (control, p, *p.parents)):
    problem = 'symlink'
elif not p.is_dir() or not control.is_dir():
    problem = 'missing'
elif p.stat().st_uid != os.geteuid() or control.stat().st_uid != os.geteuid():
    problem = 'owner'
elif any(q.exists() for q in (control / 'commondir', control / 'modules', p / '.gitmodules')):
    problem = 'unsupported'
busy = any((control / marker).exists() for marker in ('MERGE_HEAD', 'CHERRY_PICK_HEAD',
    'REVERT_HEAD', 'rebase-apply', 'rebase-merge', 'BISECT_START', 'index.lock'))
print(json.dumps({'problem': problem, 'busy': busy}))
"""


def account_for(name):
    # pwd is absent on Windows development hosts; tests replace this boundary.
    import pwd
    return pwd.getpwnam(name)


def text(value):
    return value.decode('utf8', errors='replace') if isinstance(value, bytes) else value


def valid_url(value):
    if not isinstance(value, str) or len(value) > 2048 or any(ord(c) < 33 for c in value):
        return False
    try:
        parsed = urlsplit(value)
        return bool(parsed.scheme == 'https' and parsed.hostname and not parsed.username
                    and not parsed.password and not parsed.query and not parsed.fragment)
    except ValueError:
        return False


def valid_binding(binding):
    if not isinstance(binding, dict) or any(not isinstance(binding.get(k), str) for k in FIELDS):
        return False
    if any(len(value) > 4096 or any(ord(c) < 32 for c in value) for value in (binding[k] for k in FIELDS)):
        return False
    path = PurePosixPath(binding['path'])
    prefix = binding['prefix']
    return bool(path.is_absolute() and str(path) != '/' and '..' not in path.parts
                and str(path) == binding['path']
                and re.fullmatch(r'[0-9a-f]{32}', binding['id'])
                and re.fullmatch(r'[0-9a-f]{64}', binding['revision'])
                and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_.-]{0,63}\$?', binding['owner'])
                and binding['owner'] not in ('root', 'clab-discovery')
                and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,99}', binding['remote'])
                and binding['branch'] and not binding['branch'].startswith('-')
                and valid_url(binding['push_url'])
                and (not prefix or (len(prefix) <= 500 and all(PATH_PART.fullmatch(p)
                     and p.lower() != '.git' and p not in ('.', '..') for p in prefix.split('/')))))


def owner_command(account, command):
    return ['sudo', '-n', '-H', '-u', account.pw_name, '--', '/usr/bin/env', '-i',
            'PATH=/usr/local/bin:/usr/bin:/bin', 'HOME=' + account.pw_dir,
            'USER=' + account.pw_name, 'LOGNAME=' + account.pw_name, 'LANG=C.UTF-8',
            'GIT_TERMINAL_PROMPT=0', 'GCM_INTERACTIVE=never', 'GIT_PAGER=cat',
            'GIT_LITERAL_PATHSPECS=1', 'GIT_OPTIONAL_LOCKS=0', *command]


def git(ctx, binding, account, *args, limit=1048576):
    command = ['/usr/bin/git', '--no-optional-locks', '-c', 'core.fsmonitor=false',
               '-C', binding['path'], *args]
    return ctx.run(owner_command(account, command), privileged=True, timeout=15, limit=limit)


def check_repository(ctx, binding, number):
    prefix = 'git.repo.' + str(number)
    title = 'Git repository ' + str(number)
    repair = ('As this checkout\'s registered Linux owner, run: bash '
              + shlex.quote(str(ctx.source / 'deploy/setup-git.sh')) + ' --guided --repo '
              + shlex.quote(binding['path']))
    try:
        account = account_for(binding['owner'])
        if account.pw_uid == 0 or account.pw_name != binding['owner'] or not PurePosixPath(account.pw_dir).is_absolute():
            raise ValueError()
    except (KeyError, OSError, ValueError):
        ctx.add(prefix + '.owner', 'FAIL', title + ': Linux owner',
                'The registered ordinary Linux account is missing or invalid.', repair)
        return
    inspected = ctx.run(owner_command(account, ['/usr/bin/python3', '-I', '-c', CHECK_PATH, binding['path']]),
                        privileged=True, timeout=15, limit=4096)
    try:
        report = json.loads(text(inspected.stdout)) if inspected.ok else None
        problem = report['problem'] if isinstance(report, dict) and isinstance(report.get('problem'), str) else 'unavailable'
    except (ValueError, KeyError, TypeError):
        problem = 'unavailable'
    if problem:
        details = {
            'symlink': 'The checkout or .git path uses a symlink, which the manager does not support.',
            'missing': 'The registered owner cannot access a standard checkout with a .git directory.',
            'owner': 'The checkout and .git directory must belong to their registered owner.',
            'unsupported': 'Linked worktrees and submodules are not supported by manager Git saves.',
        }
        ctx.add(prefix + '.checkout', 'FAIL', title + ': checkout and owner',
                details.get(problem, 'Could not check the checkout as its registered owner.'), repair)
        return
    root = git(ctx, binding, account, 'rev-parse', '--show-toplevel', limit=8192)
    bare = git(ctx, binding, account, 'rev-parse', '--is-bare-repository', limit=1024)
    head = git(ctx, binding, account, 'rev-parse', '--verify', 'HEAD', limit=1024)
    tracked = git(ctx, binding, account, 'ls-files', '--stage', limit=1048576)
    if not (root.ok and text(root.stdout).strip() == binding['path'] and bare.ok
            and text(bare.stdout).strip() == 'false' and head.ok and HEX.fullmatch(text(head.stdout).strip())
            and tracked.ok and not any(line.startswith('160000 ') for line in text(tracked.stdout).splitlines())):
        ctx.add(prefix + '.checkout', 'FAIL', title + ': checkout and owner',
                'A readable, non-bare repository root with an initial commit and no submodules is required.', repair)
        return
    ctx.add(prefix + '.checkout', 'PASS', title + ': checkout and owner',
            'The registered owner can read the standard checkout and its initial commit.')

    identities = [git(ctx, binding, account, 'var', role, limit=4096)
                  for role in ('GIT_AUTHOR_IDENT', 'GIT_COMMITTER_IDENT')]
    identity_ok = all(result.ok for result in identities)
    ctx.add(prefix + '.identity', 'PASS' if identity_ok else 'FAIL', title + ': commit identity',
            'Author and committer identity are configured.' if identity_ok
            else 'Git author or committer identity is missing or invalid for the registered owner.',
            '' if identity_ok else repair)

    branch = git(ctx, binding, account, 'symbolic-ref', '--quiet', '--short', 'HEAD', limit=8192)
    ref = git(ctx, binding, account, 'check-ref-format', '--branch', binding['branch'], limit=8192)
    remote = git(ctx, binding, account, 'remote', 'get-url', '--push', '--all', binding['remote'], limit=8192)
    rewrites = git(ctx, binding, account, 'config', '--get-regexp', r'^url\..*\.(insteadof|pushinsteadof)$', limit=8192)
    urls = text(remote.stdout).splitlines() if remote.ok else []
    binding_ok = (branch.ok and text(branch.stdout).strip() == binding['branch'] and ref.ok
                  and len(urls) == 1 and valid_url(urls[0]) and urls[0] == binding['push_url']
                  and rewrites.code == 1 and not rewrites.reason)
    ctx.add(prefix + '.binding', 'PASS' if binding_ok else 'FAIL', title + ': branch and destination',
            'The current branch and single HTTPS push destination match the registration.' if binding_ok
            else 'The branch or destination changed, a URL rewrite exists, or Git could not verify the registration.',
            '' if binding_ok else repair)

    scope = [binding['prefix'] + '/' + name if binding['prefix'] else name
             for name in ('latest', 'baseline', 'checkpoints')]
    staged = git(ctx, binding, account, 'diff', '--no-ext-diff', '--no-textconv', '--cached', '--name-only', '-z', '--')
    status = git(ctx, binding, account, 'status', '--porcelain=v1', '--untracked-files=all', '--no-renames', '--', *scope)
    if not staged.ok or not status.ok:
        ctx.add(prefix + '.working', 'FAIL', title + ': pending changes',
                'Could not read staging and managed-folder status as the registered owner.', repair)
    else:
        staged_count = len([name for name in text(staged.stdout).split('\0') if name])
        managed_count = len(text(status.stdout).splitlines())
        busy = bool(report.get('busy'))
        dirty = staged_count > 0 or managed_count > 0 or busy
        ctx.add(prefix + '.working', 'WARN' if dirty else 'PASS', title + ': pending changes',
                f'{staged_count} staged file(s); {managed_count} changed entry/entries in managed folders.'
                + (' An existing merge, rebase or Git lock needs review.' if busy else '')
                + (' A new export may be blocked.' if dirty else ' No staged or managed-folder changes found.'),
                'For a failed manager save, repair its original error and retry that saved operation. '
                'Review unrelated edits as the owner; do not discard or reset them.' if dirty else '')

    if not ctx.git_remote:
        ctx.add(prefix + '.remote', 'INFO', title + ': remote read',
                'Not tested. Run with --git-remote to check remote branch access without fetching or pushing.')
    elif not binding_ok:
        ctx.add(prefix + '.remote', 'SKIP', title + ': remote read',
                'Resolve the registered branch and destination before checking network access.')
    else:
        result = git(ctx, binding, account, 'ls-remote', '--exit-code', binding['push_url'],
                     'refs/heads/' + binding['branch'], limit=4096)
        lines = text(result.stdout).splitlines() if result.ok else []
        parts = lines[0].split('\t') if len(lines) == 1 else []
        remote_ok = len(parts) == 2 and HEX.fullmatch(parts[0]) and parts[1] == 'refs/heads/' + binding['branch']
        ctx.add(prefix + '.remote', 'PASS' if remote_ok else 'FAIL', title + ': remote read',
                'The remote branch is reachable. Public repositories can allow anonymous reads.' if remote_ok
                else 'Remote branch access failed or timed out. Check connectivity, branch existence and the owner\'s noninteractive HTTPS login.',
                '' if remote_ok else repair)
    ctx.add(prefix + '.push', 'INFO', title + ': push permission',
            'Not exercised. Remote read access does not prove write permission or acceptance by branch rules. '
            'Complete a deliberate Save progress and push to verify publishing.')


def check_git(ctx):
    result = ctx.run(['/usr/bin/python3', '-I', str(ctx.source / 'deploy/git-registrations.py')],
                     privileged=True, timeout=15, limit=1048576)
    try:
        value = json.loads(text(result.stdout)) if result.ok else None
        public = value.get('result') if isinstance(value, dict) else None
        if (not isinstance(public, dict) or public.get('protocol') != 'clab-manager-git-v1'
                or public.get('version') != ctx.version):
            raise ValueError()
        repositories = public.get('repositories')
        if not isinstance(repositories, list):
            raise ValueError()
    except (ValueError, TypeError):
        ctx.add('git.registry', 'FAIL', 'Git repository registry',
                'Could not safely read the registered checkout settings. No repository commands were run.',
                'Check sudo access, source files and the root-owned /etc/clab-manager/git.json registry; retain existing settings.')
        return
    if not repositories:
        ctx.add('git.registry', 'FAIL' if ctx.require_git else 'WARN', 'Git repository registry',
                'No Git checkout is registered. Git export and push are not configured.',
                'As your normal VM account, run: bash ' + shlex.quote(str(ctx.source / 'deploy/setup-git.sh')))
        return
    ctx.add('git.registry', 'PASS', 'Git repository registry',
            f'{len(repositories)} repository registration(s) found; credentials are omitted.')
    if len(repositories) > MAX_REPOSITORIES:
        ctx.add('git.limit', 'WARN', 'Git check limit',
                f'Only the first {MAX_REPOSITORIES} registrations are checked in this run; remaining checkouts are unverified.')
    ids = [item.get('id') for item in repositories if isinstance(item, dict) and isinstance(item.get('id'), str)]
    for number, binding in enumerate(repositories[:MAX_REPOSITORIES], 1):
        if not valid_binding(binding) or ids.count(binding['id']) != 1:
            ctx.add('git.repo.' + str(number), 'FAIL', 'Git repository ' + str(number) + ': registration',
                    'Registration fields are invalid or unsafe. No commands were run for this checkout.',
                    'Review this entry using guided Git setup; retain the current checkout and its files.')
            continue
        check_repository(ctx, binding, number)
