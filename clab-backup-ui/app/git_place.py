"""Placing a lab in a folder of a repository, so that no folder choice is ever refused (docs/git-redesign/DESIGN.md
2.4 to 2.8, section 4 and 7.4; owner goal G2).

The decisions are made by the pure module git_places.py; the routes here gather its inputs (the helper's list, tree and
saved states through `GitProgress.checkout_view`, the labs and jobs from the store), ask the questions the design defines
and apply the person's choice under `GitProgress.changing` (one connection change at a time). A folder answer is never an
HTTP error: the only 4xx a folder choice can meet is the 500-character rule and a malformed body. Nothing here uploads,
nothing sends Git command text, and the helper receives only `mode`, `prefix`, `url`, `retire`, `initialize` and the
binding of a registration. A stored binding is replaced by a new dict, never edited in place.
"""
import copy
import threading
import time
import uuid
from typing import Literal, Optional

from fastapi import HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from . import git_places
from .git_progress import (CHECKOUT_VIEW_SECONDS, HelperRefused, _append_git_job, digest, host_identity, job_pending, kept_on_vm,
                           may_hold_commit, move_destination, repository_display_name, strip_credentials)
from .inventory import PLATFORMS
from .runner import now

RAW_LIMIT = 4096            # a typed path longer than this is refused before it is cleaned (it is over 500 in any case)
HOUSEKEEPING_ABOVE = 200    # DESIGN.md 2.4, review F13: a checkout with more VM records than this loses a few unused ones
HOUSEKEEPING_BATCH = 5
EMPTY_REPOSITORY = 'This repository has no commits yet'   # the start of host_git.connect's fixed sentence (S1, H4)
FORBIDDEN = ('registration', 'prefix', 'overlap')          # words no message of these routes may carry (PROMPT 6.3)

TOO_LONG = git_places.TOO_LONG
ACKNOWLEDGE = 'Acknowledge that full device configurations will be committed and pushed to this repository.'
DEVICES = 'Select distinct supported devices from this lab.'
IN_USE = 'This folder is already used for saves on the VM.'
NO_SOURCE = 'Choose a repository, or paste the address of one.'
UNKNOWN = 'This repository is not on the VM. Refresh the list.'
NO_ANSWER = 'The VM did not answer with the repository folder. Try again.'
VM_BUSY = 'The VM could not use this folder right now. Try again in a moment.'
VM_CHANGED = 'VM connection changed. Connect again.'
LAB_GONE = 'Lab not found.'
STORE_FAILED = 'Could not save the repository connection.'
FOLDER_NOT_STORED = 'The folder could not be stored. Nothing was created.'
RESETTING = 'Finish the storage reset first.'
MOVE_REASONS = {
    'same': 'This lab already saves in this folder.',
    'nothing': 'There are no saved files to bring along.',
    'not-empty': 'The new folder already holds saved files. The saved files stay in {old}.',
    'unfinished': 'A save of this lab has not finished. Its files stay in {old}.',
    'elsewhere': 'Saved files stay in the repository the lab leaves.',
    'queue': 'The folder changed, but bringing the saved files along could not be queued. They stay in {old}.',
}


def shown(folder): return folder or 'the top level'


def clean_text(text):
    """A helper sentence as the person may see it: the words of the VM's plumbing never reach a page."""
    text = str(text or '')
    return VM_BUSY if any(word in text.lower() for word in FORBIDDEN) else text


def same_remote(left, right):
    """Whether two HTTPS addresses name one repository (credentials, a trailing slash, `.git` and case ignored)."""
    def plain(value): return strip_credentials(str(value or '').strip()).rstrip('/').removesuffix('.git').lower()
    return bool(plain(left)) and plain(left) == plain(right)


def remote_name(url):
    """The repository's name from its address, for the empty-repository question."""
    return strip_credentials(str(url or '').strip()).rstrip('/').rsplit('/', 1)[-1].removesuffix('.git') or 'repository'


def saved_index(files):
    """How many saved files each lab folder holds in its saved-state folders (latest, baseline, checkpoints), for every
    folder at once: an answer per listed folder must not cost the size of the repository each time."""
    counts = {}
    for path in files or ():
        parts = str(path).split('/')
        for i, part in enumerate(parts[:-1]):
            if part in git_places.RESERVED:
                key = '/'.join(parts[:i]); counts[key] = counts.get(key, 0) + 1
    return counts


class Placement:
    def __init__(self, progress):
        self.progress = progress; self.store = progress.store
        self.seen = {}; self.seen_lock = threading.Lock()   # registration id -> (time, registration) from the last lists

    # ----- inputs

    def host(self):
        with self.store.lock: return host_identity(self.store.state.get('host', {}))

    def lab(self, lab_id):
        with self.store.lock:
            lab = self.store.lab(lab_id)
            if not lab: raise HTTPException(404, LAB_GONE)
            return copy.deepcopy(lab)

    def catalog(self):
        """The helper's list; every registration it names is remembered for a few seconds so a typed path is cheap."""
        rows = [r for r in self.progress.catalog()['repositories'] if isinstance(r, dict) and r.get('id') and isinstance(r.get('path'), str)]
        at = time.monotonic()
        with self.seen_lock: self.seen = {r['id']: (at, r) for r in rows}
        return rows

    def registration(self, rid, fresh=False):
        if not fresh:
            with self.seen_lock: hit = self.seen.get(rid)
            if hit and time.monotonic() - hit[0] <= CHECKOUT_VIEW_SECONDS: return copy.deepcopy(hit[1])
        found = next((r for r in self.catalog() if r['id'] == rid), None)
        if not found: raise HTTPException(404, UNKNOWN)
        return copy.deepcopy(found)

    @staticmethod
    def handle(reg, before):
        """A binding to ask the helper about a checkout with (any registration of it; never stored on a lab as it is)."""
        return dict(binding_id=reg['id'], revision=reg.get('revision', ''), repository=reg, host_identity=before)

    @staticmethod
    def bound(lab, before):
        """The lab's binding when it was made on the VM connected now, else None."""
        binding = lab.get('git_binding')
        return binding if isinstance(binding, dict) and binding.get('host_identity') == before else None

    def own(self, lab, path, before):
        """The lab's folder in the checkout at `path` ('' is the top level), or None when it saves elsewhere or nowhere."""
        binding = self.bound(lab, before)
        if not binding or binding.get('repository', {}).get('path') != path: return None
        return str(binding['repository'].get('prefix') or '')

    def placed(self, lab, path, before):
        return dict(id=lab['id'], name=lab['name'], prefix=self.own(lab, path, before))

    def devices(self, lab, asked):
        """The devices of the new binding: the request's (refused only when invalid), else the lab's current selection
        still in the lab, else every supported device. No selection and an empty one both mean "not chosen here": the
        first save sends none, and nobody places a lab in order to save nothing."""
        supported = [n['name'] for n in lab.get('nodes', []) if n.get('platform') in PLATFORMS]
        if asked:
            if len(set(asked)) != len(asked) or not set(asked) <= set(supported): raise HTTPException(400, DEVICES)
            return list(asked)
        previous = (lab.get('git_binding') or {}).get('node_names') or []
        return [n for n in previous if n in supported] or supported

    def unfinished(self, lab_id):
        """A save of this lab that has not reached its commit (review F12): after a move its retry would write into the
        folder the lab left. Lab states and repository updates write elsewhere."""
        with self.store.lock:
            return any(j.get('lab_id') == lab_id and job_pending(j) and not j.get('commit') and j.get('kind') != 'state'
                       and j.get('target') != 'update' for j in self.store.state.get('git_jobs', []))

    def waiting(self, lab_id):
        """The saves of this lab that wait for upload with a commit (or may hold one) on the VM."""
        with self.store.lock:
            return [copy.deepcopy(j) for j in self.store.state.get('git_jobs', []) if j.get('lab_id') == lab_id and job_pending(j)
                    and may_hold_commit(j) and not j.get('pushed') and j.get('target') != 'update']

    def in_use(self):
        """The VM records a lab is connected to or a waiting save names (its own frozen binding, else its lab's): never
        the manager's to replace. Called under the store lock."""
        state = self.store.state; ids = set()
        labs = {lab['id']: lab for lab in state.get('labs', [])}
        for lab in labs.values():
            if isinstance(lab.get('git_binding'), dict): ids.add(lab['git_binding'].get('binding_id'))
        for job in state.get('git_jobs', []):
            if not (job_pending(job) or kept_on_vm(job)): continue
            frozen = job.get('binding') if isinstance(job.get('binding'), dict) else (labs.get(job.get('lab_id')) or {}).get('git_binding')
            if isinstance(frozen, dict): ids.add(frozen.get('binding_id'))
        return ids

    def bring(self, own, counts, folder, unfinished, purpose='save'):
        """Whether the line that brings the lab's saved files along applies to `folder` (DESIGN.md 2.6, review F12)."""
        if own is None or purpose == 'state':
            return {'offered': False, 'files': 0, 'from': '' if own is None else own, 'reason': 'state' if purpose == 'state' else 'elsewhere'}
        files = counts.get(own, 0)
        reason = ('same' if folder == own else 'nothing' if not files else 'not-empty' if counts.get(folder, 0)
                  else 'unfinished' if unfinished else '')
        return {'offered': not reason, 'files': files, 'from': own, 'reason': reason}

    # ----- the checkouts on the VM and the default place (DESIGN.md 2.8)

    def checkouts(self, catalog, lab, before):
        binding = self.bound(lab, before) or {}
        here = binding.get('repository', {}).get('path')
        groups = {}
        for reg in catalog: groups.setdefault(reg['path'], []).append(reg)
        rows = []
        for path, regs in groups.items():
            mine = next((r for r in regs if r['id'] == binding.get('binding_id')), None) if path == here else None
            pick = mine or next((r for r in regs if r.get('prefix') == ''), None) or regs[0]
            named = pick if pick.get('push_url') else next((r for r in regs if r.get('push_url')), pick)
            # `remote` and `branch`: where uploads of this repository go, for the place being chosen (both are public on a binding).
            rows.append(dict(id=pick['id'], name=repository_display_name(named), remote=strip_credentials(named.get('push_url', '')),
                             branch=str(named.get('branch') or ''), path=path, current=path == here, reg=pick))
        return rows

    def history(self, lab_id, before):
        """(the checkout this lab used last, {checkout: newest save there}) from the manager's own jobs."""
        last = ''; used = {}; newest = ''
        with self.store.lock:
            for job in self.store.state.get('git_jobs', []):
                where = (job.get('destination') or {}).get('checkout')
                if not where or (job.get('host_identity') or before) != before: continue
                created = str(job.get('created') or '')
                used[where] = max(used.get(where, ''), created)
                if job.get('lab_id') == lab_id and created >= newest: newest, last = created, where
        return last, used

    def default(self, lab, rows, before):
        """`git_places.default_place` with the checkout view built only for the repository it will choose."""
        here = next((r['path'] for r in rows if r['current']), '')
        last, used = self.history(lab['id'], before)
        last = here or last
        entries = [dict(id=r['id'], name=r['name'], path=r['path'], last_used=used.get(r['path'], ''), prefix=self.own(lab, r['path'], before)) for r in rows]
        chosen = (next((e for e in entries if last and e['path'] == last), None) or
                  (max((e for e in entries if e['last_used']), key=lambda e: e['last_used'], default=None)) or
                  min(entries, key=lambda e: (str(e['name'] or '').lower(), str(e['path'] or ''))))
        for attempt in range(2):
            view = self.progress.checkout_view(self.handle(next(r['reg'] for r in rows if r['path'] == chosen['path']), before))
            place = git_places.default_place(dict(id=lab['id'], name=lab['name'], prefix=None, last_repository=last),
                                             [dict(e, checkout=view) if e is chosen else e for e in entries])
            if place['repository'] == chosen['id'] or attempt: break
            chosen = next(e for e in entries if e['id'] == place['repository'])
        own = self.own(lab, chosen['path'], before)
        place['answer'] = dict(place['answer'], bring=self.bring(own, saved_index(view['files']), place['answer']['folder'], self.unfinished(lab['id'])))
        return place

    def tree(self, lab, reg, before):
        view = self.progress.checkout_view(self.handle(reg, before))
        own = self.own(lab, reg['path'], before); counts = saved_index(view['files']); unfinished = self.unfinished(lab['id'])
        folders = [dict(a, bring=self.bring(own, counts, a['folder'], unfinished))
                   for a in git_places.folder_answers(dict(id=lab['id'], name=lab['name'], prefix=own), view)]
        sizes = view.get('sizes') or {}
        # `truncated`: the file list was cut at the tree cap; `dirs_truncated`: a folder may be missing from `folders` too
        # (the chooser then says so; with every directory listed it must not).
        return dict(repository=reg['id'], head=view.get('head', ''), truncated=bool(view.get('truncated')), dirs_truncated=bool(view.get('dirs_truncated')),
                    saved=view.get('saved') or {},
                    folders=folders, files=[dict(path=p, size=sizes.get(p, 0)) for p in view['files']],
                    own=None if own is None else dict(folder=own, files=counts.get(own, 0)))

    # ----- placing a lab (POST …/git/place)

    def connect(self, url, initialize):
        """Connect the checkout of `url` at its top level, exactly what guided setup registers. Returns a registration,
        or the empty-repository question."""
        request = {'mode': 'connect', 'url': url, 'prefix': ''}
        if initialize: request['initialize'] = True
        try: reg = self.progress.invoke(request)
        except ValueError as exc:
            text = str(exc)
            if text.startswith(EMPTY_REPOSITORY) and not initialize:
                return None, {'question': {'kind': 'empty', 'name': remote_name(url), 'bring': self.bring(None, {}, '', False)}}
            # A checkout of this repository the VM already holds (a top level it would not take, for one) is used as it is.
            known = [r for r in self.catalog() if same_remote(r.get('push_url'), url)]
            reg = next((r for r in known if r.get('prefix') == ''), None) or (known[0] if known else None)
            if not reg: raise HelperRefused(text, clean_text(text))
        if not isinstance(reg, dict) or not reg.get('id') or not isinstance(reg.get('path'), str): raise HTTPException(409, NO_ANSWER)
        return reg, None

    def colliding_question(self, placed, handle, folder, hits):
        """The one-button question for a folder that collides with saves on the VM the manager may not replace."""
        self.progress.forget_views()
        view = self.progress.checkout_view(handle, fresh=True)
        answer = git_places.place_answer(placed, view, folder)
        if answer['kind'] != 'lab' or not answer['collision']:
            with self.store.lock: labs = self.progress.bound_labs()
            who = next((labs[h['id']] for h in hits if h['id'] in labs), None)
            beside = git_places.Tree(placed, view).beside(folder, git_places.folder_name(placed['name']))
            answer = dict(answer, kind='lab', collision=True, lab=dict(who) if who else None, beside=beside, mark='')
        counts = saved_index(view['files'])
        question = dict(answer, bring=self.bring(placed['prefix'], counts, answer['folder'], self.unfinished(placed['id'])))
        if question['lab'] is None: question['sentence'] = IN_USE
        return {'question': question}

    def register(self, placed, handle, folder, before):
        """The VM record of `folder` (an existing one is reused; nothing is retired). On a collision with records nothing
        uses, those are replaced (review F6, F7); otherwise the answer is the one-button question."""
        try: return self.progress.invoke({'mode': 'register-prefix', 'prefix': folder}, handle), None
        except ValueError as exc: text = str(exc)
        path = handle['repository']['path']
        regs = [r for r in self.catalog() if r['path'] == path]
        hits = [r for r in regs if git_places.colliding(folder, str(r.get('prefix') or ''))]
        if not hits: raise HelperRefused(text, clean_text(text), checkout=(handle['host_identity'], path))
        # Decided under the store lock; `changing` keeps every other connection change out until this request ends.
        with self.store.lock: used = self.in_use()
        if any(h['id'] in used for h in hits): return None, self.colliding_question(placed, handle, folder, hits)
        spare = next((r for r in regs if r not in hits), None)
        try:
            for extra in hits[:-1]:
                if spare is None: return None, self.colliding_question(placed, handle, folder, hits)
                self.progress.invoke({'mode': 'register-prefix', 'prefix': spare.get('prefix', ''), 'retire': True}, self.handle(extra, before))
            return self.progress.invoke({'mode': 'register-prefix', 'prefix': folder, 'retire': True}, self.handle(hits[-1], before)), None
        except ValueError:
            # The VM keeps a record that holds a waiting save (H7), or it changed meanwhile: the person chooses.
            return None, self.colliding_question(placed, handle, folder, hits)

    def housekeeping(self, path, folder, keep, before):
        """DESIGN.md 2.4, review F13: above 200 VM records of one checkout, retire up to five that nothing uses, oldest
        first, through the helper's own safe retire. Best effort: a refusal is ignored and nothing reaches the person."""
        try:
            regs = [r for r in self.catalog() if r['path'] == path]
            if len(regs) <= HOUSEKEEPING_ABOVE: return
            with self.store.lock: used = self.in_use()
            for reg in [r for r in regs if r['id'] not in used and r['id'] != keep and r.get('prefix') != folder][:HOUSEKEEPING_BATCH]:
                try: self.progress.invoke({'mode': 'register-prefix', 'prefix': folder, 'retire': True}, self.handle(reg, before))
                except ValueError: continue
        except Exception: return
        finally: self.progress.forget_views()

    def place(self, lab_id, data):
        raw = data.folder
        if len(raw) > RAW_LIMIT: raise HTTPException(400, TOO_LONG)
        try: git_places.clean_folder(raw)
        except ValueError: raise HTTPException(400, TOO_LONG)
        url = data.url.strip(); repository = data.repository.strip()
        if bool(url) == bool(repository): raise HTTPException(400, NO_SOURCE)
        if self.store.reset_pending: raise HTTPException(409, RESETTING)
        before = self.host(); lab = self.lab(lab_id)
        node_names = self.devices(lab, data.node_names)
        bound = self.bound(lab, before)
        if url and not data.acknowledge and not (bound and same_remote(bound['repository'].get('push_url'), url)): raise HTTPException(400, ACKNOWLEDGE)
        if url:
            reg, question = self.connect(url, data.initialize)
            if question: return question
        else: reg = self.registration(repository, fresh=True)
        path = reg['path']; here = bool(bound) and bound['repository'].get('path') == path
        if not data.acknowledge and not here: raise HTTPException(400, ACKNOWLEDGE)
        handle = self.handle(reg, before)
        view = self.progress.checkout_view(handle, fresh=True)
        own = str(bound['repository'].get('prefix') or '') if here else None
        placed = dict(id=lab_id, name=lab['name'], prefix=own)
        try: answer = git_places.place_answer(placed, view, raw)
        except ValueError: raise HTTPException(400, TOO_LONG)
        counts = saved_index(view['files']); unfinished = self.unfinished(lab_id)

        def ask(found, **more): return {'question': dict(found, bring=self.bring(own, counts, found['folder'], unfinished), **more)}

        kind = answer['kind']; folder = answer['folder']; take = None
        if kind in ('lab', 'state') and data.choice == 'beside':
            folder = answer['beside']
            again = git_places.place_answer(placed, view, folder) if folder else None
            if not again or again['kind'] != 'free' or again['folder'] != folder: return ask(again or answer)
            answer = again
        elif kind == 'lab' and answer['collision']:
            if answer['lab'] is not None: return ask(answer)       # the other lab's saves lie inside: only beside is offered
        elif kind == 'lab':
            if data.choice != 'take': return ask(answer)
            take = answer['lab']['id']
        elif kind == 'state':
            if data.choice != 'take': return ask(answer)       # take: Replace it (latest) or use it beside a flat state

        changes = not here or folder != own
        current = next((r for r in view['registrations'] if bound and r['id'] == bound.get('binding_id') and r.get('revision') == bound.get('revision')), None)
        if not changes and current and (data.node_names is None or list(node_names) == list(bound.get('node_names') or [])):
            return {'saved': True, 'binding': bound, 'job': None, 'moved': False, 'move_reason': ''}
        if changes and data.pending != 'keep':
            waiting = self.waiting(lab_id)
            if waiting:
                names = [str(j.get('note') or '') or ('Folder move' if j.get('target') == 'move' else 'Unnamed save') for j in waiting]
                return {'question': {'kind': 'pending', 'count': len(waiting), 'names': names, 'folder': folder,
                                     'bring': self.bring(own, counts, folder, unfinished)}}

        created, question = self.register(placed, handle, folder, before)
        if question: return question
        if not isinstance(created, dict) or not created.get('id') or created.get('path') != path: raise HTTPException(409, NO_ANSWER)

        dropped = []
        with self.store.lock:
            if host_identity(self.store.state.get('host', {})) != before: raise HTTPException(409, VM_CHANGED)
            target = self.store.lab(lab_id)
            if not target: raise HTTPException(404, LAB_GONE)
            node_names = self.devices(target, data.node_names)   # the lab as it is now
            # A new dict: the stored binding is replaced, never edited (pending saves keep their own copy).
            binding = dict(binding_id=created['id'], revision=created.get('revision', ''), repository=copy.deepcopy(created), host_identity=before,
                           node_names=list(node_names), review_before_push=True)
            # One lab per VM record, checked again right before storing (review "Point 9": the take is one section).
            others = [o for o in self.store.state['labs'] if o['id'] != lab_id and isinstance(o.get('git_binding'), dict)
                      and (o['git_binding'].get('binding_id') == created['id'] or (o['git_binding'].get('host_identity') == before
                           and o['git_binding'].get('repository', {}).get('path') == path and str(o['git_binding']['repository'].get('prefix') or '') == folder))]
            conflict = bool(others) and not (take and all(o['id'] == take for o in others))
            if not conflict:
                old = target.get('git_binding'); dropped = [(o, o['git_binding']) for o in others]
                for other, _ in dropped: other.pop('git_binding', None)
                target['git_binding'] = binding
                try: self.store.save()
                except OSError:
                    for other, previous in dropped: other['git_binding'] = previous
                    if old is None: target.pop('git_binding', None)
                    else: target['git_binding'] = old
                    raise HTTPException(500, STORE_FAILED)
        if conflict:
            # Another lab took this folder meanwhile: the person is asked again, never refused.
            self.progress.forget_views()
            fresh = self.progress.checkout_view(handle, fresh=True)
            return {'question': dict(git_places.place_answer(placed, fresh, folder), bring=self.bring(own, saved_index(fresh['files']), folder, unfinished))}
        if bound: self.progress.remember_folders(bound['repository'].get('path', ''), str(bound['repository'].get('prefix') or ''))
        self.progress.remember_folders(path, folder)
        self.progress.forget_views()
        for other, _ in dropped: self.store.event('git.unlink', 'Lab disconnected from its folder: another lab now saves there.', lab_id=other['id'])
        self.store.event('git.destination' if bound else 'git.connect', 'Lab now saves to ' + shown(folder) + ' in ' + repository_display_name(created) + '.', lab_id=lab_id)

        job = None; moved = False; reason = ''
        if data.move_files:
            with self.store.lock:
                line = self.bring(own, counts, folder, self.unfinished(lab_id))
                if line['offered']:
                    request = dict(source_prefix=own, push=False, message='Move ' + lab['name'] + ' progress to ' + (folder + '/' if folder else 'the repository top level'))
                    job = dict(id=uuid.uuid4().hex, lab_id=lab_id, lab_name=lab['name'], created=now(), status='queued', message='Folder move queued.',
                               backup_job_id='', target='move', checkpoint='', note='', pushed=False, review_before_push=False,
                               binding_digest=digest(binding), binding=copy.deepcopy(binding), request=request,
                               want_push=False,   # a move never uploads by itself (review F2): it waits for Upload like a save
                               node_names=list(node_names), capture_context={}, destination=move_destination(binding), host_identity=before)
                    _append_git_job(self.store.state, job)
                    try: self.store.save()
                    except OSError:
                        self.store.state['git_jobs'].remove(job); job = None; line = dict(line, reason='queue')
            if job: job = self.progress.schedule(job); moved = True
            else: reason = MOVE_REASONS[line['reason']].format(old=shown(own or ''))
        if len(view['registrations']) >= HOUSEKEEPING_ABOVE: self.housekeeping(path, folder, created['id'], before)
        return {'saved': True, 'binding': binding, 'job': job, 'moved': moved, 'move_reason': reason}

    # ----- New folder… (always possible, PROMPT 6.2)

    def new_folder(self, rid, data):
        if len(data.parent) > RAW_LIMIT or len(data.name) > RAW_LIMIT: raise HTTPException(400, TOO_LONG)
        before = self.host(); reg = self.registration(rid)
        lab = self.lab(data.lab_id) if data.lab_id else {'id': '', 'name': ''}
        placed = self.placed(lab, reg['path'], before) if data.lab_id else dict(id='', name='', prefix=None)
        handle = self.handle(reg, before)
        view = self.progress.checkout_view(handle)
        tree = git_places.Tree(placed, view)
        try:
            parent = git_places.clean_folder(data.parent)
            name = git_places.clean_folder(data.name)
        except ValueError: raise HTTPException(400, TOO_LONG)
        typed = '/'.join(p.strip() for p in data.name.split('/') if p.strip()); typed_parent = '/'.join(p.strip() for p in data.parent.split('/') if p.strip())
        corrected = name != typed or parent != typed_parent
        if not name: name = 'folder'; corrected = True
        above = '/'.join(tree.leave_state(parent.split('/') if parent else []))
        full = git_places.join(above, name)
        try: git_places.clean_folder(full)
        except ValueError: raise HTTPException(400, TOO_LONG)
        folder = '/'.join(tree.leave_state(full.split('/')))
        adjusted = 'above-state' if above != parent or folder != full else 'corrected' if corrected else ''
        existed = folder in tree.listed
        if not existed:
            self.progress.remember_folders(reg['path'], folder)
            if folder not in self.progress.planned_folders(reg['path']): raise HTTPException(500, FOLDER_NOT_STORED)
            self.store.event('git.folder', 'Repository folder planned for later saves.', lab_id=data.lab_id)
        view = self.progress.checkout_view(handle)   # the helper's part is cached; the planned folders are read again
        answer = git_places.place_answer(placed, view, folder)
        own = placed['prefix']
        answer['bring'] = self.bring(own, saved_index(view['files']), answer['folder'], self.unfinished(lab['id']) if lab['id'] else False)
        return {'folder': folder, 'existed': existed, 'adjusted': adjusted, 'answer': answer}

    # ----- routes

    def install(self, app):
        progress = self.progress

        class Check(BaseModel):
            model_config = ConfigDict(extra='forbid')
            repository: str = Field(min_length=1, max_length=120)
            folder: str = Field(default='', max_length=65536)
            purpose: Literal['', 'save', 'state'] = 'save'
            name: str = Field(default='', max_length=200)

        class Place(BaseModel):
            model_config = ConfigDict(extra='forbid')
            repository: str = Field(default='', max_length=120)
            url: str = Field(default='', max_length=2048)
            folder: str = Field(default='', max_length=65536)
            choice: Literal['', 'beside', 'take'] = ''
            pending: Literal['', 'keep'] = ''
            move_files: bool = False
            node_names: Optional[list[str]] = Field(default=None, max_length=500)
            acknowledge: bool = False
            initialize: bool = False

        class NewFolder(BaseModel):
            model_config = ConfigDict(extra='forbid')
            lab_id: str = Field(default='', max_length=64)
            parent: str = Field(default='', max_length=65536)
            name: str = Field(default='', max_length=65536)

        @app.get('/api/labs/{lab_id}/git/places')
        def places(lab_id: str, repository: str = Query(default='', max_length=120)):
            lab = self.lab(lab_id); before = self.host()
            catalog = self.catalog()
            rows = self.checkouts(catalog, lab, before)
            out = dict(repositories=[{k: r[k] for k in ('id', 'name', 'remote', 'branch', 'path', 'current')} for r in sorted(rows, key=lambda r: (r['name'].lower(), r['path']))],
                       default=self.default(lab, rows, before) if rows else None)
            if repository:
                reg = next((r for r in catalog if r['id'] == repository), None)
                if not reg: raise HTTPException(404, UNKNOWN)
                out['tree'] = self.tree(lab, reg, before)
            return out

        @app.post('/api/labs/{lab_id}/git/places/check')
        def check(lab_id: str, data: Check):
            if len(data.folder) > RAW_LIMIT: raise HTTPException(400, TOO_LONG)
            lab = self.lab(lab_id); before = self.host()
            reg = self.registration(data.repository)
            view = progress.checkout_view(self.handle(reg, before))
            placed = self.placed(lab, reg['path'], before); purpose = 'state' if data.purpose == 'state' else 'save'
            try: answer = git_places.place_answer(placed, view, data.folder, purpose, data.name)
            except ValueError: raise HTTPException(400, TOO_LONG)
            answer['bring'] = self.bring(placed['prefix'], saved_index(view['files']), answer['folder'], self.unfinished(lab_id), purpose)
            return answer

        @app.post('/api/labs/{lab_id}/git/place')
        def place(lab_id: str, data: Place):
            with progress.changing(lab_id):
                # A refusal of the VM is the lab's status before it is the answer (the chip then says why, like a refused save).
                try: result = self.place(lab_id, data)
                except HelperRefused as exc: progress.placement_refused(lab_id, exc); raise
                # What was remembered described the folder the lab left (or a refusal that is over): the next check says anew.
                if result.get('saved'): progress.statuses.pop(lab_id, None)
                return result

        @app.post('/api/git/repositories/{binding_id}/folders/new')
        def new_folder(binding_id: str, data: NewFolder):
            return self.new_folder(binding_id, data)


def install(app, progress):
    placement = Placement(progress)
    app.state.git_place = placement
    placement.install(app)
    return placement
