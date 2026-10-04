"""The VM Git helper, answered from memory, as it behaves after the Git save and load redesign (DESIGN.md 2.3, H1 to H7).

`FakeGit` replaces `app.git_progress.remote_git`: it takes (host, request, stopping) and answers like
`clab-backup-ui/app/host_git.py`, or raises ValueError with the helper's own sentence. Several checkouts (repositories)
live side by side; every checkout keeps its commits, the tree of each, the commits the fake remote holds and the helper's
journals, so a push carries every earlier waiting commit exactly like `GitRepository.push` / `mark_synced`.

Where the real helper has a pure function or a fixed sentence the fake imports it instead of copying it, so a rule cannot
drift: `snapshot`, `content_digest`, `colliding`, `collision_message`, `base_prefix`, `relpath`, `clone_url`,
`same_repository`, `manifest_summary` (the history rows' `summary`), `display_text`, the START_* and connect sentences and
the limits (MAX_TREE, MAX_DIRS, MAX_OUTGOING, SUMMARY_*). What is copied is only what the real helper writes inline, and
`check_fixture.py` compares each copied sentence with the manager's table of the helper's sentences (`HELPER_PROBLEMS`).

Shapes and orders the manager relies on (host_git.py): `history` answers `head`, `commits`, `versions` (each with `summary`,
`state` inside it) and `summaries_truncated`; `browse` answers `files` and `dirs` in Git's own tree order with `truncated` and
`dirs_truncated`; `compare` answers `outgoing` OLDEST FIRST with `{commit, operation_id, subject, files, approved}` and
`outgoing_truncated`, or `outgoing: None` when the remote cannot be asked.
"""
import base64
import hashlib
import json
import re
import threading
import time

from app import __version__
from app.git_progress import PROTOCOL, UNREGISTERED
from app.host_git import (DIRS_BYTES, EMPTY_REPOSITORY, MAX_DIRS, MAX_OUTGOING, MAX_TREE, NOT_MANAGER_SAVES, NOT_SYNCHRONIZED,
                          OUTGOING_BYTES, OUTGOING_FILES, REMOTE_AHEAD, RESERVED, SAVE_UNKNOWN, SAVE_WAITS, SLUG, START_FAILED,
                          START_MESSAGE, START_README, SUMMARY_BYTES, SUMMARY_FILE, SUMMARY_TOTAL, base_prefix, clone_url,
                          collision_message, colliding, content_digest, digest, display_text, manifest_summary, relpath,
                          repository_name, same_repository, snapshot, snapshot_file, snapshot_folder)

OPERATION = re.compile(r'[0-9a-f]{32}\Z')
STAGES = ('validate', 'clean', 'manifest', 'write')    # where in the helper's order a problem is raised (see `gate`)
# switch value -> (the helper's sentence, the stage that raises it). The sentences are the helper's (host_git.py):
#   validate  every mode that opens the checkout (history, browse, read-version, compare, status, publish, ...)
#   clean     status, publish, move, update and the late check of a push; NOT history, browse, read-version or compare
#   manifest  status and publish (they read the folder's existing manifest)
#   write     publish and move only (the commit identity is asked right before a save is written)
PROBLEMS = {
    'operation': ('Finish the existing Git operation before saving lab progress.', 'clean'),
    'staged': ('The repository already has staged changes. If an earlier manager save failed, fix its reported issue and retry that '
               'original save: Retry commits automatically. For unrelated staged work, resolve it as the repository owner first.', 'clean'),
    'edits': ('The repository has unsaved edits in the selected scope. Resolve them before continuing.', 'clean'),
    'settings': ('The repository branch changed. Restore the registered branch or register it again.', 'validate'),
    'files': ('Existing snapshot files no longer match their saved manifest. Review the repository before exporting.', 'manifest'),
    'identity': ('Git commit identity is missing or invalid. As the registered Linux owner, run guided Git setup or set user.name and '
                 'user.email inside this checkout, then retry the original save.', 'write'),
    # A fixture shortcut: the real `status` never says this (it is the answer of a push or an update); it lets a browser pass
    # show the chip's `diverged` state without making a waiting save first. The real thing is `remote_ahead`.
    'diverged': ('The remote branch advanced or diverged. Resolve the branch before pushing; no force push was attempted.', 'clean'),
}
PROBLEMS['permission'] = PROBLEMS['identity']   # the name the first fixture used; upload failures are `push_refused`
PUSH_FAILED = 'The commit is saved on the VM, but push failed. Check authentication, branch permissions or remote changes, then retry.'
REMOTE_UNAVAILABLE = "The remote branch is unavailable. Check connectivity and the owner's noninteractive HTTPS Git login."
PUSH_PREFLIGHT = ('Git push preflight failed. Authenticate as the registered Linux owner and check remote write access. For GitHub use gh auth '
                  'login and gh auth setup-git; your GitHub website password cannot authenticate a Git push. No commits were pushed.')
RESULT_KEYS = ('status', 'commit', 'changed_files', 'message', 'pushed', 'snapshot_path', 'synced_operations')


def sha1(*parts):
    return hashlib.sha1('\0'.join(map(str, parts)).encode()).hexdigest()


def tree_key(path, directory=False):
    """Git's order of a tree listing (`ls-tree -r`): a directory sorts as its name plus a slash, so `a-b` comes before `a/c`."""
    parts = path.split('/')
    return tuple(p + '/' for p in parts[:-1]) + (parts[-1] + '/' if directory else parts[-1],)


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

    def approved(self):
        """The revisions whose journals a push accepts: those of this checkout's current registrations (host_git `known_commits`)."""
        return {r['revision'] for r in self.registrations}

    def known_commits(self, revisions=None):
        revisions = self.approved() if revisions is None else revisions
        return {j['commit'] for j in self.journals.values() if j.get('commit') and j.get('verified') and j.get('revision') in revisions}

    def scope(self, reg, name):
        return '/'.join(p for p in (reg['prefix'], name) if p)

    def manifest_at(self, tree, folder):
        raw = tree.get(snapshot_file(folder, 'manifest.json'))
        return json.loads(raw) if raw is not None else None


def descriptor(reg):
    return {k: reg[k] for k in ('id', 'label', 'owner', 'path', 'remote', 'push_url', 'branch', 'prefix', 'revision')}


class FakeGit:
    def __init__(self, control):
        self.control = control
        self.checkouts = {}
        self.remotes = {}            # normalized url -> {'empty': bool}: repositories the VM can reach by address
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

    def find(self, request, planning=False):
        """host_git.main(): an id the registry does not hold is `Select a registered Git repository.`; a stale revision (dispatch,
        plan_prefix) is `The repository binding changed.` `planning` is register-prefix, which has one sentence for both."""
        for checkout in self.checkouts.values():
            for reg in checkout.registrations:
                if reg['id'] == request.get('binding_id'):
                    if reg['revision'] != request.get('revision'):
                        raise ValueError('The repository binding changed. Select it again.')
                    return checkout, reg
        raise ValueError('The repository binding changed. Select it again.' if planning else UNREGISTERED)

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
            if mode == 'register-prefix':
                checkout, reg = self.find(request, planning=True)
                return self.register_prefix(checkout, reg, request)
            checkout, reg = self.find(request)
            handler = {'status': self.status, 'publish': self.publish, 'push': self.retry_push, 'history': self.history,
                       'read-version': self.read_version, 'compare': self.compare, 'update': self.update, 'browse': self.browse,
                       'move': self.move}.get(mode)
            if not handler:
                raise ValueError('Unsupported Git operation.')
            return handler(checkout, reg, request)

    # --- the checkout's own state (the problems a status can answer) --------------------------------------------

    def problem(self, checkout):
        """(sentence, stage) of the switched problem, or None. Any other value is a sentence of the `clean` stage."""
        value = self.control.get('status_problem', checkout.name)
        if not value:
            return None
        return PROBLEMS.get(value) or (str(value), 'clean')

    def gate(self, checkout, through):
        """The sentences the helper raises before it reads or writes: every stage up to `through`, in the helper's order
        (validate, clean, the folder's manifest, the commit identity)."""
        found = self.problem(checkout)
        if found and STAGES.index(found[1]) <= STAGES.index(through):
            raise ValueError(found[0])
        return checkout.head

    def remote_head(self, checkout):
        if self.control.get('remote_unreachable', checkout.name):
            raise ValueError(REMOTE_UNAVAILABLE)
        return next((c['commit'] for c in checkout.commits if c['commit'] in checkout.remote), '')

    def has_waiting(self, checkout, reg):
        """host_git `check_waiting`: a save made through this registration that the remote lacks. A remote that cannot be asked
        refuses once something could be waiting; with nothing to ask about the remote is not asked."""
        commits = {j['commit'] for j in checkout.journals.values() if j.get('commit') and j.get('revision') == reg['revision']
                   and j.get('pushed') is not True and checkout.commit(j['commit'])}
        if not commits:
            return
        if self.control.get('remote_unreachable', checkout.name):
            raise ValueError(SAVE_UNKNOWN)
        if any(c not in checkout.remote for c in commits):
            raise ValueError(SAVE_WAITS)

    # --- modes ----------------------------------------------------------------------------------------------------

    def status(self, checkout, reg, request):
        result = {'repository': descriptor(reg), 'head': '', 'ready': False, 'problem': '', 'baseline_revision': '', 'latest_manifest': None}
        found = self.problem(checkout)
        if found and found[1] == 'validate':
            result['problem'] = found[0]
            return result
        result['head'] = checkout.head
        if found and STAGES.index(found[1]) <= STAGES.index('manifest'):
            result['problem'] = found[0]
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
        self.gate(checkout, 'validate')
        paths = sorted(checkout.files, key=tree_key)
        files, truncated = [], False
        for path in paths:
            if len(files) >= MAX_TREE:
                truncated = True
                break
            files.append(dict(path=path, size=len(checkout.files[path])))
        saved = {}
        for name in RESERVED:
            scope = checkout.scope(reg, name)
            times = [c['time'] for c in checkout.commits if any(f == scope or f.startswith(scope + '/') for f in c['files'])]
            saved[name] = max(times) if times else None
        directories = set()
        for path in paths:
            parts = path.split('/')[:-1]
            directories.update('/'.join(parts[:n]) for n in range(1, len(parts) + 1))
        dirs, size, dirs_truncated = [], 0, False
        for path in sorted(directories, key=lambda p: tree_key(p, True)):
            size += len(path.encode()) + 3
            if len(dirs) >= MAX_DIRS or size > DIRS_BYTES:
                dirs_truncated = True
                break
            dirs.append(path)
        return {'repository': descriptor(reg), 'head': checkout.head, 'files': files, 'truncated': truncated, 'saved': saved,
                'folders': [dict(id=r['id'], label=r['label'], prefix=r['prefix']) for r in checkout.registrations],
                'dirs': dirs, 'dirs_truncated': dirs_truncated}

    def history(self, checkout, reg, request):
        self.gate(checkout, 'validate')
        scopes = tuple(checkout.scope(reg, n) for n in RESERVED)
        commits = [dict(commit=c['commit'], time=c['time'], message=display_text(c['message'].split('\n', 1)[0], 500))
                   for c in checkout.commits if any(f == s or f.startswith(s + '/') for f in c['files'] for s in scopes)][:50]
        connected = {checkout.scope(reg, 'latest'), checkout.scope(reg, 'baseline')}
        checkpoints = checkout.scope(reg, 'checkpoints') + '/'
        versions, raw, others = [], {}, 0
        for path in sorted(checkout.files, key=tree_key):
            if path != 'manifest.json' and not path.endswith('/manifest.json'):
                continue
            folder = path.rsplit('/', 1)[0] if '/' in path else ''
            try:
                snapshot_folder(folder)
            except ValueError:
                continue
            here = folder in connected or (folder.startswith(checkpoints) and '/' not in folder[len(checkpoints):])
            if not here and others >= 500:
                continue
            others += not here
            versions.append(dict(name=folder, path=folder, commit=checkout.head, connected=here, summary=None))
            raw[folder] = checkout.files[path]
        versions.sort(key=lambda v: (not v['connected'], v['path']))
        truncated = self.summarize(reg, checkout, versions, raw)
        return {'head': checkout.head, 'commits': commits, 'versions': versions, 'summaries_truncated': truncated}

    def summarize(self, reg, checkout, versions, raw):
        """host_git `summarize`: the budgets go to the lab's own states first (latest, baseline, its checkpoints); a manifest over 256 KiB is
        never read; the summaries stop at about 4 MiB. `unreadable_states` is the fixture's way to make a manifest unreadable."""
        own = {checkout.scope(reg, 'latest'): 0, checkout.scope(reg, 'baseline'): 1}
        order = sorted(versions, key=lambda v: (not v['connected'], own.get(v['path'], 2) if v['connected'] else 0, v['path']))
        budget, truncated = SUMMARY_TOTAL, False
        unreadable = self.control.get('unreadable_states') or []
        for version in order:
            data = raw[version['path']]
            if len(data) > SUMMARY_FILE:
                continue
            if len(data) > budget:
                truncated = True
                continue
            budget -= len(data)
            version['summary'] = None if version['path'] in unreadable else manifest_summary(data)
        output = 0
        for version in order:
            if version['summary'] is None:
                continue
            output += len(json.dumps(version['summary'], ensure_ascii=False).encode())
            if output > SUMMARY_BYTES:
                version['summary'] = None
                truncated = True
        return truncated

    def read_version(self, checkout, reg, request):
        self.gate(checkout, 'validate')
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
                if key == 'restore_artifact' and not item.get(key):
                    continue
                name = relpath(item.get(key))
                if '/' in name or name == 'manifest.json':
                    raise ValueError('Invalid saved snapshot filename.')
                blob = found['tree'].get(snapshot_file(folder, name))
                if blob is None:
                    raise ValueError('The saved snapshot is missing files or exceeds its limit.')
                files[name] = base64.b64encode(blob).decode()
        result = {'manifest': manifest, 'files': files}
        snapshot(result)
        return {'snapshot': result}

    def outgoing(self, checkout):
        """host_git `outgoing`: (rows oldest first, truncated), or (None, False) when the remote cannot be asked."""
        if self.control.get('remote_unreachable', checkout.name):
            return None, False
        pending = checkout.unpushed()
        truncated = len(pending) > MAX_OUTGOING
        made = {}
        for operation in sorted(checkout.journals):
            journal = checkout.journals[operation]
            if journal.get('commit') and not journal.get('unchanged'):
                made.setdefault(journal['commit'], operation)
        approved = checkout.known_commits()
        result, size = [], 0
        for c in pending[:MAX_OUTGOING]:     # newest first, so the budget keeps the newest
            row = {'commit': c['commit'], 'operation_id': made.get(c['commit']), 'approved': c['commit'] in approved,
                   'subject': display_text(c['message'].split('\n', 1)[0]), 'files': sorted(c['files'], key=tree_key)[:OUTGOING_FILES]}
            cost = len(json.dumps(row, ensure_ascii=False).encode())
            if not result:
                while cost > OUTGOING_BYTES and row['files']:
                    row['files'] = row['files'][:len(row['files']) // 2]
                    truncated = True
                    cost = len(json.dumps(row, ensure_ascii=False).encode())
            elif size + cost > OUTGOING_BYTES:
                truncated = True
                break
            size += cost
            result.append(row)
        return result[::-1], truncated

    def compare(self, checkout, reg, request):
        journal = checkout.journals.get(request.get('operation_id'))
        if not journal or not journal.get('commit') or journal.get('revision') != reg['revision']:
            raise ValueError('Select saved progress with a recorded commit.')
        outgoing, truncated = self.outgoing(checkout)
        if journal.get('unchanged') or not journal.get('changed_files'):
            return {'files': [], 'outgoing': outgoing, 'outgoing_truncated': truncated}
        self.gate(checkout, 'validate')
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
        return {'files': rows, 'outgoing': outgoing, 'outgoing_truncated': truncated}

    def update(self, checkout, reg, request):
        head = self.gate(checkout, 'clean')
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
            head = self.gate(checkout, 'write')
            if not retry_before_write and req.get('expected_head') != head:
                raise ValueError('The repository changed since it was selected. Refresh status and retry the preserved snapshot.')
            target = req.get('target')
            if target not in ('latest', 'baseline', 'checkpoint'):
                raise ValueError('Choose latest, baseline or checkpoint.')
            for key in ('replace_baseline', 'allow_removed', 'push', 'checkpoint_only'):
                if key in req and type(req[key]) is not bool:
                    raise ValueError('Invalid save option.')
            design = manifest.get('kind') == 'network-design'
            if 'kind' in manifest and not design:
                raise ValueError('Unsupported snapshot kind.')
            if design and target != 'checkpoint':
                raise ValueError('A design export goes to its own checkpoint folder.')
            # H8, as host_git `publish`: an existing save kept as a checkpoint writes only that checkpoint; `latest` keeps
            # the newest save. The option is refused with any other target and for a design export.
            only = req.get('checkpoint_only') is True
            if only and (target != 'checkpoint' or design):
                raise ValueError('Invalid save option.')
            folders = [] if target == 'baseline' or design or only else [checkout.scope(reg, 'latest')]
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
                inside = [p[len(folder) + 1:] for p in checkout.files if p.startswith(folder + '/')]
                existing = {p for p in inside if '/' not in p}
                if existing - (old_names | {'manifest.json'}):
                    raise ValueError('The destination contains files outside its manager manifest; preserve or move them first.')
                if not old and inside:     # any entry, a subfolder included (the helper lists the directory itself)
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
                    try:
                        if self.remote_head(checkout) == head:
                            journal.update(pushed=True, message='No configuration changes; already up to date.')
                        else:
                            journal.update(message='No configuration changes; remote synchronization needs attention.')
                    except ValueError:
                        journal.update(message='No configuration changes; remote status is unknown.')
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
        head = self.gate(checkout, 'validate')
        remote = self.remote_head(checkout)
        if remote == commit or commit in checkout.remote:
            return self.mark_synced(checkout, journal)
        if not journal.get('verified'):
            raise ValueError('This unchanged save points to a commit created outside manager saves. Publish it as the repository owner first.')
        if head != commit:
            raise ValueError('The checkout moved since this save. Push the newest saved progress or resolve it as the repository owner.')
        self.gate(checkout, 'clean')
        if self.control.get('remote_ahead', checkout.name):
            raise ValueError(PROBLEMS['diverged'][0])
        if not {c['commit'] for c in checkout.unpushed()} <= checkout.known_commits():
            raise ValueError('The push would include commits created outside manager saves. Publish or resolve them as the repository owner first.')
        if self.control.take('push_fail_once', checkout.name) or self.control.get('push_refused', checkout.name):
            raise ValueError(PUSH_FAILED)
        checkout.remote.update(c['commit'] for c in checkout.commits)
        return self.mark_synced(checkout, journal)

    def mark_synced(self, checkout, journal):
        synced, approved = [], checkout.approved()
        for other in checkout.journals.values():
            if other.get('verified') and other.get('commit') and other['commit'] in checkout.remote and other.get('revision') in approved:
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
            head = self.gate(checkout, 'write')
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

    def check_registered(self, checkout, retiring=None):
        """host_git `register()`: the first folder of a checkout needs the branch to equal the remote; a further one may sit on
        saves that wait for upload (every commit in between a verified manager save), then the push access is probed."""
        further = any(r is not retiring for r in checkout.registrations)
        remote = self.remote_head(checkout)
        ahead = bool(self.control.get('remote_ahead', checkout.name))
        if not ahead and remote == checkout.head:
            pass
        elif not further:
            raise ValueError(NOT_SYNCHRONIZED)
        elif ahead:
            raise ValueError(REMOTE_AHEAD)
        else:
            revisions = {r['revision'] for r in checkout.registrations if r is not retiring}
            between = {c['commit'] for c in checkout.unpushed()}
            if not between or not between <= checkout.known_commits(revisions):
                raise ValueError(NOT_MANAGER_SAVES)
        if self.control.get('push_refused', checkout.name):
            raise ValueError(PUSH_PREFLIGHT)

    def register_prefix(self, checkout, source, req):
        """plan_prefix, then the retire check (H7), then the owner's `register`: nesting is never refused (H1), only a real collision."""
        prefix = relpath(req.get('prefix'), empty=True)
        retire = req.get('retire') is True
        if prefix == source['prefix']:
            return descriptor(source)
        existing = next((r for r in checkout.registrations if r['prefix'] == prefix), None)
        if existing:
            if retire:
                self.has_waiting(checkout, source)
                checkout.registrations.remove(source)
            return descriptor(existing)
        base_prefix(prefix)
        self.check_collision(checkout, prefix, ignore=source if retire else None)
        if retire:
            self.has_waiting(checkout, source)
        self.check_registered(checkout, retiring=source if retire else None)
        new = self.register(checkout, prefix, label=req.get('label') or (checkout.name + (' / ' + prefix if prefix else '')))
        if retire:
            checkout.registrations.remove(source)
        return descriptor(new)

    def connect(self, req):
        answer = self.connect_checkout(req)
        self.control.set(no_repositories=None)   # a VM with nothing registered has something once a repository is connected
        return answer

    def connect_checkout(self, req):
        if 'initialize' in req and type(req['initialize']) is not bool:
            raise ValueError('Invalid connect option.')
        url = clone_url(req.get('url'))
        prefix = relpath(req.get('prefix'), empty=True)
        key = self.key(url)
        checkout = next((c for c in self.checkouts.values() if same_repository(c.url, url)), None)
        if checkout:
            existing = next((r for r in checkout.registrations if r['prefix'] == prefix), None)
            if existing:
                return descriptor(existing)
        base_prefix(prefix)
        if checkout:
            self.check_collision(checkout, prefix)
        if 'forbidden' in url:
            raise ValueError('The GitHub account signed in on the VM cannot push to ' + url.split('github.com/')[-1].removesuffix('.git') +
                             '. Check the repository name, or grant that account write access on GitHub.')
        remote = self.remotes.get(key, {'empty': False})
        if checkout is None:
            if 'missing' in url:
                raise ValueError('Cloning failed. Check the URL and that the VM account is signed in to GitHub with access to this repository (gh auth login).')
            checkout = self.add_checkout(repository_name(url), url)
            if not remote['empty']:
                checkout.add_commit('Initial commit', {'README.md': ('# ' + checkout.name + '\n').encode()}, pushed=True, age=86400 * 30)
        if not checkout.commits:
            self.unborn(checkout, remote, req.get('initialize') is True)
        elif checkout.registrations:
            self.check_registered(checkout)
        return descriptor(self.register(checkout, prefix, label=checkout.name + (' / ' + prefix if prefix else '')))

    def unborn(self, checkout, remote, initialize):
        """host_git `unborn`: a clone whose branch has no commit yet. The remote now has its branch (someone added a README on
        GitHub): the clone is finished, nothing is pushed. No ref at all: only `initialize: true` starts it, with the fixed
        README and message; otherwise the helper's sentence, and the clone stays as it was (the next connect retries it)."""
        if self.control.get('remote_unreachable', checkout.name):
            raise ValueError(REMOTE_UNAVAILABLE)
        if not remote['empty']:
            checkout.add_commit('Initial commit', {'README.md': ('# ' + checkout.name + '\n').encode()}, pushed=True, age=86400 * 30)
            return
        if not initialize:
            raise ValueError(EMPTY_REPOSITORY)
        if self.control.get('initialize_fails', checkout.name):
            raise ValueError(START_FAILED)
        checkout.add_commit(START_MESSAGE, {'README.md': START_README}, pushed=True)
        remote['empty'] = False

    def add_readme(self, url):
        """The instructor adds a README on GitHub: the empty remote now has its branch (a later connect finishes the clone)."""
        remote = self.remotes.get(self.key(url))
        if not remote:
            raise ValueError('No such remote: ' + str(url))
        remote['empty'] = False
        return {'url': url, 'empty': False}

    # --- what the control and the self-check read -------------------------------------------------------------------

    def describe(self):
        return {'repositories': {name: dict(url=c.url, head=c.head, commits=len(c.commits), waiting=len(c.unpushed()), files=len(c.files),
                                            registrations=[dict(id=r['id'], prefix=r['prefix']) for r in c.registrations])
                                 for name, c in self.checkouts.items()},
                'remote_only': {k: v for k, v in self.remotes.items()}}
