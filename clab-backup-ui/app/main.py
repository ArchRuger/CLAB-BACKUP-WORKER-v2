import copy
import hmac
import io
import json
import os
from pathlib import Path
import tempfile
import time
import uuid
import zipfile
from contextlib import asynccontextmanager
import paramiko
from fastapi import FastAPI, Request, UploadFile, File, Form, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.exceptions import RequestValidationError
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from starlette.background import BackgroundTask
from .inventory import PLATFORMS, parse_inventory, literal, address, port
from .store import Store
from .runner import Runner, readiness, now, effective_credentials
from .node_services import NodeServices
from . import topology
from .discovery import Discovery, lab_status, node_available
from .downloads import migrate_download_metadata, decorate_job, config_names, archive_name, stored_path
from . import __version__

APP=Path(__file__).parent

def create_app(data_dir=None):
    store=Store(data_dir or os.environ.get('DATA_DIR','/data'))
    migrate_download_metadata(store)
    runner=Runner(store)
    services=NodeServices(store)
    discovery=Discovery(store)
    @asynccontextmanager
    async def lifespan(app):
        print(f'NOS Backup UI access token: {store.token}',flush=True)
        runner.start()
        discovery.start()
        yield
        discovery.close()
        services.close()
        runner.close()
    app=FastAPI(title='Containerlab Node Manager',version=__version__,lifespan=lifespan,docs_url=None,redoc_url=None,openapi_url=None)
    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, exc):
        return JSONResponse({"detail":"Check the request fields and upload sizes."},status_code=422)
    app.state.store=store; app.state.runner=runner
    app.state.discovery=discovery
    app.state.node_services=services
    services.install(app)
    topology.install(app,store)
    @app.middleware('http')
    async def guard(request, call_next):
        if request.url.path.startswith('/api/'):
            supplied=request.headers.get('authorization','').removeprefix('Bearer ')
            expected=store.token
            if not expected or not hmac.compare_digest(supplied.encode('utf8'),expected.encode('utf8')):
                return JSONResponse({'detail':'Enter the UI access token from the worker startup log.'},status_code=401)
            if request.method in ('POST','PUT','PATCH','DELETE'):
                try: size=int(request.headers.get('content-length','0'))
                except ValueError: return JSONResponse({'detail':'Invalid request length'},status_code=400)
                if size>2_500_000 or size<=0:
                    return JSONResponse({'detail':'Upload limit is 2.5 MB per request; content length is required.'},status_code=413)
        started=time.monotonic()
        response=await call_next(request)
        if request.url.path.startswith('/api/') and (request.method!='GET' or request.url.path.endswith('/download')):
            parts=request.url.path.split('/')
            lab_id=parts[3] if len(parts)>3 and parts[2]=='labs' else ''
            job_id=parts[3] if len(parts)>3 and parts[2]=='jobs' else ''
            if job_id:
                with store.lock:
                    matched=next((j for j in store.state['jobs'] if j['id']==job_id),None)
                    if matched: lab_id=matched['lab_id']
            route=request.scope.get('route')
            store.event('api.request',f'{request.method} {getattr(route, "path", "/api/unknown")} â†’ {response.status_code} ({time.monotonic()-started:.3f}s)',
                        level='error' if response.status_code>=400 else 'info',lab_id=lab_id,job_id=job_id)
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['Referrer-Policy']='no-referrer'
        response.headers['X-Frame-Options']='DENY'
        response.headers['Cache-Control']='no-store'
        # xterm's DOM renderer creates font, cell-width and ANSI-color styles.
        # Permit those only in its dedicated document; scripts remain self-only.
        styles="'self' 'unsafe-inline'" if request.url.path=='/static/terminal.html' else "'self'"
        response.headers['Content-Security-Policy']=f"default-src 'self'; script-src 'self'; style-src {styles}; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'"
        return response
    def get_lab(lab_id):
        lab=store.lab(lab_id)
        if not lab: raise HTTPException(404,'Lab not found')
        return lab
    def public_lab(lab):
        result={k:copy.deepcopy(v) for k,v in lab.items() if k not in ('nodes','profiles','monitor_host','drawing','definition_yaml')}
        result['profiles']=[{k:p[k] for k in ('id','label','platform','username','auth')} for p in lab['profiles']]
        result['nodes']=[]
        for n in lab['nodes']:
            row={k:copy.deepcopy(v) for k,v in n.items() if k not in ('username','password','enable_password','container_name')}
            row['available']=node_available(store.state,lab,n)
            row['readiness']=readiness(lab,n) if row['available'] else 'Lab unavailable'
            row['inventory_credentials']=bool(n.get('username') and n.get('password'))
            row['ssh_ready']=row['available'] and bool(effective_credentials(lab,n).get('username'))
            result['nodes'].append(row)
        result['deployment']=lab_status(store.state,lab)
        return result
    discovery.install(app,public_lab)
    @app.get('/api/state')
    def state():
        with store.lock:
            return {'labs':[public_lab(l) for l in store.state['labs']],
                    'jobs':[decorate_job(copy.deepcopy(j)) for j in store.state['jobs']],
                    'platforms':PLATFORMS, 'version':__version__, 'discovery':discovery.public()}
    class RemoveLab(BaseModel):
        model_config = ConfigDict(extra='forbid')
        name: str = Field(min_length=1, max_length=120)
        prevent_reimport: bool = True

    @app.delete('/api/labs/{lab_id}')
    def remove_lab(lab_id: str, data: RemoveLab):
        with store.lock:
            lab = get_lab(lab_id)
            if data.name != lab['name']:
                raise HTTPException(409, 'The lab name changed. Reopen Remove lab and try again.')
            if any(j['lab_id'] == lab_id and j['status'] in ('queued', 'running') for j in store.state['jobs']):
                raise HTTPException(409, 'Wait for this lab backup or login job to finish before removing it.')
            name = lab.get('deployment_name') or lab['name']
            previous = store.state
            updated = copy.deepcopy(previous)
            updated['labs'] = [l for l in updated['labs'] if l['id'] != lab_id]
            updated['jobs'] = [j for j in updated['jobs'] if j['lab_id'] != lab_id]
            ignored = set(updated.get('ignored_labs', []))
            if data.prevent_reimport: ignored.add(name)
            else: ignored.discard(name)
            updated['ignored_labs'] = sorted(ignored)
            updated.get('discovery', {}).get('file_errors', {}).pop(name, None)
            store.state = updated
            try: store.save()
            except OSError:
                store.state = previous
                raise HTTPException(500, 'Could not save the removal. The workspace was retained.')
            discovery.sources.pop(name, None)
            with services.lock:
                services.checks = {k:v for k,v in services.checks.items() if k[0] != lab_id}
                services.tickets = {k:v for k,v in services.tickets.items() if v[1] != lab_id}
            store.event('lab.remove', 'Removed saved workspace and history entries; backup files and audit logs retained; automatic import '+('excluded' if data.prevent_reimport else 'allowed'), lab_id=lab_id)
            return {'removed': lab_id, 'name': lab['name'], 'prevent_reimport': data.prevent_reimport}

    @app.get('/api/logs')
    def logs(lab_id: str='', job_id: str='', level: str='', node: str='', limit: int=Query(500,ge=1,le=2000)):
        return {'events':store.events(lab_id,job_id,level,node,limit)}
    @app.post('/api/inventory')
    async def upload_inventory(name: str=Form(...), inventory: UploadFile=File(...),
                               lab_id: str=Form(''), topology: UploadFile|None=File(None)):
        try:
            name=literal(name.strip(),'Lab name',120)
            if not name: raise ValueError('Enter a lab name')
            raw=await inventory.read(1024*1024+1)
            extra=await topology.read(1024*1024+1) if topology and topology.filename else None
            nodes=parse_inventory(raw,extra)
            for node in nodes: node['endpoint_mode']='manual'
        except (ValueError,TypeError,RecursionError) as exc:
            raise HTTPException(400,str(exc))
        finally:
            await inventory.close()
            if topology: await topology.close()
        with store.lock:
            if lab_id:
                lab=get_lab(lab_id)
                old={n['name']:n for n in lab['nodes']}
                for node in nodes:
                    previous=old.get(node['name'])
                    if previous:
                        node['profile_id']=previous.get('profile_id','')
                        node['short_name']=node.get('short_name') or previous.get('short_name','')
                        node['platform']=node['platform'] or previous['platform']
                        node['enabled']=previous['enabled'] and bool(node['platform'])
                lab.update(name=name,nodes=nodes,updated=now(),source=Path(inventory.filename or 'inventory.yml').name)
            else:
                lab={'id':uuid.uuid4().hex,'name':name,'nodes':nodes,'profiles':[],
                     'defaults':{},'interval':0,'next_run':None,'created':now(),'updated':now(),
                     'source':Path(inventory.filename or 'inventory.yml').name}
                store.state['labs'].append(lab)
            if lab['interval'] and any(readiness(lab,n)!='Ready' for n in lab['nodes'] if n['enabled']):
                lab.update(interval=0,next_run=None)
            store.save()
            store.event('inventory.import',f'Imported {len(nodes)} nodes; {sum(n["enabled"] for n in nodes)} enabled',lab_id=lab['id'])
            return public_lab(lab)
    class NodeEdit(BaseModel):
        model_config=ConfigDict(extra='forbid')
        name: str
        address: str
        port: int=22
        platform: str=''
        profile_id: str=''
        enabled: bool=True
        short_name: str|None=None
        endpoint_mode: str|None=None
    @app.put('/api/labs/{lab_id}/node')
    def edit_node(lab_id: str, edit: NodeEdit):
        with store.lock:
            lab=get_lab(lab_id)
            node=next((n for n in lab['nodes'] if n['name']==edit.name),None)
            if not node: raise HTTPException(404,'Node not found')
            if edit.platform and edit.platform not in PLATFORMS: raise HTTPException(400,'Unsupported NOS')
            if edit.profile_id and not any(p['id']==edit.profile_id for p in lab['profiles']):
                raise HTTPException(400,'Credential profile not found')
            try: endpoint=address(edit.address); ssh_port=port(edit.port)
            except ValueError as exc: raise HTTPException(400,str(exc))
            store.event('node.edit',f'Connection updated: {endpoint}:{ssh_port}; NOS {edit.platform or "unmapped"}; enabled={edit.enabled}; profile={edit.profile_id or "default/inventory"}',lab_id=lab_id,node=node['name'])
            if edit.short_name is not None:
                try: node['short_name']=literal(edit.short_name.strip(),'Download device name',200)
                except ValueError as exc: raise HTTPException(400,str(exc))
            if edit.endpoint_mode not in (None,'manual','auto'): raise HTTPException(400,'Choose automatic or manual addressing')
            if edit.endpoint_mode=='auto' and not lab.get('deployment_name'): raise HTTPException(400,'Link a deployed lab before using automatic addresses')
            if edit.endpoint_mode is not None:
                node['endpoint_mode']=edit.endpoint_mode
            elif (endpoint,ssh_port)!=(node['address'],node['port']):
                node['endpoint_mode']='manual'
            node.update(address=endpoint,port=ssh_port,platform=edit.platform,
                        profile_id=edit.profile_id,enabled=edit.enabled and bool(edit.platform))
            if edit.endpoint_mode=='auto':
                from .discovery import reconcile
                reconcile(store.state)
            store.save()
            return public_lab(lab)
    @app.post('/api/labs/{lab_id}/profiles')
    async def profile(lab_id: str, label: str=Form(...), platform: str=Form(...),
                      username: str=Form(...), auth: str=Form('password'), password: str=Form(''),
                      passphrase: str=Form(''), enable_password: str=Form(''), make_default: bool=Form(True),
                      private_key: UploadFile|None=File(None)):
        if platform not in (*PLATFORMS,'ssh') or auth not in ('password','key'):
            raise HTTPException(400,'Choose a supported NOS and authentication method')
        try:
            label=literal(label.strip(),'Profile name',120)
            username=literal(username.strip(),'Username',128)
            if not label or not username: raise ValueError('Profile name and username are required')
            enable_password=literal(enable_password,'Enable password'); password=literal(password,'Password'); passphrase=literal(passphrase,'Key passphrase')
            key=''
            if auth=='key':
                if not private_key: raise ValueError('Upload the SSH private key')
                raw=await private_key.read(65537)
                if len(raw)>65536: raise ValueError('SSH key must be smaller than 64 KiB')
                key=raw.decode('utf8')
                valid=False
                for keytype in (paramiko.RSAKey,paramiko.ECDSAKey,paramiko.Ed25519Key):
                    try:
                        keytype.from_private_key(io.StringIO(key),password=passphrase or None)
                        valid=True; break
                    except (paramiko.SSHException,ValueError,TypeError): pass
                if not valid: raise ValueError('Cannot read the private key; verify its format and passphrase')
        except (ValueError,UnicodeError) as exc:
            raise HTTPException(400,str(exc))
        finally:
            if private_key: await private_key.close()
        with store.lock:
            lab=get_lab(lab_id)
            p={'id':uuid.uuid4().hex,'label':label,'platform':platform,'username':username,'auth':auth,
               'password':password if auth=='password' else '', 'private_key':key,'passphrase':passphrase,'enable_password':enable_password}
            lab['profiles'].append(p)
            store.event('credentials.create',f'{platform} {auth} profile {p["id"]} created; default={make_default}; enable credential configured={bool(enable_password)}',lab_id=lab_id)
            if make_default: lab['defaults'][platform]=p['id']
            store.save()
            return public_lab(lab)
    class Schedule(BaseModel):
        interval: int=Field(ge=0,le=10080)
    @app.put('/api/labs/{lab_id}/schedule')
    def schedule(lab_id: str, data: Schedule):
        with store.lock:
            lab=get_lab(lab_id)
            if data.interval:
                nodes=[n for n in lab['nodes'] if n['enabled']]
                if not nodes or any(readiness(lab,n)!='Ready' for n in nodes):
                    raise HTTPException(400,'Complete credentials for enabled nodes before scheduling')
            store.event('schedule.update',f'Backup interval set to {data.interval} minutes (0 means manual)',lab_id=lab_id)
            lab.update(interval=data.interval,next_run=time.time()+data.interval*60 if data.interval else None)
            store.save()
            return public_lab(lab)
    class JobRequest(BaseModel):
        operation: str='backup'
        node_names: list[str]|None=Field(default=None,max_length=2000)
    @app.post('/api/labs/{lab_id}/jobs')
    def job(lab_id: str, data: JobRequest):
        if data.operation not in ('backup','test'): raise HTTPException(400,'Invalid operation')
        try: return runner.submit(lab_id,data.operation,node_names=data.node_names)
        except ValueError as exc: raise HTTPException(400,str(exc))
    def finished_backup(job_id):
        with store.lock:
            job=next((copy.deepcopy(j) for j in store.state['jobs'] if j['id']==job_id),None)
        if not job or job.get('operation')!='backup': raise HTTPException(404,'Backup not found')
        if job['status'] in ('queued','running'): raise HTTPException(409,'Wait for the backup to finish')
        return decorate_job(job)

    @app.get('/api/jobs/{job_id}/nodes/{node_index}/download')
    def download_device(job_id: str, node_index: int):
        job=finished_backup(job_id)
        if node_index<0 or node_index>=len(job['nodes']): raise HTTPException(404,'Device backup not found')
        node=job['nodes'][node_index]
        if node_index not in config_names(job): raise HTTPException(404,'This device has no successful configuration backup')
        path=stored_path(store,job,node)
        if not path: raise HTTPException(404,'Configuration file is unavailable')
        store.event('download.device',f"Configuration download requested: {node['download_name']}",
                    lab_id=job['lab_id'],job_id=job_id,node=node['name'])
        return FileResponse(path,filename=node['download_name'],media_type='application/octet-stream')

    @app.get('/api/jobs/{job_id}/download')
    def download(job_id: str):
        job=finished_backup(job_id)
        names=config_names(job)
        if not names: raise HTTPException(404,'This job has no saved configurations')
        files=[]
        for index,name in names.items():
            path=stored_path(store,job,job['nodes'][index])
            if not path: raise HTTPException(404,'A configuration file is unavailable; download available devices individually')
            files.append((path,name))
            # The manifest describes the names actually present in this archive.
            job['nodes'][index]['file']=name
        fd,path=tempfile.mkstemp(suffix='.zip'); os.close(fd)
        try:
            with zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED) as archive:
                for source,name in files: archive.write(source,name)
                archive.writestr('manifest.json',json.dumps(job,indent=2))
            store.event('download.archive',f"Archive download requested: {archive_name(job)}; {len(files)} configurations",
                        lab_id=job['lab_id'],job_id=job_id)
        except Exception:
            os.unlink(path); raise
        return FileResponse(path,filename=archive_name(job),media_type='application/zip',
                            background=BackgroundTask(os.unlink,path))
    app.mount('/static',StaticFiles(directory=APP/'static'),name='static')
    @app.get('/')
    def index(): return FileResponse(APP/'static/index.html')
    return app
