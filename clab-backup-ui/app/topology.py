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
from .inventory import read_data, DEFAULT_CREDENTIALS
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


# containerlab wires each supported kind's own port names onto sequential "ethN" container
# veths in a fixed, documented order — never a "+1" guess. `offset` is how many veths the
# image reserves for itself before the first data port (so container index = N + offset);
# `prefix` is the NOS-style name that port N is drawn with. Sources, each kind's own manual
# page on containerlab.dev:
#  - juniper_vjunosswitch / vjunosevolved / vjunosrouter: https://containerlab.dev/manual/kinds/vr-vjunosswitch/
#    (and the vjunosevolved/vjunosrouter pages next to it) — the first data interface is eth1 == ge-0/0/0.
#  - juniper_cjunosevolved: https://containerlab.dev/manual/kinds/cjunosevolved/ — eth1-eth3 are the
#    image's own re0-mgmt/fabric/internal interfaces; the first data port et-0/0/0 is eth4 (confirmed
#    against a live `restore-square` deploy log and matches telemetry_names.nos_interface).
#  - juniper_vqfx: https://containerlab.dev/manual/kinds/vr-vqfx/ — the first data interface is
#    eth1 == xe-0/0/0.
#  - cisco_xrv9k: https://containerlab.dev/manual/kinds/vr-xrv9k/ — the first data interface is
#    eth1 == Gi0/0/0/0 (also confirmed live and by telemetry_names.nos_interface).
#  - arista_ceos: https://containerlab.dev/manual/kinds/ceos/ — EthernetN is eth(N) exactly.
#  - nokia_srlinux (see NOKIA_PORT below): https://containerlab.dev/manual/kinds/srl/ — containerlab
#    keeps the NOS's own `e1-N` veth name; there is no `ethN` form to reverse.
PORT_RULES={
    'juniper_vjunosswitch':('ge-0/0/',re.compile(r'(?i)^ge-0/0/(\d+)$'),1),
    'juniper_vjunosevolved':('ge-0/0/',re.compile(r'(?i)^ge-0/0/(\d+)$'),1),
    'juniper_vjunosrouter':('ge-0/0/',re.compile(r'(?i)^ge-0/0/(\d+)$'),1),
    'juniper_cjunosevolved':('et-0/0/',re.compile(r'(?i)^et-0/0/(\d+)$'),4),
    'juniper_vqfx':('xe-0/0/',re.compile(r'(?i)^xe-0/0/(\d+)$'),1),
    'cisco_xrv9k':('Gi0/0/0/',re.compile(r'(?i)^(?:gi|gigabitethernet)0/0/0/(\d+)$'),1),
    'vr-xrv9k':('Gi0/0/0/',re.compile(r'(?i)^(?:gi|gigabitethernet)0/0/0/(\d+)$'),1),
    'arista_ceos':('Ethernet',re.compile(r'(?i)^(?:ethernet|et)(\d+)$'),0),
}
# A name already shaped like the container's own veth (`eth3`, or the shorter `e3`) passes
# through unchanged for any kind, including `linux` and kinds with no rule above.
CONTAINER_NAME=re.compile(r'(?i)^e(?:th)?(\d+)$')
# nokia_srlinux keeps its own `e1-N` veth name rather than a generic ethN; `ethernet-1/N` is the
# same port's NOS-displayed alias. https://containerlab.dev/manual/kinds/srl/
NOKIA_PORT_LONG=re.compile(r'(?i)^ethernet-1/(\d+)$')
NOKIA_PORT_SHORT=re.compile(r'^e1-(\d+)$')


def container_interface(kind, name):
    """The Linux veth inside the container that carries a NOS-named data port.

    Returns '' when the kind or the port's shape is not recognised, so a stale or invented
    mapping is never offered; the caller still confirms the result against the runtime
    interface list before preselecting it. A breakout child or sub-interface (`ge-0/0/1:0`,
    `et-0/0/0.100`) does not name a single veth and also resolves to ''.
    """
    if not isinstance(name,str): return ''
    value=name.strip()
    if not value: return ''
    # Already the container's own veth name (any kind, including `linux` and an unknown kind).
    match=CONTAINER_NAME.fullmatch(value)
    if match: return 'eth'+match[1]
    if not isinstance(kind,str): return ''
    if kind=='nokia_srlinux':
        match=NOKIA_PORT_LONG.fullmatch(value) or NOKIA_PORT_SHORT.fullmatch(value)
        return 'e1-'+match[1] if match else ''
    _,pattern,offset=PORT_RULES.get(kind,(None,None,None))
    if not pattern: return ''
    match=pattern.fullmatch(value)
    return 'eth'+str(int(match[1])+offset) if match else ''


def displayed_interface(kind, name):
    """The label a container veth shows on the map: the NOS's own port name for that kind's
    data ports, or the veth name unchanged when there is no rule or the veth belongs to the
    image itself (reserved below the rule's offset, e.g. cJunosEvolved's own eth1-eth3)."""
    if not isinstance(name,str): return ''
    if not isinstance(kind,str): return name
    if kind=='nokia_srlinux': return name
    match=re.fullmatch(r'(?i)eth(\d+)',name.strip())
    if not match: return name
    index=int(match[1])
    prefix,_,offset=PORT_RULES.get(kind,(None,None,None))
    if not prefix or index<offset: return name
    return prefix+str(index-offset)


def exported_interface(interface, kind):
    """Reverse containerlab's XRv9k data-port mapping, not allocation patterns.

    Only XRv9k's own veth-to-port order is reversed here (eth1 == Gi0/0/0/0, from the same
    `PORT_RULES` table `container_interface` uses). This project's saved topology YAMLs
    already write Junos and EOS links with containerlab's own `ethN` names (the fixture
    regression test in test_topology.py pins that), so no other kind is reversed here; native
    YAML interface names must remain unchanged (e.g. Junos eth4).
    """
    if kind not in ('cisco_xrv9k','vr-xrv9k'): return interface
    prefix,_,offset=PORT_RULES[kind]
    match=re.fullmatch(r'eth(\d+)',interface)
    if match and int(match[1])>=offset:
        return prefix+str(int(match[1])-offset)
    return interface


def opaque_color(value):
    """Explicit fillOpacity replaces RGBA alpha in the upstream renderer."""
    match=re.fullmatch(r'rgba\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*[\d.]+\s*\)',value)
    if match: return 'rgb('+','.join(match.groups())+')'
    if value.startswith('#') and len(value) in (5,9): return value[:-1] if len(value)==5 else value[:-2]
    return value


def grid_position(index):
    """Where a node without a saved position goes: a row of eight, 160 px apart, 120 px per row."""
    return (index%8)*160, (index//8)*120


def unplaced(drawing):
    """True when the nodes still sit on the default grid: nobody and no annotations file placed them.

    Drawings saved before the flag existed are judged by their coordinates, so a workspace that was
    saved from the topology YAML alone (Deploy lab, Save to manager) can still take the positions of
    the annotations file beside the deployed topology; a node moved by hand keeps the map as it is.
    """
    if not isinstance(drawing,dict) or not drawing.get('nodes'): return False
    if 'placed' in drawing: return not drawing['placed']
    return all((n.get('x'),n.get('y'))==grid_position(i) for i,n in enumerate(drawing['nodes']))


def parse_drawing(raw, topology=None):
    if len(raw)>1024*1024: raise ValueError('Annotations must be smaller than 1 MiB')
    data=json.loads(raw)
    if not isinstance(data,dict) or not any(k in data for k in ('nodeAnnotations','networkNodeAnnotations','freeTextAnnotations','groupStyleAnnotations','freeShapeAnnotations')):
        raise ValueError('Upload a containerlab .annotations.json file')
    nodes={}; links=[]; decorations=[]; skipped_links=0; kinds={}; aliases={}; placed=False
    for index,n in enumerate(rows(data,'nodeAnnotations')+rows(data,'networkNodeAnnotations')):
        ident=text(n.get('id'))
        if not ident or ident in nodes: raise ValueError('Drawing node IDs must be unique and nonempty')
        pos=n.get('position') or {}
        if pos.get('x') is not None or pos.get('y') is not None: placed=True
        default=grid_position(index)
        nodes[ident]={'id':ident,'alias':text(n.get('yamlNodeId') or n.get('copyFrom') or ident), 'label':text(n.get('label') or ident),
                      'x':number(pos.get('x'),default[0]),'y':number(pos.get('y'),default[1]),
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
            if short not in nodes: nodes[short]={'id':short,'alias':short,'label':short,**dict(zip(('x','y'),grid_position(len(nodes))))}
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
                if node not in nodes: nodes[node]={'id':node,'alias':node,'label':node,**dict(zip(('x','y'),grid_position(len(nodes))))}
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
                d['paragraphMargin']=bounded(item.get('paragraphMargin'),d['fontSize'] if item.get('height') is None else 0,0,160)
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
    return {'schema':3,'nodes':list(nodes.values()),'links':links,'decorations':decorations,'has_links_source':bool(topology),'skipped_links':skipped_links,'placed':placed,
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
    platforms={n['name']:n.get('platform','') for n in lab['nodes']}
    from .layout import revision
    result={**drawing,'nodes':[],'revision':revision(drawing)}
    bound={}
    for n in drawing['nodes']:
        matches=aliases.get(n['alias'],set())
        inventory_name=next(iter(matches)) if len(matches)==1 else None
        result['nodes'].append({**n,'inventory_name':inventory_name})
        bound[n['id']]=inventory_name
    # The container veth Wireshark can capture on for this drawn port, or '' when the device's
    # kind is unknown or the port's own drawn name is not one container_interface recognises;
    # the browser still confirms it against the live interface list before offering it.
    result['links']=[[{**ep,'capture_interface':container_interface(platforms.get(bound.get(ep['node']),''),ep['interface'])} for ep in pair] for pair in drawing['links']]
    return result


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
        username=creds.get('username') or n.get('username') or DEFAULT_CREDENTIALS.get(n.get('platform') or '',('',''))[0]
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
            raw_annotations=await annotations.read(1024*1024+1)
            result=parse_drawing(raw_annotations,await topology.read(1024*1024+1) if topology and topology.filename else None)
        except (ValueError,TypeError,AttributeError,RecursionError) as exc: raise HTTPException(400,'Invalid drawing: '+str(exc))
        finally:
            await annotations.close()
            if topology: await topology.close()
        with store.lock:
            from .lab_operations import operation_busy
            if operation_busy(store.state,lab_id): raise HTTPException(409,'Wait for the lab operation to finish.')
            from .layout import keep_document
            lab=lab_for(lab_id); lab['drawing']=result; keep_document(lab,raw_annotations); store.save()
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
