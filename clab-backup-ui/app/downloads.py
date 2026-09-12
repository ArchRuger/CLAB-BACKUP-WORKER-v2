"""Stable, Windows-safe download names, independent of storage filenames."""
from datetime import datetime, timezone
from pathlib import Path
import re

FORMATS = {
    'juniper_cjunosevolved': ('cjunosevo', 'cfg'),
    'juniper_vqfx': ('vQFX', 'cfg'),
    'juniper_vjunosswitch': ('vJunos-switch', 'cfg'),
    'cisco_xrv9k': ('IOS-XR', 'txt'),
    'arista_ceos': ('CEOS', 'conf'),
}


def component(value, fallback='device'):
    value=re.sub(r'[^A-Za-z0-9_.-]+','_',str(value or '')).strip('._')[:100]
    value=value.rstrip('.') or fallback
    if re.fullmatch(r'(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?',value):
        value='_'+value
    return value


def utc_time(*values):
    for value in values:
        if not value: continue
        try:
            date=datetime.fromisoformat(str(value).replace('Z','+00:00'))
            if date.tzinfo is None: date=date.replace(tzinfo=timezone.utc)
            return date.astimezone(timezone.utc)
        except (TypeError,ValueError): continue
    return None


def stamp(*values):
    date=utc_time(*values)
    return date.strftime('%Y-%m-%d_%H-%M') if date else 'unknown-time'


def short_name(node, lab_name='', config=''):
    if node.get('short_name'): return node['short_name']
    name=node['name']
    prefix=f'clab-{lab_name}-'
    if lab_name and name.startswith(prefix): return name[len(prefix):]
    # A user-facing lab label may differ from the original containerlab name.
    # Use the actual NOS hostname when that makes an otherwise ambiguous prefix clear.
    if name.startswith('clab-'):
        match=re.search(r'(?m)^(?:set system host-name|hostname)\s+([^\s;]+)',config)
        if match:
            host=match[1].strip('"')
            if name.endswith('-'+host): return host
    # Preserve ambiguous names rather than silently cutting a hyphenated lab/device name.
    return name


def stored_path(store, job, node):
    filename=node.get('file','')
    if not filename or Path(filename).name!=filename or '\\' in filename:
        return None
    folder=store.root/'backups'/job['lab_id']/'history'/job['id']
    path=folder/filename
    if path.is_symlink() or not path.is_file(): return None
    if not path.resolve().is_relative_to(store.root.resolve()): return None
    if any(parent.is_symlink() for parent in (folder,folder.parent,folder.parent.parent)):
        return None
    return path


def migrate_download_metadata(store):
    """One-time metadata backfill; historical configuration files are never rewritten."""
    changed=False
    with store.lock:
        for job in store.state['jobs']:
            if job.get('operation')!='backup' or job['status'] in ('queued','running'): continue
            lab=store.lab(job['lab_id']) or {}
            current={n['name']:n for n in lab.get('nodes',[])}
            for node in job['nodes']:
                if not node.get('file') or node.get('download_metadata_version'): continue
                path=stored_path(store,job,node)
                if not path: continue
                try:
                    with path.open(errors='replace') as stream: config=stream.read(65536)
                    modified=path.stat().st_mtime
                except OSError:
                    store.event('download.metadata.unavailable','Historical configuration could not be read for naming',
                                level='warning',lab_id=job['lab_id'],job_id=job['id'],node=node['name'])
                    continue
                platform=node.get('platform','')
                if platform not in FORMATS:
                    suffix=path.suffix.lower()
                    if suffix=='.set' or re.search(r'(?m)^set system ',config): platform='juniper_cjunosevolved'
                    elif suffix=='.conf' or re.search(r'(?m)^! (?:device:|Command: show running-config)',config): platform='arista_ceos'
                    elif suffix=='.txt' or '!! IOS XR Configuration' in config: platform='cisco_xrv9k'
                    else: platform=current.get(node['name'],{}).get('platform','')
                source={**current.get(node['name'],{}),**node}
                captured=utc_time(node.get('captured_at'),job.get('finished'),job.get('started'),job.get('created'))
                captured=captured or datetime.fromtimestamp(modified,timezone.utc)
                node.update(platform=platform,short_name=short_name(source,job.get('lab_name',lab.get('name','')),config),
                            captured_at=captured.isoformat(),capture_time_source='legacy job time',download_metadata_version=1)
                changed=True
        if changed: store.save()


def config_names(job):
    """Return names keyed by stable node index; disambiguate Windows case-fold collisions."""
    names={}; used=set()
    for index,node in enumerate(job['nodes']):
        if not node.get('file') or node.get('status')!='succeeded': continue
        kind,extension=FORMATS.get(node.get('platform'),('Device',component(Path(node['file']).suffix.lstrip('.'),'cfg')))
        name=component(short_name(node,job.get('lab_name','')))
        time=stamp(node.get('captured_at'),job.get('finished'),job.get('started'),job.get('created'))
        candidate=f'{kind}_{name}_{time}UTC.{extension}'
        number=1
        while candidate.casefold() in used:
            number+=1
            candidate=f'{kind}_{name}_{number}_{time}UTC.{extension}'
        used.add(candidate.casefold());names[index]=candidate
    return names


def archive_name(job):
    return f"{component(job.get('lab_name'),'lab')}_{stamp(job.get('started'),job.get('created'),job.get('finished'))}.zip"


def decorate_job(job):
    job['archive_name']=archive_name(job)
    job['download_timezone']='UTC'
    for index,name in config_names(job).items(): job['nodes'][index]['download_name']=name
    return job
