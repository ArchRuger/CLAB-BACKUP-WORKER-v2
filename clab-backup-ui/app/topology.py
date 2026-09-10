"""Data-only topology drawings and SuperPuTTY session exports."""
import json
import math
import re
import subprocess
from urllib.parse import quote
import xml.etree.ElementTree as ET
from fastapi import File, UploadFile, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict
from .inventory import read_data
from .runner import effective_credentials


def text(value, limit=200):
    if not isinstance(value, str) or len(value)>limit or any(ord(c)<32 and c not in '\n\t' for c in value):
        raise ValueError('Invalid topology text')
    return value


def number(value, default=0):
    if value is None: return default
    if isinstance(value, bool) or not isinstance(value, (int,float)) or not math.isfinite(value) or abs(value)>100000:
        raise ValueError('Invalid drawing coordinates')
    return value


def rows(data, key):
    value=data.get(key, [])
    if not isinstance(value,list) or len(value)>2000 or any(not isinstance(x,dict) for x in value):
        raise ValueError(f'{key} must contain no more than 2000 objects')
    return value


def color(value, default):
    if not isinstance(value,str): return default
    if re.fullmatch(r'#[0-9a-fA-F]{3,8}',value) and len(value) in (4,5,7,9): return value
    if value in ('transparent','none','black','white','red','blue','green','gray'): return value
    if re.fullmatch(r'rgba?\(\s*[\d.]+\s*,\s*[\d.]+\s*,\s*[\d.]+(?:\s*,\s*[\d.]+)?\s*\)',value): return value
    return default


def bounded(value, default, minimum, maximum):
    return min(maximum,max(minimum,number(value,default)))


def exported_interface(interface, kind):
    """Reverse containerlab's XRv9k data-port mapping, not allocation patterns.

    XRv9k reserves eth1 for management; eth2 is Gi0/0/0/1. Native YAML
    interface names and other kinds must remain unchanged (e.g. Junos eth4).
    """
    match=re.fullmatch(r'eth(\d+)',interface)
    if kind in ('cisco_xrv9k','vr-xrv9k') and match and int(match[1])>=2:
        return 'Gi0/0/0/'+str(int(match[1])-1)
    return interface


def opaque_color(value):
    """Explicit fillOpacity replaces RGBA alpha in the upstream renderer."""
    match=re.fullmatch(r'rgba\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*[\d.]+\s*\)',value)
    if match: return 'rgb('+','.join(match.groups())+')'
    if value.startswith('#') and len(value) in (5,9): return value[:-1] if len(value)==5 else value[:-2]
    return value


def parse_drawing(raw, topology=None):
    if len(raw)>1024*1024: raise ValueError('Annotations must be smaller than 1 MiB')
    data=json.loads(raw)
    if not isinstance(data,dict) or not any(k in data for k in ('nodeAnnotations','networkNodeAnnotations','freeTextAnnotations','groupStyleAnnotations','freeShapeAnnotations')):
        raise ValueError('Upload a containerlab .annotations.json file')
    nodes={}; links=[]; decorations=[]; skipped_links=0; kinds={}; aliases={}
    for index,n in enumerate(rows(data,'nodeAnnotations')+rows(data,'networkNodeAnnotations')):
        ident=text(n.get('id'))
        if not ident or ident in nodes: raise ValueError('Drawing node IDs must be unique and nonempty')
        pos=n.get('position') or {}
        nodes[ident]={'id':ident,'alias':text(n.get('yamlNodeId') or n.get('copyFrom') or ident), 'label':text(n.get('label') or ident),
                      'x':number(pos.get('x'),(index%8)*160),'y':number(pos.get('y'),(index//8)*120),
                      'icon':text(n.get('icon') or 'router'), 'iconColor':color(n.get('iconColor'),'#0066ff'),
                      'labelPosition':text(n.get('labelPosition') or 'bottom'),
                      'labelBackgroundColor':color(n.get('labelBackgroundColor'),'#454545'),
                      'iconCornerRadius':bounded(n.get('iconCornerRadius'),4,0,32),
                      'interfacePattern':text(n.get('interfacePattern') or ''),
                      'direction':text(n.get('direction') or 'up')}
    if topology:
        topo=read_data(topology)
        body=topo.get('topology',topo)
        if not isinstance(body,dict) or not isinstance(body.get('nodes',{}),dict): raise ValueError('Invalid topology nodes')
        if len(body.get('nodes',{}))>2000: raise ValueError('Too many topology nodes')
        for ident,n in body.get('nodes',{}).items():
            if not isinstance(n,dict): n={}
            ident=text(ident); short=text(n.get('shortname') or ident)
            kinds[short]=n.get('kind','')
            for alias in (ident,short,n.get('longname')):
                if isinstance(alias,str): aliases[alias]=short
            # Export keys may be container names; annotations use short names.
            if short in nodes: continue
            if short not in nodes: nodes[short]={'id':short,'alias':short,'label':short,'x':len(nodes)%8*160,'y':len(nodes)//8*120}
        for link in rows(body,'links'):
            endpoints=link.get('endpoints')
            if isinstance(endpoints,dict): endpoints=[endpoints[k] for k in ('a','z') if k in endpoints]
            if not isinstance(endpoints,list) or len(endpoints)!=2:
                skipped_links+=1
                continue
            pair=[]
            for ep in endpoints:
                if isinstance(ep,str): node,sep,interface=ep.partition(':')
                elif isinstance(ep,dict): node=ep.get('node',ep.get('node-short-name','')); interface=ep.get('interface',ep.get('interface-name',''))
                else: raise ValueError('Invalid link endpoint')
                node=text(node); interface=text(interface)
                node=aliases.get(node,node)
                if 'topology' not in topo: interface=exported_interface(interface,kinds.get(node,''))
                if node not in nodes: nodes[node]={'id':node,'alias':node,'label':node,'x':len(nodes)%8*160,'y':len(nodes)//8*120}
                pair.append({'node':node,'interface':interface})
            links.append(pair)
    for edge in rows(data,'edgeAnnotations'):
        if edge.get('endpointLabelOffsetEnabled') is not True: continue
        offset=bounded(edge.get('endpointLabelOffset'),20,0,200)
        source=(edge.get('source'),edge.get('sourceEndpoint'))
        target=(edge.get('target'),edge.get('targetEndpoint'))
        for pair in links:
            ends=[(ep['node'],ep['interface']) for ep in pair]
            if ends==[source,target] or ends==[target,source]:
                for ep in pair: ep['label_offset']=offset
    for key in ('groupStyleAnnotations','freeShapeAnnotations','freeTextAnnotations'):
        for item in rows(data,key):
            pos=item.get('position') or {}
            shape=item.get('shapeType','rectangle')
            if shape not in ('rectangle','circle','line'): shape='rectangle'
            d={'type':'text' if key=='freeTextAnnotations' else 'group' if key=='groupStyleAnnotations' else shape,'x':number(pos.get('x')),'y':number(pos.get('y')),
               'width':max(1,number(item.get('width'),200)),'height':max(1,number(item.get('height'),120)),
               'text':text(item.get('text',item.get('name','')),4000)}
            is_group=key=='groupStyleAnnotations'
            d.update(fillColor=color(item.get('backgroundColor') if is_group else item.get('fillColor'),'#e5e7eb' if is_group else 'transparent'),
                     fillOpacity=bounded(item.get('backgroundOpacity') if is_group else item.get('fillOpacity'),1,0,1),
                     borderColor=color(item.get('borderColor'),'#78909c'),
                     borderWidth=bounded(item.get('borderWidth'),1,0,20),
                     borderStyle=item.get('borderStyle') if item.get('borderStyle') in ('solid','dashed','dotted','double') else 'dashed' if is_group else 'solid',
                     cornerRadius=bounded(item.get('borderRadius') if is_group else item.get('cornerRadius'),8 if is_group else 0,0,1000),
                     color=color(item.get('labelColor',item.get('color')),'#607d8b'),
                     labelPosition=text(item.get('labelPosition') or 'top-left'),
                     fontSize=bounded(item.get('fontSize'),14,6,160),
                     fontColor=color(item.get('fontColor'),'#333333'),
                     fontWeight='bold' if item.get('fontWeight')=='bold' else 'normal',
                     fontStyle='italic' if item.get('fontStyle')=='italic' else 'normal',
                     textAlign=item.get('textAlign') if item.get('textAlign') in ('left','center','right') else 'left',
                     textDecoration='underline' if item.get('textDecoration')=='underline' else 'none',
                     backgroundColor=color(item.get('backgroundColor'),'transparent'),
                     rotation=number(item.get('rotation'),0),zIndex=number(item.get('zIndex'),-1 if key!='freeTextAnnotations' else 1))
            if ('backgroundOpacity' if is_group else 'fillOpacity') in item:
                d['fillColor']=opaque_color(d['fillColor'])
            if key=='freeTextAnnotations':
                # Legacy auto-sized markdown notes have a 1em paragraph margin.
                # Their saved position is the outer box, not the first glyph.
                d['paragraphMargin']=d['fontSize'] if item.get('height') is None else 0
                d['fontFamily']=item.get('fontFamily') if item.get('fontFamily') in ('Arial','Verdana','Georgia','monospace','sans-serif','serif') else 'Arial'
                d['width']=bounded(item.get('width'),max(50,max((len(line) for line in d['text'].splitlines()),default=0)*d['fontSize']*.6+8),1,100000)
                d['height']=bounded(item.get('height'),max(1,len(d['text'].splitlines()))*d['fontSize']*1.5+8+2*d['paragraphMargin'],1,100000)
            end=item.get('endPosition') or {}
            d.update(x2=number(end.get('x'),d['x']+d['width']),y2=number(end.get('y'),d['y']+d['height']))
            decorations.append(d)
    if not nodes: raise ValueError('No nodes found; include the lab topology YAML')
    if len(nodes)>2000: raise ValueError('Too many drawing nodes')
    settings=data.get('viewerSettings') or {}
    if not isinstance(settings,dict): raise ValueError('Invalid viewer settings')
    return {'schema':3,'nodes':list(nodes.values()),'links':links,'decorations':decorations,'has_links_source':bool(topology),'skipped_links':skipped_links,
            'settings':{'background':color(settings.get('gridBgColor'),'#fdf6e3'),
                        'gridColor':color(settings.get('gridColor'),'#d2cbb5'),
                        'labelMode':settings.get('linkLabelMode') if settings.get('linkLabelMode') in ('show-all','on-select','hide') else 'show-all',
                        'endpointOffset':bounded(settings.get('endpointLabelOffset'),20,0,200)}}


def bind_drawing(lab):
    drawing=lab.get('drawing')
    if not drawing: return None
    aliases={}
    for n in lab['nodes']:
        prefix='clab-'+lab['name']+'-'
        for alias in {n['name'],n.get('short_name'),n.get('definition_node'),n['name'].removeprefix(prefix)}-{None,''}:
            aliases.setdefault(alias,set()).add(n['name'])
    result={**drawing,'nodes':[]}
    for n in drawing['nodes']:
        matches=aliases.get(n['alias'],set())
        result['nodes'].append({**n,'inventory_name':next(iter(matches)) if len(matches)==1 else None})
    return result


DEFAULT_USERS={'juniper_cjunosevolved':'admin','cisco_xrv9k':'clab','arista_ceos':'admin'}


def session_xml(lab, include_passwords=False):
    root=ET.Element('ArrayOfSessionData'); used=set()
    def segment(value):
        return re.sub(r'[/\\\x00-\x1f]', '_',value).strip() or 'Unnamed'
    folder=segment(lab['name'])
    for n in lab['nodes']:
        name=segment(n.get('short_name') or n['name'].removeprefix('clab-'+lab['name']+'-'))
        if name.casefold() in used: raise ValueError('Duplicate session short names; edit node names before exporting')
        used.add(name.casefold())
        creds=effective_credentials(lab,n)
        username=creds.get('username') or n.get('username') or DEFAULT_USERS.get(n.get('platform'),'')
        if any(ord(c)<32 for c in username): raise ValueError('Username contains unsupported control characters')
        password=creds.get('password','') if creds.get('auth')=='password' else ''
        extra=''
        if include_passwords and password:
            if any(ord(c)<32 for c in password): raise ValueError('Passwords with control characters cannot be exported')
            extra='-pw '+subprocess.list2cmdline([password])
        ET.SubElement(root,'SessionData',SessionId=folder+'/'+name,SessionName=name,ImageKey='computer',Host=n['address'],Port=str(n['port']),Proto='SSH',PuttySession='Default Settings',Username=username,ExtraArgs=extra,SPSLFileName='')
    ET.indent(root)
    return ET.tostring(root,encoding='utf-8',xml_declaration=True)


def install(app,store):
    def lab_for(ident):
        lab=store.lab(ident)
        if not lab: raise HTTPException(404,'Lab not found')
        return lab
    @app.get('/api/labs/{lab_id}/topology')
    def drawing(lab_id:str):
        with store.lock: return bind_drawing(lab_for(lab_id))
    @app.post('/api/labs/{lab_id}/topology')
    async def upload(lab_id:str, annotations:UploadFile=File(...), topology:UploadFile|None=File(None)):
        try:
            result=parse_drawing(await annotations.read(1024*1024+1),await topology.read(1024*1024+1) if topology and topology.filename else None)
        except (ValueError,TypeError,AttributeError,RecursionError) as exc: raise HTTPException(400,'Invalid drawing: '+str(exc))
        finally:
            await annotations.close()
            if topology: await topology.close()
        with store.lock:
            lab=lab_for(lab_id); lab['drawing']=result; store.save()
            store.event('topology.import',f'Imported {len(result["nodes"])} drawing nodes and {len(result["links"])} links',lab_id=lab_id)
            return bind_drawing(lab)
    class Export(BaseModel):
        model_config=ConfigDict(extra='forbid')
        include_passwords:bool=False
    @app.post('/api/labs/{lab_id}/superputty')
    def export(lab_id:str,options:Export):
        with store.lock:
            try:
                lab=lab_for(lab_id)
                content=session_xml(lab,options.include_passwords)
                filename=re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_',lab['name']).strip(' .') or 'lab'
                filename=filename[:150]+'.xml'
            except ValueError as exc: raise HTTPException(400,str(exc))
            store.event('sessions.export','SuperPuTTY sessions exported; passwords included='+str(options.include_passwords),lab_id=lab_id)
        return Response(content,media_type='application/xml',headers={'Content-Disposition':"attachment; filename=\"sessions.xml\"; filename*=UTF-8''"+quote(filename,safe='')})
