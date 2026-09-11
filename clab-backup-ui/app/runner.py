import copy
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import tempfile
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import yaml
from .inventory import PLATFORMS
from .discovery import automatic_ready, node_available
from .downloads import short_name

APP = Path(__file__).parent

def now():
    return datetime.now(timezone.utc).isoformat()

def effective_credentials(lab, node):
    profile_id = node.get('profile_id') or lab.get('defaults',{}).get(node['platform'] or 'ssh')
    if profile_id:
        profile = next((p for p in lab['profiles'] if p['id']==profile_id),None)
        return profile or {}
    if node.get('username') and node.get('password'):
        return {'username':node['username'],'password':node['password'],'auth':'password','enable_password':node.get('enable_password','')}
    return {}

def readiness(lab,node):
    if node['platform'] not in PLATFORMS:
        return 'Choose NOS'
    creds=effective_credentials(lab,node)
    if not creds.get('username'):
        return 'Needs credentials'
    return 'Ready'

def make_inventory(lab, nodes, work, operation):
    hosts = {}
    for index,node in enumerate(nodes):
        platform = PLATFORMS[node['platform']]
        creds = effective_credentials(lab,node)
        variables = {'ansible_host':node['address'],'ansible_port':node['port'],
                     'ansible_connection':'ansible.netcommon.network_cli',
                     'ansible_network_cli_ssh_type':'paramiko',
                     'ansible_network_os':platform['os'],'ansible_user':creds['username'],
                     'ansible_host_key_checking':False,'ansible_paramiko_look_for_keys':False,
                     'ansible_connect_timeout':30,'ansible_command_timeout':300,
                     'backup_command':'show version' if operation=='test' else platform['command']}
        if node['platform']=='arista_ceos':
            variables.update(ansible_become=True, ansible_become_method='enable')
            if creds.get('enable_password'):
                variables['ansible_become_password']=creds['enable_password']
        variables['ansible_persistent_log_messages']=False
        if creds.get('auth')=='key':
            key = work/f'key-{index}'
            key.write_text(creds['private_key'])
            key.chmod(0o600)
            variables['ansible_private_key_file'] = str(key)
            if creds.get('passphrase'):
                variables['ansible_password'] = creds['passphrase']
        else:
            variables['ansible_password'] = creds.get('password','')
        # Internal aliases cannot inject inventory patterns or filenames.
        hosts[f'node_{index}'] = variables
    return {'all':{'children':{'targets':{'hosts':hosts}}}}

def filename(node):
    base=re.sub(r'[^A-Za-z0-9_.-]','_',node['name'])[:100].strip('.') or 'node'
    digest=hashlib.sha256(node['name'].encode()).hexdigest()[:8]
    return f'{base}-{digest}.{PLATFORMS[node["platform"]]["suffix"]}'

def normalized(platform, text):
    if not isinstance(text,str):
        raise ValueError('NOS returned an unexpected output type; previous backup retained')
    if platform=='cisco_xrv9k':
        text='\n'.join(x for x in text.splitlines() if not re.match(r'^(Building configuration|[A-Z][a-z]{2} [A-Z][a-z]{2} +\d+ )',x))
    if re.search(r'(?im)^\s*(?:%\s*(?:Invalid|Error|Incomplete|Ambiguous|Authorization|Access denied)|error:|syntax error|System is not yet ready|Waiting for editing of configuration)',text):
        raise ValueError('NOS returned a CLI error or is not ready; previous backup retained')
    if not text.strip():
        raise ValueError('NOS returned empty output; previous backup retained')
    return text.rstrip()+'\n'

class Runner:
    def __init__(self, store):
        self.store=store
        self.pool=ThreadPoolExecutor(max_workers=1)
        self.stopping=threading.Event()
        self.scheduler=threading.Thread(target=self.tick,daemon=True)
    def start(self):
        self.scheduler.start()
    def close(self):
        self.stopping.set()
        self.pool.shutdown(wait=False,cancel_futures=True)
    def submit(self, lab_id, operation='backup', source='manual', node_names=None, progress_id=None, progress_context=None):
        from .lab_operations import operation_busy
        with self.store.lock:
            if operation_busy(self.store.state,lab_id,progress_id=progress_id): raise ValueError('Wait for the lab operation to finish.')
            if self.store.reset_pending: raise ValueError('Finish the manager reset before starting a job.')
            if any(j['status'] in ('queued','running') for j in self.store.state['jobs']):
                raise ValueError('A job is already running. Wait for it to finish.')
            lab=self.store.lab(lab_id)
            if not lab:
                raise ValueError('Lab not found')
            if source=='scheduled' and not automatic_ready(self.store.state,lab):
                raise ValueError('Scheduled backup paused: lab discovery is unavailable or the lab is not fully running')
            if node_names is not None:
                known={n['name'] for n in lab['nodes']}
                if not node_names or len(set(node_names))!=len(node_names) or not set(node_names)<=known:
                    raise ValueError('Select existing, distinct nodes')
            nodes=[copy.deepcopy(n) for n in lab['nodes']
                   if (n['name'] in node_names if node_names is not None else n['enabled'])]
            if not nodes:
                raise ValueError('Enable at least one supported node')
            if any(not node_available(self.store.state,lab,n) for n in nodes):
                raise ValueError('Selected nodes are not currently available. Refresh VM discovery before connecting.')
            missing=[n['name'] for n in nodes if readiness(lab,n)!='Ready']
            if missing:
                raise ValueError('Complete NOS and credentials for: '+', '.join(missing[:8]))
            job={'id':uuid.uuid4().hex,'lab_id':lab_id,'lab_name':lab['name'],
                 'operation':operation,'created':now(),'status':'queued','message':'Waiting for SSH worker',
                 'nodes':[{'name':n['name'],'status':'queued'} for n in nodes]}
            if progress_id:
                job.update(progress_id=progress_id, progress_context=copy.deepcopy(progress_context or {}))
            self.store.state['jobs'].insert(0,job)
            # History records are retained alongside snapshots; no automatic deletion.
            old_next_run = lab.get('next_run')
            if node_names is None:
                lab['next_run']=time.time()+lab['interval']*60 if lab['interval'] else None
            try: self.store.save()
            except OSError:
                self.store.state['jobs'].remove(job)
                if node_names is None: lab['next_run'] = old_next_run
                raise
            try: self.store.event('job.queued',f'{source} {operation}: {len(nodes)} nodes queued',lab_id=lab_id,job_id=job['id'])
            except OSError: pass  # A log failure must not orphan a durable capture request.
            try: self.pool.submit(self.execute,job['id'],copy.deepcopy(lab),nodes,operation)
            except RuntimeError:
                job.update(status='interrupted', message='Worker stopped before the capture started.')
                self.store.save()
            return copy.deepcopy(job)
    def update(self, job_id, **fields):
        with self.store.lock:
            job=next(j for j in self.store.state['jobs'] if j['id']==job_id)
            job.update(fields)
            self.store.save()
    def execute(self, job_id, lab, nodes, operation):
        try:
            self._execute(job_id, lab, nodes, operation)
        except Exception:
            # Initial/terminal state writes can fail outside the capture's normal
            # error handling. Never leave a dead worker marked queued/running:
            # Git progress waits for this job's terminal state. If storage stays
            # unavailable, retain the interruption in memory; Store recovers the
            # older durable queued/running record on the next restart.
            message = 'Job interrupted before its result could be finalized. Existing backup files were retained; check storage and retry.'
            with self.store.lock:
                job = next((j for j in self.store.state['jobs'] if j['id'] == job_id), None)
                if job is None: return
                job.update(status='interrupted', finished=now(), message=message)
                for node in job.get('nodes', []):
                    if node.get('status') in ('queued', 'running'):
                        node.update(status='interrupted', message=message)
                try: self.store.save()
                except OSError: pass

    def _execute(self, job_id, lab, nodes, operation):
        self.update(job_id,status='running',message='Opening NOS CLI sessions over SSH',started=now(),
                    nodes=[{'name':n['name'],'status':'queued'} for n in nodes])
        outcomes=[]
        secrets_to_hide=[self.store.token]
        for n in nodes:
            c=effective_credentials(lab,n)
            secrets_to_hide.extend(c.get(k,'') for k in ('password','passphrase','private_key','enable_password'))
        def safe_error(message):
            message=str(message)
            message=re.sub(r'-----BEGIN [^-]*PRIVATE KEY-----.*?-----END [^-]*PRIVATE KEY-----', '[redacted key]', message, flags=re.S)
            for secret in sorted(filter(None,secrets_to_hide),key=len,reverse=True):
                message=message.replace(secret,'[redacted]')
            # Exceptions may echo device buffers containing config; omit these sections.
            message=re.split(r'(?i)(?:command output|last response|buffer|stdout|stderr)\s*[:=]',message)[0]
            message=re.sub(r'(?im)^.*(?:password|secret|community|private.key|passphrase).*$', '[sensitive diagnostic omitted]', message)
            return message[:1500]
        def log(action,message,level='info',node=''):
            try: self.store.event(action,safe_error(message),level=level,lab_id=lab['id'],job_id=job_id,node=node)
            except OSError: pass  # Capture/state persistence must not depend on audit-log availability.
        log('job.start',f'{operation} started for {len(nodes)} nodes')
        try:
            with tempfile.TemporaryDirectory(prefix='ssh-job-') as tmp:
                work=Path(tmp)
                inventory=make_inventory(lab,nodes,work,operation)
                for node in nodes:
                    log('node.prepare',f"{node['platform']} / {PLATFORMS[node['platform']]['os']} at {node['address']}:{node['port']}; "
                        + ('enable mode required; ' if node['platform']=='arista_ceos' else '')
                        + ('show version' if operation=='test' else PLATFORMS[node['platform']]['command']),node=node['name'])
                inv=work/'inventory.yml'; inv.write_text(yaml.safe_dump(inventory,sort_keys=False)); inv.chmod(0o600)
                event=work/'events.jsonl'; event.touch(mode=0o600)
                env={**os.environ,'ANSIBLE_CONFIG':str(APP/'ansible/ansible.cfg'),
                     'ANSIBLE_CALLBACK_PLUGINS':str(APP/'ansible/callback_plugins'),
                     'ANSIBLE_STDOUT_CALLBACK':'backup_events','BACKUP_EVENT_FILE':str(event),
                     'ANSIBLE_PERSISTENT_LOG_MESSAGES':'False','ANSIBLE_DEBUG':'False','ANSIBLE_VERBOSITY':'0'}
                results={}
                offset=0
                def consume():
                    nonlocal offset
                    with event.open() as stream:
                        stream.seek(offset)
                        while True:
                            line=stream.readline()
                            if not line or not line.endswith('\n'): break
                            offset=stream.tell()
                            item=json.loads(line)
                            alias=item.get('host','')
                            if not re.fullmatch(r'node_\d+',alias): continue
                            index=int(alias[5:])
                            if index>=len(nodes): continue
                            node=nodes[index]
                            status=item['status']
                            if status!='running':
                                item.setdefault('captured_at',now())
                                results[alias]=item
                            detail=(item.get('task','NOS command') + ': ' + status)
                            if status in ('failed','unreachable'):
                                detail+=': '+safe_error(item.get('message','SSH command failed'))
                            if status=='ok': detail+=f"; {len(item.get('stdout','').encode())} bytes received"
                            log('ssh.task.'+status,detail,'error' if status in ('failed','unreachable') else 'info',node['name'])
                            with self.store.lock:
                                job=next(j for j in self.store.state['jobs'] if j['id']==job_id)
                                job['nodes'][index].update(status='running' if status=='ok' else status,message=detail)
                                self.store.save()
                with open(work/'process.log','w') as process_log:
                    proc=subprocess.Popen(['ansible-playbook','-i',str(inv),str(APP/'ansible/backup.yml'),'-f','5'],
                                          env=env,stdout=process_log,stderr=process_log,start_new_session=True)
                    log('ansible.start','Ansible worker started; up to five concurrent NOS sessions')
                    deadline=time.monotonic()+max(600,len(nodes)*360)
                    try:
                        while proc.poll() is None:
                            consume()
                            if self.stopping.is_set() or time.monotonic()>deadline:
                                raise ValueError('Job interrupted or exceeded time limit; previous backups retained')
                            time.sleep(0.5)
                        consume()
                    finally:
                        if proc.poll() is None:
                            os.killpg(proc.pid,signal.SIGTERM)
                            try: proc.wait(timeout=5)
                            except subprocess.TimeoutExpired:
                                os.killpg(proc.pid,signal.SIGKILL); proc.wait()
                log('ansible.exit',f'Ansible exited with code {proc.returncode}','info' if proc.returncode==0 else 'error')
                process_diagnostic=safe_error((work/'process.log').read_text(errors='replace'))
                if process_diagnostic.strip(): log('ansible.diagnostic',process_diagnostic,'warning')
                success=0
                root=self.store.root/'backups'/lab['id']
                for index,node in enumerate(nodes):
                    result=results.get(f'node_{index}',{'status':'failed','message':
                        'No NOS result returned. '+(process_diagnostic or 'Verify SSH reachability and the image build.')})
                    outcome={'name':node['name'],'status':'failed'}
                    if result['status']=='ok':
                        try:
                            text=normalized(node['platform'],result.get('stdout',''))
                            log('node.validate',f'Accepted {len(text.encode())} bytes of NOS output',node=node['name'])
                            if operation=='backup':
                                name=filename(node)
                                latest=root/'latest'; history=root/'history'/job_id
                                latest.mkdir(parents=True,exist_ok=True,mode=0o700)
                                history.mkdir(parents=True,exist_ok=True,mode=0o700)
                                log('backup.write',f'Writing history and latest: {name}',node=node['name'])
                                self.store.atomic(history/name,text.encode())
                                self.store.atomic(latest/name,text.encode())
                                outcome.update(file=name,platform=node['platform'],
                                               short_name=short_name(node,lab['name'],text),
                                               captured_at=result.get('captured_at',now()),
                                               capture_time_source='NOS command completed',download_metadata_version=1)
                            outcome['status']='succeeded'
                            outcome['message']='Configuration saved' if operation=='backup' else 'NOS show version succeeded'
                            success+=1
                        except (ValueError,OSError) as exc:
                            outcome['message']=safe_error(exc)
                    else:
                        outcome['message']=safe_error(result.get('message','SSH command failed'))
                    outcomes.append(outcome)
                    log('node.'+outcome['status'],outcome['message'],'info' if outcome['status']=='succeeded' else 'error',node['name'])
                git_error=None
                if operation=='backup' and success:
                    try:
                        log('git.start','Recording successful configurations in Git')
                        latest=root/'latest'
                        def git(*args):
                            return subprocess.run(['git','-C',str(latest),*args],check=True,capture_output=True,text=True)
                        if not (latest/'.git').exists(): git('init','-q')
                        git('config','user.email','backup@worker.local'); git('config','user.name','NOS Backup')
                        git('add','--all')
                        if git('diff','--cached','--name-only').stdout:
                            git('commit','-q','-m',f'Backup {job_id}')
                            log('git.commit','Configuration changes committed')
                        else: log('git.unchanged','Configurations unchanged; no commit needed')
                    except (OSError,subprocess.SubprocessError) as exc:
                        log('git.diagnostic',safe_error(getattr(exc,'stderr','') or str(exc)),'error')
                        git_error='Files saved, but Git commit failed'
                        log('git.failed',git_error,'error')
                status='succeeded' if success==len(nodes) and not git_error and proc.returncode==0 else ('partial' if success else 'failed')
                log('job.finish',f'{status}: {success}/{len(nodes)} NOS sessions succeeded','info' if status=='succeeded' else 'error')
                self.update(job_id,status=status,finished=now(),nodes=outcomes,
                            message=git_error or (f'Ansible exited with code {proc.returncode}; {success}/{len(nodes)} sessions succeeded' if proc.returncode else f'{success}/{len(nodes)} NOS sessions completed successfully'))
        except Exception as exc:
            # Detailed exception strings may contain secrets; expose controlled errors only.
            message=safe_error(f'{type(exc).__name__}: {exc}')
            log('job.failed',message,'error')
            self.update(job_id,status='failed',finished=now(),message=message,
                        nodes=outcomes or [{'name':n['name'],'status':'failed','message':message} for n in nodes])
    def tick(self):
        while not self.stopping.wait(2):
            if self.store.reset_pending: continue
            state=self.store.snapshot()
            for lab in state['labs']:
                if lab['interval'] and lab.get('next_run') and lab['next_run']<=time.time():
                    try: self.submit(lab['id'],source='scheduled')
                    except ValueError as exc:
                        self.store.event('schedule.deferred',str(exc),level='warning',lab_id=lab['id'])
                        with self.store.lock:
                            current=self.store.lab(lab['id'])
                            if current:
                                current['next_run']=time.time()+60
                                self.store.save()
                    break
