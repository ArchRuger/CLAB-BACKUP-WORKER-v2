"""Editable, uncompressed draw.io XML; no external images or services required.

Format: https://www.drawio.com/docs/reference/diagram-generation/
"""
import copy
import math
import xml.etree.ElementTree as ET
from .layout import arrange

LAYOUTS = ('map', 'interactive', 'rows', 'columns')
THEMES = ('manager', 'print')


def drawio(lab, layout='map', theme='manager'):
    """The lab's stored picture as draw.io XML. Built from stored data only.

    layout: map (the stored positions; `interactive` is its old name), rows or columns (the manager's own
    arrangement for the file only; the stored map is never changed and notes, boxes and groups are left out
    because they were placed for the saved positions). theme: manager (the map's colours) or print (black on white)."""
    if layout not in LAYOUTS:
        raise ValueError('Choose a supported layout.')
    if theme not in THEMES:
        raise ValueError('Choose a supported theme.')
    printing = theme == 'print'
    drawing = lab.get('drawing') or {'nodes': [], 'links': [], 'decorations': []}
    if layout in ('rows', 'columns'):
        drawing = copy.deepcopy(drawing)
        placed = arrange(drawing, layout)
        for n in drawing['nodes']:
            n['x'], n['y'] = placed[n['id']]
        drawing['decorations'] = []
    settings = drawing.get('settings', {})
    boxed = settings.get('nodeStyle') == 'boxed'
    box = 64 if settings.get('boxSpacing') == 'narrow' else 80
    size = box if boxed else 40
    elbow = settings.get('linkStyle') == 'elbow'
    background = '#ffffff' if printing else settings.get('background', '#fff8e5')
    document = ET.Element('mxfile', host='Containerlab Node Manager')
    page = ET.SubElement(document, 'diagram', id='lab-topology', name=lab['name'])
    model = ET.SubElement(page, 'mxGraphModel', grid='1', gridSize='10', page='0',
                          background=background)
    root = ET.SubElement(model, 'root')
    ET.SubElement(root, 'mxCell', id='0')
    ET.SubElement(root, 'mxCell', id='1', parent='0')

    def cell(ident, value='', style='', parent='1', **attrs):
        return ET.SubElement(root, 'mxCell', id=ident, value=str(value), style=style,
                             parent=parent, **attrs)

    def geometry(c, x, y, w, h):
        return ET.SubElement(c, 'mxGeometry', x=str(x), y=str(y), width=str(w),
                             height=str(h), **{'as': 'geometry'})

    def safe(value):
        # Imported values cannot inject additional mxGraph style properties.
        return str(value).replace(';', '').replace('=', '')

    decorations = drawing.get('decorations', [])
    containers = [(i, d) for i, d in enumerate(decorations)
                  if d['type'] in ('group', 'rectangle', 'circle')]

    def parent_for(n, w=size, h=size):
        matches = [(i, d) for i, d in containers if d['x'] <= n['x'] and d['y'] <= n['y']
                   and d['x']+d['width'] >= n['x']+w and d['y']+d['height'] >= n['y']+h]
        if matches:
            i, d = min(matches, key=lambda pair: pair[1]['width']*pair[1]['height'])
            return f'annotation-{i}', n['x']-d['x'], n['y']-d['y']
        return '1', n['x'], n['y']

    for i, d in sorted(enumerate(decorations), key=lambda pair: (pair[1].get('zIndex', 0), pair[1].get('level', 1))):
        kind = d['type']
        text = d.get('text', '')
        font_style = (1 if d.get('fontWeight') == 'bold' else 0) | (2 if d.get('fontStyle') == 'italic' else 0) | (4 if d.get('textDecoration') == 'underline' else 0)
        font_color = '#000000' if printing else safe(d.get('fontColor') or d.get('color') or '#607d8b')
        line_color = '#000000' if printing else safe(d.get('borderColor') or d.get('color') or '#607d8b')
        style = f"html=0;whiteSpace=wrap;fontSize={d.get('fontSize', 14)};fontColor={font_color};fontStyle={font_style};fontFamily={safe(d.get('fontFamily', 'Arial'))};rotation={d.get('rotation', 0)};"
        if kind == 'line':
            size_ = d.get('lineArrowSize', 10)
            arrows = (f'startArrow=classic;startSize={size_};' if d.get('lineStartArrow') else '') + (f'endArrow=classic;endSize={size_};' if d.get('lineEndArrow') else 'endArrow=none;')
            c = cell(f'annotation-{i}', text, style+f"{arrows}strokeColor={line_color};strokeWidth={d.get('borderWidth', 1)};dashed={int(d.get('borderStyle') == 'dashed')};", edge='1')
            g = ET.SubElement(c, 'mxGeometry', relative='1', **{'as': 'geometry'})
            ET.SubElement(g, 'mxPoint', x=str(d['x']), y=str(d['y']), **{'as': 'sourcePoint'})
            ET.SubElement(g, 'mxPoint', x=str(d.get('x2', d['x']+d['width'])), y=str(d.get('y2', d['y']+d['height'])), **{'as': 'targetPoint'})
            continue
        if kind == 'text':
            style += f"text;strokeColor=none;fillOpacity={d.get('fillOpacity', 1)*100};fillColor={'none' if printing else safe(d.get('backgroundColor') or 'none')};{'rounded=1;' if d.get('roundedBackground', True) else ''}align={safe(d.get('textAlign', 'left'))};verticalAlign=top;spacing=4;"
        else:
            label = d.get('labelPosition', 'top-left')
            style += f"shape={'ellipse' if kind == 'circle' else 'rectangle'};container=1;collapsible=0;recursiveResize=0;fillColor={'none' if printing else safe(d.get('fillColor') or 'none')};fillOpacity={d.get('fillOpacity', 1)*100};strokeColor={'#000000' if printing else safe(d.get('borderColor') or '#607d8b')};strokeWidth={d.get('borderWidth', 1)};dashed={int(d.get('borderStyle') == 'dashed')};rounded={int(bool(d.get('cornerRadius', 0)))};absoluteArcSize=1;arcSize={d.get('cornerRadius', 0)*2};verticalLabelPosition={'bottom' if 'bottom' in label else 'top'};verticalAlign={'top' if 'bottom' in label else 'bottom'};align={'right' if 'right' in label else 'center' if 'center' in label else 'left'};"
        c = cell(f'annotation-{i}', text, style, vertex='1')
        geometry(c, d['x'], d['y'], d['width'], d['height'])

    # Native editable symbol cells grouped with each node, rather than external icons.
    node_ids = {}
    nodes = {n['id']: n for n in drawing['nodes']}
    for i, n in enumerate(drawing['nodes']):
        ident = f'node-{i}'; node_ids[n['id']] = ident
        parent, x, y = parent_for(n)
        position = n.get('labelPosition', 'bottom')
        # The editor's label positions, including the four corners (the label diagonally off the icon's corner).
        label_style = {'center': 'verticalLabelPosition=middle;labelPosition=center;align=center;verticalAlign=middle;',
                       'top': 'verticalLabelPosition=top;verticalAlign=bottom;',
                       'left': 'labelPosition=left;align=right;verticalAlign=middle;',
                       'right': 'labelPosition=right;align=left;verticalAlign=middle;',
                       'top-left': 'labelPosition=left;verticalLabelPosition=top;align=right;verticalAlign=bottom;',
                       'top-right': 'labelPosition=right;verticalLabelPosition=top;align=left;verticalAlign=bottom;',
                       'bottom-left': 'labelPosition=left;verticalLabelPosition=bottom;align=right;verticalAlign=top;',
                       'bottom-right': 'labelPosition=right;verticalLabelPosition=bottom;align=left;verticalAlign=top;'}.get(position, 'verticalLabelPosition=bottom;verticalAlign=top;')
        if boxed:
            # A boxed node carries its name inside the box, at the bottom.
            label_style = 'verticalLabelPosition=middle;labelPosition=center;align=center;verticalAlign=bottom;'
        if printing:
            look = f"rounded=1;absoluteArcSize=1;arcSize={n.get('iconCornerRadius', 4)*2};fillColor=#ffffff;strokeColor=#000000;strokeWidth=1.5;fontColor=#000000;fontSize=11;labelBackgroundColor=none;spacing=4;html=0;"
        else:
            look = f"rounded=1;absoluteArcSize=1;arcSize={n.get('iconCornerRadius', 4)*2};fillColor={safe(n.get('iconColor') or '#0066ff')};strokeColor=none;fontColor=#ffffff;fontSize=11;labelBackgroundColor={safe(n.get('labelBackgroundColor') or '#454545')};spacing=4;html=0;"
        c = cell(ident, n.get('label') or n.get('alias') or n['id'], look+label_style, parent=parent, vertex='1')
        geometry(c, x, y, size, size)
        shift_x, shift_y = ((size-40)/2, 6) if boxed else (0, 0)
        symbol_color = '#000000' if printing else '#ffffff'
        icon = n.get('icon', 'router')
        if icon == 'server':
            for row in range(3):
                item=cell(f'symbol-{i}-{row}', '', f'rounded=0;fillColor=none;strokeColor={symbol_color};strokeWidth=1.5;', parent=ident, vertex='1')
                geometry(item, 9+shift_x, 7+row*9+shift_y, 22, 8)
        else:
            segments = [(7,13,33,13),(33,27,7,27)] if icon == 'switch' else [(20,20,20,5),(20,20,35,20),(20,20,20,35),(20,20,5,20)]
            rotation=dict(up=0,right=90,down=180,left=270).get(n.get('direction'),0)*math.pi/180
            for j,(x1,y1,x2,y2) in enumerate(segments):
                def rotate(x,y):
                    return 20+(x-20)*math.cos(rotation)-(y-20)*math.sin(rotation),20+(x-20)*math.sin(rotation)+(y-20)*math.cos(rotation)
                x1,y1=rotate(x1,y1);x2,y2=rotate(x2,y2)
                x1+=shift_x;x2+=shift_x;y1+=shift_y;y2+=shift_y
                item=cell(f'symbol-{i}-{j}', '', f'endArrow=open;endSize=5;strokeColor={symbol_color};strokeWidth=1.5;', parent=ident, edge='1')
                g=ET.SubElement(item,'mxGeometry',relative='1',**{'as':'geometry'})
                ET.SubElement(g,'mxPoint',x=str(x1),y=str(y1),**{'as':'sourcePoint'})
                ET.SubElement(g,'mxPoint',x=str(x2),y=str(y2),**{'as':'targetPoint'})

    for i, pair in enumerate(drawing.get('links', [])):
        if len(pair) != 2 or any(e['node'] not in node_ids for e in pair):
            continue
        a, b = pair
        c = cell(f'link-{i}', style=('endArrow=none;startArrow=none;strokeColor=#000000;strokeWidth=2;rounded=0;html=0;' if printing else 'endArrow=none;startArrow=none;strokeColor=#79df87;strokeWidth=3;rounded=0;html=0;')+('edgeStyle=orthogonalEdgeStyle;' if elbow else ''),
                 edge='1', source=node_ids[a['node']], target=node_ids[b['node']])
        ET.SubElement(c, 'mxGeometry', relative='1', **{'as': 'geometry'})
        dx, dy = nodes[b['node']]['x']-nodes[a['node']]['x'], nodes[b['node']]['y']-nodes[a['node']]['y']
        length = math.hypot(dx, dy) or 1
        for j, e in enumerate(pair):
            if not e.get('interface'): continue
            label = cell(f'interface-{i}-{j}', e['interface'], f"edgeLabel;html=0;align=center;verticalAlign=middle;fontSize=10;fontColor={'#333333' if printing else '#607d8b'};labelBackgroundColor={'#ffffff' if printing else '#fff8e5'};resizable=0;", parent=f'link-{i}', vertex='1', connectable='0')
            offset = min(.45, (20+settings.get('endpointOffset', 20))/length)
            g = geometry(label, (-1+2*offset)*(1 if j == 0 else -1), 0, 0, 0)
            g.set('relative', '1')
            ET.SubElement(g, 'mxPoint', x='0', y='-8', **{'as': 'offset'})
    return ET.tostring(document, encoding='utf-8', xml_declaration=True)
