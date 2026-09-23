import copy
import json
import logging
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
from .inventory import PLATFORMS, DEFAULT_CREDENTIALS, image_default_credentials
from .discovery import automatic_ready, node_available
from .downloads import short_name

APP = Path(__file__).parent
# Bookkeeping cap on 'jobs' (every backup and login-test run), mirroring the one lab_operations.py
# already keeps on 'operations', but per lab_id: a single lab's schedule (a 1-minute interval reaches
# 500 jobs in about 8 hours) must never evict every *other* lab's history along with its own. The
# stored files a job's downloads point at are untouched; only the job record itself is dropped, and
# never one still queued or running, nor one a pending Git save or a busy/interrupted restore still
# needs to find by id (see protected_job_ids).
JOB_CAP = 300
# The post-backup local git commands (below, in _execute) get the same bounded deadline as the
# ansible-playbook run a few lines above them; a stuck git process must not stall the one-worker
# backup pipeline forever.
GIT_TIMEOUT = 120

def now():
    return datetime.now(timezone.utc).isoformat()

def effective_credentials(lab, node):
    profile_id = node.get('profile_id') or lab.get('defaults',{}).get(node['platform'] or 'ssh')
    if profile_id:
        profile = next((p for p in lab['profiles'] if p['id']==profile_id),None)
        return profile or {}
    if node.get('username') and node.get('password'):
        return {'username':node['username'],'password':node['password'],'auth':'password','enable_password':node.get('enable_password','')}
    default = DEFAULT_CREDENTIALS.get(node.get('platform') or '')
    if default:
        return {'username':default[0],'password':default[1],'auth':'password','enable_password':'','default':True}
    image_default = image_default_credentials(node)
    if image_default:
        return {'username':image_default[0],'password':image_default[1],'auth':'password','enable_password':'','default':True}
    return {}

def credential_source(lab, node):
    """'profile', 'inventory', 'default' (containerlab's or the image's documented login) or '' when none applies."""
    profile_id = node.get('profile_id') or lab.get('defaults',{}).get(node.get('platform') or 'ssh')
    if profile_id:
        return 'profile' if any(p['id']==profile_id for p in lab['profiles']) else ''
    if node.get('username') and node.get('password'):
        return 'inventory'
    if (node.get('platform') or '') in DEFAULT_CREDENTIALS or image_default_credentials(node):
        return 'default'
    return ''

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
        # Junos backups also fetch a hierarchical restore-grade candidate (see backup.yml). Where the
        # backup command already yields the loadable candidate (EOS), it is not run a second time:
        # two captures seconds apart could disagree, and the artifact must equal what was saved.
        if operation=='backup' and platform.get('restore') and platform['restore']!=platform['command']:
            variables['restore_command']=platform['restore']
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

# The auxiliary Junos restore-artifact task in backup.yml is matched by its task name.
RESTORE_TASK = 'Fetch restore artifact'

def restore_filename(node):
    """Companion file holding the whole-device restore candidate, beside the backup."""
    base=re.sub(r'[^A-Za-z0-9_.-]','_',node['name'])[:100].strip('.') or 'node'
    digest=hashlib.sha256(node['name'].encode()).hexdigest()[:8]
    suffix=PLATFORMS[node['platform']].get('restore_suffix')
    return f'{base}-{digest}.{suffix}' if suffix else ''

# CLI answers that mean the command did not run: syntax errors, denied commands and
# the not-ready replies a NOS gives while it is still booting.
CLI_ERROR=re.compile(r'(?im)^\s*(?:%\s*(?:Invalid|Error|Incomplete|Ambiguous|Authorization|Access denied|System is not yet ready)|error:|syntax error|System is not yet ready|Waiting for editing of configuration)')

def normalized(platform, text):
    if not isinstance(text,str):
        raise ValueError('NOS returned an unexpected output type; previous backup retained')
    if platform=='cisco_xrv9k':
        text='\n'.join(x for x in text.splitlines() if not re.match(r'^(Building configuration|[A-Z][a-z]{2} [A-Z][a-z]{2} +\d+ )',x))
    if CLI_ERROR.search(text):
        raise ValueError('NOS returned a CLI error or is not ready; previous backup retained')
    if not text.strip():
        raise ValueError('NOS returned empty output; previous backup retained')
    return text.rstrip()+'\n'

def job_environment(work, event):
    """Environment for one ansible-playbook run.

    HOME is the job's temporary directory: lab containers generate new SSH host
    keys on every deploy, and Ansible's paramiko transport records the keys it
    accepts in ~/.ssh/known_hosts and then refuses a changed key with "host key
    mismatch". A per-job home starts without known_hosts, so a redeployed lab is
    backed up and tested without recreating the manager. Collections come from the
    image's explicit ANSIBLE_COLLECTIONS_PATH, never from the home directory.
    """
    (work/'.ssh').mkdir(mode=0o700, exist_ok=True)
    return {**os.environ,'HOME':str(work),'ANSIBLE_CONFIG':str(APP/'ansible/ansible.cfg'),
            'ANSIBLE_CALLBACK_PLUGINS':str(APP/'ansible/callback_plugins'),
            'ANSIBLE_STDOUT_CALLBACK':'backup_events','BACKUP_EVENT_FILE':str(event),
            'ANSIBLE_HOST_KEY_CHECKING':'False','ANSIBLE_PERSISTENT_LOG_MESSAGES':'False',
            'ANSIBLE_DEBUG':'False','ANSIBLE_VERBOSITY':'0'}

def trim_jobs(jobs, cap, protected, newest_first):
    """Cap one globally-bounded stored job list (git_progress.py 'git_jobs', restore.py
    'restore_jobs') at its newest `cap` entries without ever dropping one `protected` calls true
    for (pending/in-flight work that must survive to be found again). `newest_first` matches how
    the caller stores (and reads) the list: True when the newest entry is inserted at index 0,
    False when it is appended at the end (both callers append). Entries kept only for being
    protected keep their original relative order."""
    if len(jobs)<=cap: return jobs
    newest,older=(jobs[:cap],jobs[cap:]) if newest_first else (jobs[-cap:],jobs[:-cap])
    survivors=[j for j in older if protected(j)]
    return newest+survivors if newest_first else survivors+newest

def trim_jobs_per_lab(jobs, cap, protected):
    """Cap 'jobs' (stored newest-first, one flat list shared by every lab) at its newest `cap`
    entries *per lab_id*, so one lab's own history never evicts another lab's, plus every entry
    `protected` calls true for regardless of age. Original (newest-first) order is preserved."""
    seen={}
    result=[]
    for job in jobs:
        lab_id=job.get('lab_id')
        seen[lab_id]=seen.get(lab_id,0)+1
        if seen[lab_id]<=cap or protected(job): result.append(job)
    return result

def protected_job_ids(state):
    """Job ids that 'jobs' must keep findable even past its cap, because something outside
    'jobs' still looks one up by id: a Git save job_pending() calls pending (its capture is
    compared and re-read on every retry, by backup_job_id: losing it makes every future retry
    fail with "the original capture is unavailable", forever); a restore job that is still busy
    or was left 'interrupted' by a restart (its pre/post safety backups, read back by
    pre_backup_job_id on the restart recheck path). Both imports are late (inside the function,
    not at module level): git_progress.py and lab_operations.py (through topology.py) each import
    this module at their own top level, so a top-level import here of either would be a real cycle,
    same as submit()'s existing late import of RESTORE_BUSY below."""
    from .git_progress import job_pending
    from .lab_operations import RESTORE_BUSY
    ids=set()
    for j in state.get('git_jobs',[]):
        if job_pending(j) and j.get('backup_job_id'): ids.add(j['backup_job_id'])
    for j in state.get('restore_jobs',[]):
        if j.get('status') in RESTORE_BUSY or j.get('status')=='interrupted':
            ids.update(j[k] for k in ('pre_backup_job_id','post_backup_job_id') if j.get(k))
    return ids

class Runner:
    def __init__(self, store):
        self.store=store
        self.pool=ThreadPoolExecutor(max_workers=1)
        self.stopping=threading.Event()
        self.scheduler=None
    def start(self):
        self.scheduler=threading.Thread(target=self.tick,daemon=True)
        self.scheduler.start()
    def close(self):
        self.stopping.set()
        self.pool.shutdown(wait=False,cancel_futures=True)
        if self.scheduler: self.scheduler.join(timeout=2)
    def submit(self, lab_id, operation='backup', source='manual', node_names=None, progress_id=None, progress_context=None):
        from .lab_operations import operation_busy, RESTORE_BUSY
        with self.store.lock:
            if operation_busy(self.store.state,lab_id,progress_id=progress_id): raise ValueError('Wait for the lab operation to finish.')
            # A restore's own pre/post backups pass their restore job id as progress_id and
            # are allowed; any other backup waits for the restore (on any lab) to finish.
            if any(j.get('status') in RESTORE_BUSY and j.get('id') != progress_id for j in self.store.state.get('restore_jobs',[])):
                raise ValueError('A configuration restore is in progress. Wait for it to finish.')
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
                 'operation':operation,'source':source,'created':now(),'status':'queued','message':'Waiting for SSH worker',
                 'nodes':[{'name':n['name'],'status':'queued'} for n in nodes]}
            if progress_id:
                job.update(progress_id=progress_id, progress_context=copy.deepcopy(progress_context or {}))
            self.store.state['jobs'].insert(0,job)
            # Backup/history files on disk are retained regardless; only this bookkeeping record is
            # capped, per lab (never one still queued/running, or one a pending Git save or a busy/
            # interrupted restore still needs to find by id).
            still_needed=protected_job_ids(self.store.state)
            self.store.state['jobs']=trim_jobs_per_lab(self.store.state['jobs'],JOB_CAP,
                lambda j:j['status'] in ('queued','running') or j['id'] in still_needed)
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
                env=job_environment(work,event)
                results={}
                restore_results={}
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
                            # The restore artifact is an auxiliary capture: record it, but
                            # never let it set the node's visible status or fail the backup.
                            if item.get('task')==RESTORE_TASK:
                                if status!='running':
                                    item.setdefault('captured_at',now())
                                    restore_results[alias]=item
                                continue
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
                                # The digest of what was stored: a later reader (Git save, restore) refuses a capture that
                                # no longer matches it. Captures taken before this field existed carry none.
                                outcome.update(file=name,platform=node['platform'],sha256=hashlib.sha256(text.encode()).hexdigest(),
                                               short_name=short_name(node,lab['name'],text),
                                               captured_at=result.get('captured_at',now()),
                                               capture_time_source='NOS command completed',download_metadata_version=1)
                                # Store the hierarchical restore candidate beside the backup.
                                # Best-effort: its absence only means "not restore-capable".
                                rr=restore_results.get(f'node_{index}')
                                rname=restore_filename(node)
                                same=PLATFORMS[node['platform']].get('restore')==PLATFORMS[node['platform']]['command']
                                if rname and (same or (rr and rr.get('status')=='ok')):
                                    try:
                                        rtext=text if same else normalized(node['platform'],rr.get('stdout',''))
                                        self.store.atomic(history/rname,rtext.encode())
                                        self.store.atomic(latest/rname,rtext.encode())
                                        outcome.update(restore_file=rname,restore_sha256=hashlib.sha256(rtext.encode()).hexdigest(),
                                                       restore_format=PLATFORMS[node['platform']].get('restore_format',''))
                                        log('restore.capture',f'Stored restore-grade candidate: {rname} ({len(rtext.encode())} bytes)',node=node['name'])
                                    except (ValueError,OSError) as exc:
                                        log('restore.capture.skip',f'No restore candidate stored: {safe_error(exc)}','warning',node['name'])
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
                            return subprocess.run(['git','-C',str(latest),*args],check=True,capture_output=True,text=True,timeout=GIT_TIMEOUT)
                        if not (latest/'.git').exists(): git('init','-q')
                        git('config','user.email','backup@worker.local'); git('config','user.name','NOS Backup')
                        git('add','--all')
                        if git('diff','--cached','--name-only').stdout:
                            git('commit','-q','-m',f'Backup {job_id}')
                            log('git.commit','Configuration changes committed')
                        else: log('git.unchanged','Configurations unchanged; no commit needed')
                    except subprocess.TimeoutExpired as exc:
                        log('git.diagnostic',safe_error(getattr(exc,'stderr','') or str(exc)),'error')
                        # subprocess.run(timeout=...) has already killed and reaped the git process by
                        # the time it raises this, and the runner's single worker is this repository's
                        # only writer, so a lock it left behind is safe to clear now: otherwise every
                        # later backup of this lab fails to commit ("Unable to create '...index.lock'").
                        cleared=[name for name in ('index.lock','config.lock') if (latest/'.git'/name).exists()]
                        for name in cleared:
                            try: (latest/'.git'/name).unlink()
                            except OSError: pass
                        git_error='Files saved, but the Git history step timed out'+(
                            '; cleared a stale '+' and '.join(cleared)+' left by it' if cleared else '')
                        log('git.failed',git_error,'error')
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
            try:
                state=self.store.snapshot()
                for lab in state['labs']:
                    if lab['interval'] and lab.get('next_run') and lab['next_run']<=time.time():
                        try: self.submit(lab['id'],source='scheduled')
                        except ValueError as exc:
                            try: self.store.event('schedule.deferred',str(exc),level='warning',lab_id=lab['id'])
                            except OSError: pass
                            with self.store.lock:
                                current=self.store.lab(lab['id'])
                                if current:
                                    current['next_run']=time.time()+60
                                    self.store.save()
                        break
            except OSError:
                logging.getLogger(__name__).warning('Scheduler could not persist its work; check manager storage. Retrying on the next tick.')
