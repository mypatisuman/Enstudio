"""
dxf.py — DXF P&ID export for EngineeringStudio
AutoCAD R2010 format via ezdxf. All block and layer names carry ES_ prefix
for namespace isolation in customer drawings.

Coordinate system:
  - Normalized (0-1) node positions from Claude Pass 1 or BFS fallback
  - Y-flipped: normalized y=0 (top) → DXF y_max; y=1 (bottom) → DXF y_min
  - Canvas: 1000×700 mm, TITLE_H=30 mm reserved at bottom
"""
from __future__ import annotations
import io
import math
from collections import deque
from typing import Dict, List, Tuple

try:
    import ezdxf
    HAS_EZDXF = True
except ImportError:
    HAS_EZDXF = False

try:
    from .kind_normalize import normalize_render_kind
except ImportError:  # pragma: no cover - script run standalone, not as package
    from kind_normalize import normalize_render_kind

# ── Canvas constants ──────────────────────────────────────────────────────────
CANVAS_W = 1000
CANVAS_H = 700
TITLE_H  = 30
MARGIN   = 20

EQ_W  = 20    # equipment half-width
EQ_H  = 14    # equipment half-height
BUB_R = 14    # instrument bubble radius

# ── Layer table ───────────────────────────────────────────────────────────────
LAYERS: List[Tuple[str, int]] = [
    ('ES_PIPING',      7),   # white/black — process pipe runs
    ('ES_SIGNAL',      3),   # green — signal/instrument lines
    ('ES_EQUIPMENT',   1),   # red — process equipment
    ('ES_INSTRUMENTS', 4),   # cyan — DCS instruments
    ('ES_MECHANICAL',  8),   # dark grey — valves, relief
    ('ES_OFFPAGE',     6),   # magenta — off-page connectors
    ('ES_TEXT',        7),   # white/black — tag labels
    ('ES_TITLE',       7),   # white/black — title block
]

LAYER_FOR_KIND: Dict[str, str] = {
    **{k: 'ES_EQUIPMENT'   for k in ('vessel', 'separator', 'heat_exchanger', 'pump',
                                      'compressor', 'column', 'reactor', 'absorber',
                                      'adsorption', 'filter', 'meter')},
    **{k: 'ES_INSTRUMENTS' for k in ('transmitter', 'controller', 'indicator',
                                      'recorder', 'switch', 'analyzer', 'element')},
    **{k: 'ES_MECHANICAL'  for k in ('valve', 'checkvalve', 'relief')},
    'off_page_connector': 'ES_OFFPAGE',
}

BLOCK_FOR_KIND: Dict[str, str] = {
    'vessel':             'ES_VESSEL',
    'separator':          'ES_SEPARATOR',
    'heat_exchanger':     'ES_HX',
    'pump':               'ES_PUMP',
    'compressor':         'ES_COMPRESSOR',
    'column':             'ES_COLUMN',
    'reactor':            'ES_REACTOR',
    'absorber':           'ES_ABSORBER',
    'adsorption':         'ES_ABSORBER',
    'filter':             'ES_FILTER',
    'meter':              'ES_METER',
    'transmitter':        'ES_TRANSMITTER',
    'controller':         'ES_CONTROLLER',
    'indicator':          'ES_INDICATOR',
    'recorder':           'ES_RECORDER',
    'switch':             'ES_SWITCH',
    'analyzer':           'ES_ANALYZER',
    'element':            'ES_ELEMENT',
    'valve':              'ES_VALVE',
    'checkvalve':         'ES_CHECKVALVE',
    'relief':             'ES_RELIEF',
    'off_page_connector': 'ES_OFFPAGE_SYM',
}


def _to_dxf(x_norm: float, y_norm: float) -> Tuple[float, float]:
    """Normalized (0-1) → DXF mm coordinates with Y-flip."""
    uw = CANVAS_W - 2 * MARGIN
    uh = CANVAS_H - TITLE_H - 2 * MARGIN
    return (MARGIN + x_norm * uw,
            MARGIN + TITLE_H + (1.0 - y_norm) * uh)


def _setup_layers(doc) -> None:
    for name, color in LAYERS:
        if name not in doc.layers:
            layer = doc.layers.new(name)
            layer.color = color
    # Define dashed linetype for signal layer
    try:
        if 'ES_DASHED' not in doc.linetypes:
            doc.linetypes.new('ES_DASHED', dxfattribs={
                'description': 'Dashed',
                'pattern': [0.5, -0.25]
            })
        doc.layers.get('ES_SIGNAL').dxf.linetype = 'ES_DASHED'
    except Exception:
        pass  # Signal layer falls back to solid — still colour-differentiated


def _attdef(blk, y_off: float) -> None:
    blk.add_attdef('TAG', insert=(0, y_off),
                   dxfattribs={'height': 2.5, 'layer': 'ES_TEXT'})


def _define_blocks(doc) -> None:
    EL = 'ES_EQUIPMENT'
    IL = 'ES_INSTRUMENTS'
    ML = 'ES_MECHANICAL'
    OL = 'ES_OFFPAGE'

    # ── Process equipment ─────────────────────────────────────────────────────

    b = doc.blocks.new('ES_VESSEL')
    b.add_lwpolyline([(-EQ_W, -EQ_H), (EQ_W, -EQ_H), (EQ_W, EQ_H), (-EQ_W, EQ_H)],
                     close=True, dxfattribs={'layer': EL})
    _attdef(b, -EQ_H - 5)

    b = doc.blocks.new('ES_SEPARATOR')
    b.add_ellipse((0, 0), major_axis=(EQ_W, 0), ratio=EQ_H / EQ_W,
                  dxfattribs={'layer': EL})
    _attdef(b, -EQ_H - 5)

    b = doc.blocks.new('ES_HX')
    b.add_lwpolyline([(-EQ_W, -EQ_H), (EQ_W, -EQ_H), (EQ_W, EQ_H), (-EQ_W, EQ_H)],
                     close=True, dxfattribs={'layer': EL})
    b.add_line((-EQ_W, -EQ_H), (EQ_W, EQ_H), dxfattribs={'layer': EL})
    b.add_line((-EQ_W, EQ_H), (EQ_W, -EQ_H), dxfattribs={'layer': EL})
    _attdef(b, -EQ_H - 5)

    b = doc.blocks.new('ES_PUMP')
    b.add_circle((0, 0), EQ_H, dxfattribs={'layer': EL})
    h = EQ_H * 0.55
    b.add_lwpolyline([(-h, h), (-h, -h), (EQ_H, 0)], close=True,
                     dxfattribs={'layer': EL})
    _attdef(b, -EQ_H - 5)

    b = doc.blocks.new('ES_COMPRESSOR')
    r = EQ_H * 1.2
    pts = [(r * math.cos(math.radians(30 + 60 * i)),
            r * math.sin(math.radians(30 + 60 * i))) for i in range(6)]
    b.add_lwpolyline(pts, close=True, dxfattribs={'layer': EL})
    _attdef(b, -r - 5)

    b = doc.blocks.new('ES_COLUMN')
    cw, ch = EQ_H * 0.7, EQ_W
    b.add_lwpolyline([(-cw, -ch), (cw, -ch), (cw, ch), (-cw, ch)],
                     close=True, dxfattribs={'layer': EL})
    _attdef(b, -ch - 5)

    b = doc.blocks.new('ES_REACTOR')
    b.add_lwpolyline([(-EQ_W, -EQ_H), (EQ_W, -EQ_H),
                      (EQ_W, EQ_H * 0.4), (-EQ_W, EQ_H * 0.4)],
                     close=True, dxfattribs={'layer': EL})
    b.add_arc((0, EQ_H * 0.4), EQ_W, 0, 180, dxfattribs={'layer': EL})
    _attdef(b, -EQ_H - 5)

    b = doc.blocks.new('ES_ABSORBER')
    aw, ah = EQ_H, EQ_W
    b.add_lwpolyline([(-aw, -ah), (aw, -ah), (aw, ah), (-aw, ah)],
                     close=True, dxfattribs={'layer': EL})
    _attdef(b, -ah - 5)

    b = doc.blocks.new('ES_FILTER')
    b.add_lwpolyline([(-EQ_W, -EQ_H), (EQ_W, -EQ_H), (EQ_W, EQ_H), (-EQ_W, EQ_H)],
                     close=True, dxfattribs={'layer': EL})
    for xi in (-EQ_W * 0.5, 0.0, EQ_W * 0.5):
        b.add_line((xi - EQ_W * 0.25, -EQ_H), (xi + EQ_W * 0.25, EQ_H),
                   dxfattribs={'layer': EL})
    _attdef(b, -EQ_H - 5)

    b = doc.blocks.new('ES_METER')
    b.add_circle((0, 0), EQ_H, dxfattribs={'layer': EL})
    b.add_line((0, -EQ_H), (0, EQ_H), dxfattribs={'layer': EL})
    _attdef(b, -EQ_H - 5)

    # ── Instruments (bubbles) ─────────────────────────────────────────────────

    b = doc.blocks.new('ES_TRANSMITTER')
    b.add_circle((0, 0), BUB_R, dxfattribs={'layer': IL})
    _attdef(b, -BUB_R - 5)

    b = doc.blocks.new('ES_CONTROLLER')
    b.add_circle((0, 0), BUB_R, dxfattribs={'layer': IL})
    b.add_line((-BUB_R, 0), (BUB_R, 0), dxfattribs={'layer': IL})
    _attdef(b, -BUB_R - 5)

    b = doc.blocks.new('ES_INDICATOR')
    b.add_circle((0, 0), BUB_R, dxfattribs={'layer': IL})
    _attdef(b, -BUB_R - 5)

    b = doc.blocks.new('ES_RECORDER')
    b.add_circle((0, 0), BUB_R, dxfattribs={'layer': IL})
    r2 = BUB_R * 0.4
    b.add_lwpolyline([(-r2, -r2), (r2, -r2), (r2, r2), (-r2, r2)],
                     close=True, dxfattribs={'layer': IL})
    _attdef(b, -BUB_R - 5)

    b = doc.blocks.new('ES_SWITCH')
    b.add_circle((0, 0), BUB_R, dxfattribs={'layer': IL})
    r2 = BUB_R * 0.5
    b.add_lwpolyline([(0, -r2), (r2, 0), (0, r2), (-r2, 0)],
                     close=True, dxfattribs={'layer': IL})
    _attdef(b, -BUB_R - 5)

    b = doc.blocks.new('ES_ANALYZER')
    b.add_circle((0, 0), BUB_R, dxfattribs={'layer': IL})
    r2 = BUB_R * 0.5
    b.add_lwpolyline([(-r2, -r2 * 0.5), (0, r2), (r2, -r2 * 0.5)],
                     dxfattribs={'layer': IL})
    b.add_line((-r2 * 0.6, 0), (r2 * 0.6, 0), dxfattribs={'layer': IL})
    _attdef(b, -BUB_R - 5)

    b = doc.blocks.new('ES_ELEMENT')
    b.add_line((-BUB_R, 0), (BUB_R, 0), dxfattribs={'layer': IL})
    b.add_line((0, -BUB_R), (0, BUB_R), dxfattribs={'layer': IL})
    _attdef(b, -BUB_R - 5)

    # ── Mechanical ────────────────────────────────────────────────────────────

    s = EQ_H
    b = doc.blocks.new('ES_VALVE')
    b.add_lwpolyline([(-s, -s), (-s, s), (0, 0)], close=True,
                     dxfattribs={'layer': ML})
    b.add_lwpolyline([(s, -s), (s, s), (0, 0)], close=True,
                     dxfattribs={'layer': ML})
    _attdef(b, -s - 5)

    b = doc.blocks.new('ES_CHECKVALVE')
    b.add_lwpolyline([(-s, -s), (-s, s), (0, 0)], close=True,
                     dxfattribs={'layer': ML})
    b.add_line((0, -s), (0, s), dxfattribs={'layer': ML})
    _attdef(b, -s - 5)

    b = doc.blocks.new('ES_RELIEF')
    b.add_circle((0, 0), EQ_H * 0.7, dxfattribs={'layer': ML})
    sv = EQ_H * 0.55
    b.add_lwpolyline([(0, sv * 1.8), (-sv, EQ_H * 0.7), (sv, EQ_H * 0.7)],
                     close=True, dxfattribs={'layer': ML})
    _attdef(b, -EQ_H - 5)

    b = doc.blocks.new('ES_OFFPAGE_SYM')
    fw, fh = EQ_W * 0.8, EQ_H
    b.add_lwpolyline([(-fw, -fh), (-fw, fh), (fw * 0.3, fh), (fw, 0), (fw * 0.3, -fh)],
                     close=True, dxfattribs={'layer': OL})
    b.add_attdef('TAG', insert=(0, -fh - 5),
                 dxfattribs={'height': 2.5, 'layer': 'ES_TEXT'})


def _bfs_positions(nodes: list, edges: list) -> Dict[str, Tuple[float, float]]:
    """BFS topological layout → normalized (0-1) positions."""
    adj = {n['id']: [] for n in nodes}
    in_count = {n['id']: 0 for n in nodes}
    for e in edges:
        if e.get('kind') != 'signal':
            if e['from'] in adj:
                adj[e['from']].append(e['to'])
            if e['to'] in in_count:
                in_count[e['to']] += 1

    roots = [n['id'] for n in nodes if in_count.get(n['id'], 0) == 0] or \
            ([nodes[0]['id']] if nodes else [])

    layer_map: Dict[str, int] = {}
    visited: set = set()
    q: deque = deque((r, 0) for r in roots)
    while q:
        nid, layer = q.popleft()
        if nid in visited:
            continue
        visited.add(nid)
        layer_map[nid] = layer
        for nb in adj.get(nid, []):
            if nb not in visited:
                q.append((nb, layer + 1))

    max_layer = max(layer_map.values(), default=0)
    for n in nodes:
        if n['id'] not in layer_map:
            layer_map[n['id']] = max_layer + 1
    max_layer = max(layer_map.values(), default=0)

    layers: Dict[int, list] = {}
    for nid, lyr in layer_map.items():
        layers.setdefault(lyr, []).append(nid)

    positions: Dict[str, Tuple[float, float]] = {}
    for lyr, nids in sorted(layers.items()):
        for row, nid in enumerate(nids):
            x = (lyr + 0.5) / (max_layer + 1)
            y = (row + 0.5) / len(nids)
            positions[nid] = (x, y)
    return positions


def _node_positions(nodes: list, edges: list) -> Dict[str, Tuple[float, float]]:
    """Return normalized (0-1) positions for all nodes."""
    has_xy = [n for n in nodes if n.get('x') is not None and n.get('y') is not None]
    if len(has_xy) >= max(1, len(nodes) * 0.5):
        pos = {n['id']: (float(n['x']), float(n['y'])) for n in has_xy}
        if len(pos) < len(nodes):
            bfs = _bfs_positions(nodes, edges)
            for n in nodes:
                if n['id'] not in pos:
                    pos[n['id']] = bfs.get(n['id'], (0.5, 0.5))
        return pos
    return _bfs_positions(nodes, edges)


def generate_dxf(ympl_doc: dict, project_name: str = 'P&ID') -> bytes:
    """
    Generate AutoCAD R2010 DXF from YMPL topology.
    Returns UTF-8-encoded DXF bytes.
    """
    if not HAS_EZDXF:
        raise ImportError('ezdxf is required: pip install ezdxf>=1.3')

    nodes = ympl_doc.get('nodes', [])
    edges = ympl_doc.get('edges', [])

    doc = ezdxf.new('R2010')
    doc.header['$INSUNITS'] = 4  # millimetres
    _setup_layers(doc)
    _define_blocks(doc)

    msp = doc.modelspace()

    # Compute DXF mm positions
    norm_pos = _node_positions(nodes, edges)
    dxf_pos: Dict[str, Tuple[float, float]] = {
        nid: _to_dxf(x, y) for nid, (x, y) in norm_pos.items()
    }

    # Insert block references. kind is normalized from the raw YOLO type
    # string (e.g. "Ball_Valve") to the canonical kind BLOCK_FOR_KIND/
    # LAYER_FOR_KIND key on (e.g. "valve") — without this, raw type strings
    # never matched exactly and the node was silently skipped (no block, no
    # fallback text — nothing drawn at all).
    for node in nodes:
        nid   = node['id']
        label = node.get('label', nid)
        pos   = dxf_pos.get(nid)
        if not pos:
            continue
        kind  = normalize_render_kind(node.get('kind', 'default'))
        if kind == 'junction':
            # Junctions are splice points, not equipment — a small dot only.
            try:
                msp.add_circle(pos, radius=1.5, dxfattribs={'layer': 'ES_MECHANICAL'})
            except Exception:
                pass
            continue
        block = BLOCK_FOR_KIND.get(kind)
        layer = LAYER_FOR_KIND.get(kind, 'ES_EQUIPMENT')
        if not block:
            continue
        try:
            ref = msp.add_blockref(block, insert=pos, dxfattribs={'layer': layer})
            ref.add_auto_attribs({'TAG': label})
        except Exception:
            # Fallback: plain text label
            t = msp.add_text(label, dxfattribs={'height': 3, 'layer': 'ES_TEXT'})
            t.dxf.insert = pos

    # Draw connections
    for edge in edges:
        p1 = dxf_pos.get(edge['from'])
        p2 = dxf_pos.get(edge['to'])
        if not p1 or not p2:
            continue
        edge_layer = 'ES_SIGNAL' if edge.get('kind') == 'signal' else 'ES_PIPING'
        try:
            msp.add_lwpolyline([p1, p2], dxfattribs={'layer': edge_layer})
        except Exception:
            pass

    # Title block
    tb_y = MARGIN + TITLE_H * 0.5
    for txt, ht, ty in ((project_name, 5, tb_y), ('EngineeringStudio P&ID Export', 3, tb_y + 8)):
        t = msp.add_text(txt, dxfattribs={'height': ht, 'layer': 'ES_TITLE'})
        t.dxf.insert = (MARGIN, ty)
    msp.add_lwpolyline([(0, 0), (CANVAS_W, 0), (CANVAS_W, CANVAS_H), (0, CANVAS_H)],
                       close=True, dxfattribs={'layer': 'ES_TITLE'})
    msp.add_line((0, TITLE_H), (CANVAS_W, TITLE_H), dxfattribs={'layer': 'ES_TITLE'})

    stream = io.StringIO()
    doc.write(stream)
    return stream.getvalue().encode('utf-8')
