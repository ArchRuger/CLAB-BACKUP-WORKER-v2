"""Validated visual annotations; never alters deployed nodes or topology wiring."""
import hashlib
import json
from .topology import color, number


def revision(drawing):
    return hashlib.sha256(json.dumps(drawing, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def decorations(items):
    if len(items) > 2000 or len(json.dumps(items).encode()) > 1024 * 1024:
        raise ValueError('Use at most 2000 annotations and 1 MiB of annotation data.')
    result = []
    ranges = {'width': (1,100000,200), 'height': (1,100000,100), 'fontSize': (6,160,14),
              'fillOpacity': (0,1,.22), 'borderWidth': (0,20,1), 'cornerRadius': (0,1000,8),
              'paragraphMargin': (0,160,0), 'rotation': (-360,360,0), 'zIndex': (-100000,100000,0)}
    choices = {'borderStyle': ('solid','dashed','dotted','double'), 'fontWeight': ('normal','bold'),
               'fontStyle': ('normal','italic'), 'textDecoration': ('none','underline'),
               'textAlign': ('left','center','right'), 'fontFamily': ('Arial','Verdana','Georgia','monospace','sans-serif','serif'),
               'labelPosition': ('top-left','top-center','top-right','bottom-left','bottom-center','bottom-right')}
    colors = {'fillColor':'transparent','borderColor':'#78909c','fontColor':'#333333',
              'color':'#607d8b','backgroundColor':'transparent'}
    for item in items:
        kind=item.get('type')
        if kind not in ('text','rectangle','circle','line','group'):
            raise ValueError('Choose text, box, circle, line or group annotations.')
        text=item.get('text','')
        if not isinstance(text,str) or len(text)>4000 or any(ord(c)<32 and c not in '\n\t' for c in text):
            raise ValueError('Annotation text must contain at most 4000 printable characters.')
        row={'type':kind,'text':text,'x':number(item.get('x')),'y':number(item.get('y'))}
        for key,(low,high,default) in ranges.items():
            value=number(item.get(key),default)
            if not low<=value<=high: raise ValueError('Annotation size or style is outside the supported range.')
            row[key]=value
        for key,values in choices.items():
            value=item.get(key,values[0])
            if value not in values: raise ValueError('Unsupported annotation style.')
            row[key]=value
        for key,default in colors.items():
            value=item.get(key,default)
            if color(value,None) is None: raise ValueError('Use a supported annotation color.')
            row[key]=value
        row['x2']=number(item.get('x2'),min(100000,row['x']+row['width']))
        row['y2']=number(item.get('y2'),min(100000,row['y']+row['height']))
        result.append(row)
    return result


def annotations(drawing):
    """Export the .annotations.json format accepted by the existing importer."""
    out={'nodeAnnotations':[], 'freeTextAnnotations':[], 'freeShapeAnnotations':[], 'groupStyleAnnotations':[], 'edgeAnnotations':[]}
    for n in drawing['nodes']:
        item={k:v for k,v in n.items() if k not in ('x','y','inventory_name','alias')}
        item.update(position={'x':n['x'],'y':n['y']},yamlNodeId=n.get('alias',n['id']))
        out['nodeAnnotations'].append(item)
    for i,d in enumerate(drawing.get('decorations',[])):
        item={k:v for k,v in d.items() if k not in ('type','x','y','x2','y2')}
        item.update(id=f'annotation-{i}',position={'x':d['x'],'y':d['y']},
                    endPosition={'x':d.get('x2',d['x']+d['width']),'y':d.get('y2',d['y']+d['height'])})
        # The upstream format treats explicit opacity as replacing color alpha.
        # Omit the default to preserve imported RGBA/hex-alpha fills verbatim.
        preserve_alpha = d.get('fillOpacity',1)==1
        if preserve_alpha: item.pop('fillOpacity',None)
        if d['type']=='group':
            item.update(name=d.get('text',''),backgroundColor=d.get('fillColor','transparent'),
                        backgroundOpacity=d.get('fillOpacity',1),borderRadius=d.get('cornerRadius',8),labelColor=d.get('color','#607d8b'))
            if preserve_alpha: item.pop('backgroundOpacity',None)
            out['groupStyleAnnotations'].append(item)
        elif d['type']=='text': out['freeTextAnnotations'].append(item)
        else:
            item.update(shapeType=d['type'],labelColor=d.get('color','#607d8b'))
            out['freeShapeAnnotations'].append(item)
    for pair in drawing.get('links',[]):
        if any('label_offset' in e for e in pair):
            out['edgeAnnotations'].append(dict(source=pair[0]['node'],sourceEndpoint=pair[0]['interface'],
                target=pair[1]['node'],targetEndpoint=pair[1]['interface'],endpointLabelOffsetEnabled=True,
                endpointLabelOffset=pair[0].get('label_offset',20)))
    s=drawing.get('settings',{})
    out['viewerSettings']=dict(gridBgColor=s.get('background','#fdf6e3'),gridColor=s.get('gridColor','#d2cbb5'),
        linkLabelMode=s.get('labelMode','show-all'),endpointLabelOffset=s.get('endpointOffset',20))
    return out
