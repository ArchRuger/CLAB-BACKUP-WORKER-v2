"""What a repository folder is for a lab: one answer per folder (docs/git-redesign/DESIGN.md 2.5).

The tree's marks, the sentence under a typed path, the chooser's question and the route that applies a
choice all read the answer made here, so two texts on one screen cannot disagree and no folder choice
ends in a refusal. The module is pure: plain data in, plain data out, no I/O and nothing imported from the
rest of the manager. The constants below are copies of the VM helper's and must stay equal to them.

`lab` is `{'id', 'name', 'prefix'}`; `prefix` is the folder the lab saves to in this checkout, or None.
`checkout` is `{'registrations': [{'id', 'prefix', 'lab': {'id', 'name'} or None}], 'files', 'dirs',
'states': {folder: summary or None}, 'planned': [folder], 'pending_states': [{'prefix', 'name'}],
'truncated'}`, and optionally `'lab_states'`: folders the manager itself wrote as lab states (never
"an earlier folder of this lab", whatever lab id their manifest carries).
"""
import re

RESERVED = ('latest', 'baseline', 'checkpoints')   # host_git.RESERVED: what a lab writes inside its folder
PART_LIMIT = 181                                   # host_git.PATH_PART: one first character and at most 180 more
PATH_LIMIT = 500                                   # host_git.relpath
KINDS = ('free', 'own', 'own-before', 'lab', 'state')
NAME_LIMIT = 60                                    # a folder named after a lab or a state, as the page cut it before
BESIDE_TRIES = 1000
UNSAFE = re.compile(r'[^A-Za-z0-9_.-]+')
UNSAFE_ENDS = re.compile(r'\A[^A-Za-z0-9_.-]+|[^A-Za-z0-9_.-]+\Z')
TOO_LONG = 'A folder path can be at most 500 characters long.'


def clean_folder(value):
    """The path a person typed, corrected instead of refused: '' is the top level. Unsafe characters at
    the ends of a name are dropped like spaces (`BGP (2)` reads `BGP-2`, not `BGP-2-`), every other run
    becomes one dash, and what cannot start a name is stripped. The only error left is the length."""
    parts = []
    for part in str('' if value is None else value).split('/'):
        part = UNSAFE.sub('-', UNSAFE_ENDS.sub('', part))
        if part.lower() == '.git': part = 'git'
        part = part.lstrip('.-')[:PART_LIMIT]
        if part: parts.append(part)
    folder = '/'.join(parts)
    if len(folder) > PATH_LIMIT: raise ValueError(TOO_LONG)
    return folder


def folder_name(name, fallback='lab'):
    """One folder name made from a lab's or a state's name. It is never one of the names a lab writes
    inside its folder: a lab called `latest` saves in `lab-latest`."""
    name = clean_folder(str('' if name is None else name).replace('/', '-'))[:NAME_LIMIT].rstrip('-') or fallback
    return fallback + '-' + name if name in RESERVED else name


def colliding(prefix, other):
    """Two lab folders write the same files only when one lies inside a folder the other writes its saves
    into (latest, baseline, checkpoints). Otherwise they may sit inside, above or beside each other.
    Mirrors `colliding()` of app/host_git.py (DESIGN.md 2.3 H1): the helper decides, this predicts it."""
    def inside(a, b): return any(a == f or a.startswith(f + '/') for f in ((b + '/' if b else '') + n for n in RESERVED))
    return prefix != other and (inside(prefix, other) or inside(other, prefix))


def state_name(path):
    """The name a saved state is listed under (DESIGN.md 3.8, N3): its folder's name."""
    parts = [p for p in str(path or '').split('/') if p]
    if len(parts) >= 2 and parts[-2] == 'checkpoints': return parts[-1]
    if parts and parts[-1] == 'latest': parts.pop()
    if not parts: return 'Top level'
    name = parts[-1]
    return name[0].upper() + name[1:] if name == name.lower() else name


def above(path): return path.rsplit('/', 1)[0] if '/' in path else ''
def join(*parts): return '/'.join(p for p in parts if p)


def paths(items):
    for item in items or ():
        path = item.get('path') if isinstance(item, dict) else item
        if isinstance(path, str): yield path


class Tree:
    """One checkout as one lab sees it, indexed once so that an answer costs the depth of its path and not
    the size of the repository (`folder_answers` asks for every directory)."""

    def __init__(self, lab, checkout):
        lab = lab if isinstance(lab, dict) else {}
        checkout = checkout if isinstance(checkout, dict) else {}
        self.id = str(lab.get('id') or '')
        self.name = str(lab.get('name') or '')
        self.prefix = lab['prefix'].strip('/') if isinstance(lab.get('prefix'), str) else None
        self.folder_name = folder_name(self.name)
        self.dirs = {''}        # committed at HEAD
        self.files = set()      # committed files: no folder can be made where one of them is
        self.listed = {''}      # what the tree shows: committed, planned, or a connected lab's folder
        self.states = {}        # folder that holds manifest.json -> summary or None
        for path in paths(checkout.get('files')):
            path = path.strip('/')
            if not path: continue
            self.files.add(path); self.grow(self.dirs, above(path))
            if path == 'manifest.json' or path.endswith('/manifest.json'): self.states.setdefault(above(path), None)
        for path in paths(checkout.get('dirs')): self.grow(self.dirs, path.strip('/'))
        given = checkout.get('states')
        for path, summary in (given.items() if isinstance(given, dict) else ()):
            if not isinstance(path, str): continue
            self.states[path.strip('/')] = summary if isinstance(summary, dict) else None
            self.grow(self.dirs, path.strip('/'))
        self.listed |= self.dirs
        for path in paths(checkout.get('planned')):
            if path.strip('/'): self.grow(self.listed, path.strip('/'))
        self.pending = {}       # a lab state is being saved into <prefix>/latest right now (review F11)
        for item in checkout.get('pending_states') or ():
            if isinstance(item, dict) and isinstance(item.get('prefix'), str): self.pending[item['prefix'].strip('/')] = str(item.get('name') or '')
        self.lab_states = {p.strip('/') for p in paths(checkout.get('lab_states'))}
        self.others = {}        # folder -> the other connected lab that saves there
        self.at = {}            # folder -> the registrations of exactly that folder
        self.holds = {}         # folder -> the registrations that lie inside its saved-state folders
        own = [] if self.prefix is None else [{'prefix': self.prefix, 'lab': {'id': self.id, 'name': self.name}, 'own': True}]
        for item in checkout.get('registrations') or ():
            if not isinstance(item, dict) or not isinstance(item.get('prefix'), str): continue
            prefix = item['prefix'].strip('/'); who = item.get('lab')
            who = {'id': str(who.get('id') or ''), 'name': str(who.get('name') or '')} if isinstance(who, dict) else None
            mine = prefix == self.prefix or bool(who and self.id and who['id'] == self.id)
            if who and not mine:
                self.others.setdefault(prefix, who); self.grow(self.listed, prefix)
            own.append({'prefix': prefix, 'lab': who, 'own': mine})
        if self.prefix is not None: self.grow(self.listed, self.prefix)
        for reg in own:
            parts = reg['prefix'].split('/') if reg['prefix'] else []
            self.at.setdefault(reg['prefix'], []).append(reg)
            for i, part in enumerate(parts):
                if part in RESERVED: self.holds.setdefault('/'.join(parts[:i]), []).append(reg)
        # A folder some lab writes its saved states into: its own, another connected lab's, a state on its way.
        self.lab_folders = set(self.others) | set(self.pending) | ({self.prefix} if self.prefix is not None else set())

    @staticmethod
    def grow(target, path):
        while path and path not in target:
            target.add(path); path = above(path)

    def collisions(self, folder):
        """Every registration the helper's `colliding()` would name for this folder, without asking each one."""
        found = list(self.holds.get(folder, ()))
        parts = folder.split('/') if folder else []
        for i, part in enumerate(parts):
            if part in RESERVED: found += self.at.get('/'.join(parts[:i]), ())
        return found

    def leave_state(self, parts):
        """Step 2: a path that points into a saved state means the lab folder above it. A part named like a
        saved-state folder counts when it ends the path, when it is `checkpoints` before the last name, when a
        lab saves in the folder above it, or when a manifest is committed there. A connected lab's folder is
        taken as it is, whatever its name (a legacy `x/latest` registration saves to `x/latest/latest`)."""
        parts = list(parts)
        while parts and '/'.join(parts) not in self.lab_folders:
            for i, part in enumerate(parts):
                if part not in RESERVED: continue
                here = '/'.join(parts[:i + 1]); last = len(parts) - 1
                if (i == last or (part == 'checkpoints' and i == last - 1) or '/'.join(parts[:i]) in self.lab_folders
                        or here in self.states or (part == 'checkpoints' and i < last and here + '/' + parts[i + 1] in self.states)):
                    parts = parts[:i]; break
            else: break
        return parts

    def past_files(self, parts):
        """A folder cannot be made where the repository holds a file of that name. The first part of the path
        that names a committed file gets `-2`, `-3`, ... until it names none (`README.md/x` reads
        `README.md-2/x`), so a typed path is corrected, never refused. A folder of that name is used as it is."""
        parts = list(parts)
        for i in range(len(parts)):
            if '/'.join(parts[:i + 1]) not in self.files: continue
            name = parts[i]
            for n in range(2, BESIDE_TRIES):
                end = '-' + str(n); parts[i] = name[:PART_LIMIT - len(end)] + end
                if '/'.join(parts[:i + 1]) not in self.files: break
        return parts

    def own_latest(self, folder):
        """Step 4: someone's own folder named `latest`, which a save would have to write over."""
        latest = join(folder, 'latest')
        return latest in self.dirs and latest not in self.states

    def classify(self, folder):
        """Step 3 for a folder that step 2 left alone. `within` is the registered folder whose saved states
        this folder lies in: nothing below it is usable, so a suggestion starts there."""
        out = {'kind': 'free', 'lab': None, 'layout': '', 'label': '', 'collision': False, 'same_name': False, 'own_files': False, 'within': None}
        if self.prefix is not None and folder == self.prefix: return dict(out, kind='own')
        if folder in self.others: return dict(out, kind='lab', lab=dict(self.others[folder]))
        hits = self.collisions(folder)
        if hits:
            # A lab is named before a registration nothing uses; the lab's own earlier folder comes last.
            hit = next((h for h in hits if h['lab'] and not h['own']), None) or next((h for h in hits if not h['own']), hits[0])
            inside = folder != hit['prefix'] and (folder + '/').startswith(tuple(join(hit['prefix'], n) + '/' for n in RESERVED))
            return dict(out, kind='lab', collision=True, lab=dict(hit['lab']) if hit['lab'] else None, own_files=hit['own'], within=hit['prefix'] if inside else None)
        if folder in self.pending: return dict(out, kind='state', layout='latest', label=self.pending[folder] or state_name(folder))
        latest = join(folder, 'latest')
        path, layout = (latest, 'latest') if latest in self.states else (folder, 'flat') if folder in self.states else (None, '')
        if path is None: return out
        summary = self.states[path] or {}
        # A save made with "Save as a lab state…" says so in its manifest (`state`: its name), so the lab that
        # authored it never continues there by itself, whatever the manager still remembers of its jobs.
        marked = state_mark(summary)
        mine = bool(self.id) and summary.get('lab_id') == self.id
        if mine and not marked and folder not in self.lab_states and path not in self.lab_states: return dict(out, kind='own-before', layout=layout, label=state_name(path))
        return dict(out, kind='state', layout=layout, label=marked or state_name(path),
                    same_name=not mine and not marked and bool(self.name) and summary.get('lab_name') == self.name)

    def free(self, folder):
        if len(folder) > PATH_LIMIT: return False
        parts = folder.split('/') if folder else []
        return self.past_files(parts) == parts and self.leave_state(parts) == parts and self.classify(folder)['kind'] == 'free' and not self.own_latest(folder)

    def beside(self, folder, name):
        """The first of <folder>/<name>, <folder>/<name>-2, ... that can be saved to without a question. Inside
        a saved state of some lab (a legacy folder named `baseline` under a lab folder) nothing is free, so the
        suggestion starts at the lab folder above."""
        probe = (folder.split('/') if folder else []) + [name]; left = self.leave_state(probe)
        if left != probe: folder = '/'.join(left)
        for n in range(1, BESIDE_TRIES):
            candidate = join(folder, name if n == 1 else name + '-' + str(n))
            if len(candidate) > PATH_LIMIT: return ''
            if self.free(candidate): return candidate
        return ''

    def answer(self, typed, purpose='save', name=''):
        typed = str('' if typed is None else typed)
        cleaned = clean_folder(typed)
        above_state = '/'.join(self.leave_state(cleaned.split('/') if cleaned else []))
        folder = '/'.join(self.past_files(above_state.split('/') if above_state else []))
        if len(folder) > PATH_LIMIT: raise ValueError(TOO_LONG)
        as_typed = '/'.join(p.strip() for p in typed.split('/') if p.strip())
        adjusted = 'past-file' if folder != above_state else 'above-state' if folder != cleaned else 'corrected' if cleaned != as_typed else ''
        found = self.classify(folder); beside = ''
        base = folder if found['within'] is None else found['within']
        if purpose == 'state':
            # A lab's folder is never a lab state itself: the state gets its own folder inside it.
            inner = folder_name(name, 'state')
            if found['kind'] in ('own', 'lab'):
                moved = join(base, inner)
                if len(moved) > PATH_LIMIT or self.classify(moved)['kind'] in ('own', 'lab'): moved = self.beside(base, inner)
                if moved: folder, adjusted, found = moved, 'inside-lab', self.classify(moved)
            if found['kind'] == 'own-before': found = dict(found, kind='state')
            if found['kind'] == 'free' and self.own_latest(folder):
                moved = self.beside(folder, inner)
                if moved: folder, adjusted, found = moved, 'beside-files', self.classify(moved)
        elif found['own_files'] or (found['kind'] == 'free' and self.own_latest(folder)):
            # Step 4: files the save would have to write over (someone's `latest` folder, or this lab's own
            # earlier folder inside this folder's saved states). The lab goes beside them without a question.
            moved = self.beside(base, self.folder_name)
            if moved: folder, adjusted, found = moved, 'beside-files', self.classify(moved)
        elif found['kind'] in ('lab', 'state'): beside = self.beside(base, self.folder_name)
        kind = found['kind']; mark = ''
        if adjusted in ('', 'corrected', 'past-file'):
            if kind == 'own': mark = 'This lab saves here'
            elif kind == 'lab' and not found['collision']: mark = found['lab']['name'] + ' saves here'
            elif kind in ('state', 'own-before'): mark = 'Lab state: ' + found['label']
        return {'folder': folder, 'typed': typed, 'kind': kind, 'exists': folder in self.dirs, 'label': found['label'], 'lab': found['lab'],
                'layout': found['layout'], 'collision': found['collision'], 'adjusted': adjusted, 'beside': beside, 'mark': mark,
                'same_name': found['same_name']}


def place_answer(lab, checkout, folder, purpose='save', name=''):
    """What `folder` is for `lab` (DESIGN.md 2.5, 7.4). `purpose='state'` asks about a destination of
    *Save as a lab state...*; `name` is then the state's folder name. Raises only for a path over 500
    characters; `kind` is always one of KINDS."""
    return Tree(lab, checkout).answer(folder, purpose, name)


def folder_answers(lab, checkout):
    """The answer for every folder the tree lists, each with its `path`, sorted by path. A registration no
    lab uses lists nothing and marks nothing. A committed directory whose name the helper would not take
    is listed under its real path and answered with its corrected folder."""
    tree = Tree(lab, checkout); rows = []
    for path in sorted(tree.listed):
        try: rows.append(dict(tree.answer(path), path=path))
        except ValueError: continue
    return rows


def default_place(lab, checkouts):
    """Where a first save goes with nothing typed (DESIGN.md 2.8): the repository the lab used last, else
    the one used most recently, else the first by name; in it the lab's own folder, else the folder named
    after the lab, else the first of `<name>-2`, `<name>-3`, ... that needs no question. A folder that
    holds the saves of another lab of the same name is returned with `ask`: it is never continued silently.
    An entry of `checkouts` may carry `prefix`, the lab's folder in that checkout; without it `lab['prefix']`
    counts only for the repository `lab['last_repository']` names."""
    lab = lab if isinstance(lab, dict) else {}
    entries = [c for c in checkouts or () if isinstance(c, dict)]
    if not entries: return None
    last = lab.get('last_repository')
    entry = next((c for c in entries if last and c.get('path') == last), None)
    if entry is None:
        used = [c for c in entries if c.get('last_used')]
        entry = max(used, key=lambda c: c['last_used']) if used else min(entries, key=lambda c: (str(c.get('name') or '').lower(), str(c.get('path') or '')))
    prefix = entry['prefix'] if 'prefix' in entry else lab.get('prefix') if last and entry.get('path') == last else None
    tree = Tree(dict(lab, prefix=prefix), entry.get('checkout'))
    out = {'repository': entry.get('id'), 'ask': False, 'beside': ''}
    if tree.prefix is not None: return dict(out, folder=tree.prefix, answer=tree.answer(tree.prefix))
    name = tree.folder_name
    answer = tree.answer(name)
    if answer['kind'] in ('free', 'own', 'own-before'): return dict(out, folder=answer['folder'], answer=answer)
    if answer['kind'] == 'state' and answer['same_name']:
        beside = next((c for c in (name + '-' + str(n) for n in range(2, BESIDE_TRIES)) if tree.free(c)), '')
        return dict(out, folder=answer['folder'], answer=dict(answer, beside=beside), ask=True, beside=beside)
    for n in range(2, BESIDE_TRIES):
        answer = tree.answer(name + '-' + str(n))
        if answer['kind'] in ('own', 'own-before') or (answer['kind'] == 'free' and answer['folder'] == name + '-' + str(n)):
            return dict(out, folder=answer['folder'], answer=answer)
    return dict(out, folder=answer['folder'], answer=answer)


def state_mark(summary):
    """The name a lab state gave itself in its manifest ('' for every other saved state)."""
    value = summary.get('state') if isinstance(summary, dict) else None
    return value.strip()[:200] if isinstance(value, str) else ''


def state_rows(lab, checkout):
    """One row per saved state of the checkout, named by one rule (DESIGN.md 3.8, N3) for the Load panel,
    All versions and the chooser's marks. Order: the lab's latest, its checkpoints, its baseline, the lab
    states by name, then the saved states of other connected labs."""
    tree = Tree(lab, checkout); rows = []

    def role(path, prefix):
        if path == join(prefix, 'latest'): return 'latest'
        if path == join(prefix, 'baseline'): return 'baseline'
        return 'checkpoint' if above(path) == join(prefix, 'checkpoints') and path != above(path) else ''

    for path, summary in tree.states.items():
        known = summary or {}
        group = role(path, tree.prefix) if tree.prefix is not None else ''
        who = '' if group else next((lab_['name'] for prefix, lab_ in tree.others.items() if role(path, prefix)), None)
        if not group: group = 'state' if who is None else 'other-lab'
        rows.append({'path': path, 'name': (state_mark(known) if group == 'state' else '') or state_name(path), 'group': group, 'lab': who if group == 'other-lab' else str(known.get('lab_name') or ''),
                     'kind': 'design' if known.get('kind') in ('design', 'network-design') else 'capture', 'summary': summary,
                     'layout': 'latest' if path == 'latest' or path.endswith('/latest') else 'flat'})
    # Two lab states of one name each say where they are: `Start · BGP`; the whole path when that is equal too.
    def shown(path): return above(path) if path == 'latest' or path.endswith('/latest') else path
    def apart(label):
        states = [r for r in rows if r['group'] == 'state']
        twice = {n for n in (r['name'] for r in states) if sum(1 for r in states if r['name'] == n) > 1}
        for row in states:
            if row['name'] in twice: row['name'] = label(row)
    base = {r['path']: r['name'] for r in rows}
    apart(lambda r: base[r['path']] + ' · ' + (above(shown(r['path'])).rsplit('/', 1)[-1] or 'Top level'))
    apart(lambda r: base[r['path']] + ' · ' + (r['path'] or 'Top level'))
    order = {'latest': 0, 'checkpoint': 1, 'baseline': 2, 'state': 3, 'other-lab': 4}
    rows.sort(key=lambda r: (order[r['group']], r['lab'].lower() if r['group'] == 'other-lab' else '', r['name'].lower(), r['path']))
    return rows
