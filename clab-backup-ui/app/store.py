import copy
import json
import os
from pathlib import Path
import secrets
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
        if not token.exists():
            self.atomic(token, secrets.token_urlsafe(32).encode())
        self.token = token.read_text().strip()
        self.path = self.root/'state.enc'
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
