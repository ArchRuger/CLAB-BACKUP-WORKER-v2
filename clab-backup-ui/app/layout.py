"""Validated visual annotations; never alters deployed nodes or topology wiring."""
import hashlib
import json
import math
from .topology import color, number, grid_position


def revision(drawing):
    return hashlib.sha256(json.dumps(drawing, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


# The full annotations document of a lab. The drawing is the manager's own, smaller picture of it (what the
# Topology view draws); the document is what the map editor reads and writes, with everything the manager
# does not draw kept as it came: group membership and nesting, line arrows, geo coordinates, unknown keys.
# `annotations_for` ties the stored text to the drawing derived from it, so a drawing changed by another
# path (the older Edit map dialog, a sync from the VM) is never served with a document that no longer fits.
MAX_DOCUMENT = 1024 * 1024


def keep_document(lab, raw):
    """Remember the annotations text a drawing was just derived from. Call after lab['drawing'] is set."""
    text = raw.decode('utf-8-sig') if isinstance(raw, (bytes, bytearray)) else str(raw or '')
    # Which VM sync was current when this document was written. A sync stamps the new `vm_source.synced_at` right
    # after this call, so a document a sync wrote ends up different from it; a document a person wrote (Edit map,
    # an uploaded map) is still equal to it. runner.topology_capture reads the pair to tell the two apart.
    lab['map_written_at'] = (lab.get('vm_source') or {}).get('synced_at') or ''
    if not text.strip() or len(text.encode()) > MAX_DOCUMENT or not lab.get('drawing'):
        lab.pop('annotations', None); lab.pop('annotations_for', None); return
    lab['annotations'] = text; lab['annotations_for'] = revision(lab['drawing'])


def map_document(lab):
    """The text the map editor opens: the stored document while it still belongs to the drawing, else one
    written from the drawing (positions, texts, shapes, groups, link label offsets, viewer settings)."""
    drawing = lab.get('drawing')
    if not drawing: return ''
    if lab.get('annotations') and lab.get('annotations_for') == revision(drawing): return lab['annotations']
    return json.dumps(annotations(drawing), ensure_ascii=False, indent=2)


def decorations(items):
    if len(items) > 2000 or len(json.dumps(items).encode()) > 1024 * 1024:
        raise ValueError('Use at most 2000 annotations and 1 MiB of annotation data.')
    result = []
    ranges = {'width': (1,100000,200), 'height': (1,100000,100), 'fontSize': (6,160,14),
              'fillOpacity': (0,1,.22), 'borderWidth': (0,20,1), 'cornerRadius': (0,1000,8),
              'paragraphMargin': (0,160,0), 'rotation': (-360,360,0), 'zIndex': (-100000,100000,0),
              'lineArrowSize': (4,40,10), 'level': (1,10,1)}
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
        # Booleans are exact: only `true` turns an arrow on; only `false` turns the rounded text background off.
        row['lineStartArrow']=item.get('lineStartArrow') is True
        row['lineEndArrow']=item.get('lineEndArrow') is True
        row['roundedBackground']=item.get('roundedBackground') is not False
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
        # Each style key belongs to one kind; the others never write it into the document.
        for key in ('lineStartArrow','lineEndArrow','lineArrowSize'):
            if d['type']!='line': item.pop(key,None)
        if d['type']!='text': item.pop('roundedBackground',None)
        if d['type']!='group': item.pop('level',None)
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
        linkLabelMode=s.get('labelMode','show-all'),endpointLabelOffset=s.get('endpointOffset',20),
        nodeStyle=s.get('nodeStyle','icon'),boxSpacing=s.get('boxSpacing','default'),linkStyle=s.get('linkStyle','straight'))
    return out


ARRANGE_MODES = ('rows', 'columns', 'ring')
GAP_X, GAP_Y, LIMIT = 160, 120, 100000


def _bounded(points):
    """Scale a result down in whole numbers when a very large map would leave the coordinate range."""
    reach = max((max(abs(x), abs(y)) for x, y in points.values()), default=0)
    if reach <= LIMIT: return points
    factor = LIMIT / reach
    return {k: [int(x * factor), int(y * factor)] for k, (x, y) in points.items()}


def arrange(drawing, mode):
    """Positions for every node of a drawing: {node_id: [x, y]} of integers. Pure and deterministic.

    rows: breadth-first layers of each connected component, one layer per row; columns: the same turned;
    ring: every node on a circle in document order around the centre of the current positions.
    Nothing else of the drawing is read or changed."""
    if mode not in ARRANGE_MODES: raise ValueError('Choose rows, columns or a ring.')
    nodes = drawing.get('nodes') or []
    ids = [n['id'] for n in nodes]
    if mode == 'ring':
        count = len(ids)
        if not count: return {}
        radius = max(120, GAP_X * count / (2 * math.pi))
        cx = (min(n['x'] for n in nodes) + max(n['x'] for n in nodes)) / 2
        cy = (min(n['y'] for n in nodes) + max(n['y'] for n in nodes)) / 2
        return _bounded({n['id']: [round(cx + radius * math.cos(2 * math.pi * i / count - math.pi / 2)),
                                   round(cy + radius * math.sin(2 * math.pi * i / count - math.pi / 2))]
                         for i, n in enumerate(nodes)})
    known = set(ids)
    neighbours = {i: set() for i in ids}
    degree = dict.fromkeys(ids, 0)
    for pair in drawing.get('links') or []:
        if len(pair) != 2: continue
        a, b = pair[0].get('node'), pair[1].get('node')
        if a not in known or b not in known or a == b: continue
        degree[a] += 1; degree[b] += 1
        neighbours[a].add(b); neighbours[b].add(a)
    seen = set(); components = []
    for index, start in enumerate(ids):
        if start in seen or not neighbours[start]: continue
        members = [start]; seen.add(start)
        for current in members:
            for other in sorted(neighbours[current]):
                if other not in seen: seen.add(other); members.append(other)
        components.append((-len(members), index, members))
    components.sort(key=lambda c: c[:2])
    placed = {}; offset = 0; depth = 0
    for _, _, members in components:
        root = min(members, key=lambda i: (-degree[i], i))
        layers = [[root]]; reached = {root}
        while True:
            following = []
            for current in layers[-1]:
                for other in sorted(neighbours[current]):
                    if other not in reached: reached.add(other); following.append(other)
            if not following: break
            layers.append(following)
        width = max(len(layer) for layer in layers)
        for row, layer in enumerate(layers):
            shift = (width - len(layer)) * GAP_X // 2
            for column, ident in enumerate(layer):
                placed[ident] = [offset + shift + column * GAP_X, row * GAP_Y]
        offset += (width + 1) * GAP_X
        depth = max(depth, len(layers))
    # Nodes with no link wrap eight to a row, like the default grid, below everything else.
    for index, ident in enumerate(i for i in ids if i not in seen):
        x, y = grid_position(index)
        placed[ident] = [x, y + depth * GAP_Y]
    if mode == 'columns': placed = {k: [y, x] for k, (x, y) in placed.items()}
    return _bounded({i: placed[i] for i in ids})
