import copy
import json
import os
from pathlib import Path
import shutil
import uuid
import threading
from datetime import datetime, timezone
from cryptography.fernet import Fernet

class Store:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.lock = threading.RLock()
        key = self.root/'state.key'
        if not key.exists():
            self.atomic(key, Fernet.generate_key())
        self.cipher = Fernet(key.read_bytes())
        token = self.root/'ui.token'
        self.token = token.read_text().strip() if token.exists() else ''  # Legacy token is no longer used for access.
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
        with open(tmp, 'wb') as f:
            os.chmod(tmp, 0o600)
            f.write(content)
        os.replace(tmp, path)
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
        """Resume a durable reset journal before any worker writes new state."""
        stage = self.root/'.reset-pending'
        if not stage.exists(): return
        self.checked_tree(stage)
        prepared = stage/'new-state.enc'
        if not prepared.exists():
            # A failure creating the journal cannot have moved managed files yet.
            if any(stage.iterdir()): raise OSError('Incomplete reset journal needs attention.')
            stage.rmdir(); return
        payload = prepared.read_bytes()
        fresh = json.loads(self.cipher.decrypt(payload))
        current = json.loads(self.cipher.decrypt(self.path.read_bytes())) if self.path.exists() else {}
        if current.get('reset_id') != fresh['reset_id']:
            for name in ('backups', 'events.jsonl', 'events.jsonl.1', 'events.jsonl.2', 'events.jsonl.3', 'ui.token'):
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

    def reset(self):
        with self.lock:
            if self.reset_pending:
                self.finish_reset(); return
            for name in ('backups', 'events.jsonl', 'events.jsonl.1', 'events.jsonl.2', 'events.jsonl.3', 'ui.token'):
                self.checked_tree(self.root/name)
            host = copy.deepcopy(self.state.get('host', {}))
            if host: host['revision'] = uuid.uuid4().hex
            fresh = {'labs': [], 'jobs': [], 'operations': [], 'git_jobs': [], 'ignored_labs': [],
                     'host': host, 'reset_id': uuid.uuid4().hex}
            stage = self.root/'.reset-pending'
            stage.mkdir(mode=0o700)
            self.atomic(stage/'new-state.enc', self.cipher.encrypt(json.dumps(fresh).encode()))
            self.finish_reset()
    def lab(self, lab_id):
        return next((x for x in self.state['labs'] if x['id'] == lab_id), None)

    def event(self, action, message, *, level='info', lab_id='', job_id='', node=''):
        # Callers supply controlled metadata or scrubbed errors, never command output.
        entry = dict(time=datetime.now(timezone.utc).isoformat(), action=action,
                     message=str(message)[:4000], level=level, lab_id=lab_id,
                     job_id=job_id, node=node)
        with self.lock:
            path=self.root/'events.jsonl'
            # Keep a bounded operational log: active file plus three 5 MiB rotations.
            if path.exists() and path.stat().st_size >= 5*1024*1024:
                for index in (3,2,1):
                    source=path if index==1 else self.root/f'events.jsonl.{index-1}'
                    if source.exists(): source.replace(self.root/f'events.jsonl.{index}')
            fd=os.open(path, os.O_WRONLY|os.O_CREAT|os.O_APPEND, 0o600)
            with os.fdopen(fd,'a',encoding='utf8') as stream:
                stream.write(json.dumps(entry)+'\n')
        return entry

    def events(self, lab_id='', job_id='', level='', node='', limit=500):
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
                    result.append(entry)
                    if len(result)>=limit: return result
            return result
