"""The VM Git helper, answered from memory, as it behaves after the Git save and load redesign (DESIGN.md 2.3, H1 to H7).

`FakeGit` replaces `app.git_progress.remote_git`: it takes (host, request, stopping) and answers like
`clab-backup-ui/app/host_git.py`, or raises ValueError with the helper's own sentence. Several checkouts (repositories)
live side by side; every checkout keeps its commits, the tree of each, the commits the fake remote holds and the helper's
journals, so a push carries every earlier waiting commit exactly like `GitRepository.push` / `mark_synced`.

Where the real helper has a pure function the fake imports it (`snapshot`, `content_digest`, `colliding`, `base_prefix`,
`relpath`, `clone_url`, `same_repository`), so a rule cannot drift from the helper.
"""
import base64
import hashlib
import json
import re
import threading
import time

from app import __version__
from app.git_progress import PROTOCOL
from app.host_git import (RESERVED, SLUG, base_prefix, clone_url, collision_message, colliding, content_digest, digest, relpath,
                          repository_name, same_repository, snapshot, snapshot_file, snapshot_folder)

OPERATION = re.compile(r'[0-9a-f]{32}\Z')
MAX_TREE = 4000
MAX_DIRS = 20000
PROBLEMS = {
    'operation': 'Finish the existing Git operation before saving lab progress.',
    'staged': ('The repository already has staged changes. If an earlier manager save failed, fix its reported issue and retry that '
               'original save: Retry commits automatically. For unrelated staged work, resolve it as the repository owner first.'),
    'edits': 'The repository has unsaved edits in the selected scope. Resolve them before continuing.',
    'diverged': 'The remote branch advanced or diverged. Resolve the branch before pushing; no force push was attempted.',
    'permission': 'The GitHub account signed in on the VM cannot push to the repository. Check the repository name, or grant that account write access on GitHub.',
}
PUSH_FAILED = 'The commit is saved on the VM, but push failed. Check authentication, branch permissions or remote changes, then retry.'
REMOTE_UNAVAILABLE = "The remote branch is unavailable. Check connectivity and the owner's noninteractive HTTPS Git login."
RESULT_KEYS = ('status', 'commit', 'changed_files', 'message', 'pushed', 'snapshot_path', 'synced_operations')


def sha1(*parts):
    return hashlib.sha1('\0'.join(map(str, parts)).encode()).hexdigest()


class Checkout:
    """One repository on the VM: its commits (newest first), the tree of each, what the fake remote holds, the journals."""

    def __init__(self, name, url, path, owner='clabllm', branch='main'):
        self.name, self.url, self.path, self.owner, self.branch = name, url, path, owner, branch
        self.commits = []        # newest first: {commit, time, message, operation_id, files, tree, registration}
        self.files = {}          # the tree at HEAD
        self.remote = set()      # commit ids the remote branch holds
        self.journals = {}       # operation id -> journal
        self.registrations = []
        self.counter = 0

    @property
    def head(self):
        return self.commits[0]['commit'] if self.commits else ''

    def add_commit(self, message, changes, operation_id='', pushed=False, age=0, registration=''):
        """Apply `changes` ({path: bytes | None}) on top of HEAD as one commit; returns its id."""
        for path, raw in changes.items():
            if raw is None:
                self.files.pop(path, None)
            else:
                self.files[path] = raw
        self.counter += 1
        commit = sha1(self.name, self.head, message, self.counter)
        self.commits.insert(0, dict(commit=commit, time=int(time.time() - age), message=message, operation_id=operation_id,
                                    files=list(changes), tree=dict(self.files), registration=registration))
        if pushed:
            self.remote.add(commit)
            self.remote.update(c['commit'] for c in self.commits[1:])   # a pushed commit carries everything below it
        return commit

    def commit(self, ref):
        return next((c for c in self.commits if c['commit'] == ref), None)

    def unpushed(self):
        """Commits the remote lacks, newest first."""
        out = []
        for c in self.commits:
            if c['commit'] in self.remote:
                break
            out.append(c)
        return out

    def known_commits(self):
        return {j['commit'] for j in self.journals.values() if j.get('commit') and j.get('verified')}

    def scope(self, reg, name):
        return '/'.join(p for p in (reg['prefix'], name) if p)

    def manifest_at(self, tree, folder):
        raw = tree.get(snapshot_file(folder, 'manifest.json'))
        return json.loads(raw) if raw is not None else None


def descriptor(reg):
    return {k: reg[k] for k in ('id', 'label', 'owner', 'path', 'remote', 'push_url', 'branch', 'prefix', 'revision')}


def summary_of(raw):
    """H3: the bounded summary of one manifest, or None when it cannot be read (the real helper's null)."""
    try:
        manifest = json.loads(raw)
        if not isinstance(manifest, dict) or manifest.get('schema') not in (1, 2) or not isinstance(manifest.get('files'), list):
            return None

        def text(value):
            if value is None:
                return ''
            if not isinstance(value, str) or any(ord(c) < 32 or ord(c) == 127 for c in value):
                raise ValueError
            return value[:200]
        devices = []
        for item in manifest['files']:
            if not isinstance(item, dict):
                return None
            if item.get('node'):
                devices.append(dict(node=text(item['node']), short_name=text(item.get('short_name')), platform=text(item.get('platform')),
                                    restore=bool(item.get('restore_artifact'))))
        return dict(lab_id=text(manifest.get('lab_id')), lab_name=text(manifest.get('lab_name')), kind=text(manifest.get('kind')),
                    captured_at=text(manifest.get('captured_at') or manifest.get('generated_at')),
                    topology_digest=text(manifest.get('topology_digest')), devices=devices[:500])
    except (ValueError, TypeError):
        return None


class FakeGit:
    def __init__(self, control):
        self.control = control
        self.checkouts = {}
        self.remotes = {}            # normalized url -> {'empty': bool} for repositories reachable only by address
        self.lock = threading.RLock()

    # --- building the fixture -----------------------------------------------------------------------------------

    def add_checkout(self, name, url, **kw):
        checkout = self.checkouts[name] = Checkout(name, url, kw.pop('path', f'/home/clabllm/labs/{name}'), **kw)
        return checkout

    def register(self, checkout, prefix, id=None, label=None):
        reg = dict(id=id or 'reg-' + hashlib.sha1((checkout.path + '|' + prefix).encode()).hexdigest()[:8],
                   label=label or (checkout.name + (' / ' + prefix if prefix else '')), owner=checkout.owner, path=checkout.path,
                   remote='origin', push_url=checkout.url, branch=checkout.branch, prefix=prefix,
                   revision='rev-' + hashlib.sha1((checkout.path + '|' + prefix).encode()).hexdigest()[:6])
        checkout.registrations.append(reg)
        return reg

    def remote_only(self, url, empty):
        self.remotes[self.key(url)] = {'empty': empty}

    @staticmethod
    def key(url):
        return url.rstrip('/').removesuffix('.git').lower()

    def find(self, request):
        for checkout in self.checkouts.values():
            for reg in checkout.registrations:
                if reg['id'] == request.get('binding_id'):
                    if reg['revision'] != request.get('revision'):
                        break
                    return checkout, reg
        raise ValueError('The repository binding changed. Select it again.')

    def registrations(self):
        regs = [r for c in self.checkouts.values() for r in c.registrations]
        first = self.control.get('list_first')
        return sorted(regs, key=lambda r: 0 if first and r['path'].rsplit('/', 1)[-1] == first else 1)

    # --- the gateway --------------------------------------------------------------------------------------------

    def __call__(self, host, request, stopping=None):
        if self.control.get('vm_unreachable'):
            raise ConnectionError('fixture: the VM Git helper is switched off')
        mode = request.get('mode')
        with self.lock:
            if mode == 'list':
                regs = [] if self.control.get('no_repositories') else self.registrations()
                return {'protocol': PROTOCOL, 'version': __version__, 'repositories': [descriptor(r) for r in regs]}
            if mode == 'connect':
                return self.connect(request)
            checkout, reg = self.find(request)
            if mode == 'register-prefix':
                return self.register_prefix(checkout, reg, request)
            handler = {'status': self.status, 'publish': self.publish, 'push': self.retry_push, 'history': self.history,
                       'read-version': self.read_version, 'compare': self.compare, 'update': self.update, 'browse': self.browse,
                       'move': self.move}.get(mode)
            if not handler:
                raise ValueError('Unsupported Git operation.')
            return handler(checkout, reg, request)

    # --- the checkout's own state (the problems a status can answer) --------------------------------------------

    def problem(self, checkout):
        value = self.control.get('status_problem', checkout.name)
        if not value:
            return ''
        return PROBLEMS.get(value, str(value))

    def guard(self, checkout):
        """validate() then clean(): the sentences the helper raises before it reads or writes."""
        text = self.problem(checkout)
        if text:
            raise ValueError(text)
        return checkout.head

    def remote_head(self, checkout):
        if self.control.get('remote_unreachable', checkout.name):
            raise ValueError(REMOTE_UNAVAILABLE)
        return next((c['commit'] for c in checkout.commits if c['commit'] in checkout.remote), '')

    # --- modes ----------------------------------------------------------------------------------------------------

    def status(self, checkout, reg, request):
        result = {'repository': descriptor(reg), 'head': checkout.head, 'ready': False, 'problem': '', 'baseline_revision': '', 'latest_manifest': None}
        text = self.problem(checkout)
        if text:
            result['problem'] = text
            return result
        try:
            latest = checkout.manifest_at(checkout.files, checkout.scope(reg, 'latest'))
            baseline = checkout.manifest_at(checkout.files, checkout.scope(reg, 'baseline'))
        except ValueError:
            result['problem'] = 'Existing snapshot manifest is invalid.'
            return result
        result.update(latest_manifest=latest, baseline_revision=digest(baseline) if baseline else '', ready=True)
        return result

    def browse(self, checkout, reg, request):
        self.guard(checkout)
        paths = sorted(checkout.files)
        files = [dict(path=p, size=len(checkout.files[p])) for p in paths[:MAX_TREE]]
        dirs = set()
        for path in paths:
            parts = path.split('/')[:-1]
            dirs.update('/'.join(parts[:n]) for n in range(1, len(parts) + 1))
        saved = {}
        for name in RESERVED:
            scope = checkout.scope(reg, name)
            times = [c['time'] for c in checkout.commits if any(f.startswith(scope + '/') for f in c['files'])]
            saved[name] = max(times) if times else None
        return {'repository': descriptor(reg), 'head': checkout.head, 'files': files, 'truncated': len(paths) > MAX_TREE, 'saved': saved,
                'folders': [dict(id=r['id'], label=r['label'], prefix=r['prefix']) for r in checkout.registrations],
                'dirs': sorted(dirs)[:MAX_DIRS], 'dirs_truncated': len(dirs) > MAX_DIRS}

    def history(self, checkout, reg, request):
        self.guard(checkout)
        scopes = tuple(checkout.scope(reg, n) + '/' for n in RESERVED)
        commits = [dict(commit=c['commit'], time=c['time'], message=c['message'].splitlines()[0][:500] if c['message'] else '')
                   for c in checkout.commits if any(f.startswith(scopes) for f in c['files'])][:50]
        connected = {checkout.scope(reg, 'latest'), checkout.scope(reg, 'baseline')}
        checkpoints = checkout.scope(reg, 'checkpoints') + '/'
        unreadable = self.control.get('unreadable_states') or []
        versions = []
        for path in sorted(checkout.files):
            if path != 'manifest.json' and not path.endswith('/manifest.json'):
                continue
            folder = path.rsplit('/', 1)[0] if '/' in path else ''
            try:
                snapshot_folder(folder)
            except ValueError:
                continue
            here = folder in connected or (folder.startswith(checkpoints) and '/' not in folder[len(checkpoints):])
            if not here and sum(1 for v in versions if not v['connected']) >= 500:
                continue
            versions.append(dict(name=folder, path=folder, commit=checkout.head, connected=here,
                                 summary=None if folder in unreadable else summary_of(checkout.files[path])))
        versions.sort(key=lambda v: (not v['connected'], v['path']))
        return {'head': checkout.head, 'commits': commits, 'versions': versions}

    def read_version(self, checkout, reg, request):
        self.guard(checkout)
        commit, folder = request.get('commit'), request.get('path')
        if not isinstance(commit, str) or not re.fullmatch(r'[0-9a-f]{40}', commit) or not isinstance(folder, str):
            raise ValueError('Select a listed snapshot path and exact commit.')
        folder = snapshot_folder(folder)
        found = checkout.commit(commit)
        if not found:
            raise ValueError('The selected commit is outside this repository branch history.')
        raw = found['tree'].get(snapshot_file(folder, 'manifest.json'))
        if raw is None:
            raise ValueError('This folder holds no saved configuration (manifest.json) at the selected commit.')
        try:
            manifest = json.loads(raw)
        except ValueError:
            raise ValueError('The saved version manifest is invalid.') from None
        if not isinstance(manifest, dict) or not isinstance(manifest.get('files'), list) or len(manifest['files']) > 500:
            raise ValueError('Invalid saved snapshot manifest.')
        files = {}
        for item in manifest['files']:
            for key in ('path', 'restore_artifact'):
                name = item.get(key) if isinstance(item, dict) else None
                if name:
                    blob = found['tree'].get(snapshot_file(folder, relpath(name)))
                    if blob is None:
                        raise ValueError('The saved snapshot is missing files or exceeds its limit.')
                    files[name] = base64.b64encode(blob).decode()
        return {'snapshot': {'manifest': manifest, 'files': files}}

    def compare(self, checkout, reg, request):
        journal = checkout.journals.get(request.get('operation_id'))
        if not journal or not journal.get('commit') or journal.get('revision') != reg['revision']:
            raise ValueError('Select saved progress with a recorded commit.')
        outgoing = None if self.control.get('remote_unreachable', checkout.name) else [
            dict(commit=c['commit'], operation_id=c['operation_id'], subject=c['message'].splitlines()[0][:200] if c['message'] else '', files=list(c['files']))
            for c in checkout.unpushed()]
        if journal.get('unchanged') or not journal.get('changed_files'):
            return {'files': [], 'outgoing': outgoing}
        found = checkout.commit(journal['commit'])
        index = checkout.commits.index(found)
        parent = checkout.commits[index + 1] if index + 1 < len(checkout.commits) else None
        folder = journal['snapshot_path']

        def read(tree):
            raw = tree.get(snapshot_file(folder, 'manifest.json'))
            if raw is None:
                return {}
            out = {}
            for item in json.loads(raw)['files']:
                for key in ('path', 'restore_artifact'):
                    if item.get(key) and snapshot_file(folder, item[key]) in tree:
                        out[item[key]] = tree[snapshot_file(folder, item[key])]
            return out
        after, before = read(found['tree']), read(parent['tree']) if parent else {}
        rows = []
        for name in sorted(set(before) | set(after)):
            if before.get(name) == after.get(name):
                continue
            rows.append({'name': name, 'status': 'added' if name not in before else 'removed' if name not in after else 'changed',
                         'before': before.get(name, b'').decode('utf8', errors='replace'), 'after': after.get(name, b'').decode('utf8', errors='replace')})
        return {'files': rows, 'outgoing': outgoing}

    def update(self, checkout, reg, request):
        head = self.guard(checkout)
        if request.get('expected_head') != head:
            raise ValueError('The checkout changed. Refresh repository status before updating.')
        self.remote_head(checkout)
        if checkout.unpushed():
            raise ValueError('Local and remote history diverged or local commits are pending. Resolve them as the repository owner.')
        if self.control.get('remote_ahead', checkout.name):
            checkout.add_commit('Update from the instructor', {'README.md': checkout.files.get('README.md', b'') + b'Updated online.\n'}, pushed=True)
            self.control.set(**{k: None for k in ('remote_ahead', 'remote_ahead@' + checkout.name)})
        return {'status': 'updated', 'head': checkout.head, 'message': 'Updated from remote using fast-forward only.'}

    # --- publish and push -----------------------------------------------------------------------------------------

    @staticmethod
    def result(journal):
        return {key: journal.get(key) for key in RESULT_KEYS}

    def publish(self, checkout, reg, req):
        operation = req.get('operation_id')
        if not isinstance(operation, str) or not OPERATION.fullmatch(operation):
            raise ValueError('Invalid progress operation ID.')
        manifest, files = snapshot(req.get('snapshot'))
        request_digest = digest(req)
        journal = checkout.journals.get(operation)
        retry_before_write = bool(journal and not journal.get('commit') and not journal.get('changed_files'))
        if journal:
            if journal['request_digest'] != request_digest:
                raise ValueError('This operation ID already belongs to a different snapshot or save action.')
            if journal.get('commit'):
                if req.get('push') and journal.get('verified') and not journal.get('pushed'):
                    return self.retry_push(checkout, reg, req)
                return self.result(journal)
        journal = checkout.journals[operation] = dict(operation_id=operation, request_digest=request_digest, revision=reg['revision'], registration=reg['id'],
                                                       status='needs_attention', commit=None, verified=False, changed_files=[], pushed=False,
                                                       snapshot_path='', message='Snapshot preserved; export has not completed.')
        try:
            head = self.guard(checkout)
            if not retry_before_write and req.get('expected_head') != head:
                raise ValueError('The repository changed since it was selected. Refresh status and retry the preserved snapshot.')
            target = req.get('target')
            if target not in ('latest', 'baseline', 'checkpoint'):
                raise ValueError('Choose latest, baseline or checkpoint.')
            for key in ('replace_baseline', 'allow_removed', 'push'):
                if key in req and type(req[key]) is not bool:
                    raise ValueError('Invalid save option.')
            design = manifest.get('kind') == 'network-design'
            if 'kind' in manifest and not design:
                raise ValueError('Unsupported snapshot kind.')
            if design and target != 'checkpoint':
                raise ValueError('A design export goes to its own checkpoint folder.')
            folders = [] if target == 'baseline' or design else [checkout.scope(reg, 'latest')]
            if target == 'baseline':
                old = checkout.manifest_at(checkout.files, checkout.scope(reg, 'baseline'))
                if old and (not req.get('replace_baseline') or req.get('expected_baseline') != digest(old)):
                    raise ValueError('The baseline already exists or changed. Review it and explicitly confirm replacement.')
                folders.append(checkout.scope(reg, 'baseline'))
            elif target == 'checkpoint':
                name = req.get('checkpoint')
                if not isinstance(name, str) or not SLUG.fullmatch(name) or name in ('.', '..'):
                    raise ValueError('Choose a short literal checkpoint name.')
                folder = checkout.scope(reg, 'checkpoints/' + name)
                if any(p.startswith(folder + '/') for p in checkout.files):
                    raise ValueError('This checkpoint already exists. Choose a new name.')
                folders.append(folder)
            journal['snapshot_path'] = folders[-1]
            expected = {}
            for folder in folders:
                old = checkout.manifest_at(checkout.files, folder)
                if old and (old.get('kind') == 'network-design') != design:
                    raise ValueError('This folder holds a different kind of snapshot; choose another name.')
                old_names, old_devices = set(), set()
                for item in (old or {}).get('files', []):
                    name = relpath(item.get('path'))
                    old_names.add(name)
                    if not item.get('kind'):
                        old_devices.add(name)
                    if item.get('restore_artifact'):
                        old_names.add(relpath(item['restore_artifact']))
                existing = {p[len(folder) + 1:] for p in checkout.files if p.startswith(folder + '/') and '/' not in p[len(folder) + 1:]}
                if existing - (old_names | {'manifest.json'}):
                    raise ValueError('The destination contains files outside its manager manifest; preserve or move them first.')
                if not old and existing:
                    raise ValueError('The destination is not an empty manager snapshot folder.')
                if old_devices - set(files) and not req.get('allow_removed'):
                    raise ValueError('This capture removes previously saved devices. Review the new device scope before allowing removal.')
                if old and content_digest(old) == content_digest(manifest):
                    continue
                for name, raw in files.items():
                    expected[folder + '/' + name] = raw
                for name in old_names - set(files):
                    expected[folder + '/' + name] = None
                expected[folder + '/manifest.json'] = (json.dumps(manifest, sort_keys=True, indent=2, ensure_ascii=False) + '\n').encode()
            changed = [name for name, raw in expected.items() if checkout.files.get(name) != raw]
            if not changed:
                journal.update(status='unchanged', unchanged=True, message='No configuration changes.', commit=head, verified=head in checkout.known_commits())
                if req.get('push'):
                    if journal['verified']:
                        return self.retry_push(checkout, reg, req)
                    journal.update(pushed=head in checkout.remote, message='No configuration changes; ' + ('already up to date.' if head in checkout.remote else 'remote synchronization needs attention.'))
                return self.result(journal)
            message = req.get('message') or ('Save ' + str(manifest.get('lab_name', 'lab')) + ' progress')
            if not isinstance(message, str) or len(message) > 500 or any(ord(c) < 32 for c in message):
                raise ValueError('Use a short single-line commit note.')
            commit = checkout.add_commit(message, {n: expected[n] for n in changed}, operation_id=operation, registration=reg['id'])
            journal.update(status='committed', commit=commit, verified=True, changed_files=changed, message='Saved in the VM repository; not pushed.')
            return self.retry_push(checkout, reg, req) if req.get('push') else self.result(journal)
        except ValueError as error:
            journal.update(status='needs_attention', message=str(error), pushed=False)
            return self.result(journal)

    def retry_push(self, checkout, reg, req):
        journal = checkout.journals.get(req.get('operation_id'))
        if not journal or journal.get('revision') != reg['revision']:
            raise ValueError('Saved progress journal not found for this binding.')
        try:
            return self.push(checkout, journal)
        except ValueError as error:
            journal.update(status='needs_attention', pushed=False, message=str(error))
            return self.result(journal)

    def push(self, checkout, journal):
        commit = journal.get('commit')
        if not commit or (not journal.get('verified') and not journal.get('unchanged')):
            raise ValueError('This save has no verified commit to push. Review its export status.')
        head = self.guard(checkout)
        remote = self.remote_head(checkout)
        if remote == commit or commit in checkout.remote:
            return self.mark_synced(checkout, journal)
        if not journal.get('verified'):
            raise ValueError('This unchanged save points to a commit created outside manager saves. Publish it as the repository owner first.')
        if head != commit:
            raise ValueError('The checkout moved since this save. Push the newest saved progress or resolve it as the repository owner.')
        if self.control.get('remote_ahead', checkout.name):
            raise ValueError(PROBLEMS['diverged'])
        if not {c['commit'] for c in checkout.unpushed()} <= checkout.known_commits():
            raise ValueError('The push would include commits created outside manager saves. Publish or resolve them as the repository owner first.')
        if self.control.take('push_fail_once', checkout.name) or self.control.get('push_refused', checkout.name):
            raise ValueError(PUSH_FAILED)
        checkout.remote.update(c['commit'] for c in checkout.commits)
        return self.mark_synced(checkout, journal)

    def mark_synced(self, checkout, journal):
        synced = []
        for other in checkout.journals.values():
            if other.get('verified') and other.get('commit') and other['commit'] in checkout.remote:
                other.update(status='synced', pushed=True, message='Saved to Git.')
                synced.append(other['operation_id'])
        if journal['operation_id'] not in synced:
            synced.append(journal['operation_id'])
        journal.update(status='synced', pushed=True, message='Saved to Git.', synced_operations=synced)
        return self.result(journal)

    # --- move -------------------------------------------------------------------------------------------------------

    def move(self, checkout, reg, req):
        operation = req.get('operation_id')
        if not isinstance(operation, str) or not OPERATION.fullmatch(operation):
            raise ValueError('Invalid progress operation ID.')
        source = relpath(req.get('source_prefix'), empty=True)
        if source == reg['prefix']:
            raise ValueError('Choose a different folder for this lab.')
        if not isinstance(req.get('message'), str) or not req['message'].strip():
            raise ValueError('A move needs a commit note.')
        request_digest = digest({k: v for k, v in req.items() if k not in ('push', 'expected_head')})
        journal = checkout.journals.get(operation)
        if journal:
            if journal['request_digest'] != request_digest:
                raise ValueError('This operation ID already belongs to a different action.')
            if journal.get('commit'):
                if req.get('push') and journal.get('verified') and not journal.get('pushed'):
                    return self.retry_push(checkout, reg, req)
                return self.result(journal)
        journal = checkout.journals[operation] = dict(operation_id=operation, request_digest=request_digest, revision=reg['revision'], registration=reg['id'],
                                                       status='needs_attention', commit=None, verified=False, changed_files=[], pushed=False,
                                                       snapshot_path=checkout.scope(reg, 'latest'), message='Move prepared; nothing has been committed.')
        try:
            head = self.guard(checkout)
            if req.get('expected_head') != head:
                raise ValueError('The repository changed since it was selected. Refresh status and retry the move.')
            old_folders = [('/'.join(p for p in (source, n) if p)) + '/' for n in RESERVED]
            paths = [p for p in sorted(checkout.files) if p.startswith(tuple(old_folders))]
            if not paths:
                raise ValueError('There are no saved files to move yet.')
            changes = {}
            for old in paths:
                new = checkout.scope(reg, old[len(source) + 1:] if source else old)
                if new in checkout.files or new in changes:
                    raise ValueError('The new folder already contains saved files. Choose an empty folder.')
                changes[old] = None
                changes[new] = checkout.files[old]
            commit = checkout.add_commit(req['message'], changes, operation_id=operation, registration=reg['id'])
            journal.update(status='committed', commit=commit, verified=True, changed_files=list(changes), message='Saved in the VM repository; not pushed.')
            return self.retry_push(checkout, reg, req) if req.get('push') else self.result(journal)
        except ValueError as error:
            journal.update(status='needs_attention', message=str(error), pushed=False)
            return self.result(journal)

    # --- registrations -----------------------------------------------------------------------------------------------

    def check_collision(self, checkout, prefix, ignore=None):
        for other in checkout.registrations:
            if other is ignore:
                continue
            if colliding(prefix, other['prefix']):
                raise ValueError(collision_message(prefix, other['prefix']))

    def waiting_saves(self, checkout, reg):
        waiting = {c['commit'] for c in checkout.unpushed()}
        return any(j.get('registration') == reg['id'] and j.get('commit') in waiting for j in checkout.journals.values())

    def register_prefix(self, checkout, source, req):
        """H1 and H7: nesting is never refused; only a real collision is, and a retire that would strand a waiting save."""
        prefix = relpath(req.get('prefix'), empty=True)
        retire = req.get('retire') is True
        if prefix == source['prefix']:
            return descriptor(source)
        existing = next((r for r in checkout.registrations if r['prefix'] == prefix), None)
        if existing:
            if retire:
                self.retire(checkout, source)
            return descriptor(existing)
        base_prefix(prefix)
        self.check_collision(checkout, prefix, ignore=source if retire else None)
        new = self.register(checkout, prefix, label=req.get('label') or (checkout.name + (' / ' + prefix if prefix else '')))
        if retire:
            self.retire(checkout, source)
        return descriptor(new)

    def retire(self, checkout, reg):
        if self.control.get('remote_unreachable', checkout.name):
            raise ValueError(REMOTE_UNAVAILABLE)
        if self.waiting_saves(checkout, reg):
            raise ValueError('A save made in that folder still waits for upload.')
        if reg in checkout.registrations:
            checkout.registrations.remove(reg)

    def connect(self, req):
        answer = self.connect_checkout(req)
        self.control.set(no_repositories=None)   # a VM with nothing registered has something once a repository is connected
        return answer

    def connect_checkout(self, req):
        url = clone_url(req.get('url'))
        prefix = base_prefix(req.get('prefix', ''))
        key = self.key(url)
        checkout = next((c for c in self.checkouts.values() if self.key(c.url) == key), None)
        if checkout:
            existing = next((r for r in checkout.registrations if r['prefix'] == prefix), None)
            if existing:
                return descriptor(existing)
            self.check_collision(checkout, prefix)
            return descriptor(self.register(checkout, prefix, label=repository_name(url) + (' / ' + prefix if prefix else '')))
        if 'forbidden' in url:
            raise ValueError('The GitHub account signed in on the VM cannot push to ' + url.split('github.com/')[-1].removesuffix('.git') +
                             '. Check the repository name, or grant that account write access on GitHub.')
        if 'missing' in url:
            raise ValueError('Cloning failed. Check the URL and that the VM account is signed in to GitHub with access to this repository (gh auth login).')
        name = repository_name(url)
        remote = self.remotes.get(key, {'empty': False})
        if remote['empty'] and req.get('initialize') is not True:
            raise ValueError('This repository has no commits yet. Add a README on GitHub first, then connect it.')
        checkout = self.add_checkout(name, url)
        if remote['empty']:
            checkout.add_commit('Start the repository', {'README.md': ('# ' + name + '\n').encode()}, pushed=True)
            remote['empty'] = False
        else:
            checkout.add_commit('Initial commit', {'README.md': ('# ' + name + '\n').encode()}, pushed=True, age=86400 * 30)
        return descriptor(self.register(checkout, prefix, label=name + (' / ' + prefix if prefix else '')))

    # --- what the control and the self-check read -------------------------------------------------------------------

    def describe(self):
        return {'repositories': {name: dict(url=c.url, head=c.head, commits=len(c.commits), waiting=len(c.unpushed()), files=len(c.files),
                                            registrations=[dict(id=r['id'], prefix=r['prefix']) for r in c.registrations])
                                 for name, c in self.checkouts.items()},
                'remote_only': {k: v for k, v in self.remotes.items()}}
