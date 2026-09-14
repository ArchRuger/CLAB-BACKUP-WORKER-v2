"""Grafana lab map: a weathermap generated from the lab's saved drawing.

The optional Grafana stack renders the map with the community Flow panel plugin
(andrewbmchugh-flow-panel), the same plugin srl-labs uses in srl-telemetry-lab: an SVG
whose elements carry ids, and a panel configuration that binds those ids to the time
series of the panel's queries (colour, label text, dash animation). srl-labs draws that
SVG by hand for every lab (clab-io-draw plus a draw.io export); here the manager draws
it from the drawing its own map already uses (positions, icons, labels, wiring) and
binds it to the metrics it exports, so every lab gets a map without a drawing tool.

The generated dashboard is written as a file that Grafana provisions (MapPublisher);
nothing here talks to Grafana. The SVG is plain SVG with one element per cell: a path
per link direction, a circle per port and per node status, a text per rate label. The
plugin replaces the text of a leaf that holds a single text node, sets fill and stroke
on a cell's elements and drives animation-duration and animation-direction on them; the
dash animation itself is CSS inside the SVG. Everything derives from saved state (the
drawing and the node list), never from telemetry samples, so a file can be rebuilt at
any time and carries no secrets: names, positions and colours only.
"""
import hashlib
import json
import math
import os
from pathlib import Path
from urllib.parse import quote
from xml.sax.saxutils import escape as _escape

from .telemetry_metrics import STATE_CODES
from .telemetry_names import endpoint_candidates

PLUGIN = 'andrewbmchugh-flow-panel'
PLUGIN_VERSION = '1.20.1'                # pinned; setup_telemetry.py installs exactly this one
UID_PREFIX = 'clab-map-'
FOLDER_UID = 'clab-lab-maps'             # Grafana folder holding the provisioned lab maps
DATASOURCE = {'type': 'prometheus', 'uid': 'clab-prometheus'}
CANVAS = '#fdf6e3'                       # the manager map's own canvas, used in both Grafana themes
# Threshold levels sit strictly between the values they separate (a discrete value never lands
# on a level, so the colour does not depend on the plugin's comparison rule; seen live: a port at
# exactly 0 kept its previous colour with a level of 0).
# Link colour by the far end's receive rate (bit/s): idle grey, then the srl-telemetry-lab palette.
TRAFFIC_LEVELS = ((-1, '#bec8d2'), (10_000, '#4bdd33'), (500_000, '#ffff00'), (1_000_000, '#ff8000'), (5_000_000, '#ff3154'))
# Dash animation: still below 2 kbit/s, one cycle in 2.5 s at 10 kbit/s, 0.3 s from 5 Mbit/s up.
FLOW = {'thresholdOffValue': 2_000, 'thresholdLwrValue': 10_000, 'thresholdLwrDurationSecs': 2.5,
        'thresholdUprValue': 5_000_000, 'thresholdUprDurationSecs': 0.3, 'unidirectional': True}
PORT_LEVELS = ((-0.5, '#ff3154'), (0.5, '#4bdd33'))                  # oper-status 0 down / 1 up
NODE_LEVELS = ((-1.5, '#ff3154'), (-0.5, '#bec8d2'), (0.5, '#79e8f6'), (1.5, '#ff8000'), (2.5, '#4bdd33'))   # STATE_CODES -1 … 3
SIZE, R = 40, 20
ICONS = {'switch': 'M-13-8H13M-13 8H13M8-13L13-8L8-3M-8 3L-13 8L-8 13',
         'server': 'M-12-13H12V13H-12ZM-12-4H12M-12 4H12M-7-9H-3M-7 0H-3M-7 9H-3',
         'router': 'M-14-5H-5V-14M-9-10L-5-14L-1-10M5-14V-5H14M10-9L14-5L10-1M14 5H5V14M1 10L5 14L9 10M-5 14V5H-14M-10 1L-14 5L-10 9'}
# Colours the plugin drives (stroke of a link, fill of a dot) are presentation attributes on the
# element, never stylesheet rules: a CSS rule would win over the attribute the plugin sets.
STYLE = ('@keyframes clab-flow{to{stroke-dashoffset:-24}}'
         '.link{stroke-width:3;fill:none;stroke-linecap:round}'
         '.flow{stroke-dasharray:14 10;animation-name:clab-flow;animation-timing-function:linear;animation-iteration-count:infinite;animation-duration:0s}'
         '.plain{stroke:#87a9ab;stroke-width:2;fill:none}'
         '.iface rect{fill:#fffdf4;fill-opacity:.95}.iface text{fill:#607d8b;font-size:10px}'
         '.rate{font-size:11px;font-weight:600}'
         '.device-body{stroke:#fff;stroke-width:1}.device-symbol{stroke:#fff;stroke-width:1.4;stroke-linecap:round;stroke-linejoin:round;fill:none}'
         '.device-label rect{fill:#454545}.device-label text{fill:#fff;font-size:11px}'
         '.port{stroke:#fff;stroke-width:1.2}.status{stroke:#fff;stroke-width:1.5}'
         '.deco-text{fill:#333;font-size:14px}.deco-label{fill:#607d8b;font-size:12px}')


def esc(value):
    return _escape(str(value), {'"': '&quot;'})


def fmt(value):
    """Compact SVG numbers."""
    return str(int(value)) if float(value).is_integer() else f'{value:.1f}'


def map_uid(lab_id):
    """Grafana uids are limited to 40 characters; lab ids are 32-character hex strings."""
    clean = ''.join(c if c.isalnum() or c in '-_' else '-' for c in str(lab_id))[:24]
    return UID_PREFIX + (clean or 'lab')


def promql_string(value):
    return str(value).replace('\\', '\\\\').replace('"', '\\"').replace('\n', ' ')


def series_in(node, interface):
    return f'{node}:{interface}:in'


def series_oper(node, interface):
    return f'oper:{node}:{interface}'


def series_state(node):
    return f'state:{node}'


def icon_path(icon):
    icon = (icon or 'router').lower()
    if 'switch' in icon:
        return ICONS['switch']
    if any(word in icon for word in ('server', 'linux', 'host')):
        return ICONS['server']
    return ICONS['router']


def thresholds(levels):
    return [{'color': color, 'level': level} for level, color in levels]


def inventory(lab):
    """Inventory name -> (short name as the metrics label it, platform)."""
    return {n['name']: (n.get('short_name') or n['name'], n.get('platform') or '') for n in lab.get('nodes', [])}


def nos_interface(platform, drawn):
    candidates = endpoint_candidates(platform, drawn)
    return candidates[0] if candidates else str(drawn)


def bounds(drawing):
    xs, ys = [], []
    for n in drawing.get('nodes', []):
        cx, cy = n['x'] + 20, n['y'] + 20
        xs += [cx - 50, cx + 50]
        ys += [cy - 45, cy + 55]
    for d in drawing.get('decorations', []):
        xs += [d['x'], d.get('x2', d['x'] + d.get('width', 0)), d['x'] + d.get('width', 0)]
        ys += [d['y'], d.get('y2', d['y'] + d.get('height', 0)), d['y'] + d.get('height', 0)]
    if not xs:
        return (0, 0, 400, 240)
    x0, y0 = min(xs) - 30, min(ys) - 30
    return (math.floor(x0), math.floor(y0), max(320, math.ceil(max(xs) - x0 + 30)), max(200, math.ceil(max(ys) - y0 + 30)))


def decoration(d):
    x, y, w, h = d['x'], d['y'], d.get('width', 0), d.get('height', 0)
    cx, cy = x + w / 2, y + h / 2
    dash = {'dashed': '6 4', 'dotted': '2 3'}.get(d.get('borderStyle'), '')
    attrs = (f'fill="{esc(d.get("fillColor") or "transparent")}" fill-opacity="{d.get("fillOpacity", .22)}" '
             f'stroke="{esc(d.get("borderColor") or "#78909c")}" stroke-width="{d.get("borderWidth", 1)}" stroke-dasharray="{dash}"')
    kind = d.get('type')
    if kind == 'text':
        size = d.get('fontSize', 14)
        anchor = {'center': 'middle', 'right': 'end'}.get(d.get('textAlign'), 'start')
        tx = cx if anchor == 'middle' else x + w - 4 if anchor == 'end' else x + 4
        lines = str(d.get('text', '')).split('\n')
        spans = ''.join(f'<tspan x="{fmt(tx)}" dy="{fmt(size * 1.5) if i else 0}">{esc(line)}</tspan>' for i, line in enumerate(lines))
        body = (f'<rect x="{fmt(x)}" y="{fmt(y)}" width="{fmt(w)}" height="{fmt(h)}" fill="{esc(d.get("backgroundColor") or "transparent")}"/>'
                f'<text class="deco-text" x="{fmt(tx)}" y="{fmt(y + size + 4 + d.get("paragraphMargin", 0))}" text-anchor="{anchor}" font-size="{size}" '
                f'fill="{esc(d.get("fontColor") or d.get("color") or "#333")}">{spans}</text>')
    else:
        if kind == 'circle':
            body = f'<ellipse cx="{fmt(cx)}" cy="{fmt(cy)}" rx="{fmt(w / 2)}" ry="{fmt(h / 2)}" {attrs}/>'
        elif kind == 'line':
            body = f'<line x1="{fmt(x)}" y1="{fmt(y)}" x2="{fmt(d.get("x2", x + w))}" y2="{fmt(d.get("y2", y + h))}" {attrs}/>'
        else:
            body = f'<rect x="{fmt(x)}" y="{fmt(y)}" width="{fmt(w)}" height="{fmt(h)}" rx="{d.get("cornerRadius", 8)}" {attrs}/>'
        if d.get('text'):
            pos = d.get('labelPosition') or 'top-left'
            anchor = 'middle' if 'center' in pos else 'end' if 'right' in pos else 'start'
            tx = cx if anchor == 'middle' else x + w - 10 if anchor == 'end' else x + 10
            ty = y + h + 18 if pos.startswith('bottom') else y - 7
            body += (f'<text class="deco-label" x="{fmt(tx)}" y="{fmt(ty)}" text-anchor="{anchor}" fill="{esc(d.get("color") or "#607d8b")}" '
                     f'font-size="{d.get("fontSize", 12)}">{esc(d["text"])}</text>')
    return f'<g transform="rotate({d.get("rotation", 0)} {fmt(cx)} {fmt(cy)})">{body}</g>'


def label_box(text, x, y, anchor, size, pad=4):
    """A background rectangle sized from the glyph count (the browser is not available to measure)."""
    width = len(str(text)) * size * 0.62 + 2 * pad
    left = x - width / 2 if anchor == 'middle' else x - width + pad if anchor == 'end' else x - pad
    return f'<rect x="{fmt(left)}" y="{fmt(y - size - 1)}" width="{fmt(width)}" height="{fmt(size + 5)}" rx="3"/>'


def render(drawing, lab):
    """The SVG and the Flow panel cells of one lab: {'svg', 'panel_config', 'cells', 'bounds'}."""
    names = inventory(lab)
    positions = {n['id']: n for n in drawing.get('nodes', [])}
    settings = drawing.get('settings') or {}
    box = bounds(drawing)
    cells = {}
    parts = []
    dots = []          # port dots are drawn last so the node icons never cover them

    def matched(node):
        """(short name, platform, inventory name) for a drawn node matched to the inventory, else None."""
        inventory_name = node.get('inventory_name')
        if inventory_name and inventory_name in names:
            short, platform = names[inventory_name]
            return short, platform, inventory_name
        return None

    for d in sorted(drawing.get('decorations', []), key=lambda item: item.get('zIndex', 0)):
        parts.append(decoration(d))
    for pair in drawing.get('links', []):
        a, b = positions.get(pair[0]['node']), positions.get(pair[1]['node'])
        if not a or not b:
            continue
        ax, ay, bx, by = a['x'] + 20, a['y'] + 20, b['x'] + 20, b['y'] + 20
        if (ax, ay) == (bx, by):
            parts.append(f'<path class="plain" d="M{fmt(ax - 12)} {fmt(ay - 20)}C{fmt(ax - 60)} {fmt(ay - 75)},{fmt(ax + 60)} {fmt(ay - 75)},{fmt(ax + 12)} {fmt(ay - 20)}"/>')
            continue
        dx, dy = bx - ax, by - ay
        length = math.hypot(dx, dy) or 1
        ux, uy = dx / length, dy / length
        radius = 20 / max(abs(ux), abs(uy))
        start, end = (ax + ux * radius, ay + uy * radius), (bx - ux * radius, by - uy * radius)
        mid = ((start[0] + end[0]) / 2, (start[1] + end[1]) / 2)
        offset = min(length * .45, radius + (pair[0].get('label_offset') or settings.get('endpointOffset') or 20))
        nx, ny = -uy, ux
        ends = ((a, pair[0], start, (ax + ux * offset, ay + uy * offset + 3)), (b, pair[1], end, (bx - ux * offset, by - uy * offset + 3)))
        for index, (node, endpoint, origin, label_at) in enumerate(ends):
            peer_node, peer_endpoint = ends[1 - index][0], ends[1 - index][1]
            own, peer = matched(node), matched(peer_node)
            drawn = str(endpoint.get('interface', ''))
            half = f'M{fmt(origin[0])} {fmt(origin[1])}L{fmt(mid[0])} {fmt(mid[1])}'
            # The rate sits beside the wire near its own node (40 % of the way to the middle, so the two
            # labels of a short link never meet), clear of the interface label that stays on the wire.
            rate_at = (origin[0] + (mid[0] - origin[0]) * .4 - nx * 15, origin[1] + (mid[1] - origin[1]) * .4 - ny * 15 + 4)
            if own and peer:
                short, platform, _ = own
                peer_short, peer_platform, _ = peer
                # This half carries what this node sends, measured where it arrives: the far end's
                # receive counter (cEOS in a container reports no transmit octets on data ports).
                sent = series_in(peer_short, nos_interface(peer_platform, str(peer_endpoint.get('interface', ''))))
                link_id, rate_id, port_id = f'link:{short}:{drawn}', f'rate:{short}:{drawn}', f'port:{short}:{drawn}'
                parts.append(f'<path id="cell-{esc(link_id)}" class="link flow" stroke="#bec8d2" d="{half}"/>')
                dots.append(f'<circle id="cell-{esc(port_id)}" class="port" cx="{fmt(origin[0])}" cy="{fmt(origin[1])}" r="4.5" fill="#bec8d2"/>')
                parts.append(f'<text id="cell-{esc(rate_id)}" class="rate" x="{fmt(rate_at[0])}" y="{fmt(rate_at[1])}" text-anchor="middle" fill="#334155">&#8593;</text>')
                cells[link_id] = {'dataRef': sent, 'strokeColor': {'thresholds': thresholds(TRAFFIC_LEVELS)}, 'flowAnimation': dict(FLOW)}
                cells[rate_id] = {'label': {'dataRef': sent, 'units': 'bps', 'decimalPoints': 1, 'separator': 'space'}}
                cells[port_id] = {'dataRef': series_oper(short, nos_interface(platform, drawn)), 'fillColor': {'thresholds': thresholds(PORT_LEVELS)}}
            else:
                parts.append(f'<path class="plain" d="{half}"/>')
            if settings.get('labelMode') != 'hide' and drawn:
                parts.append(f'<g class="iface">{label_box(drawn, label_at[0], label_at[1], "middle", 10)}'
                             f'<text x="{fmt(label_at[0])}" y="{fmt(label_at[1])}" text-anchor="middle">{esc(drawn)}</text></g>')
    for node in drawing.get('nodes', []):
        cx, cy = node['x'] + 20, node['y'] + 20
        rotation = {'up': 0, 'right': 90, 'down': 180, 'left': 270}.get(node.get('direction'), 0)
        pos = node.get('labelPosition') or 'bottom'
        tx, ty, anchor = 0, R + 15, 'middle'
        if 'top' in pos:
            ty = -R - 9
        if pos == 'left':
            tx, ty, anchor = -R - 8, 5, 'end'
        if pos == 'right':
            tx, ty, anchor = R + 8, 5, 'start'
        body = (f'<g transform="rotate({rotation})"><rect class="device-body" x="{-R}" y="{-R}" width="{SIZE}" height="{SIZE}" '
                f'rx="{node.get("iconCornerRadius", 4)}" fill="{esc(node.get("iconColor") or "#0066ff")}"/><path class="device-symbol" d="{icon_path(node.get("icon"))}"/></g>')
        if pos != 'none':
            body += (f'<g class="device-label">{label_box(node.get("label", ""), tx, ty, anchor, 11)}'
                     f'<text x="{tx}" y="{ty}" text-anchor="{anchor}">{esc(node.get("label", ""))}</text></g>')
        own = matched(node)
        if own:
            node_id = f'node:{own[0]}'
            body += f'<circle id="cell-{esc(node_id)}" class="status" cx="{R - 2}" cy="{-R + 2}" r="5" fill="#bec8d2"/>'
            cells[node_id] = {'dataRef': series_state(own[0]), 'fillColor': {'thresholds': thresholds(NODE_LEVELS)}}
        parts.append(f'<g transform="translate({fmt(cx)} {fmt(cy)})">{body}</g>')
    parts.extend(dots)
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{box[0]} {box[1]} {box[2]} {box[3]}" width="{box[2]}" height="{box[3]}" '
           f'font-family="Segoe UI, Helvetica, Arial, sans-serif"><style>{STYLE}</style>'
           f'<rect x="{box[0]}" y="{box[1]}" width="{box[2]}" height="{box[3]}" fill="{CANVAS}"/>' + ''.join(parts) + '</svg>')
    config = {'cellIdPreamble': 'cell-', 'datapoint': 'lastNotNull', 'gradientMode': 'none',
              'background': {'darkThemeColor': CANVAS, 'lightThemeColor': CANVAS}, 'cells': cells}
    # YAML is a superset of JSON, so the plugin parses this as its panel configuration.
    return {'svg': svg, 'panel_config': json.dumps(config, indent=1, sort_keys=True), 'cells': cells, 'bounds': box}


def target(ref, expr, legend):
    return {'refId': ref, 'datasource': dict(DATASOURCE), 'expr': expr, 'legendFormat': legend,
            'range': True, 'instant': False, 'editorMode': 'code', 'format': 'time_series'}


def dashboard(lab, drawing):
    """A complete Grafana dashboard for one lab: the Flow panel with inline SVG and configuration."""
    rendered = render(drawing, lab)
    name = lab.get('name', '')
    selector = '{lab="' + promql_string(name) + '"}'
    x0, y0, width, height = rendered['bounds']
    rows = max(10, min(40, round(1200 * height / width / 30)))
    var_lab = '?var-lab=' + quote(name, safe='')
    links = [{'title': title, 'type': 'link', 'url': '/d/' + uid + var_lab, 'icon': 'dashboard', 'keepTime': True,
              'includeVars': False, 'targetBlank': False, 'asDropdown': False, 'tags': [], 'tooltip': ''}
             for title, uid in (('Lab overview', 'clab-lab-overview'), ('Interfaces', 'clab-interface'), ('BGP', 'clab-bgp'))]
    panel = {'id': 1, 'type': PLUGIN, 'title': name,
             'description': 'Generated by the Containerlab Node Manager from the saved drawing. Links are coloured and animated by the '
                            'receive rate of the far end; port dots show oper-status, the node dot the telemetry state.',
             'gridPos': {'x': 0, 'y': 0, 'w': 24, 'h': rows}, 'datasource': dict(DATASOURCE),
             'targets': [target('A', 'clab_interface_receive_bits_per_second' + selector, '{{node}}:{{interface}}:in'),
                         target('B', 'clab_interface_oper_up' + selector, 'oper:{{node}}:{{interface}}'),
                         target('C', 'clab_telemetry_node_state_code' + selector, 'state:{{node}}')],
             'options': {'svg': rendered['svg'], 'panelConfig': rendered['panel_config'], 'siteConfig': '',
                         'animationsEnabled': True, 'animationControlEnabled': True, 'highlighterEnabled': False,
                         'panZoomEnabled': True, 'timeSliderEnabled': True, 'testDataEnabled': False},
             'fieldConfig': {'defaults': {}, 'overrides': []}}
    return {'uid': map_uid(lab['id']), 'title': 'Lab map \u00b7 ' + name, 'tags': ['containerlab', 'node-manager', 'lab-map'],
            'editable': False, 'schemaVersion': 41, 'version': 1, 'refresh': '10s', 'graphTooltip': 1, 'timezone': 'browser',
            'time': {'from': 'now-15m', 'to': 'now'},
            'timepicker': {'refresh_intervals': ['5s', '10s', '30s', '1m', '5m'],
                           'quick_ranges': [{'display': 'Last 5 minutes', 'from': 'now-5m', 'to': 'now'},
                                            {'display': 'Last 15 minutes', 'from': 'now-15m', 'to': 'now'}]},
            'annotations': {'list': []}, 'templating': {'list': []}, 'links': links, 'panels': [panel],
            'description': f'Weathermap of lab {name}: generated from the manager drawing, not editable in Grafana.'}


def dashboard_json(lab, drawing):
    return json.dumps(dashboard(lab, drawing), indent=1, sort_keys=True, ensure_ascii=False) + '\n'


def signature(lab, drawing):
    """Cheap change detector: the drawing revision and the node identities the map binds to."""
    body = [lab.get('id'), lab.get('name'), drawing.get('revision') or json.dumps(drawing, sort_keys=True),
            [[n['name'], n.get('short_name'), n.get('platform')] for n in lab.get('nodes', [])]]
    return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()


class MapPublisher:
    """Keeps one provisioned dashboard file per drawn lab in a folder Grafana reads (30 s refresh)."""
    def __init__(self, folder, enabled):
        self.folder = Path(folder) if folder else None
        self.enabled = bool(enabled and folder)
        self.signatures = {}      # uid -> signature of the file last written or verified
        self.writes = 0
        self.removals = 0
        self.error = ''

    def reconcile(self, entries):
        """entries: iterable of (lab, drawing or None). Writes changed maps, removes maps of vanished labs."""
        if self.folder is None:
            return
        wanted = {}
        if self.enabled:
            for lab, drawing in entries:
                if not drawing:
                    continue
                uid = map_uid(lab['id'])
                sig = signature(lab, drawing)
                wanted[uid] = None if self.signatures.get(uid) == sig and (self.folder / (uid + '.json')).is_file() else (sig, lab, drawing)
        elif not self.folder.is_dir():
            return
        try:
            self.folder.mkdir(parents=True, exist_ok=True, mode=0o755)
            for uid, item in wanted.items():
                if item is None:
                    continue
                sig, lab, drawing = item
                path = self.folder / (uid + '.json')
                text = dashboard_json(lab, drawing)
                if path.is_file() and path.read_text(encoding='utf-8') == text:
                    self.signatures[uid] = sig
                    continue
                temporary = path.with_name(path.name + '.tmp')
                temporary.write_text(text, encoding='utf-8')
                os.chmod(temporary, 0o644)          # Grafana reads it through a read-only bind mount as another user
                os.replace(temporary, path)
                self.signatures[uid] = sig
                self.writes += 1
            for path in self.folder.glob(UID_PREFIX + '*.json'):
                if path.stem not in wanted:
                    path.unlink()
                    self.signatures.pop(path.stem, None)
                    self.removals += 1
            self.error = ''
        except OSError as error:
            self.error = 'The Grafana lab map folder is not writable (' + (error.strerror or 'OS error') + ').'

    def stats(self):
        return {'enabled': self.enabled, 'folder': str(self.folder) if self.folder else '', 'dashboards': len(self.signatures),
                'writes': self.writes, 'removals': self.removals, 'error': self.error, 'plugin': PLUGIN, 'plugin_version': PLUGIN_VERSION}
