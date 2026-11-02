import copy
import json
import logging
import os
from pathlib import Path
import shutil
import uuid
import threading
from datetime import datetime, timezone
from cryptography.fernet import Fernet

AUDIT_FILE = 'audit.jsonl'               # the security record (sign-on DESIGN.md 10.1)
AUDIT_FAILURES_FILE = 'audit-failures.jsonl'   # what a scanner can produce at will, summed per source and minute
# The files a reset moves aside. The two audit files and their rotations are never in this list: the
# manager never moves, deletes or truncates them except by their own rotation (DESIGN.md 3.3, ruling 7).
# `ui.token` is no longer read by anything; it stays here so an old install's file is still moved aside.
RESET_MOVES = ('backups', 'network-design', 'events.jsonl', 'events.jsonl.1', 'events.jsonl.2', 'events.jsonl.3', 'ui.token')

class Store:
    ROTATE_BYTES = 5*1024*1024   # every log file: the active file plus three rotations of this size
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.lock = threading.RLock()
        self.event_error = False
        self.audit_error = False
        self.audit_failures_error = False
        key = self.root/'state.key'
        if not key.exists():
            self.atomic(key, Fernet.generate_key())
        self.cipher = Fernet(key.read_bytes())
        self.path = self.root/'state.enc'
        self.finish_reset()
        self.state = json.loads(self.cipher.decrypt(self.path.read_bytes())) if self.path.exists() else {'labs': [], 'jobs': []}
        for job in self.state['jobs']:
            if job['status'] in ('queued','running'):
                job['status'] = 'interrupted'
                job['message'] = 'Worker restarted during this job; run again.'
        self.save()
        self.event('worker.start', 'Worker initialized; unfinished jobs marked interrupted')
    @staticmethod
    def atomic(path, content):
        tmp = path.with_name(path.name+'.tmp')
        try:
            with open(tmp, 'wb') as f:
                os.chmod(tmp, 0o600)
                f.write(content)
            os.replace(tmp, path)
        except BaseException:
            # A failed write (full disk) must not leave its half-written temporary file behind.
            tmp.unlink(missing_ok=True)
            raise
    def save(self):
        with self.lock:
            self.atomic(self.path, self.cipher.encrypt(json.dumps(self.state).encode()))
    def snapshot(self):
        with self.lock:
            return copy.deepcopy(self.state)

    @property
    def reset_pending(self):
        return (self.root/'.reset-pending').exists()

    def checked_tree(self, path):
        root = self.root.resolve()
        if path.is_symlink() or getattr(path, 'is_junction', lambda: False)() or not path.resolve().is_relative_to(root) or path.resolve() == root:
            raise OSError('Unsafe manager storage path; reset stopped.')
        if path.is_dir():
            for child in path.iterdir(): self.checked_tree(child)

    def finish_reset(self):
        """Resume a durable reset journal before any worker writes new state; True when one was applied."""
        stage = self.root/'.reset-pending'
        if not stage.exists(): return False
        self.checked_tree(stage)
        prepared = stage/'new-state.enc'
        if not prepared.exists():
            # A failure creating the journal cannot have moved managed files yet: the only entry it can
            # leave is the journal's own temporary file (a write cut off before atomic() could remove it).
            partial = stage/'new-state.enc.tmp'
            entries = list(stage.iterdir())
            if entries == [partial] and partial.is_file(): partial.unlink()
            elif entries: raise OSError('Incomplete reset journal needs attention.')
            stage.rmdir(); return False
        payload = prepared.read_bytes()
        fresh = json.loads(self.cipher.decrypt(payload))
        current = json.loads(self.cipher.decrypt(self.path.read_bytes())) if self.path.exists() else {}
        if current.get('reset_id') != fresh['reset_id']:
            for name in RESET_MOVES:
                source = self.root/name
                if source.exists():
                    self.checked_tree(source)
                    os.replace(source, stage/name)
            self.atomic(self.path, payload)
        self.state = fresh
        # Validate the absolute staged tree again before recursive deletion.
        self.checked_tree(stage)
        for child in stage.iterdir():
            if child == prepared: continue
            if child.is_dir(): shutil.rmtree(child)
            else: child.unlink()
        prepared.unlink()
        stage.rmdir()
        return True

    def reset(self):
        with self.lock:
            # A journal that was never prepared is cleared and the reset then runs from the start.
            if self.reset_pending and self.finish_reset(): return
            for name in RESET_MOVES:
                self.checked_tree(self.root/name)
            host = copy.deepcopy(self.state.get('host', {}))
            if host: host['revision'] = uuid.uuid4().hex
            # `users` survives like `host`: a reset that emptied it would reopen setup mode on an exposed
            # address (DESIGN.md 3.3). A journal prepared by an older release carries no `users` and applies as it is.
            fresh = {'labs': [], 'jobs': [], 'operations': [], 'git_jobs': [], 'ignored_labs': [],
                     'host': host, 'users': copy.deepcopy(self.state.get('users', {})), 'reset_id': uuid.uuid4().hex}
            stage = self.root/'.reset-pending'
            stage.mkdir(mode=0o700)
            self.atomic(stage/'new-state.enc', self.cipher.encrypt(json.dumps(fresh).encode()))
            self.finish_reset()
    def lab(self, lab_id):
        return next((x for x in self.state['labs'] if x['id'] == lab_id), None)

    @staticmethod
    def now():
        return datetime.now(timezone.utc).isoformat(timespec='microseconds')

    @classmethod
    def append_line(cls, root, name, line):
        """Append one line to a bounded log under `root`: the active file plus three rotations of ROTATE_BYTES, mode 0600.
        A static operation so another process (app.recover) can write without a Store; raises OSError."""
        root = Path(root)
        path = root/name
        if path.exists() and path.stat().st_size >= cls.ROTATE_BYTES:
            for index in (3,2,1):
                source=path if index==1 else root/f'{name}.{index-1}'
                if source.exists(): source.replace(root/f'{name}.{index}')
        fd=os.open(path, os.O_WRONLY|os.O_CREAT|os.O_APPEND, 0o600)
        with os.fdopen(fd,'a',encoding='utf8') as stream:
            stream.write(line+'\n')

    def _warn_once(self, flag, failed, sentence):
        # A log write cannot undo a successful host action or state save. Report the gap once, without
        # echoing filesystem diagnostics or secrets, and stay silent until a write succeeds again.
        if failed and not getattr(self, flag):
            logging.getLogger(__name__).warning(sentence)
        setattr(self, flag, failed)

    def event(self, action, message, *, level='info', lab_id='', job_id='', node='', actor='-'):
        # Callers supply controlled metadata or scrubbed errors, never command output. `actor` is the user
        # name of the request in hand, or '-' for nobody (a background thread, a socket without a session);
        # never a source address, because GET /api/logs serves this file to every operator (DESIGN.md 10.3).
        entry = dict(time=self.now(), action=action,
                     message=str(message)[:4000], level=level, lab_id=lab_id,
                     job_id=job_id, node=node, actor=actor)
        with self.lock:
            try:
                self.append_line(self.root, 'events.jsonl', json.dumps(entry))
                self._warn_once('event_error', False, '')
            except OSError:
                self._warn_once('event_error', True, 'Action log write failed; check manager storage permissions and free space. Some audit events were not recorded.')
        return entry

    def events(self, lab_id='', job_id='', level='', node='', limit=500, actor=''):
        with self.lock:
            result=[]
            for suffix in ('','.1','.2','.3'):
                path=self.root/('events.jsonl'+suffix)
                if not path.exists(): continue
                for line in reversed(path.read_text().splitlines()):
                    try: entry=json.loads(line)
                    except ValueError: continue
                    if lab_id and entry['lab_id']!=lab_id: continue
                    if job_id and entry['job_id']!=job_id: continue
                    if level and entry['level']!=level: continue
                    if node and node.lower() not in entry['node'].lower(): continue
                    if actor and entry.get('actor','-')!=actor: continue
                    result.append(entry)
                    if len(result)>=limit: return result
            return result

    # ---- the audit files (sign-on DESIGN.md 10) ----
    @staticmethod
    def audit_entry(event, *, actor, source, outcome, target='', detail='', time=None):
        """The entry shape of both audit files. `detail` is controlled vocabulary (a reason, a count, a role),
        never user input, bounded to 200 characters; it never carries a password, a code, a session id or a hash."""
        return dict(time=time or Store.now(), event=event, actor=actor, source=source, outcome=outcome,
                    target=str(target)[:200], detail=str(detail)[:200])

    @classmethod
    def append_audit(cls, root, entry, name=AUDIT_FILE):
        """Append one entry to an audit file without a Store (app.recover runs in another process); raises OSError."""
        cls.append_line(root, name, json.dumps(entry))

    def audit(self, event, *, actor, source, outcome, target='', detail='', time=None):
        """The security record, audit.jsonl: its own rotation and its own write-failure flag."""
        entry = self.audit_entry(event, actor=actor, source=source, outcome=outcome, target=target, detail=detail, time=time)
        with self.lock:
            try:
                self.append_audit(self.root, entry, AUDIT_FILE)
                self._warn_once('audit_error', False, '')
            except OSError:
                self._warn_once('audit_error', True, 'Audit log write failed; check manager storage permissions and free space. Some security events were not recorded.')
        return entry

    def audit_failure(self, event, *, actor, source, outcome, detail, time=None):
        """audit-failures.jsonl: the summed failure events, so a flood cannot rotate the security record away."""
        entry = self.audit_entry(event, actor=actor, source=source, outcome=outcome, detail=detail, time=time)
        with self.lock:
            try:
                self.append_audit(self.root, entry, AUDIT_FAILURES_FILE)
                self._warn_once('audit_failures_error', False, '')
            except OSError:
                self._warn_once('audit_failures_error', True, 'Sign-in failure log write failed; check manager storage permissions and free space. Some failed attempts were not recorded.')
        return entry

    def audit_entries(self, limit, offset, *, event='', actor='', outcome='', since='', address='', extra=()):
        """Both audit files with their rotations, merged with `extra` (the open failure buckets) by time, newest
        first: (the page, the total after the filters). `event` is one code or a comma-separated list; an unknown
        code matches nothing. `address` matches the start of the `source` field."""
        events = {code.strip() for code in event.split(',') if code.strip()} if event else None
        floor = None
        if since:
            try: floor = datetime.fromisoformat(since)
            except ValueError: floor = None
            else:
                if floor.tzinfo is None: floor = floor.replace(tzinfo=timezone.utc)
        def keep(entry):
            if not isinstance(entry, dict) or 'time' not in entry: return False
            if events is not None and entry.get('event') not in events: return False
            if actor and entry.get('actor') != actor: return False
            if outcome and entry.get('outcome') != outcome: return False
            if address and not str(entry.get('source', '')).startswith(address): return False
            if floor is not None:
                try: when = datetime.fromisoformat(entry['time'])
                except (TypeError, ValueError): return False
                if when.tzinfo is None: when = when.replace(tzinfo=timezone.utc)
                if when < floor: return False
            return True
        result = [entry for entry in extra if keep(entry)]
        with self.lock:
            for name in (AUDIT_FILE, AUDIT_FAILURES_FILE):
                for suffix in ('', '.1', '.2', '.3'):
                    path = self.root/(name+suffix)
                    if not path.exists(): continue
                    for line in path.read_text(encoding='utf8').splitlines():
                        try: entry = json.loads(line)
                        except ValueError: continue
                        if keep(entry): result.append(entry)
        result.sort(key=lambda entry: str(entry['time']), reverse=True)
        return result[offset:offset+limit] if limit > 0 else [], len(result)
