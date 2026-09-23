"""Restricted VM Git dispatcher. Installed root-owned; repository work runs as its owner.

No network credentials pass through this protocol. Only root can register bindings.
The worker deliberately retains the owner's Git configuration, hooks and helper,
after permanently dropping supplementary groups/GID/UID. Stdlib only.
"""
import base64
import contextlib
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import signal
import stat
import subprocess
import sys
import threading
import uuid
from urllib.parse import urlsplit

PROTOCOL = 'clab-manager-git-v1'
VERSION = '1.30.36'
MAX_FILE = 2 * 1024 * 1024
MAX_TOTAL = 16 * 1024 * 1024
MAX_JSON = 24 * 1024 * 1024
REGISTRY = Path('/etc/clab-manager/git.json')
GIT = '/usr/bin/git'
HEX = re.compile(r'(?:[0-9a-f]{40}|[0-9a-f]{64})\Z')
ID = re.compile(r'[0-9a-f]{32}\Z')
SLUG = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,99}\Z')
PATH_PART = re.compile(r'[A-Za-z0-9_][A-Za-z0-9_.-]{0,180}\Z')
GITHUB_PART = re.compile(r'[A-Za-z0-9_.-]+\Z')
GH = '/usr/bin/gh'
ENGINEER = Path('/etc/clab-manager/engineer.json')
MAX_TREE = 4000
MAX_MOVE = 1500


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


def relpath(value, empty=False):
    if empty and value == '': return ''
    if not isinstance(value, str) or not value or len(value) > 500 or '\\' in value:
        raise ValueError('Use a safe relative repository path.')
    parts = value.split('/')
    if any(not PATH_PART.fullmatch(p) or p.lower() == '.git' or p in ('.', '..') for p in parts):
        raise ValueError('Use literal repository paths without traversal or hidden Git paths.')
    return '/'.join(parts)


RESERVED = ('latest', 'baseline', 'checkpoints')


def base_prefix(value):
    """A lab folder (registration prefix): the folder Save progress writes `latest`, `baseline` and
    `checkpoints/<name>` into. Those names cannot be a lab folder themselves, or the next save would
    nest a second snapshot folder inside the first (`working/latest/latest`)."""
    prefix = relpath(value, empty=True)
    parts = prefix.split('/') if prefix else []
    if parts and (parts[-1] in RESERVED or (len(parts) >= 2 and parts[-2] == 'checkpoints')):
        parent = '/'.join(parts[:-2] if parts[-2:-1] == ['checkpoints'] else parts[:-1])
        raise ValueError('latest, baseline and checkpoints are the folders Save progress writes inside a lab folder. '
                         'Choose the folder above them: its saves go to ' + (parent + '/latest' if parent else 'latest at the repository root') + '.')
    return prefix


def snapshot_folder(value):
    """A snapshot folder: any safe repository folder, `''` (or `/`) for the repository root. Whether it
    is a snapshot is decided by its manifest, which read_version then validates."""
    if value in ('', '/'): return ''
    if isinstance(value, str) and value.startswith('/'): value = value[1:]
    return relpath(value)


def snapshot_file(folder, name):
    return folder + '/' + name if folder else name


def checked_url(value, allow_local=False):
    if not isinstance(value, str) or len(value) > 2048 or any(ord(c) < 33 for c in value):
        raise ValueError('Invalid Git remote URL.')
    url = urlsplit(value)
    if allow_local and (url.scheme == 'file' or Path(value).is_absolute()): return value
    if url.scheme != 'https' or not url.hostname or url.username or url.password or url.query or url.fragment:
        raise ValueError('Configure one HTTPS remote without embedded credentials, query or fragment.')
    return value


def clone_url(value):
    """The HTTPS clone URL a student pastes. GitHub page links (tree/blob/...) resolve to the
    repository's clone URL; nothing else is rewritten, and no credentials may be embedded."""
    problem = 'Use the HTTPS clone URL (Code > HTTPS) without a username, token, query or fragment.'
    if not isinstance(value, str) or not 1 <= len(value) <= 2048 or any(ord(c) <= 32 or ord(c) == 127 for c in value) or '%' in value or '\\' in value:
        raise ValueError(problem)
    url = urlsplit(value)
    if url.scheme != 'https' or not url.hostname or url.username or url.password or url.query or url.fragment or not url.path.strip('/'):
        raise ValueError(problem)
    if url.hostname.lower() == 'github.com':
        parts = url.path.strip('/').split('/')
        if len(parts) > 2 and parts[2] in ('tree', 'blob', 'commit', 'commits', 'pull', 'pulls', 'issues', 'actions', 'settings', 'releases', 'wiki'):
            parts = parts[:2]
        if len(parts) != 2 or not all(GITHUB_PART.fullmatch(p) for p in parts) or any(p in ('.', '..') for p in parts) or not parts[1].removesuffix('.git'):
            raise ValueError('Use the GitHub repository clone URL: https://github.com/OWNER/REPOSITORY.git (Code > HTTPS). Page links such as /tree/main are not clone URLs.')
        return 'https://github.com/' + parts[0] + '/' + parts[1].removesuffix('.git') + '.git'
    return checked_url(value)


def same_repository(left, right):
    def normalized(value):
        host = urlsplit(value).hostname
        if host and host.lower() == 'github.com':
            return value.rstrip('/').removesuffix('.git').lower()
        return value
    return normalized(left) == normalized(right)


def repository_name(url):
    name = urlsplit(url).path.rstrip('/').rsplit('/', 1)[-1].removesuffix('.git')
    if not PATH_PART.fullmatch(name) or name in ('.', '..'): raise ValueError('The repository name cannot be used as a VM folder name.')
    return name


def descriptor(binding):
    return {k: binding[k] for k in ('id', 'label', 'owner', 'path', 'remote', 'push_url', 'branch', 'prefix', 'revision')}


def overlapping(prefix, other):
    return not prefix or not other or prefix.startswith(other + '/') or other.startswith(prefix + '/')


def no_links(path, require=True):
    path = Path(path)
    for part in (path, *path.parents):
        if part.is_symlink(): raise ValueError('Symlinked repository paths are not supported.')
    if require and not path.exists(): raise ValueError('The registered repository path is missing.')
    return path


def snapshot(value):
    if not isinstance(value, dict) or set(value) != {'manifest', 'files'}:
        raise ValueError('A complete manifest and file map are required.')
    manifest, encoded = value['manifest'], value['files']
    # Schema 1 (config files only) and schema 2 (Junos backups also carry a hierarchical
    # restore-grade artifact per node, referenced by a file entry's `restore_artifact`).
    if not isinstance(manifest, dict) or manifest.get('schema') not in (1, 2) or not isinstance(encoded, dict):
        raise ValueError('Unsupported snapshot schema.')
    files = manifest.get('files')
    if not isinstance(files, list) or not 1 <= len(files) <= 500 or len(json.dumps(manifest)) > MAX_FILE:
        raise ValueError('The snapshot requires between 1 and 500 bounded files.')
    result = {}; total = 0

    def take(name, size, sha):
        nonlocal total
        name = relpath(name)
        if '/' in name or name == 'manifest.json' or name in result: raise ValueError('Snapshot filenames must be unique plain filenames.')
        data = encoded.get(name)
        if not isinstance(data, str) or len(data) > (MAX_FILE + 2) // 3 * 4: raise ValueError('Missing or oversized snapshot file.')
        try: raw = base64.b64decode(data, validate=True)
        except Exception: raise ValueError('Invalid snapshot file encoding.') from None
        total += len(raw)
        if not raw or len(raw) > MAX_FILE or total > MAX_TOTAL: raise ValueError('Snapshot exceeds the transfer limits.')
        if type(size) is not int or size != len(raw) or sha != hashlib.sha256(raw).hexdigest():
            raise ValueError('Snapshot file length or checksum did not match its manifest.')
        result[name] = raw

    for item in files:
        if not isinstance(item, dict): raise ValueError('Invalid snapshot file metadata.')
        take(item.get('path'), item.get('size'), item.get('sha256'))
        if item.get('restore_artifact'):
            take(item['restore_artifact'], item.get('restore_size'), item.get('restore_sha256'))
    if set(result) != set(encoded): raise ValueError('The file map must exactly match the manifest.')
    return manifest, result


def content_digest(manifest):
    return digest({k: v for k, v in manifest.items() if k not in ('backup_job_id', 'captured_at')})


def atomic_json(path, value):
    no_links(path, False); path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = path.parent / ('.tmp-' + uuid.uuid4().hex)
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, 'w', encoding='utf8', newline='\n') as stream:
            json.dump(value, stream, sort_keys=True, ensure_ascii=False); stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, path)
        sync_directory(path.parent)
    finally:
        if temporary.exists(): temporary.unlink()


def sync_directory(path):
    if os.name == 'posix':
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        try: os.fsync(fd)
        finally: os.close(fd)


def command(argv, cwd, env, limit=MAX_JSON, timeout=45):
    process = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                               start_new_session=os.name == 'posix')
    expired = threading.Event()
    def kill():
        try:
            # Credential helpers/hooks may inherit stdout and outlive Git itself.
            # The group's lifetime does not end when the direct child exits.
            if os.name == 'posix': os.killpg(process.pid, getattr(signal, 'SIGKILL', 9))
            elif process.poll() is None: process.kill()
        except ProcessLookupError: pass
    def expire():
        expired.set(); kill()
    timer = threading.Timer(timeout, expire); timer.start()
    try:
        output = process.stdout.read(limit + 1)
        if expired.is_set(): raise ValueError('Git command timed out. Check the repository and credential helper before retrying.')
        if len(output) > limit: kill(); raise ValueError('Git output exceeded its bounded response limit.')
        code = process.wait(timeout=5)
        if expired.is_set(): raise ValueError('Git command timed out. Check the repository and credential helper before retrying.')
        return code, output
    finally:
        timer.cancel(); timer.join(); kill(); process.wait(); process.stdout.close()


class GitRepository:
    """Construct only AFTER the production dispatcher has dropped privileges.

    The explicit executable/environment/local-remote parameters are test seams;
    protocol requests cannot select them.
    """
    def __init__(self, binding, *, git=GIT, allow_local=False, env=None, gh=GH):
        self.binding = binding; self.root = no_links(binding['path'], require=not binding.get('_pending')); self.allow_local = allow_local
        self.git = git; self.gh = gh
        self.env = {'PATH': '/usr/local/bin:/usr/bin:/bin', 'HOME': binding['home'],
                    'USER': binding['owner'], 'LOGNAME': binding['owner'], 'LANG': 'C.UTF-8',
                    'GIT_TERMINAL_PROMPT': '0', 'GCM_INTERACTIVE': 'never', 'GIT_PAGER': 'cat',
                    'GIT_LITERAL_PATHSPECS': '1'}
        if env is not None: self.env.update(env)
        self.prefix = relpath(binding.get('prefix', ''), empty=True)
        self.control = no_links(self.root / '.git', False)
        if binding.get('_pending') and not self.control.exists(): return
        if not self.control.exists(): raise ValueError('This directory is not a Git checkout: .git is missing. Run guided Git setup to clone a repository; mkdir alone is insufficient.')
        if not self.control.is_dir(): raise ValueError('Linked worktrees and bare repositories are not supported.')
        self.state = self.control / 'clab-manager'; no_links(self.state, False)
        self.state.mkdir(mode=0o700, exist_ok=True)
        if os.name == 'posix':
            if self.state.stat().st_uid != os.geteuid(): raise ValueError('Git progress storage must belong to the registered owner.')
            self.state.chmod(0o700)

    def run(self, *args, check=True, limit=MAX_JSON, timeout=45):
        code, raw = command([self.git, '-c', 'color.ui=false', *args], self.root, self.env, limit, timeout)
        if check and code: raise ValueError('Git could not complete this operation. Check the repository as its registered owner.')
        return (code, raw) if not check else raw.decode('utf8').strip()

    def scope(self, name): return '/'.join(p for p in (self.prefix, name) if p)

    def registration(self, previous=None):
        binding = {k: v for k, v in self.binding.items() if not k.startswith('_')}
        unchanged = previous and all(previous.get(k) == v for k, v in binding.items() if k not in ('revision', 'anchor'))
        if unchanged:
            binding['anchor'] = previous['anchor']
            binding['revision'] = previous['revision']
        else:
            binding['revision'] = digest({k: v for k, v in binding.items() if k != 'revision'})
        return binding

    def commit_identity(self):
        for role in ('GIT_AUTHOR_IDENT', 'GIT_COMMITTER_IDENT'):
            code, _ = self.run('var', role, check=False)
            if code:
                raise ValueError('Git commit identity is missing or invalid. As the registered Linux owner, run guided Git setup or set user.name and user.email inside this checkout, then retry the original save.')

    def check_push_access(self):
        code, _ = self.run('push', '--dry-run', '--porcelain', '--no-follow-tags', self.binding['remote'],
                           'HEAD:refs/heads/' + self.binding['branch'], check=False, timeout=90)
        if code:
            raise ValueError('Git push preflight failed. Authenticate as the registered Linux owner and check remote write access. For GitHub use gh auth login and gh auth setup-git; your GitHub website password cannot authenticate a Git push. No commits were pushed.')

    def descriptor(self):
        return {k: self.binding[k] for k in ('id', 'label', 'owner', 'path', 'remote', 'push_url', 'branch', 'prefix', 'revision')}

    @contextlib.contextmanager
    def lock(self):
        path = no_links(self.state / 'lock', False)
        with path.open('a+b') as stream:
            try:
                if os.name == 'posix':
                    import fcntl
                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                else:
                    import msvcrt
                    stream.seek(0); stream.write(b'0'); stream.flush(); stream.seek(0)
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            except (OSError, BlockingIOError): raise ValueError('Another Git operation is already running for this repository.') from None
            try: yield
            finally:
                if os.name == 'posix': fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
                else: stream.seek(0); msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)

    def validate(self):
        no_links(self.root); no_links(self.control)
        if self.run('rev-parse', '--show-toplevel').replace('\\', '/') != str(self.root).replace('\\', '/'):
            raise ValueError('Select the repository root of a standard checkout.')
        if self.run('rev-parse', '--is-bare-repository') != 'false': raise ValueError('Bare repositories are unsupported.')
        if self.run('rev-parse', '--git-common-dir').replace('\\', '/') not in ('.git', str(self.control).replace('\\', '/')):
            raise ValueError('Linked worktrees are unsupported.')
        if (self.control / 'commondir').exists() or (self.control / 'modules').exists() or (self.root / '.gitmodules').exists():
            raise ValueError('Submodules and linked worktrees are unsupported.')
        if any(line.startswith('160000 ') for line in self.run('ls-files', '--stage', limit=MAX_TOTAL).splitlines()):
            raise ValueError('Submodules are unsupported.')
        if self.run('symbolic-ref', '--quiet', '--short', 'HEAD') != self.binding['branch']:
            raise ValueError('The repository branch changed. Restore the registered branch or register it again.')
        # Reject URL rewrites instead of displaying one URL and pushing to another.
        code, _ = self.run('config', '--get-regexp', r'^url\..*\.(insteadof|pushinsteadof)$', check=False)
        if code == 0: raise ValueError('Git URL rewrites are unsupported for registered repositories.')
        urls = self.run('remote', 'get-url', '--push', '--all', self.binding['remote']).splitlines()
        if len(urls) != 1 or checked_url(urls[0], self.allow_local) != self.binding['push_url']:
            raise ValueError('The Git push destination changed. Register the repository again.')
        head = self.run('rev-parse', '--verify', 'HEAD')
        if not HEX.fullmatch(head): raise ValueError('Initialize the repository with its first commit.')
        return head

    def clean(self, entire=False):
        if any((self.control / marker).exists() for marker in ('MERGE_HEAD', 'CHERRY_PICK_HEAD', 'REVERT_HEAD', 'rebase-apply', 'rebase-merge', 'BISECT_START', 'index.lock')):
            raise ValueError('Finish the existing Git operation before saving lab progress.')
        if self.run('diff', '--cached', '--name-only', '-z'): raise ValueError('The repository already has staged changes. If an earlier manager save failed, fix its reported issue and retry that original save: Retry commits automatically. For unrelated staged work, resolve it as the repository owner first.')
        args = [] if entire else ['--', self.scope('latest'), self.scope('baseline'), self.scope('checkpoints')]
        if self.run('status', '--porcelain=v1', '--untracked-files=all', *args):
            raise ValueError('The repository has unsaved edits in the selected scope. Resolve them before continuing.')

    def file(self, relative):
        path = no_links(self.root / relpath(relative), False)
        if path.exists() and (not path.is_file() or path.stat().st_nlink != 1): raise ValueError('Only ordinary, unlinked snapshot files are supported.')
        return path

    def read_manifest(self, folder):
        path = self.file(folder + '/manifest.json')
        if not path.exists(): return None
        if path.stat().st_size > MAX_FILE: raise ValueError('Existing manifest is too large.')
        try: value = json.loads(path.read_text(encoding='utf8'))
        except Exception: raise ValueError('Existing snapshot manifest is invalid.') from None
        if not isinstance(value, dict) or value.get('schema') not in (1, 2) or not isinstance(value.get('files'), list):
            raise ValueError('Existing snapshot manifest is invalid.')
        total = 0; seen = set()
        if not 1 <= len(value['files']) <= 500: raise ValueError('Existing snapshot manifest has an invalid file count.')

        def check(name, size, sha):
            nonlocal total
            name = relpath(name)
            if '/' in name or name == 'manifest.json' or name in seen: raise ValueError('Existing snapshot manifest has unsafe or duplicate filenames.')
            seen.add(name); item_path = self.file(folder + '/' + name)
            if not item_path.exists() or item_path.stat().st_size > MAX_FILE: raise ValueError('Existing snapshot files are missing or too large.')
            raw = item_path.read_bytes(); total += len(raw)
            if total > MAX_TOTAL or len(raw) != size or hashlib.sha256(raw).hexdigest() != sha:
                raise ValueError('Existing snapshot files no longer match their saved manifest. Review the repository before exporting.')

        for item in value['files']:
            if not isinstance(item, dict): raise ValueError('Existing snapshot manifest contains invalid file metadata.')
            check(item.get('path'), item.get('size'), item.get('sha256'))
            if item.get('restore_artifact'):
                check(item['restore_artifact'], item.get('restore_size'), item.get('restore_sha256'))
        return value

    def status(self):
        result = {'repository': self.descriptor(), 'head': '', 'ready': False, 'problem': '', 'baseline_revision': '', 'latest_manifest': None}
        try:
            result['head'] = self.validate(); self.clean()
            result['latest_manifest'] = self.read_manifest(self.scope('latest'))
            baseline = self.read_manifest(self.scope('baseline'))
            result['baseline_revision'] = digest(baseline) if baseline else ''
            result['ready'] = True
        except ValueError as error: result['problem'] = str(error)
        return result

    def journal_path(self, operation):
        if not isinstance(operation, str) or not ID.fullmatch(operation): raise ValueError('Invalid progress operation ID.')
        return no_links(self.state / 'journals' / (operation + '.json'), False)

    def load_journal(self, operation):
        path = self.journal_path(operation)
        if not path.exists(): return None
        if path.stat().st_size > MAX_JSON: raise ValueError('The saved progress journal is invalid.')
        return json.loads(path.read_text(encoding='utf8'))

    def save_journal(self, journal): atomic_json(self.journal_path(journal['operation_id']), journal)

    def known_commits(self):
        result = set()
        directory = no_links(self.state / 'journals', False)
        if not directory.exists(): return result
        for path in directory.glob('*.json'):
            no_links(path)
            if path.stat().st_size > MAX_JSON: continue
            value = json.loads(path.read_text(encoding='utf8'))
            if value.get('commit') and value.get('verified') and value.get('binding_revision') in self.binding.get('_approved_revisions', [self.binding['revision']]):
                result.add(value['commit'])
        return result

    def remote_head(self):
        code, raw = self.run('ls-remote', '--exit-code', self.binding['push_url'], 'refs/heads/' + self.binding['branch'], check=False, limit=4096, timeout=45)
        if code: raise ValueError('The remote branch is unavailable. Check connectivity and the owner\'s noninteractive HTTPS Git login.')
        lines = raw.decode('utf8').splitlines()
        if len(lines) != 1 or not HEX.fullmatch(lines[0].split('\t')[0]): raise ValueError('The remote branch response was invalid.')
        return lines[0].split('\t')[0]

    def verify_tree(self, commit, expected, paths, parent):
        if not HEX.fullmatch(commit): raise ValueError('Invalid Git commit identity.')
        actual = set(filter(None, self.run('diff-tree', '--no-commit-id', '--name-only', '-r', '-z', parent, commit).split('\0')))
        if actual != set(paths): raise ValueError('Git hooks changed files outside the approved snapshot. Review the local commit; it was not pushed.')
        for name, raw in expected.items():
            code, blob = self.run('show', commit + ':' + name, check=False, limit=MAX_FILE + 1)
            if raw is None:
                if code == 0: raise ValueError('The committed deletion did not match the approved snapshot.')
            elif code or blob != raw: raise ValueError('Git filters or hooks changed snapshot content. Review the local commit; it was not pushed.')

    def result(self, journal):
        return {key: journal.get(key) for key in ('status', 'commit', 'changed_files', 'message', 'pushed', 'snapshot_path', 'synced_operations')}

    def mark_synced(self, journal, remote):
        synced = []; directory = no_links(self.state / 'journals', False)
        for path in directory.glob('*.json'):
            no_links(path)
            if path.stat().st_size > MAX_JSON: continue
            other = json.loads(path.read_text(encoding='utf8'))
            if not other.get('verified') or not other.get('commit') or other.get('binding_revision') not in self.binding.get('_approved_revisions', [self.binding['revision']]): continue
            code, _ = self.run('merge-base', '--is-ancestor', other['commit'], remote, check=False)
            if not code:
                other.update(status='synced', pushed=True, message='Saved to Git.'); self.save_journal(other); synced.append(other['operation_id'])
        if journal['operation_id'] not in synced: synced.append(journal['operation_id'])
        journal.update(status='synced', pushed=True, message='Saved to Git.', synced_operations=synced); self.save_journal(journal)
        return self.result(journal)

    def push(self, journal):
        commit = journal.get('commit')
        if commit and not journal.get('verified') and not journal.get('unchanged') and journal.get('expected') and journal.get('parent'):
            expected = {p: None if b is None else base64.b64decode(b) for p, b in journal['expected'].items()}
            self.verify_tree(commit, expected, journal['changed_files'], journal['parent'])
            if self.validate() != commit: raise ValueError('The checkout moved after this save. Review its commit before retrying.')
            self.clean(); journal['verified'] = True; self.save_journal(journal)
        if not commit or (not journal.get('verified') and not journal.get('unchanged')): raise ValueError('This save has no verified commit to push. Review its export status.')
        head = self.validate()
        remote = self.remote_head()
        if remote == commit:
            return self.mark_synced(journal, remote)
        # Fetch objects only; never change the index, checkout, refs or FETCH_HEAD.
        self.run('fetch', '--no-tags', '--no-recurse-submodules', '--no-write-fetch-head', self.binding['push_url'], 'refs/heads/' + self.binding['branch'], timeout=60)
        code, _ = self.run('merge-base', '--is-ancestor', commit, remote, check=False)
        if code == 0: return self.mark_synced(journal, remote)
        if not journal.get('verified'): raise ValueError('This unchanged save points to a commit created outside manager saves. Publish it as the repository owner first.')
        if head != commit: raise ValueError('The checkout moved since this save. Push the newest saved progress or resolve it as the repository owner.')
        self.clean()
        code, _ = self.run('merge-base', '--is-ancestor', remote, commit, check=False)
        if code: raise ValueError('The remote branch advanced or diverged. Resolve the branch before pushing; no force push was attempted.')
        outgoing = set(self.run('rev-list', remote + '..' + commit).splitlines())
        if not outgoing.issubset(self.known_commits()): raise ValueError('The push would include commits created outside manager saves. Publish or resolve them as the repository owner first.')
        if self.validate() != commit: raise ValueError('The checkout changed before push; review the repository.')
        self.clean()
        code, _ = self.run('push', '--porcelain', '--no-follow-tags', self.binding['push_url'], commit + ':refs/heads/' + self.binding['branch'], check=False, timeout=90)
        if code: raise ValueError('The commit is saved on the VM, but push failed. Check authentication, branch permissions or remote changes, then retry.')
        if self.remote_head() != commit: raise ValueError('Push returned, but its remote result could not be verified. Retry the saved progress.')
        return self.mark_synced(journal, commit)

    def retry_push(self, req):
        journal = self.load_journal(req.get('operation_id'))
        if not journal or journal.get('binding_revision') != self.binding['revision']: raise ValueError('Saved progress journal not found for this binding.')
        try: return self.push(journal)
        except ValueError as error:
            journal.update(status='needs_attention', pushed=False, message=str(error)); self.save_journal(journal); return self.result(journal)

    def finish_export(self, journal, req):
        self.commit_identity()
        """Resume only files still matching their journaled before or after bytes."""
        expected = {p: None if b is None else base64.b64decode(b) for p, b in journal['expected'].items()}
        before = journal['before']; changed = journal['changed_files']; head = journal['parent']
        if self.validate() != head: raise ValueError('The checkout changed during export. Preserve the snapshot and review the working files.')
        if any((self.control / marker).exists() for marker in ('MERGE_HEAD', 'CHERRY_PICK_HEAD', 'REVERT_HEAD', 'rebase-apply', 'rebase-merge', 'index.lock')):
            raise ValueError('Finish the existing Git operation before retrying export.')
        staged = set(filter(None, self.run('diff', '--cached', '--no-renames', '--name-only', '-z').split('\0')))
        if staged - set(changed): raise ValueError('Unrelated files entered the index during export; no commit was attempted.')
        for name in staged:
            code, raw = self.run('show', ':' + name, check=False, limit=MAX_FILE + 1)
            indexed = None if code else hashlib.sha256(raw).hexdigest()
            after = expected[name]; after_digest = hashlib.sha256(after).hexdigest() if after is not None else None
            if indexed not in (before[name], after_digest): raise ValueError('An exported file has separately staged edits. Preserve those edits before retrying.')
        # The journal owns only these exact changes, never a recursive directory.
        for name in changed:
            path = self.file(name); current = path.read_bytes() if path.exists() else None
            fingerprint = hashlib.sha256(current).hexdigest() if current is not None else None
            after = expected[name]; after_digest = hashlib.sha256(after).hexdigest() if after is not None else None
            if fingerprint not in (before[name], after_digest): raise ValueError('An exported file was edited after saving began. Review it before retrying; the snapshot is preserved.')
        for name in changed:
            raw = expected[name]; path = self.file(name)
            if raw is None: path.unlink(missing_ok=True)
            else:
                no_links(path.parent, False); path.parent.mkdir(parents=True, exist_ok=True)
                temporary = path.parent / ('.clab-save-' + uuid.uuid4().hex)
                fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, 'wb') as stream: stream.write(raw); stream.flush(); os.fsync(stream.fileno())
                os.replace(temporary, path)
            sync_directory(path.parent)
        if self.validate() != head: raise ValueError('The checkout changed before staging. Review the working files.')
        self.run('add', '-A', '--', *changed)
        staged = set(filter(None, self.run('diff', '--cached', '--no-renames', '--name-only', '-z').split('\0')))
        if staged != set(changed): raise ValueError('Git staging changed the approved file set. Review the index; nothing was pushed.')
        for name in changed:
            raw = expected[name]
            if raw is None: continue
            code, content = self.run('show', ':' + name, check=False, limit=MAX_FILE + 1)
            if code or raw != content: raise ValueError('Git filters changed the saved configuration. Review attributes and staged files; nothing was pushed.')
        message = req.get('message') or ('Save ' + str(req['snapshot']['manifest'].get('lab_name', 'lab')) + ' progress')
        if not isinstance(message, str) or len(message) > 500 or any(ord(c) < 32 for c in message): raise ValueError('Use a short single-line commit note.')
        message_file = self.state / ('message-' + journal['operation_id'] + '.txt')
        no_links(message_file, False); message_file.write_text(message + '\n\nManager-Operation: ' + journal['operation_id'] + '\n', encoding='utf8')
        try: self.run('commit', '--only', '-F', str(message_file), '--', *changed, timeout=90)
        finally: message_file.unlink(missing_ok=True)
        commit = self.run('rev-parse', 'HEAD'); journal['commit'] = commit; self.save_journal(journal)
        self.verify_tree(commit, expected, changed, head)
        if self.validate() != commit: raise ValueError('The checkout changed after committing. Review the preserved commit before pushing.')
        self.clean()
        journal.update(status='committed', verified=True, message='Saved in the VM repository; not pushed.'); self.save_journal(journal)
        return self.retry_push(req) if req.get('push') else self.result(journal)

    def publish(self, req):
        operation = req.get('operation_id'); self.journal_path(operation)
        manifest, files = snapshot(req.get('snapshot'))
        request_digest = digest(req)
        journal = self.load_journal(operation)
        # An explicit retry may adopt the owner's repaired HEAD only while this
        # journal proves we have never prepared or written any repository files.
        # Once parent/expected paths exist, recovery remains bound to that parent.
        retry_before_write = bool(journal and not journal.get('parent') and not journal.get('expected') and not journal.get('changed_files') and not journal.get('commit'))
        if journal:
            if journal.get('request_digest') != request_digest: raise ValueError('This operation ID already belongs to a different snapshot or save action.')
            if journal.get('commit'):
                if not journal.get('verified') and not journal.get('unchanged') and journal.get('expected') and journal.get('parent'):
                    try:
                        expected = {p: None if b is None else base64.b64decode(b) for p, b in journal['expected'].items()}
                        self.verify_tree(journal['commit'], expected, journal['changed_files'], journal['parent'])
                        if self.validate() != journal['commit']: raise ValueError('The checkout moved after this save. Review its commit before retrying.')
                        self.clean()
                        journal.update(status='committed', verified=True, message='Verified the saved commit; not pushed.'); self.save_journal(journal)
                    except ValueError as error:
                        journal.update(status='needs_attention', message=str(error)); self.save_journal(journal); return self.result(journal)
                if req.get('push') and journal.get('verified') and not journal.get('pushed'): return self.retry_push(req)
                return self.result(journal)
            # Reconcile a response lost immediately after commit, before journal update.
            parent = journal.get('parent')
            if parent:
                found = self.run('log', '-30', '--format=%H', '--fixed-strings', '--grep=Manager-Operation: ' + operation).splitlines()
                if len(found) == 1:
                    expected = {p: None if b is None else base64.b64decode(b) for p, b in journal['expected'].items()}
                    try: self.verify_tree(found[0], expected, journal['changed_files'], parent)
                    except ValueError as error:
                        journal.update(status='needs_attention', commit=found[0], verified=False, message=str(error)); self.save_journal(journal); return self.result(journal)
                    journal.update(status='committed', commit=found[0], verified=True, message='Recovered the saved commit.'); self.save_journal(journal)
                    return self.retry_push(req) if req.get('push') else self.result(journal)
                try: return self.finish_export(journal, req)
                except ValueError as error:
                    journal.update(status='needs_attention', message=str(error)); self.save_journal(journal); return self.result(journal)
        archive = no_links(self.state / 'snapshots' / (operation + '.json'), False)
        atomic_json(archive, req['snapshot'])
        journal = {'operation_id': operation, 'request_digest': request_digest, 'binding_revision': self.binding['revision'],
                   'status': 'needs_attention', 'commit': None, 'verified': False, 'changed_files': [], 'pushed': False,
                   'snapshot_path': '', 'recovery_path': str(archive), 'message': 'Snapshot preserved; export has not completed.'}
        self.save_journal(journal)
        try:
            head = self.validate(); self.clean(); self.commit_identity()
            if not retry_before_write and req.get('expected_head') != head: raise ValueError('The repository changed since it was selected. Refresh status and retry the preserved snapshot.')
            target = req.get('target')
            if target not in ('latest', 'baseline', 'checkpoint'): raise ValueError('Choose latest, baseline or checkpoint.')
            for key in ('replace_baseline', 'allow_removed', 'push'):
                if key in req and type(req[key]) is not bool: raise ValueError('Invalid save option.')
            folders = [] if target == 'baseline' else [self.scope('latest')]
            if target == 'baseline':
                old = self.read_manifest(self.scope('baseline'))
                if old and (not req.get('replace_baseline') or req.get('expected_baseline') != digest(old)):
                    raise ValueError('The baseline already exists or changed. Review it and explicitly confirm replacement.')
                folders.append(self.scope('baseline'))
            elif target == 'checkpoint':
                name = req.get('checkpoint')
                if not isinstance(name, str) or not SLUG.fullmatch(name) or name in ('.', '..'): raise ValueError('Choose a short literal checkpoint name.')
                folder = self.scope('checkpoints/' + name)
                if no_links(self.root / folder, False).exists(): raise ValueError('This checkpoint already exists. Choose a new name.')
                folders.append(folder)
            journal['snapshot_path'] = folders[-1]
            expected = {}; changed = []; before_hashes = {}
            for folder in folders:
                old = self.read_manifest(folder)
                # Every file the existing manifest owns: each device file and, for a schema-2 snapshot,
                # the restore-grade artifact it references. Only the device files count as devices.
                old_names = set(); old_devices = set()
                if old:
                    for item in old['files']:
                        name = relpath(item.get('path'))
                        if '/' in name or name == 'manifest.json': raise ValueError('Existing manifest contains an invalid file path.')
                        old_names.add(name); old_devices.add(name)
                        if item.get('restore_artifact'):
                            artifact = relpath(item['restore_artifact'])
                            if '/' in artifact or artifact == 'manifest.json': raise ValueError('Existing manifest contains an invalid file path.')
                            old_names.add(artifact)
                directory = no_links(self.root / folder, False)
                if directory.exists():
                    # Only files: the export owns `<folder>/<name>` entries and never a subdirectory, so a
                    # legacy nested `latest/latest` folder does not block saving into the snapshot around it.
                    entries = list(directory.iterdir()); existing = {p.name for p in entries if not p.is_dir()}
                    if existing - (old_names | {'manifest.json'}): raise ValueError('The destination contains files outside its manager manifest; preserve or move them first.')
                    if not old and entries: raise ValueError('The destination is not an empty manager snapshot folder.')
                removed = old_devices - set(files)
                if removed and not req.get('allow_removed'): raise ValueError('This capture removes previously saved devices. Review the new device scope before allowing removal.')
                if old and content_digest(old) == content_digest(manifest): continue
                for name, raw in files.items(): expected[folder + '/' + name] = raw
                # Removed devices and artifacts the new manifest no longer references leave the folder.
                for name in old_names - set(files): expected[folder + '/' + name] = None
                expected[folder + '/manifest.json'] = (json.dumps(manifest, sort_keys=True, indent=2, ensure_ascii=False) + '\n').encode()
            for name, raw in expected.items():
                path = self.file(name)
                before = path.read_bytes() if path.exists() else None
                if before != raw:
                    changed.append(name); before_hashes[name] = hashlib.sha256(before).hexdigest() if before is not None else None
            if not changed:
                journal.update(status='unchanged', unchanged=True, message='No configuration changes.', commit=head, verified=head in self.known_commits())
                self.save_journal(journal)
                if req.get('push'):
                    if journal['verified']: return self.retry_push(req)
                    try:
                        if self.remote_head() == head: journal.update(pushed=True, message='No configuration changes; already up to date.')
                        else: journal.update(message='No configuration changes; remote synchronization needs attention.')
                    except ValueError: journal.update(message='No configuration changes; remote status is unknown.')
                    self.save_journal(journal)
                return self.result(journal)
            # Record exact bytes before the first write; no rollback/reset can discard owner edits.
            journal.update(parent=head, changed_files=changed, before=before_hashes, expected={p: None if b is None else base64.b64encode(b).decode() for p, b in expected.items()})
            self.save_journal(journal)
            if self.validate() != head: raise ValueError('The repository changed before export.')
            self.clean()
            return self.finish_export(journal, req)
        except ValueError as error:
            journal.update(status='needs_attention', message=str(error), pushed=False); self.save_journal(journal); return self.result(journal)

    def history(self):
        self.validate()
        raw = self.run('log', '-50', '--format=%H%x00%ct%x00%s', '--', self.scope('latest'), self.scope('baseline'), self.scope('checkpoints'), limit=128 * 1024)
        commits = []
        for line in raw.splitlines():
            parts = line.split('\0', 2)
            if len(parts) == 3: commits.append({'commit': parts[0], 'time': int(parts[1]), 'message': parts[2][:500]})
        head = self.run('rev-parse', 'HEAD'); versions = []
        # Every snapshot folder committed anywhere in this checkout (a folder holding manifest.json,
        # whatever its name or depth: Final, Broken/latest, course/lab/reference/solution, the root),
        # each identified by its exact repository path; `connected` marks this lab's own three kinds.
        connected = {self.scope('latest'), self.scope('baseline')}
        checkpoints = self.scope('checkpoints') + '/'
        for path in self.run('ls-tree', '-r', '--name-only', head, limit=MAX_TOTAL).splitlines():
            if path != 'manifest.json' and not path.endswith('/manifest.json'): continue
            folder = path.rsplit('/', 1)[0] if '/' in path else ''
            try: snapshot_folder(folder)
            except ValueError: continue
            here = folder in connected or (folder.startswith(checkpoints) and '/' not in folder[len(checkpoints):])
            # The cap bounds the other folders; this lab's own snapshots are always listed.
            if not here and sum(1 for v in versions if not v['connected']) >= 500: continue
            versions.append({'name': folder, 'path': folder, 'commit': head, 'connected': here})
        versions.sort(key=lambda version: (not version['connected'], version['path']))
        return {'commits': commits, 'versions': versions}

    def allowed_repo_version(self, folder):
        """A snapshot folder anywhere in this checkout: any safe repository folder ('' or '/' is the
        root). Its name decides nothing; the manifest must exist at the commit and pass the integrity
        check. Lets a lab apply a saved state from any folder without first rebinding to it."""
        try: snapshot_folder(folder)
        except ValueError: return False
        return True

    def read_version(self, req):
        self.validate(); commit = req.get('commit'); folder = req.get('path')
        if not isinstance(commit, str) or not HEX.fullmatch(commit) or not isinstance(folder, str) or not self.allowed_repo_version(folder):
            raise ValueError('Select a listed snapshot path and exact commit.')
        folder = snapshot_folder(folder)
        code, _ = self.run('merge-base', '--is-ancestor', commit, 'HEAD', check=False)
        if code: raise ValueError('The selected commit is outside this repository branch history.')
        code, raw = self.run('show', commit + ':' + snapshot_file(folder, 'manifest.json'), check=False, limit=MAX_FILE)
        if code: raise ValueError('This folder holds no saved configuration (manifest.json) at the selected commit.')
        raw = raw.decode('utf8', errors='replace')
        try: manifest = json.loads(raw)
        except Exception: raise ValueError('The saved version manifest is invalid.') from None
        files = {}; total = 0
        if not isinstance(manifest, dict) or not isinstance(manifest.get('files'), list) or len(manifest['files']) > 500: raise ValueError('Invalid saved snapshot manifest.')

        def read_one(name):
            nonlocal total
            name = relpath(name)
            if '/' in name or name == 'manifest.json': raise ValueError('Invalid saved snapshot filename.')
            code, content = self.run('show', commit + ':' + snapshot_file(folder, name), check=False, limit=MAX_FILE)
            total += len(content)
            if code or total > MAX_TOTAL: raise ValueError('The saved snapshot is missing files or exceeds its limit.')
            files[name] = base64.b64encode(content).decode()

        for item in manifest['files']:
            read_one(item.get('path'))
            # Schema 2: the Junos restore-grade artifact travels with the config file.
            if item.get('restore_artifact'):
                read_one(item['restore_artifact'])
        result = {'manifest': manifest, 'files': files}; snapshot(result)
        return {'snapshot': result}

    def compare(self, req):
        journal = self.load_journal(req.get('operation_id'))
        if not journal or not journal.get('commit') or journal.get('binding_revision') != self.binding['revision']:
            raise ValueError('Select saved progress with a recorded commit.')
        if journal.get('unchanged') or not journal.get('changed_files'):
            return {'files': []}
        commit, folder = journal['commit'], journal['snapshot_path']
        after = self.read_version({'commit': commit, 'path': folder})['snapshot']['files']
        parent = self.run('rev-parse', commit + '^')
        code, _ = self.run('cat-file', '-e', parent + ':' + snapshot_file(folder, 'manifest.json'), check=False)
        before = {} if code else self.read_version({'commit': parent, 'path': folder})['snapshot']['files']
        result = []; size = 0
        for name in sorted(set(before) | set(after)):
            if before.get(name) == after.get(name): continue
            old = base64.b64decode(before[name]) if name in before else b''
            new = base64.b64decode(after[name]) if name in after else b''
            size += len(old) + len(new)
            if size > 8 * 1024 * 1024: raise ValueError('This comparison is too large to view inline. Download its saved versions instead.')
            result.append({'name': name, 'status': 'added' if name not in before else 'removed' if name not in after else 'changed',
                           'before': old.decode('utf8', errors='replace'), 'after': new.decode('utf8', errors='replace')})
        return {'files': result}

    def update(self, req):
        head = self.validate(); self.clean(entire=True)
        if req.get('expected_head') != head: raise ValueError('The checkout changed. Refresh repository status before updating.')
        remote = self.remote_head()
        self.run('fetch', '--no-tags', '--no-recurse-submodules', '--no-write-fetch-head', self.binding['push_url'], 'refs/heads/' + self.binding['branch'], timeout=60)
        code, _ = self.run('merge-base', '--is-ancestor', head, remote, check=False)
        if code: raise ValueError('Local and remote history diverged or local commits are pending. Resolve them as the repository owner.')
        if self.validate() != head: raise ValueError('The checkout changed during fetch.')
        self.clean(entire=True); self.run('merge', '--ff-only', remote, timeout=90)
        return {'status': 'updated', 'head': self.validate(), 'message': 'Updated from remote using fast-forward only.'}

    def tool(self, argv, timeout=30, limit=64 * 1024):
        # Before a clone exists the checkout folder is missing; GitHub CLI checks then run from the owner's home.
        return command(argv, self.root if self.root.is_dir() else self.binding['home'], self.env, limit, timeout)

    def prepare_state(self):
        self.control = no_links(self.root / '.git', False)
        if not self.control.is_dir(): raise ValueError('Linked worktrees and bare repositories are not supported.')
        self.state = self.control / 'clab-manager'; no_links(self.state, False)
        self.state.mkdir(mode=0o700, exist_ok=True)
        if os.name == 'posix':
            if self.state.stat().st_uid != os.geteuid(): raise ValueError('Git progress storage must belong to the registered owner.')
            self.state.chmod(0o700)

    def browse(self):
        """The committed tree at HEAD: what saves have put in the repository, never the working files."""
        head = self.validate()
        code, raw = self.tool([self.git, '-c', 'color.ui=false', 'ls-tree', '-r', '-l', '-z', head], timeout=60, limit=MAX_JSON)
        if code: raise ValueError('Git could not list the repository contents. Check the repository as its registered owner.')
        files = []; truncated = False
        for line in filter(None, raw.decode('utf8', errors='replace').split('\0')):
            meta, _, path = line.partition('\t')
            fields = meta.split()
            if len(fields) != 4 or fields[1] != 'blob' or not path: continue
            if len(files) >= MAX_TREE: truncated = True; break
            files.append({'path': path, 'size': int(fields[3]) if fields[3].isdigit() else 0})
        saved = {}
        for name in ('latest', 'baseline', 'checkpoints'):
            code, raw = self.tool([self.git, '-c', 'color.ui=false', 'log', '-1', '--format=%ct', head, '--', self.scope(name)])
            value = raw.decode('utf8', errors='replace').strip()
            saved[name] = int(value) if not code and value.isdigit() else None
        folders = [{'id': b['id'], 'label': b['label'], 'prefix': b['prefix']} for b in self.binding.get('_siblings', [descriptor(self.binding)])]
        return {'repository': self.descriptor(), 'head': head, 'files': files, 'truncated': truncated, 'saved': saved, 'folders': folders}

    def ensure_identity(self, url):
        if not any(self.run('var', role, check=False)[0] for role in ('GIT_AUTHOR_IDENT', 'GIT_COMMITTER_IDENT')): return
        name = email = ''
        host = urlsplit(url).hostname
        if host and host.lower() == 'github.com' and Path(self.gh).exists():
            code, raw = self.tool([self.gh, 'api', 'user', '--jq', '[(.id|tostring), .login, (.name // "")] | @tsv'])
            # Only the line ending is trimmed: an account without a display name ends the line with an empty
            # third field, and strip() would eat that tab and lose the field.
            fields = raw.decode('utf8', errors='replace').rstrip('\r\n').split('\t') if not code else []
            if len(fields) == 3 and re.fullmatch(r'[0-9]+', fields[0]) and GITHUB_PART.fullmatch(fields[1]):
                name = (fields[2].strip() or fields[1])[:200]
                email = fields[0] + '+' + fields[1] + '@users.noreply.github.com'
        if not name or not email or any(ord(c) < 32 or ord(c) == 127 for c in name):
            raise ValueError('This VM account has no Git commit identity yet. Run guided Git setup on the VM once, or set user.name and user.email inside the checkout as that account.')
        self.run('config', '--local', 'user.name', name); self.run('config', '--local', 'user.email', email)
        self.commit_identity()

    def check_permission(self, url):
        host = urlsplit(url).hostname
        if not host or host.lower() != 'github.com': return
        if not Path(self.gh).exists():
            raise ValueError('GitHub CLI is not installed on the VM. Install gh and sign in as the VM account (gh auth login), or run guided Git setup on the VM.')
        code, _ = self.tool([self.gh, 'auth', 'status', '--hostname', 'github.com'])
        if code: raise ValueError('The VM account is not signed in to GitHub. On the VM, run gh auth login --hostname github.com --git-protocol https --web as that account, then try again.')
        code, _ = self.tool([self.gh, 'auth', 'setup-git', '--hostname', 'github.com'])
        if code: raise ValueError('GitHub CLI could not configure the Git credential helper for the VM account.')
        slug = urlsplit(url).path.strip('/').removesuffix('.git')
        code, raw = self.tool([self.gh, 'api', 'repos/' + slug, '--jq', '.permissions.push'])
        if code or raw.strip() != b'true':
            raise ValueError('The GitHub account signed in on the VM cannot push to ' + slug + '. Check the repository name, or grant that account write access on GitHub.')

    def register(self, previous=None):
        """Validate this checkout exactly as the terminal wizard does before it is registered.

        Runs as the owner. Fills branch, push URL, anchor and revision into the binding it returns."""
        binding = self.binding
        if os.name == 'posix' and (self.root.stat().st_uid != os.geteuid() or self.control.stat().st_uid != os.geteuid()):
            raise ValueError('The checkout and .git must be owned by the registered account.')
        binding['branch'] = self.run('symbolic-ref', '--quiet', '--short', 'HEAD')
        self.run('check-ref-format', '--branch', binding['branch'])
        urls = self.run('remote', 'get-url', '--push', '--all', binding['remote']).splitlines()
        if len(urls) != 1: raise ValueError('Configure exactly one HTTPS push URL.')
        binding['push_url'] = checked_url(urls[0], self.allow_local)
        binding['anchor'] = self.validate(); self.clean(); self.commit_identity()
        if self.remote_head() != binding['anchor']:
            raise ValueError('Before linking, synchronize the current branch with its existing remote branch using your ordinary Git login.')
        self.check_push_access()
        return self.registration(previous)

    def connect(self, url):
        """Clone (or adopt) the checkout for a pasted URL as the owner, then validate it for registration."""
        path = self.root
        if not (path / '.git').is_dir():
            if path.exists() and (not path.is_dir() or any(path.iterdir())):
                raise ValueError('The VM folder ' + str(path) + ' contains files but is not a Git checkout. Choose another repository name or clean that folder on the VM; nothing was overwritten.')
            self.check_permission(url)
            no_links(path.parent, False); path.parent.mkdir(parents=True, exist_ok=True)
            code, _ = command([self.git, '-c', 'color.ui=false', 'clone', '--', url, str(path)], str(path.parent), self.env, MAX_JSON, 300)
            if code: raise ValueError('Cloning failed. Check the URL and that the VM account is signed in to GitHub with access to this repository (gh auth login).')
            self.root = no_links(path)
        else:
            self.check_permission(url)
        self.prepare_state()
        actual = checked_url(self.run('remote', 'get-url', '--push', self.binding['remote']), self.allow_local)
        if not same_repository(actual, url):
            raise ValueError('The VM folder ' + str(path) + ' already holds a different repository (' + actual + '). Choose another repository name.')
        code, _ = self.run('rev-parse', '--verify', 'HEAD', check=False)
        if code: raise ValueError('This repository has no commits yet. Add a README on GitHub first, then connect it.')
        self.ensure_identity(url)
        return self.register(None)

    def other_scope(self, source, name): return '/'.join(p for p in (source, name) if p)

    def move(self, req):
        """Move every saved folder from another registered prefix of this checkout into this one, as one commit."""
        operation = req.get('operation_id'); self.journal_path(operation)
        source = relpath(req.get('source_prefix'), empty=True)
        if source == self.prefix: raise ValueError('Choose a different folder for this lab.')
        if not isinstance(req.get('message'), str) or not req['message'].strip(): raise ValueError('A move needs a commit note.')
        request_digest = digest({k: v for k, v in req.items() if k not in ('push', 'expected_head')})
        journal = self.load_journal(operation)
        if journal:
            if journal.get('request_digest') != request_digest: raise ValueError('This operation ID already belongs to a different action.')
            if journal.get('commit'):
                if not journal.get('verified') and journal.get('expected') and journal.get('parent'):
                    try:
                        expected = {p: None if b is None else base64.b64decode(b) for p, b in journal['expected'].items()}
                        self.verify_tree(journal['commit'], expected, journal['changed_files'], journal['parent'])
                        if self.validate() != journal['commit']: raise ValueError('The checkout moved after this change. Review its commit before retrying.')
                        self.clean(); journal.update(status='committed', verified=True, message='Verified the move commit; not pushed.'); self.save_journal(journal)
                    except ValueError as error:
                        journal.update(status='needs_attention', message=str(error)); self.save_journal(journal); return self.result(journal)
                if req.get('push') and journal.get('verified') and not journal.get('pushed'): return self.retry_push(req)
                return self.result(journal)
            if journal.get('parent'):
                found = self.run('log', '-30', '--format=%H', '--fixed-strings', '--grep=Manager-Operation: ' + operation).splitlines()
                if len(found) == 1:
                    expected = {p: None if b is None else base64.b64decode(b) for p, b in journal['expected'].items()}
                    try: self.verify_tree(found[0], expected, journal['changed_files'], journal['parent'])
                    except ValueError as error:
                        journal.update(status='needs_attention', commit=found[0], verified=False, message=str(error)); self.save_journal(journal); return self.result(journal)
                    journal.update(status='committed', commit=found[0], verified=True, message='Recovered the move commit.'); self.save_journal(journal)
                    return self.retry_push(req) if req.get('push') else self.result(journal)
                try: return self.finish_export(journal, req)
                except ValueError as error:
                    journal.update(status='needs_attention', message=str(error)); self.save_journal(journal); return self.result(journal)
        journal = {'operation_id': operation, 'request_digest': request_digest, 'binding_revision': self.binding['revision'],
                   'status': 'needs_attention', 'commit': None, 'verified': False, 'changed_files': [], 'pushed': False,
                   'snapshot_path': self.scope('latest'), 'message': 'Move prepared; nothing has been committed.'}
        self.save_journal(journal)
        try:
            head = self.validate(); self.clean(); self.commit_identity()
            if req.get('expected_head') != head: raise ValueError('The repository changed since it was selected. Refresh status and retry the move.')
            old_folders = [self.other_scope(source, name) for name in ('latest', 'baseline', 'checkpoints')]
            if self.run('status', '--porcelain=v1', '--untracked-files=all', '--', *old_folders):
                raise ValueError('The current folder has unsaved edits. Resolve them as the repository owner before moving.')
            listed = self.run('ls-tree', '-r', '--name-only', '-z', head, '--', *old_folders, limit=MAX_JSON)
            paths = [p for p in listed.split('\0') if p]
            if not paths: raise ValueError('There are no saved files to move yet.')
            if len(paths) > MAX_MOVE: raise ValueError('Too many saved files to move in one step. Move the folder with Git on the VM instead.')
            expected = {}; before = {}; total = 0
            for old_path in paths:
                relative = old_path[len(source) + 1:] if source else old_path
                new_path = self.scope(relative)
                if new_path in expected or relpath(new_path) != new_path: raise ValueError('The move produced an unsafe destination path.')
                raw = self.file(old_path).read_bytes(); total += len(raw)
                if len(raw) > MAX_FILE or total > MAX_TOTAL: raise ValueError('The saved folders are too large to move in one step. Move them with Git on the VM instead.')
                if self.file(new_path).exists(): raise ValueError('The new folder already contains saved files. Choose an empty folder.')
                expected[old_path] = None; before[old_path] = hashlib.sha256(raw).hexdigest()
                expected[new_path] = raw; before[new_path] = None
            changed = list(expected)
            journal.update(parent=head, changed_files=changed, before=before, expected={p: None if b is None else base64.b64encode(b).decode() for p, b in expected.items()})
            self.save_journal(journal)
            if self.validate() != head: raise ValueError('The repository changed before the move.')
            result = self.finish_export(journal, req)
            for folder in sorted({str(PurePosixPath(p).parent) for p in paths}, key=len, reverse=True):
                for candidate in (folder, *[str(x) for x in PurePosixPath(folder).parents]):
                    if candidate in ('', '.') or (source and not (candidate == source or candidate.startswith(source + '/'))): break
                    try: os.rmdir(self.root / candidate)
                    except OSError: break
            return result
        except ValueError as error:
            journal.update(status='needs_attention', message=str(error), pushed=False); self.save_journal(journal); return self.result(journal)

    def dispatch(self, req):
        if req.get('binding_id') != self.binding['id'] or req.get('revision') != self.binding['revision']:
            raise ValueError('The repository binding changed. Select it again.')
        with self.lock():
            mode = req.get('mode')
            if mode == 'status': return self.status()
            if mode == 'publish': return self.publish(req)
            if mode == 'push': return self.retry_push(req)
            if mode == 'history': return self.history()
            if mode == 'read-version': return self.read_version(req)
            if mode == 'compare': return self.compare(req)
            if mode == 'update': return self.update(req)
            if mode == 'browse': return self.browse()
            if mode == 'move': return self.move(req)
            raise ValueError('Unsupported Git operation.')


def registry_owner(config, requested=None):
    """The VM account that owns new clones: the single registered owner, else the engineer account."""
    owners = sorted({b['owner'] for b in config['repositories']})
    if requested is not None:
        if not isinstance(requested, str) or requested not in owners: raise ValueError('Choose a VM account that already owns a registered repository.')
        return requested
    if len(owners) == 1: return owners[0]
    if not owners and ENGINEER.exists():
        root_file(ENGINEER)
        value = json.loads(ENGINEER.read_text(encoding='utf8'))
        owner = value.get('owner') if isinstance(value, dict) else None
        if isinstance(owner, str) and owner: return owner
    if owners: raise ValueError('Several VM accounts own registered repositories. Run guided Git setup on the VM as the intended account instead.')
    raise ValueError('No VM account is set up for Git yet. Run guided Git setup on the VM once (bash deploy/setup-git.sh).')


def account_lookup(owner):
    import pwd
    return pwd.getpwnam(owner)


def account_binding(owner, path, remote, prefix, label, lookup=None):
    account = (lookup or account_lookup)(owner)
    if account.pw_uid == 0 or owner == 'clab-discovery': raise ValueError('Choose the ordinary VM account that owns and authenticates this Git checkout.')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,99}', remote): raise ValueError('Use a literal remote name.')
    if not isinstance(label, str) or not label or len(label) > 100 or any(ord(c) < 32 for c in label): raise ValueError('Use a short repository label.')
    return {'id': uuid.uuid4().hex, 'label': label, 'owner': owner, 'uid': account.pw_uid, 'gid': account.pw_gid, 'home': account.pw_dir,
            'path': str(path), 'remote': remote, 'prefix': prefix, 'branch': '', 'push_url': '', 'revision': ''}


def check_overlap(config, path, prefix, ignore=None):
    for b in config['repositories']:
        if b is ignore or b['path'] != str(path): continue
        if overlapping(prefix, b['prefix']):
            raise ValueError('Lab folders in one repository cannot overlap: ' + (b['prefix'] or 'the repository root') + ' is already a lab folder. Choose a folder beside it.')


def plan_prefix(config, req, lookup=None):
    """Root: describe a sibling registration of an existing checkout; nothing has run as the owner yet.

    With retire, the source registration is about to be replaced by the new folder, so it does not
    count as an overlap: a lab registered at the repository root can move into a subfolder."""
    source = next((b for b in config['repositories'] if b['id'] == req.get('binding_id')), None)
    if not source or source['revision'] != req.get('revision'): raise ValueError('The repository binding changed. Select it again.')
    prefix = relpath(req.get('prefix'), empty=True)
    if prefix == source['prefix']: return source, None
    existing = next((b for b in config['repositories'] if b['path'] == source['path'] and b['prefix'] == prefix), None)
    if existing: return existing, None
    # A registration that already exists (a legacy `x/latest` one included) stays selectable and
    # repairable; only a new lab folder must not be a snapshot folder name.
    base_prefix(prefix)
    check_overlap(config, source['path'], prefix, ignore=source if req.get('retire') is True else None)
    label = req.get('label') or (Path(source['path']).name + (' / ' + prefix if prefix else ''))
    binding = account_binding(source['owner'], source['path'], source['remote'], prefix, label, lookup)
    return None, binding


def plan_connect(config, req, lookup=None):
    """Root: resolve owner, checkout folder and registration for a pasted clone URL."""
    url = clone_url(req.get('url')); prefix = relpath(req.get('prefix'), empty=True)
    owner = registry_owner(config, req.get('owner'))
    known = [b for b in config['repositories'] if b['owner'] == owner and same_repository(b['push_url'], url)]
    if known:
        path = known[0]['path']; remote = known[0]['remote']
        existing = next((b for b in known if b['prefix'] == prefix), None)
        if existing: return existing, None, url
        base_prefix(prefix)
    else:
        base_prefix(prefix)
        path = str(Path((lookup or account_lookup)(owner).pw_dir) / 'labs' / repository_name(url)); remote = 'origin'
        if any(b['path'] == path for b in config['repositories']):
            raise ValueError('The VM folder for this repository name already holds another registered repository. Choose a repository with a different name.')
    check_overlap(config, path, prefix)
    label = repository_name(url) + (' / ' + prefix if prefix else '')
    binding = account_binding(owner, path, remote, prefix, label, lookup)
    binding['_pending'] = True
    return None, binding, url


def run_as_owner(binding, work):
    """Fork: the child drops privileges permanently, runs Git as the owner and reports one JSON result."""
    read_fd, write_fd = os.pipe(); pid = os.fork()
    if pid == 0:
        os.close(read_fd)
        try:
            drop_owner(binding)
            result = {'binding': work()}
        except ValueError as error: result = {'error': str(error)}
        except Exception: result = {'error': "Could not prepare the repository as its owner. Check checkout permissions and the owner's HTTPS Git login."}
        with os.fdopen(write_fd, 'w') as stream: json.dump(result, stream)
        os._exit(0)
    os.close(write_fd)
    with os.fdopen(read_fd) as stream: raw = stream.read(65537)
    os.waitpid(pid, 0)
    if len(raw) > 65536: raise ValueError('Unexpected registration response.')
    result = json.loads(raw)
    if 'error' in result: raise ValueError(result['error'])
    return result['binding']


def store_binding(config, binding):
    binding = {k: v for k, v in binding.items() if not k.startswith('_')}
    config['repositories'] = [b for b in config['repositories'] if b['id'] != binding['id']] + [binding]
    atomic_json(REGISTRY, config)
    return descriptor(binding)


def register_prefix(config, req, run=run_as_owner, lookup=None):
    existing, binding = plan_prefix(config, req, lookup)
    if existing: result = descriptor(existing)
    else:
        binding = run(binding, lambda: GitRepository(binding).register(None))
        binding = {k: v for k, v in binding.items() if not k.startswith('_')}
        config['repositories'] = [b for b in config['repositories'] if b['id'] != binding['id']] + [binding]
        result = descriptor(binding)
    if req.get('retire') is True and result['id'] != req.get('binding_id'):
        # The lab moved away: its previous folder registration is retired so it cannot block or confuse later choices.
        config['repositories'] = [b for b in config['repositories'] if b['id'] != req.get('binding_id')]
    if not existing or req.get('retire') is True: atomic_json(REGISTRY, config)
    return result


def connect(config, req, run=run_as_owner, lookup=None):
    existing, binding, url = plan_connect(config, req, lookup)
    if existing: return descriptor(existing)
    return store_binding(config, run(binding, lambda: GitRepository(binding).connect(url)))


def root_file(path):
    no_links(path)
    value = path.stat()
    if not stat.S_ISREG(value.st_mode) or value.st_uid != 0 or value.st_mode & 0o022:
        raise ValueError('The Git helper and bindings must be root-owned and not writable by other users.')


def load_registry():
    root_file(REGISTRY)
    if REGISTRY.stat().st_size > MAX_FILE: raise ValueError('Git repository registry is too large.')
    value = json.loads(REGISTRY.read_text(encoding='utf8'))
    if not isinstance(value.get('repositories'), list): raise ValueError('Invalid Git repository registry.')
    return value


def drop_owner(binding):
    import pwd
    account = pwd.getpwnam(binding['owner'])
    if account.pw_uid == 0 or account.pw_name == 'clab-discovery' or account.pw_uid != binding['uid'] or account.pw_gid != binding['gid'] or account.pw_dir != binding['home']:
        raise ValueError('The registered Git owner changed or is not an ordinary VM account.')
    os.initgroups(account.pw_name, account.pw_gid); os.setgid(account.pw_gid); os.setuid(account.pw_uid)
    if os.geteuid() == 0 or os.getegid() != account.pw_gid: raise ValueError('Could not drop Git worker privileges.')
    os.umask(0o077); os.chdir(account.pw_dir)


def main():
    try:
        if len(sys.argv) != 1 or os.name != 'posix' or os.geteuid() != 0: raise ValueError('Invoke the installed Git helper through the discovery gateway.')
        root_file(Path(GIT)); root_file(Path(__file__))
        raw = sys.stdin.buffer.read(MAX_JSON + 1)
        if len(raw) > MAX_JSON: raise ValueError('Git request exceeds 24 MiB.')
        req = json.loads(raw)
        if not isinstance(req, dict): raise ValueError('A structured Git request is required.')
        config = load_registry()
        if req.get('mode') == 'list':
            result = {'protocol': PROTOCOL, 'version': VERSION, 'repositories': [descriptor(b) for b in config['repositories']]}
        elif req.get('mode') == 'register-prefix':
            result = register_prefix(config, req)
        elif req.get('mode') == 'connect':
            result = connect(config, req)
        else:
            matches = [b for b in config['repositories'] if b['id'] == req.get('binding_id')]
            if len(matches) != 1: raise ValueError('Select a registered Git repository.')
            binding = dict(matches[0])
            binding['_approved_revisions'] = [b['revision'] for b in config['repositories'] if b['path'] == binding['path'] and b['push_url'] == binding['push_url'] and b['branch'] == binding['branch'] and b['uid'] == binding['uid']]
            binding['_siblings'] = [{'id': b['id'], 'label': b['label'], 'prefix': b['prefix']} for b in config['repositories'] if b['path'] == binding['path'] and b['uid'] == binding['uid']]
            drop_owner(binding)
            result = GitRepository(binding).dispatch(req)
        output = json.dumps({'result': result}, ensure_ascii=False)
        if len(output.encode('utf8')) > MAX_JSON: raise ValueError('The Git response is too large to transfer. Select a smaller snapshot.')
        print(output)
    except ValueError as error:
        print(json.dumps({'error': str(error)})); sys.exit(1)
    except Exception:
        print(json.dumps({'error': 'The Git helper could not finish. Check installation and repository permissions as its owner.'})); sys.exit(1)


if __name__ == '__main__': main()
