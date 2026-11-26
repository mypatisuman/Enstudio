"""
svg_pid.py — ISA-5.1 P&ID SVG Generator
EngineeringStudio Phase 2

Generates a clean, downloadable SVG P&ID from stored YMPL topology.
Pure Python — no external dependencies beyond standard library.
Output opens in browser, Inkscape, Illustrator, AutoCAD (import).

Layout: BFS topological layering (left = feed, right = product)
Symbols: ISA-5.1 / ISO 10628 standard shapes
"""

from __future__ import annotations
from collections import defaultdict, deque
from typing import Dict, List, Tuple, Optional
import math
import re
from functools import lru_cache
from pathlib import Path

try:
    from .kind_normalize import normalize_render_kind
except ImportError:  # pragma: no cover - script run standalone, not as package
    from kind_normalize import normalize_render_kind  # type: ignore


# ── Layout constants ──────────────────────────────────────────────────────────

NODE_W  = 60    # symbol bounding box width
NODE_H  = 45    # symbol bounding box height
GAP_X   = 120   # horizontal gap between layers
GAP_Y   = 90    # vertical gap within layer
MARGIN  = 80    # page margin (larger value keeps nodes away from all edges)

# ── Colour palette ────────────────────────────────────────────────────────────
# Mirrors the real values the interactive Canvas screen uses (see
# frontend/src/domain/isa/classification.ts equipColors/instrColors
# and components/canvas/theme.ts) so the SVG export matches Canvas's actual
# dark theme instead of an unrelated light palette invented for this file.

CANVAS_BG    = '#0B1220'   # Theme.canvas
GRID_COLOR   = '#1B2435'   # Theme.grid
TEXT_COLOR   = '#EDF2F7'   # Theme.text
TEXT_MUTED   = '#8B95A7'   # Theme.textMuted
PROCESS_PIPE = '#D6DCE5'   # Theme.processPipe
SIGNAL_PIPE  = '#8B93A6'   # Theme.signalPipe
PANEL_BG     = '#111827'   # Theme.labelBackground — used for the legend panel
# Tee/junction dot. Light grey reads on the dark canvas but vanishes on a white
# sheet — and a junction is where several pipes meet, so an invisible one makes
# every pipe into it look like it stops in mid-air. Remapped for the light
# background like every other theme colour.
JUNCTION_DOT = '#E5E7EB'

# Layer ids emitted by generate_svg_pid, in paint order. `layers=None` renders
# the control view (everything except the decorative grid); ALL_LAYERS renders
# every one. Passing an explicit set renders only those.
ALL_LAYERS = (
    'layer-background',
    'layer-grid',
    'layer-annotations',
    'layer-piping',
    'layer-signals',
    'layer-equipment',
    'layer-instruments',
    'layer-mechanical',
    'layer-connectors',
    'layer-junctions',
    'layer-other',
)
CONTROL_LAYERS = tuple(l for l in ALL_LAYERS if l != 'layer-grid')

# Print/engineering background. The dark palette above matches the interactive
# Canvas; on paper it prints as a solid black sheet with near-white pipes, which
# is backwards from drawing-office convention. Swapping the handful of theme
# hexes for light equivalents is the same approach the desktop export already
# takes (frontend CanvasExportCapture.tsx applyLightTheme).
# ponytail: string remap over the finished SVG, not a themed renderer — it
# covers the theme constants, and a per-element palette would need draw_symbol
# to take a theme argument throughout.
LIGHT_BG = '#FFFFFF'
_LIGHT_REMAP = {
    CANVAS_BG:    LIGHT_BG,
    PANEL_BG:     '#F1F3F5',
    GRID_COLOR:   '#DCE1E8',
    TEXT_COLOR:   '#101418',
    TEXT_MUTED:   '#5A6472',
    PROCESS_PIPE: '#1A1F26',
    SIGNAL_PIPE:  '#5A6472',
}


def _hex_to_rgb(h: str) -> Tuple[int, int, int]:
    h = h.lstrip('#')
    if len(h) == 3:
        h = ''.join(c * 2 for c in h)
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _mix(a: str, b: str, t: float) -> str:
    """Blend hex `a` toward hex `b` by t (0 = a, 1 = b)."""
    ar, ag, ab = _hex_to_rgb(a)
    br, bg, bb = _hex_to_rgb(b)
    return '#{:02X}{:02X}{:02X}'.format(
        round(ar + (br - ar) * t),
        round(ag + (bg - ag) * t),
        round(ab + (bb - ab) * t),
    )


def _build_light_remap() -> Dict[str, str]:
    """Light equivalent of every colour the dark palettes use.

    Derived from the dark palettes rather than hand-listed, so adding an
    equipment kind or ISA letter above cannot leave a dark swatch behind on a
    white sheet. Each entry keeps its hue — a blue vessel stays blue — but the
    roles inverted for paper:

      fill   very dark tint  ->  near-white tint of the same hue, so symbol
                                 bodies sit on the sheet instead of punching
                                 dark holes in it
      stroke saturated hue   ->  same hue darkened, for ink contrast on white
      text   light pastel    ->  same hue darkened well past the stroke
    """
    remap: Dict[str, str] = {
        CANVAS_BG:    LIGHT_BG,
        PANEL_BG:     '#F4F6F8',
        GRID_COLOR:   '#DCE1E8',
        TEXT_COLOR:   '#101418',
        TEXT_MUTED:   '#5A6472',
        PROCESS_PIPE: '#1A1F26',
        SIGNAL_PIPE:  '#5A6472',
        JUNCTION_DOT: '#1A1F26',
    }
    palettes: List[dict] = (
        list(COLORS.values())
        + list(LETTER_COLORS.values())
        + [LETTER_DEFAULT, VALVE_COLOR]
    )
    for entry in palettes:
        stroke = entry.get('stroke')
        if not stroke:
            continue
        fill = entry.get('fill')
        if fill:
            remap.setdefault(fill, _mix(stroke, '#FFFFFF', 0.90))
        text = entry.get('text')
        if text:
            remap.setdefault(text, _mix(stroke, '#000000', 0.55))
        remap.setdefault(stroke, _mix(stroke, '#000000', 0.30))
    return remap


def _apply_light_theme(svg: str) -> str:
    """Swap dark-canvas colours for print-friendly equivalents.

    Single pass over hex tokens: replacing one at a time would let an already
    substituted colour match a later rule and shift twice.
    """
    lookup = {k.lower(): v for k, v in _build_light_remap().items()}
    out = re.sub(
        r'#[0-9a-fA-F]{6}\b',
        lambda m: lookup.get(m.group(0).lower(), m.group(0)),
        svg,
    )
    # Equipment tags are drawn inside the shape as `fill="white"` — correct on
    # the dark canvas, invisible once the body becomes a near-white tint. Named
    # colours don't match the hex pass above, so handle it explicitly.
    return out.replace('fill="white"', f'fill="{lookup.get(TEXT_COLOR.lower(), "#101418")}"')


# Coordinate-pair count per path command, and which of those pairs are real
# points rather than parameters. Only the elliptical arc is irregular: its 7
# args are `rx ry x-axis-rotation large-arc-flag sweep-flag x y`, so reading
# the numbers in naive pairs turns the two flags into a coordinate — usually
# (0,0) or (0,1). That injected a phantom point at the origin for every arc in
# the drawing, dragging measured bounds up to the top-left corner and padding
# the viewBox with empty sheet.
_PATH_ARGS = {'M': 2, 'L': 2, 'T': 2, 'H': 1, 'V': 1,
              'C': 6, 'S': 4, 'Q': 4, 'A': 7, 'Z': 0}
_PATH_TOKEN = re.compile(r'[MmLlHhVvCcSsQqTtAaZz]|-?\d*\.?\d+(?:[eE][-+]?\d+)?')


def _path_points(d: str) -> List[Tuple[float, float]]:
    """Every real (x, y) a path passes through or is steered by.

    Control points count: a quadratic/cubic curve stays inside the convex hull
    of its control points, so including them bounds the curve conservatively.
    """
    pts: List[Tuple[float, float]] = []
    cur = None
    args: List[float] = []

    def flush():
        if cur is None:
            return
        u = cur.upper()
        n = _PATH_ARGS.get(u)
        if not n:
            return
        for k in range(0, len(args) - n + 1, n):
            chunk = args[k:k + n]
            if u in ('M', 'L', 'T'):
                pts.append((chunk[0], chunk[1]))
            elif u in ('C', 'S', 'Q'):
                for p in range(0, n, 2):
                    pts.append((chunk[p], chunk[p + 1]))
            elif u == 'A':
                pts.append((chunk[5], chunk[6]))   # endpoint only; skip flags
            # H/V move on a single axis — no pair to contribute

    for tok in _PATH_TOKEN.findall(d):
        if tok.isalpha():
            flush()
            cur, args = tok, []
        else:
            try:
                args.append(float(tok))
            except ValueError:
                pass
    flush()
    return pts


def measure_extents(markup: str) -> Tuple[float, float, float, float]:
    """(min_x, min_y, max_x, max_y) of already-generated SVG markup.

    Measures what was actually drawn rather than predicting it. Predicting from
    node boxes missed routed detours, symbol tag labels drawn below their node,
    and curve geometry — each of which silently fell outside the viewBox and
    was clipped. Anything unparseable is skipped: this only ever grows the
    canvas, so a miss costs whitespace, never a clipped pipe.
    """
    import xml.etree.ElementTree as _ET
    try:
        # xlink must be declared or any xlink:href in the markup (emitted by
        # draw_symbol's <use> for compatibility with older renderers) makes
        # this an unbound-prefix parse error — which silently returned a zero
        # box and collapsed the whole canvas to a couple of hundred px.
        root = _ET.fromstring(
            '<svg xmlns="http://www.w3.org/2000/svg" '
            f'xmlns:xlink="http://www.w3.org/1999/xlink">{markup}</svg>'
        )
    except _ET.ParseError:
        return (0.0, 0.0, 0.0, 0.0)

    ns = '{http://www.w3.org/2000/svg}'
    xs: List[float] = []
    ys: List[float] = []

    def put(x, y):
        try:
            xs.append(float(x)); ys.append(float(y))
        except (TypeError, ValueError):
            pass

    for el in root.iter():
        tag = el.tag.replace(ns, '')
        if tag == 'line':
            put(el.get('x1'), el.get('y1')); put(el.get('x2'), el.get('y2'))
        elif tag == 'circle':
            r = float(el.get('r') or 0)
            cx, cy = float(el.get('cx') or 0), float(el.get('cy') or 0)
            put(cx - r, cy - r); put(cx + r, cy + r)
        elif tag in ('rect', 'use'):
            # <use> carries its own viewport box, so it bounds exactly like a
            # rect — without this every sprite symbol was invisible to the
            # canvas-sizing pass.
            x, y = float(el.get('x') or 0), float(el.get('y') or 0)
            put(x, y); put(x + float(el.get('width') or 0), y + float(el.get('height') or 0))
        elif tag in ('polyline', 'polygon'):
            n = re.findall(r'-?\d*\.?\d+', el.get('points') or '')
            for i in range(0, len(n) - 1, 2):
                put(n[i], n[i + 1])
        elif tag == 'path':
            for px, py in _path_points(el.get('d') or ''):
                put(px, py)
        elif tag == 'text':
            x, y = float(el.get('x') or 0), float(el.get('y') or 0)
            fs = float(el.get('font-size') or 10)
            # y is the baseline; text hangs below it and, when centred, spreads
            # both ways. 0.6em/char is the usual sans-serif average advance.
            half = len(el.text or '') * fs * 0.6 / 2
            anchored = el.get('text-anchor') == 'middle'
            put(x - (half if anchored else 0), y - fs)
            put(x + (half if anchored else half * 2), y + fs * 0.3)

    if not xs:
        return (0.0, 0.0, 0.0, 0.0)
    return (min(xs), min(ys), max(xs), max(ys))

COLORS = {
    # Equipment — matches equipColors() exactly
    'vessel':        {'fill': '#152232', 'stroke': '#3b82f6'},
    'tank':          {'fill': '#152232', 'stroke': '#3b82f6'},
    'separator':     {'fill': '#152232', 'stroke': '#3b82f6'},
    'heat_exchanger':{'fill': '#152a1f', 'stroke': '#22c55e'},
    'pump':          {'fill': '#152215', 'stroke': '#4ade80'},
    'compressor':    {'fill': '#15182a', 'stroke': '#6366f1'},
    'reactor':       {'fill': '#2a1515', 'stroke': '#ef4444'},
    'column':        {'fill': '#20162e', 'stroke': '#a855f7'},
    'absorber':      {'fill': '#20162e', 'stroke': '#a855f7'},
    'filter':        {'fill': '#1a1c2e', 'stroke': '#60a5fa'},
    'meter':         {'fill': '#152232', 'stroke': '#3b82f6'},
    'relief':        {'fill': '#2a1515', 'stroke': '#ef4444'},
    'inlet':         {'fill': '#0d2016', 'stroke': '#22c55e'},
    'outlet':        {'fill': '#1c0e30', 'stroke': '#a855f7'},
    # Instruments — legend-only representative colors; real symbols are
    # colored by ISA tag letter via _instr_color(), matching instrColors().
    'transmitter':   {'fill': '#0c2030', 'stroke': '#0ea5e9'},
    'controller':    {'fill': '#1c0e30', 'stroke': '#a855f7'},
    'indicator':     {'fill': '#0c2030', 'stroke': '#0ea5e9'},
    'recorder':      {'fill': '#1c1400', 'stroke': '#d97706'},
    'switch':        {'fill': '#1c1400', 'stroke': '#d97706'},
    'analyzer':      {'fill': '#201c00', 'stroke': '#eab308'},
    'element':       {'fill': '#0d2016', 'stroke': '#22c55e'},
    # Mechanical — matches VALVE_C / OFFPAGE_C
    'valve':         {'fill': '#1a1c20', 'stroke': '#F4B23A'},
    'checkvalve':    {'fill': '#1a1c20', 'stroke': '#F4B23A'},
    'regulator':     {'fill': '#1a1c20', 'stroke': '#F4B23A'},
    'default':       {'fill': '#152232', 'stroke': '#3b82f6'},
}

# ISA tag-letter colors — mirrors classification.ts's LETTER_COLORS exactly.
# Real instrument bubbles are colored by the tag's first ISA letter (F/P/T/
# L/A/S), not by node "kind" — see _instr_color() below.
LETTER_COLORS = {
    'F': {'fill': '#0c2030', 'stroke': '#0ea5e9', 'text': '#7dd3fc'},
    'P': {'fill': '#1c0e30', 'stroke': '#a855f7', 'text': '#d8b4fe'},
    'T': {'fill': '#2a0f0f', 'stroke': '#ef4444', 'text': '#fca5a5'},
    'L': {'fill': '#0d2016', 'stroke': '#22c55e', 'text': '#86efac'},
    'A': {'fill': '#201c00', 'stroke': '#eab308', 'text': '#fef08a'},
    'S': {'fill': '#1c1400', 'stroke': '#d97706', 'text': '#fcd34d'},
}
LETTER_DEFAULT = {'fill': '#1e1d13', 'stroke': '#f59e0b', 'text': '#fef3c7'}
VALVE_COLOR    = {'fill': '#1a1c20', 'stroke': '#F4B23A', 'text': '#94a3b8'}
VALVE_TAG_RE   = r'^(CV|HV|XV|FV|PV|LV|TV|SV|SDV|BDV|ESD|ESDV|PSV|PRV|RV|ORV|ADV|PCV)\d*[-_]'


def _instr_color(label: str) -> dict:
    """Mirrors classification.ts's instrColors(): valve-tagged labels get
    the valve color; otherwise color by the tag's first ISA letter."""
    import re
    if re.match(VALVE_TAG_RE, label or '', re.IGNORECASE):
        return VALVE_COLOR
    m = re.match(r'^([A-Za-z]+)', label or '')
    letter = m.group(1)[0].upper() if m else '?'
    return LETTER_COLORS.get(letter, LETTER_DEFAULT)


# Edge colors by kind — process pipes / signal lines match Theme.processPipe
# / Theme.signalPipe; recycle/bypass keep distinct accent colors so they
# still read differently from a normal process line.
EDGE_COLORS = {
    'stream':  {'stroke': PROCESS_PIPE, 'width': 2.0,  'dash': ''},
    'recycle': {'stroke': '#60a5fa',    'width': 2.0,  'dash': '6,3'},
    'bypass':  {'stroke': '#F4B23A',    'width': 1.5,  'dash': '8,4'},
    'signal':  {'stroke': SIGNAL_PIPE,  'width': 1.0,  'dash': '4,3'},
    'default': {'stroke': SIGNAL_PIPE,  'width': 1.5,  'dash': ''},
}

# Edge kinds the data actually carries that are synonyms of an EDGE_COLORS key.
# "process" is the dominant kind in extracted data (adapters/engine/parser.py
# renames stream→process on export, and the LLM emits it directly), but it was
# never an EDGE_COLORS key — so `url(#arrow_process)` pointed at a marker that
# was never defined and 93% of pipes silently lost their arrowhead. An
# unresolvable marker reference is ignored by the SVG spec, so nothing errored.
EDGE_KIND_ALIASES = {
    'process':    'stream',
    'pipe':       'stream',
    'hydraulic':  'stream',
    'pneumatic':  'signal',
    'electrical': 'signal',
    'capillary':  'signal',
}


def resolve_edge_kind(kind: str) -> str:
    """Canonical EDGE_COLORS key for a raw edge kind.

    The single resolution point for edge styling: stroke, width, dash AND the
    marker id all derive from the value this returns, so a `marker-end` can
    only ever name a marker that `generate_svg_pid` actually defines. Any
    unrecognised kind lands on 'default', which is always defined.
    """
    k = (kind or '').strip().lower()
    k = EDGE_KIND_ALIASES.get(k, k)
    return k if k in EDGE_COLORS else 'default'

INSTRUMENT_KINDS = {
    'transmitter', 'controller', 'indicator',
    'recorder', 'switch', 'analyzer', 'element'
}
MECHANICAL_KINDS = {'valve', 'checkvalve', 'relief', 'regulator'}
CONNECTOR_KINDS  = {'off_page_connector', 'inlet', 'outlet'}

# Equipment kinds whose Canvas component (ISANodes.tsx) draws the tag text
# INSIDE the shape body (bold white, centered) rather than below it —
# VesselNode/HeatExNode/PumpNode/CompressorNode/ReactorNode/ColumnNode/
# FilterNode all do this; only the valve family uses a below-symbol label.
EQUIPMENT_KINDS_INLINE = {
    'vessel', 'tank', 'separator', 'heat_exchanger', 'pump', 'compressor',
    'reactor', 'column', 'absorber', 'filter',
}

# Per-node render sizes (w, h) — mirrors classification.ts's getNodeSize() so
# each symbol is drawn at its real Canvas proportions. Previously every node
# was squeezed into one fixed NODE_W×NODE_H box, which made vessels/columns
# come out the same size as a valve — the single biggest reason the export
# didn't read like the Canvas screen.
# Unscaled sizes, mirroring rawNodeSize() in the Canvas's
# domain/isa/classification.ts. Do NOT read these directly — the Canvas serves
# them through getNodeSize(), which doubles everything outside
# PIPE_SCALE_EXEMPT. _node_size() below applies that same rule.
#
# Two entries were also plain wrong against the Canvas table: 'tank' was
# (82, 98), a value the Canvas has nowhere, and 'vessel' was (130, 88), which
# is bullet_tank's size rather than vessel_h's.
_RAW_NODE_SIZES = {
    'junction': (16, 16),
    'valve': (54, 50), 'regulator': (54, 50),
    'checkvalve': (46, 36), 'relief': (54, 46),
    'pump': (62, 62), 'compressor': (70, 70),
    'heat_exchanger': (76, 76),          # hx_plate
    'vessel': (88, 60), 'separator': (88, 60),   # vessel_h
    'tank': (58, 70), 'reactor': (94, 126),      # cstr
    'filter': (70, 52), 'column': (62, 152), 'absorber': (62, 152),
    'off_page_connector': (108, 42), 'inlet': (108, 42), 'outlet': (108, 42),
    'vendor_package': (400, 300), 'package': (260, 200),
}

# Kinds the Canvas draws at their raw size — pipe-mounted fittings and
# instrument bubbles, which must stay small enough to sit on a pipe run.
# Everything else is process equipment and renders at EQUIPMENT_SCALE.
# Mirrors PIPE_SCALE_EXEMPT (classification.ts:461).
EQUIPMENT_SCALE = 2
PIPE_SCALE_EXEMPT = {
    'junction', 'valve', 'regulator', 'checkvalve', 'relief',
    'off_page_connector', 'inlet', 'outlet',
}
_INSTRUMENT_SIZE = (52, 52)
_DEFAULT_SIZE    = (108, 56)


def _node_size(node: dict) -> Tuple[float, float]:
    """Render size for a node, mirroring getNodeSize() in classification.ts.

    The Canvas draws process equipment at twice its table size and leaves
    pipe-mounted fittings and instrument bubbles alone. Reading the raw table
    directly — which this did — drew every vessel, tank, filter, pump,
    exchanger, reactor and column at half the size the Canvas shows, so
    equipment looked undersized next to correctly-sized valves.
    """
    k = normalize_render_kind(node.get('kind'))
    if k in INSTRUMENT_KINDS:
        w, h = _INSTRUMENT_SIZE          # exempt, like the Canvas's 'instrument'
    else:
        w, h = _RAW_NODE_SIZES.get(k, _DEFAULT_SIZE)
        if k not in PIPE_SCALE_EXEMPT:
            w, h = w * EQUIPMENT_SCALE, h * EQUIPMENT_SCALE
    if SYMBOL_SCALE != 1.0:
        return (w * SYMBOL_SCALE, h * SYMBOL_SCALE)
    return (w, h)

# Shared with generate_svg_pid's header-reserve calculation — keep in sync
# with what _draw_legend actually renders.
_LEGEND_ITEMS = [
    ('vessel', 'Vessel/Tank'),
    ('heat_exchanger', 'Heat Exchanger'),
    ('reactor', 'Reactor'),
    ('pump', 'Pump/Compressor'),
    ('transmitter', 'Transmitter'),
    ('controller', 'Controller'),
    ('switch', 'Switch/Alarm'),
    ('analyzer', 'Analyzer'),
    ('valve', 'Valve (mechanical)'),
    ('regulator', 'Regulator'),
    ('inlet', 'Inlet (Flow In)'),
    ('outlet', 'Outlet (Flow Out)'),
]


# ── Layout ────────────────────────────────────────────────────────────────────

# Normalised (0-1) positions map onto this sheet. These are the Canvas's own
# DEFAULT_PID_CANVAS values (frontend CanvasScreen.tsx) so a symbol occupies
# the same fraction of the sheet in the export as it does on screen — the
# export used to map onto 3300x2550 (A4 at 300DPI), which spread everything
# ~10% further apart than the Canvas for identically-sized symbols.
CANVAS_W = 3000   # normalized position target canvas width
CANVAS_H = 2200   # normalized position target canvas height
# Inset used when mapping 0-1 coordinates onto that sheet. Must equal the
# Canvas's EXTRACTED_MARGIN (frontend components/canvas/extractedLayout.ts) —
# this module previously reused its own MARGIN (80) here, which scaled every
# extracted coordinate differently from the screen.
EXTRACTED_MARGIN = 24
# Symbol scale. Symbols are drawn at real Canvas pixel sizes (_NODE_SIZES); on
# a dense sheet seen whole they read small simply because there are many of
# them. Raise this to trade overlap for legibility without touching layout.
SYMBOL_SCALE = 1.0


def _position_from_claude(nodes: List[dict]) -> Dict[str, Tuple[float, float]]:
    """
    H1: Use Claude-extracted physical coordinates.
    Maps 0.0-1.0 onto CANVAS_W x CANVAS_H — the Canvas's own sheet size — so
    the export reproduces the physical layout of the original PDF sheet at the
    same symbol-to-sheet ratio the Canvas screen shows.

    No title reserve is subtracted here: generate_svg_pid already shifts the
    whole drawing down by the header band, so squashing y a second time only
    distorted the sheet's aspect relative to the Canvas.
    """
    positioned = [n for n in nodes if n.get('x') is not None and n.get('y') is not None]
    if len(positioned) < max(1, len(nodes) * 0.5):
        return {}

    positions: Dict[str, Tuple[float, float]] = {}
    for n in positioned:
        # The extracted coordinate is the symbol's CENTRE (pixelToNormalized
        # stores cx = px + w/2), while draw_symbol takes a top-left corner —
        # so offset by half the node's own size. Treating the centre as a
        # corner put every symbol half its size down-right of where the Canvas
        # draws it, and half a box away from its own pipe centreline.
        cx, cy = sheet_point(n['x'], n['y'])
        w, h = _node_size(n)
        positions[n['id']] = (cx - w / 2, cy - h / 2)
    return positions


def topological_layout(nodes: List[dict], edges: List[dict]) -> Dict[str, Tuple[float, float]]:
    """
    Assign (x, y) coordinates.
    Priority: Claude-extracted positions (H1) → BFS layer fallback.

    ponytail: the BFS fallback below is a plain layered layout with none of
    Canvas's real dagre-pipeline quality logic (junction re-routing, soft-tag
    absorption, association edges) — it was only ever meant to cover the rare
    case where extracted coordinates are missing/sparse, not to run as the
    primary layout. A short-lived experiment made it the default and it
    produced degenerate junction chains + crossing meshes; reverted. Matching
    Canvas's real compact look would mean porting its actual dagre pipeline,
    not just skipping this branch.
    """
    if not nodes:
        return {}

    # H1: prefer Claude's extracted positions (physical replica) — this is
    # also Canvas's own default layout mode ('extracted'), so it stays the
    # default here too.
    claude_pos = _position_from_claude(nodes)
    if claude_pos:
        id_to_pos = dict(claude_pos)
        # Fill in any missing nodes with BFS relative to existing positions
        missing = [n for n in nodes if n['id'] not in id_to_pos]
        for n in missing:
            peer_x, peer_y = MARGIN, MARGIN
            for e in edges:
                if e['from'] == n['id'] and e['to'] in id_to_pos:
                    px, py = id_to_pos[e['to']]
                    peer_x, peer_y = px - NODE_W - GAP_X, py
                    break
                if e['to'] == n['id'] and e['from'] in id_to_pos:
                    px, py = id_to_pos[e['from']]
                    peer_x, peer_y = px + NODE_W + GAP_X, py
                    break
            id_to_pos[n['id']] = (peer_x, peer_y)
            
        # Fast Y-alignment pass to eliminate orthogonal kinks in drawn lines.
        # Snaps nodes that are roughly horizontal to the exact same Y.
        #
        # It nudges a node up to ~22px off its extracted coordinate, which is a
        # real (small) divergence from the Canvas — kept because the routing
        # here is computed rather than traced, and without it every near-
        # horizontal run picks up a visible kink at both ends.
        for _ in range(10):
            for e in edges:
                if e['from'] in id_to_pos and e['to'] in id_to_pos:
                    y1 = id_to_pos[e['from']][1]
                    y2 = id_to_pos[e['to']][1]
                    if 0 < abs(y1 - y2) < 45:
                        avg_y = (y1 + y2) / 2
                        id_to_pos[e['from']] = (id_to_pos[e['from']][0], avg_y)
                        id_to_pos[e['to']] = (id_to_pos[e['to']][0], avg_y)

        # Separate colliding symbols. Extracted coordinates come from the
        # original sheet, where symbols are drawn far smaller relative to the
        # page than the Canvas-sized boxes used here — so neighbours that were
        # clear on the PDF overlap once redrawn, tags landing on top of other
        # symbols. This path used to return before ever reaching the resolver.
        node_sizes = {n['id']: _node_size(n) for n in nodes}
        return _resolve_overlaps(id_to_pos, sizes=node_sizes)

    # BFS fallback
    node_ids   = {n['id'] for n in nodes}
    id_to_node = {n['id']: n for n in nodes}

    successors:   Dict[str, List[str]] = defaultdict(list)
    predecessors: Dict[str, List[str]] = defaultdict(list)
    for e in edges:
        if e.get('kind') == 'signal':
            continue
        if e['from'] in node_ids and e['to'] in node_ids:
            successors[e['from']].append(e['to'])
            predecessors[e['to']].append(e['from'])

    layers: Dict[str, int] = {}
    queue = deque()
    for n in nodes:
        if not predecessors[n['id']]:
            layers[n['id']] = 0
            queue.append(n['id'])
    if not queue:
        for n in nodes:
            layers[n['id']] = 0
            queue.append(n['id'])

    visited = set(layers.keys())
    while queue:
        nid = queue.popleft()
        for succ in successors[nid]:
            new_layer = layers[nid] + 1
            if succ not in layers or layers[succ] < new_layer:
                layers[succ] = new_layer
            if succ not in visited:
                visited.add(succ)
                queue.append(succ)

    for n in nodes:
        if n['id'] not in layers:
            layers[n['id']] = 0

    layer_groups: Dict[int, List[str]] = defaultdict(list)
    for nid, layer in layers.items():
        layer_groups[layer].append(nid)

    def kind_sort_key(nid: str) -> int:
        kind = normalize_render_kind(id_to_node.get(nid, {}).get('kind', ''))
        if kind in MECHANICAL_KINDS: return 0
        if kind in INSTRUMENT_KINDS: return 2
        return 1

    for layer in layer_groups:
        layer_groups[layer].sort(key=kind_sort_key)

    positions: Dict[str, Tuple[float, float]] = {}
    for layer_num, node_list in sorted(layer_groups.items()):
        x = MARGIN + layer_num * (NODE_W + GAP_X)
        start_y = MARGIN
        for i, nid in enumerate(node_list):
            y = start_y + i * (NODE_H + GAP_Y)
            positions[nid] = (x, y)

    return _resolve_overlaps(positions)


def _resolve_overlaps(
    positions: Dict[str, Tuple[float, float]],
    pad_x: float = NODE_W + 16,
    pad_y: float = NODE_H + 28,   # extra space for tag label below each node
    sizes: Optional[Dict[str, Tuple[float, float]]] = None,
) -> Dict[str, Tuple[float, float]]:
    """
    Iterative bounding-box overlap resolution.
    Pushes overlapping nodes apart along the axis of least penetration.
    After resolving, shifts the whole layout so no node is above/left of MARGIN.

    `sizes` gives each node's real (w, h). Without it every node is separated by
    the same fixed pad, which is wrong once symbols are drawn at their true
    Canvas sizes: a 130-wide vessel and a 16px junction were given identical
    clearance, so big equipment still collided with its neighbours and small
    symbols were pushed further apart than they needed to be.
    """
    pos = dict(positions)
    ids = list(pos.keys())
    LABEL_H = 14   # tag text drawn under the symbol
    GAP     = 16
    for _ in range(60):
        moved = False
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                a, b = ids[i], ids[j]
                ax, ay = pos[a]
                bx, by = pos[b]
                if sizes:
                    aw, ah = sizes.get(a, (NODE_W, NODE_H))
                    bw, bh = sizes.get(b, (NODE_W, NODE_H))
                    # centre-to-centre separation each pair actually needs
                    need_x = (aw + bw) / 2 + GAP
                    need_y = (ah + bh) / 2 + GAP + LABEL_H
                    over_x = need_x - abs((bx + bw / 2) - (ax + aw / 2))
                    over_y = need_y - abs((by + bh / 2) - (ay + ah / 2))
                else:
                    over_x = pad_x - abs(bx - ax)
                    over_y = pad_y - abs(by - ay)
                if over_x <= 0 or over_y <= 0:
                    continue
                if over_x < over_y:
                    shift = over_x / 2 + 1
                    if bx >= ax:
                        pos[a] = (ax - shift, ay)
                        pos[b] = (bx + shift, by)
                    else:
                        pos[a] = (ax + shift, ay)
                        pos[b] = (bx - shift, by)
                else:
                    shift = over_y / 2 + 1
                    if by >= ay:
                        pos[a] = (ax, ay - shift)
                        pos[b] = (bx, by + shift)
                    else:
                        pos[a] = (ax, ay + shift)
                        pos[b] = (bx, by - shift)
                moved = True
        if not moved:
            break

    # Shift everything so the top-left corner starts at MARGIN.
    # Nodes pushed into negative space during resolution would otherwise
    # be clipped off the top or left edge of the SVG viewport.
    if pos:
        min_x = min(x for x, _ in pos.values())
        min_y = min(y for _, y in pos.values())
        ox = MARGIN - min_x if min_x < MARGIN else 0
        oy = MARGIN - min_y if min_y < MARGIN else 0
        if ox or oy:
            pos = {k: (x + ox, y + oy) for k, (x, y) in pos.items()}

    return pos


# ── ISA-5.1 Symbol renderer ───────────────────────────────────────────────────
# Shapes below are ported point-for-point from the real Canvas symbol
# components (frontend/src/components/canvas/ISANodes.tsx) via a
# viewBox→node-box coordinate transform, so the export matches what the
# interactive Canvas actually draws instead of a hand-approximated shape.

def _port(vb_w: float, vb_h: float, x: float, y: float, box_w: float, box_h: float):
    """Maps a Canvas component's SVG viewBox coordinates into this symbol's
    (x, y, box_w, box_h) box, uniformly scaled and centered."""
    s = min(box_w / vb_w, box_h / vb_h)
    ox = x + (box_w - vb_w * s) / 2
    oy = y + (box_h - vb_h * s) / 2

    def pt(px: float, py: float) -> Tuple[float, float]:
        return ox + px * s, oy + py * s

    def poly(pts: List[Tuple[float, float]]) -> str:
        return ' '.join(f'{px:.1f},{py:.1f}' for px, py in (pt(a, b) for a, b in pts))

    return pt, poly, s


# ── Canvas symbol sprite ──────────────────────────────────────────────────────
# symbols/canvas_symbols.svg holds the Canvas's OWN symbol components rendered
# to static <symbol> defs by frontend/scripts/gen-symbols.mjs. Referencing them
# with <use> means the export shows the same 115 symbols the screen does,
# instead of the 18 this module hand-draws — and they can't drift, because
# regenerating re-renders the real components. The hand-drawn branches below
# remain as the fallback for anything the sprite has no entry for.
_SPRITE_FILE = Path(__file__).resolve().parent.parent / 'symbols' / 'canvas_symbols.svg'


@lru_cache(maxsize=1)
def load_symbol_sprite() -> Tuple[str, frozenset]:
    """(defs markup, available symbol ids). Empty when the sprite is absent."""
    try:
        raw = _SPRITE_FILE.read_text(encoding='utf-8')
    except OSError:
        return ('', frozenset())
    inner = re.search(r'<defs>(.*)</defs>', raw, re.S)
    if not inner:
        return ('', frozenset())
    ids = frozenset(re.findall(r'<symbol id="sym-([^"]+)"', raw))
    return (inner.group(1).strip(), ids)


# Normalised kind -> sprite id, for kinds whose raw name isn't already one.
# The raw detector name is tried first, so "Ball_Valve"/"Check_Valve"/"Tank"
# hit ball_valve/check_valve/tank directly without an entry here.
_KIND_TO_SYMBOL = {
    'valve': 'valve', 'regulator': 'regulator',
    'checkvalve': 'check_valve', 'relief': 'relief_valve',
    'tank': 'tank', 'vessel': 'vessel_h', 'separator': 'vessel_h',
    'filter': 'filter', 'heat_exchanger': 'hx_shell_tube',
    'pump': 'pump_cent', 'compressor': 'comp_cent', 'reactor': 'cstr',
    'column': 'vacuum_tower', 'absorber': 'vacuum_tower',
    # No sprite for off-page connectors on purpose: the Canvas renders them
    # with OffPageNode, a chevron carrying the line number INSIDE, not one of
    # the ICON_BY_TYPE symbols. 'continuation_arrow' is a bare arrow, so
    # mapping them here drew a small grey dart with the tag in tiny text
    # underneath where the Canvas shows a labelled chevron. Handled by the
    # hand-drawn branch in draw_symbol instead.
    'controller': 'ctrl_controller', 'recorder': 'ctrl_recorder',
    'switch': 'ctrl_high_switch', 'analyzer': 'instrument',
    'transmitter': 'instrument', 'indicator': 'instrument',
    'element': 'instrument',
}


def symbol_id_for(node: dict) -> Optional[str]:
    """Sprite id for a node, or None to fall back to the hand-drawn symbol."""
    _, ids = load_symbol_sprite()
    if not ids:
        return None
    k = normalize_render_kind(node.get('kind'))
    # Instrument bubbles keep the hand-drawn symbol. The sprite's 'instrument'
    # is a bare circle — the Canvas paints the ISA letter and loop number into
    # it from the tag at render time, so substituting it here produced empty
    # circles with the tag nowhere on the drawing. The hand-drawn bubble is
    # already a faithful port (r = 0.44 x size, letters inside) and carries the
    # tag, so it stays.
    if k in INSTRUMENT_KINDS:
        return None
    raw = str(node.get('kind') or '').strip().lower()
    if raw in ids:
        return raw
    sid = _KIND_TO_SYMBOL.get(k)
    return sid if sid in ids else None


def draw_symbol(node: dict, x: float, y: float) -> str:
    """
    Draw an ISA-5.1 / ISO 10628 symbol for a node at (x, y).
    Returns SVG string for the symbol + label.
    """
    kind  = node.get('kind', 'default')
    label = node.get('label', node.get('id', '?'))
    NODE_W, NODE_H = _node_size(node)   # real Canvas size for THIS node
    cx    = x + NODE_W / 2
    cy    = y + NODE_H / 2

    if kind == 'junction':
        # Junctions are splice points, not equipment — draw a small dot,
        # no label, no bounding box.
        r = 4
        return f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{JUNCTION_DOT}" stroke="none"/>'

    kind  = normalize_render_kind(kind)
    col   = COLORS.get(kind, COLORS['default'])
    fill  = col['fill']
    stroke= col['stroke']
    parts = []

    # The Canvas's own symbol, when the sprite has one. Falls through to the
    # hand-drawn branches below otherwise, so an unrecognised kind still gets a
    # shape rather than nothing. Label placement is shared either way — it runs
    # after this chain.
    _sym = symbol_id_for(node)
    if _sym:
        parts.append(
            f'<use href="#sym-{_sym}" xlink:href="#sym-{_sym}" '
            f'x="{x:.1f}" y="{y:.1f}" width="{NODE_W:.1f}" height="{NODE_H:.1f}" '
            f'color="{stroke}"/>'
        )
    if _sym:
        pass          # sprite drawn above; skip the hand-drawn fallbacks
    elif kind in ('vessel', 'separator'):
        # VesselNode (Canvas, 140x90) — full stadium pill, rx = height/2
        pt, poly, s = _port(140, 90, x, y, NODE_W, NODE_H)
        x0, y0 = pt(2, 12); x1, y1 = pt(138, 78)
        w_, h_ = x1 - x0, y1 - y0
        parts.append(f'<rect x="{x0:.1f}" y="{y0:.1f}" width="{w_:.1f}" height="{h_:.1f}" rx="{h_/2:.1f}" fill="{fill}" stroke="{stroke}" stroke-width="2"/>')

    elif kind == 'tank':
        # TankNode (Canvas, 110x130) — flat-bottomed cylinder + shallow domed roof
        pt, poly, s = _port(110, 130, x, y, NODE_W, NODE_H)
        bl, tl_ = pt(12, 26), pt(12, 118)
        br, tr_ = pt(98, 118), pt(98, 26)
        parts.append(f'<path d="M {bl[0]:.1f},{bl[1]:.1f} L {tl_[0]:.1f},{tl_[1]:.1f} L {br[0]:.1f},{br[1]:.1f} L {tr_[0]:.1f},{tr_[1]:.1f}" fill="{fill}" stroke="{stroke}" stroke-width="2" stroke-linejoin="round"/>')
        rl, rc, rr = pt(12, 26), pt(55, 8), pt(98, 26)
        parts.append(f'<path d="M {rl[0]:.1f},{rl[1]:.1f} Q {rc[0]:.1f},{rc[1]:.1f} {rr[0]:.1f},{rr[1]:.1f}" fill="{fill}" stroke="{stroke}" stroke-width="2"/>')
        g1, g2 = pt(4, 118), pt(106, 118)
        parts.append(f'<line x1="{g1[0]:.1f}" y1="{g1[1]:.1f}" x2="{g2[0]:.1f}" y2="{g2[1]:.1f}" stroke="{stroke}" stroke-width="2"/>')

    elif kind == 'heat_exchanger':
        # HeatExNode (Canvas, 80x80) — rounded shell + U-tube bundle
        pt, poly, s = _port(80, 80, x, y, NODE_W, NODE_H)
        x0, y0 = pt(2, 2); x1, y1 = pt(78, 78)
        w_, h_ = x1 - x0, y1 - y0
        parts.append(f'<rect x="{x0:.1f}" y="{y0:.1f}" width="{w_:.1f}" height="{h_:.1f}" rx="{4*s:.1f}" fill="{fill}" stroke="{stroke}" stroke-width="1.5"/>')
        p1, p2 = pt(12, 26), pt(56, 26)
        p3, p4 = pt(56, 54), pt(12, 54)
        cp1, mid, cp2 = pt(68, 26), pt(68, 40), pt(68, 54)
        parts.append(f'<line x1="{p1[0]:.1f}" y1="{p1[1]:.1f}" x2="{p2[0]:.1f}" y2="{p2[1]:.1f}" stroke="{stroke}" stroke-width="1.5"/>')
        parts.append(f'<path d="M {p2[0]:.1f},{p2[1]:.1f} Q {cp1[0]:.1f},{cp1[1]:.1f} {mid[0]:.1f},{mid[1]:.1f} Q {cp2[0]:.1f},{cp2[1]:.1f} {p3[0]:.1f},{p3[1]:.1f}" fill="none" stroke="{stroke}" stroke-width="1.5"/>')
        parts.append(f'<line x1="{p3[0]:.1f}" y1="{p3[1]:.1f}" x2="{p4[0]:.1f}" y2="{p4[1]:.1f}" stroke="{stroke}" stroke-width="1.5"/>')

    elif kind == 'pump':
        # PumpNode (Canvas, 60x60) — circle + open impeller triangle
        pt, poly, s = _port(60, 60, x, y, NODE_W, NODE_H)
        ccx, ccy = pt(30, 30)
        parts.append(f'<circle cx="{ccx:.1f}" cy="{ccy:.1f}" r="{27*s:.1f}" fill="{fill}" stroke="{stroke}" stroke-width="2"/>')
        parts.append(f'<polygon points="{poly([(54,30),(26,14),(26,46)])}" fill="none" stroke="{stroke}" stroke-width="2" stroke-linejoin="round"/>')

    elif kind == 'compressor':
        # CompressorNode (Canvas, 70x70) — circle + 3-blade fan
        pt, poly, s = _port(70, 70, x, y, NODE_W, NODE_H)
        ccx, ccy = pt(35, 35)
        parts.append(f'<circle cx="{ccx:.1f}" cy="{ccy:.1f}" r="{31*s:.1f}" fill="{fill}" stroke="{stroke}" stroke-width="2"/>')
        for ex, ey in ((59, 16), (64, 35), (59, 54)):
            px, py = pt(ex, ey)
            parts.append(f'<line x1="{ccx:.1f}" y1="{ccy:.1f}" x2="{px:.1f}" y2="{py:.1f}" stroke="{stroke}" stroke-width="2" stroke-linecap="round"/>')

    elif kind == 'reactor':
        # ReactorNode (Canvas, 100x130) — rounded body + zigzag heating coil
        pt, poly, s = _port(100, 130, x, y, NODE_W, NODE_H)
        x0, y0 = pt(2, 2); x1, y1 = pt(98, 128)
        w_, h_ = x1 - x0, y1 - y0
        parts.append(f'<rect x="{x0:.1f}" y="{y0:.1f}" width="{w_:.1f}" height="{h_:.1f}" rx="{6*s:.1f}" fill="{fill}" stroke="{stroke}" stroke-width="2"/>')
        zig = poly([(14, 65), (26, 52), (38, 65), (50, 52), (62, 65), (74, 52), (86, 65)])
        parts.append(f'<path d="M {zig.replace(" ", " L ")}" fill="none" stroke="{stroke}" stroke-width="1.5" stroke-linecap="round"/>')

    elif kind in ('column', 'absorber'):
        # ColumnNode (Canvas, 60x160) — tall rounded body + tray lines
        pt, poly, s = _port(60, 160, x, y, NODE_W, NODE_H)
        x0, y0 = pt(4, 2); x1, y1 = pt(56, 158)
        w_, h_ = x1 - x0, y1 - y0
        parts.append(f'<rect x="{x0:.1f}" y="{y0:.1f}" width="{w_:.1f}" height="{h_:.1f}" rx="{4*s:.1f}" fill="{fill}" stroke="{stroke}" stroke-width="2"/>')
        for ty in (38, 70, 102, 134):
            a, b = pt(4, ty), pt(56, ty)
            parts.append(f'<line x1="{a[0]:.1f}" y1="{a[1]:.1f}" x2="{b[0]:.1f}" y2="{b[1]:.1f}" stroke="{stroke}" stroke-width="1" opacity="0.5"/>')

    elif kind == 'filter':
        # FilterNode (Canvas, 70x50) — rounded rect + diagonal hatch
        pt, poly, s = _port(70, 50, x, y, NODE_W, NODE_H)
        x0, y0 = pt(2, 2); x1, y1 = pt(68, 48)
        w_, h_ = x1 - x0, y1 - y0
        parts.append(f'<rect x="{x0:.1f}" y="{y0:.1f}" width="{w_:.1f}" height="{h_:.1f}" rx="{4*s:.1f}" fill="{fill}" stroke="{stroke}" stroke-width="1.5"/>')
        for (ax, ay), (bx, by) in (((14, 8), (60, 40)), ((8, 22), (46, 46)), ((26, 8), (64, 44))):
            a, b = pt(ax, ay), pt(bx, by)
            parts.append(f'<line x1="{a[0]:.1f}" y1="{a[1]:.1f}" x2="{b[0]:.1f}" y2="{b[1]:.1f}" stroke="{stroke}" stroke-width="1" opacity="0.6"/>')

    elif kind == 'relief':
        # ReliefValveNode (Canvas, 52x44) — open bowtie + spring
        pt, poly, s = _port(52, 44, x, y, NODE_W, NODE_H)
        parts.append(f'<polygon points="{poly([(2,12),(2,40),(26,26)])}" fill="{fill}" stroke="{stroke}" stroke-width="1.5" stroke-linejoin="round"/>')
        parts.append(f'<polygon points="{poly([(50,12),(50,40),(26,26)])}" fill="{fill}" stroke="{stroke}" stroke-width="1.5" stroke-linejoin="round"/>')
        P = [pt(26, 12), pt(26, 2), pt(22, 2), pt(26, 5), pt(30, 2), pt(34, 5), pt(22, 8), pt(26, 11), pt(30, 8)]
        F = lambda p: f'{p[0]:.1f},{p[1]:.1f}'
        spring = (f'M{F(P[0])} L{F(P[1])} M{F(P[2])} Q{F(P[3])} {F(P[4])} '
                  f'Q{F(P[5])} {F(P[6])} Q{F(P[7])} {F(P[8])}')
        parts.append(f'<path d="{spring}" fill="none" stroke="{stroke}" stroke-width="1.2" stroke-linecap="round"/>')

    elif kind == 'valve':
        # ValveNode (Canvas, 52x46) — open bowtie + diaphragm actuator
        pt, poly, s = _port(52, 46, x, y, NODE_W, NODE_H)
        a1, a2 = pt(26, 16), pt(26, 9)
        parts.append(f'<line x1="{a1[0]:.1f}" y1="{a1[1]:.1f}" x2="{a2[0]:.1f}" y2="{a2[1]:.1f}" stroke="{stroke}" stroke-width="1.5"/>')
        d1, d2 = pt(16, 9), pt(36, 9)
        parts.append(f'<path d="M {d1[0]:.1f},{d1[1]:.1f} A {10*s:.1f} {7*s:.1f} 0 0 1 {d2[0]:.1f},{d2[1]:.1f} Z" fill="none" stroke="{stroke}" stroke-width="1.5"/>')
        parts.append(f'<polygon points="{poly([(2,16),(2,44),(26,30)])}" fill="{fill}" stroke="{stroke}" stroke-width="1.5" stroke-linejoin="round"/>')
        parts.append(f'<polygon points="{poly([(50,16),(50,44),(26,30)])}" fill="{fill}" stroke="{stroke}" stroke-width="1.5" stroke-linejoin="round"/>')

    elif kind == 'checkvalve':
        # CheckValveNode (Canvas, 44x32) — bowtie + Z indicator
        pt, poly, s = _port(44, 32, x, y, NODE_W, NODE_H)
        parts.append(f'<polygon points="{poly([(2,6),(2,26),(22,16)])}" fill="{fill}" stroke="{stroke}" stroke-width="1.5" stroke-linejoin="round"/>')
        parts.append(f'<polygon points="{poly([(42,6),(42,26),(22,16)])}" fill="{fill}" stroke="{stroke}" stroke-width="1.5" stroke-linejoin="round"/>')
        parts.append(f'<polyline points="{poly([(18,12),(26,12),(18,20),(26,20)])}" fill="none" stroke="{stroke}" stroke-width="1.5" stroke-linejoin="round"/>')

    elif kind == 'regulator':
        # RegulatorNode (Canvas, 52x46) — open bowtie + diaphragm + dashed sensing line
        pt, poly, s = _port(52, 46, x, y, NODE_W, NODE_H)
        a1, a2 = pt(26, 16), pt(26, 9)
        parts.append(f'<line x1="{a1[0]:.1f}" y1="{a1[1]:.1f}" x2="{a2[0]:.1f}" y2="{a2[1]:.1f}" stroke="{stroke}" stroke-width="1.5"/>')
        d1, d2 = pt(16, 9), pt(36, 9)
        parts.append(f'<path d="M {d1[0]:.1f},{d1[1]:.1f} A {10*s:.1f} {7*s:.1f} 0 0 1 {d2[0]:.1f},{d2[1]:.1f} Z" fill="none" stroke="{stroke}" stroke-width="1.5"/>')
        parts.append(f'<polygon points="{poly([(2,16),(2,44),(26,30)])}" fill="{fill}" stroke="{stroke}" stroke-width="1.5" stroke-linejoin="round"/>')
        parts.append(f'<polygon points="{poly([(50,16),(50,44),(26,30)])}" fill="{fill}" stroke="{stroke}" stroke-width="1.5" stroke-linejoin="round"/>')
        parts.append(f'<polyline points="{poly([(36,9),(42,9),(42,30)])}" fill="none" stroke="{stroke}" stroke-width="1" stroke-dasharray="3 2"/>')

    elif kind in INSTRUMENT_KINDS:
        # ISA instrument bubble — colored by the tag's ISA letter (matching
        # instrColors() on the real Canvas screen), not by bubble-shape kind.
        _ic = _instr_color(label)
        fill, stroke, txt = _ic['fill'], _ic['stroke'], _ic.get('text', _ic['stroke'])
        # Canvas InstrumentNode draws r=22 in a 50-unit box (~0.44 of size).
        r4 = min(NODE_W, NODE_H) * 0.44
        if kind == 'controller':
            # Circle with horizontal bar (DCS)
            parts.append(f'<circle cx="{cx}" cy="{cy}" r="{r4}" fill="{fill}" stroke="{stroke}" stroke-width="1.5"/>')
            parts.append(f'<line x1="{cx-r4}" y1="{cy}" x2="{cx+r4}" y2="{cy}" stroke="{stroke}" stroke-width="1.2"/>')
        elif kind == 'recorder':
            # Circle with two bars
            parts.append(f'<circle cx="{cx}" cy="{cy}" r="{r4}" fill="{fill}" stroke="{stroke}" stroke-width="1.5"/>')
            parts.append(f'<line x1="{cx-r4*0.7}" y1="{cy-r4*0.25}" x2="{cx+r4*0.7}" y2="{cy-r4*0.25}" stroke="{stroke}" stroke-width="1.0"/>')
            parts.append(f'<line x1="{cx-r4*0.7}" y1="{cy+r4*0.25}" x2="{cx+r4*0.7}" y2="{cy+r4*0.25}" stroke="{stroke}" stroke-width="1.0"/>')
        elif kind == 'switch':
            # Circle with diagonal line
            parts.append(f'<circle cx="{cx}" cy="{cy}" r="{r4}" fill="{fill}" stroke="{stroke}" stroke-width="1.5"/>')
            parts.append(f'<line x1="{cx-r4*0.65}" y1="{cy+r4*0.65}" x2="{cx+r4*0.65}" y2="{cy-r4*0.65}" stroke="{stroke}" stroke-width="1.2"/>')
        elif kind == 'analyzer':
            # Diamond
            parts.append(f'<polygon points="{cx},{cy-r4*1.1} {cx+r4*0.9},{cy} {cx},{cy+r4*1.1} {cx-r4*0.9},{cy}" fill="{fill}" stroke="{stroke}" stroke-width="1.5"/>')
        elif kind == 'element':
            # Filled diamond
            parts.append(f'<polygon points="{cx},{cy-r4*0.9} {cx+r4*0.75},{cy} {cx},{cy+r4*0.9} {cx-r4*0.75},{cy}" fill="{stroke}" stroke="{stroke}" stroke-width="1.0" opacity="0.85"/>')
        else:
            # Plain circle (transmitter, indicator)
            parts.append(f'<circle cx="{cx}" cy="{cy}" r="{r4}" fill="{fill}" stroke="{stroke}" stroke-width="1.5"/>')
        # Func code + loop number INSIDE the bubble — matches Canvas's
        # InstrumentNode (code centered, loop number just below it), using the
        # pastel per-letter text color, not the border color.
        import re as _re
        _m = _re.match(r'^([A-Za-z]+)[-_]?(.*)$', label or '')
        func = (_m.group(1) if _m else (label or '?')).upper()
        loop = _m.group(2) if _m else ''
        fs = 9 if len(func) > 3 else 11
        fs = fs * (min(NODE_W, NODE_H) / 52.0)   # scale with real bubble size
        if loop:
            parts.append(f'<text x="{cx:.1f}" y="{cy-r4*0.22:.1f}" text-anchor="middle" dominant-baseline="central" font-size="{fs:.1f}" font-weight="800" fill="{txt}" font-family="monospace">{_escape(func)}</text>')
            parts.append(f'<text x="{cx:.1f}" y="{cy+r4*0.36:.1f}" text-anchor="middle" dominant-baseline="central" font-size="{fs*0.72:.1f}" fill="{txt}" font-family="monospace">{_escape(loop)}</text>')
        else:
            parts.append(f'<text x="{cx:.1f}" y="{cy:.1f}" text-anchor="middle" dominant-baseline="central" font-size="{fs:.1f}" font-weight="800" fill="{txt}" font-family="monospace">{_escape(func)}</text>')

    elif kind in ('off_page_connector', 'inlet', 'outlet'):
        # Determine styling and direction
        points_right = True
        if kind == 'inlet':
            points_right = False  # Inlets point inwards (left)
            fill_c = COLORS['inlet']['fill']
            stroke_c = COLORS['inlet']['stroke']
        else:
            points_right = True   # Outlets / generic off-page point outwards (right)
            fill_c = COLORS['outlet']['fill']
            stroke_c = COLORS['outlet']['stroke']

        if points_right:
            px1, py_t, py_b = x + 4, y + 6, y + NODE_H - 6
            px_mid = x + NODE_W * 0.72
            px_tip = x + NODE_W - 4
            py_c   = y + NODE_H / 2
            
            parts.append(
                f'<polygon points="{px1},{py_t} {px_mid},{py_t} {px_tip},{py_c} '
                f'{px_mid},{py_b} {px1},{py_b}" '
                f'fill="{fill_c}" stroke="{stroke_c}" stroke-width="1.5"/>'
            )
            # No arrow inside: the Canvas's OffPageNode is a plain chevron
            # whose direction IS the arrow, and the line number now sits in
            # that space — a drawn arrow ran straight through the text.
        else:
            # Pointing left (Inlet)
            px1, py_t, py_b = x + NODE_W - 4, y + 6, y + NODE_H - 6
            px_mid = x + NODE_W * 0.28
            px_tip = x + 4
            py_c   = y + NODE_H / 2
            
            parts.append(
                f'<polygon points="{px1},{py_t} {px_mid},{py_t} {px_tip},{py_c} '
                f'{px_mid},{py_b} {px1},{py_b}" '
                f'fill="{fill_c}" stroke="{stroke_c}" stroke-width="1.5"/>'
            )
            # No arrow inside: the Canvas's OffPageNode is a plain chevron
            # whose direction IS the arrow, and the line number now sits in
            # that space — a drawn arrow ran straight through the text.

    else:
        # Generic rectangle
        parts.append(f'<rect x="{x+5}" y="{y+8}" width="{NODE_W-10}" height="{NODE_H-16}" rx="3" fill="{fill}" stroke="{stroke}" stroke-width="1.5"/>')

    # Label placement — mirrors ISANodes.tsx: instrument bubbles carry their
    # code+loop INSIDE (already drawn above, no below-label — Canvas doesn't
    # draw one); equipment shapes get the tag INSIDE the body (bold white,
    # centered); everything else (valve family, connectors) keeps a below tag.
    if kind in INSTRUMENT_KINDS:
        pass
    elif _sym:
        # Sprite symbols are open outlines (a shell-and-tube exchanger, a
        # column), not filled boxes, so a tag centred on one lands across its
        # own linework and is unreadable. The Canvas puts these below the
        # symbol in its stroke colour — an inline tag is only for the solid
        # box shapes handled below.
        parts.append(
            f'<text x="{cx:.1f}" y="{y+NODE_H+10:.1f}" text-anchor="middle" '
            f'font-size="9" font-family="Arial" fill="{stroke}" '
            f'font-weight="700">{_escape(_format_tag(label))}</text>'
        )
    elif kind in EQUIPMENT_KINDS_INLINE or kind == 'default':
        # 'default' belongs here: getNodeType() falls back to 'equipment' for
        # any kind it doesn't recognise, and the Canvas draws that as a box
        # with the tag inside. Letting it fall through to the below-tag branch
        # put the tag in 8px muted grey under a 216x112 box, where it read as
        # an unlabelled rectangle — C-110 lost its name on the sheet.
        parts.append(f'<text x="{cx:.1f}" y="{cy:.1f}" text-anchor="middle" dominant-baseline="central" font-size="10" font-family="Arial" fill="white" font-weight="700">{_escape(_format_tag(label))}</text>')
    elif kind in CONNECTOR_KINDS:
        # OffPageNode carries the line/stream number INSIDE the chevron, in the
        # flat region away from the point (ISANodes.tsx: textCx = (W-PT)/2+2,
        # fontSize 9). It was falling through to the below-tag branch, which
        # put the number in 8px muted grey under the chevron — so at sheet
        # scale each header just ended in a small unlabelled dart.
        _t = _format_tag(label)
        _avail = NODE_W * 0.72 - 8
        _max = max(4, int(_avail / 5.0))
        if len(_t) > _max:
            _t = _t[:_max - 1] + '…'
        parts.append(
            f'<text x="{x + NODE_W * 0.36:.1f}" y="{cy:.1f}" text-anchor="middle" '
            f'dominant-baseline="central" font-size="9" font-family="Arial" '
            f'fill="{stroke}" font-weight="600">{_escape(_t)}</text>'
        )
    elif kind in MECHANICAL_KINDS:
        # ValveLabel — below the symbol, in the valve's own stroke color, bold
        # small text (matches ISANodes.tsx's ValveLabel).
        vc = _instr_color(label)['stroke'] if kind != 'relief' else COLORS['relief']['stroke']
        parts.append(f'<text x="{cx:.1f}" y="{y+NODE_H+8:.1f}" text-anchor="middle" font-size="8" font-family="Arial" fill="{vc}" font-weight="700">{_escape(_format_tag(label))}</text>')
    else:
        parts.append(f'<text x="{cx}" y="{y+NODE_H+12}" text-anchor="middle" font-size="8" font-family="Arial" fill="{TEXT_MUTED}" font-weight="500">{_escape(label)}</text>')

    return '\n'.join(parts)


def _format_tag(label: str) -> str:
    """Mirrors classification.ts's formatTag(): normalize underscores to
    dashes, or insert one between a leading letter run and trailing digits
    (e.g. 'V101' -> 'V-101') so equipment tags read the same as Canvas."""
    import re
    lbl = label or ''
    if re.search(r'[-_]', lbl):
        return lbl.replace('_', '-')
    m = re.match(r'^([A-Za-z]+)(\d+.*)$', lbl)
    return f'{m.group(1)}-{m.group(2)}' if m else lbl


def _bubble_tag(label: str) -> str:
    """Extract 2-3 letter function code for instrument bubble."""
    import re
    m = re.match(r'^([A-Za-z]{1,4})', label)
    return m.group(1).upper()[:3] if m else label[:3]


def _escape(s: str) -> str:
    return s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;')


# ── Edge routing ──────────────────────────────────────────────────────────────

def _edge_offsets(edges: List[dict]) -> Dict[int, float]:
    """
    For nodes where 3+ pipe edges share the same endpoint (a manifold/header
    junction — common at backbone tie-ins), stagger each edge's orthogonal
    bend by a small amount so they fan out into visually distinct lines
    instead of stacking exactly on top of each other. That exact overlap is
    what reads as a tangled mess at busy junction points.
    """
    from_groups: Dict[str, List[int]] = defaultdict(list)
    to_groups: Dict[str, List[int]] = defaultdict(list)
    for i, e in enumerate(edges):
        from_groups[e['from']].append(i)
        to_groups[e['to']].append(i)

    STEP = 14  # px between fanned-out bend lines
    offsets: Dict[int, float] = {}
    for groups in (from_groups, to_groups):
        for idxs in groups.values():
            n = len(idxs)
            if n < 3:
                continue
            for slot, i in enumerate(idxs):
                offset = (slot - (n - 1) / 2) * STEP
                # An edge can fan out at both its source and target junction —
                # keep whichever offset is larger in magnitude.
                if abs(offsets.get(i, 0)) < abs(offset):
                    offsets[i] = offset
    return offsets


def _rounded_path(points: List[Tuple[float, float]], r: float = 8) -> str:
    """
    Orthogonal path with rounded corners at each bend — mirrors the
    smooth-step routing Canvas's real edges use (BendableEdge/WaypointEdge,
    built on React Flow's getSmoothStepPath) instead of sharp right-angle
    elbows, which is what visually reads as "not the Canvas connection way".
    """
    if len(points) < 3:
        return ' '.join(f'{"M" if i == 0 else "L"} {px:.1f},{py:.1f}' for i, (px, py) in enumerate(points))
    d = [f'M {points[0][0]:.1f},{points[0][1]:.1f}']
    for i in range(1, len(points) - 1):
        x0, y0 = points[i - 1]
        x1, y1 = points[i]
        x2, y2 = points[i + 1]
        d1x, d1y = x1 - x0, y1 - y0
        d2x, d2y = x2 - x1, y2 - y1
        len1 = math.hypot(d1x, d1y) or 1
        len2 = math.hypot(d2x, d2y) or 1
        r1 = min(r, len1 / 2)
        r2 = min(r, len2 / 2)
        ax, ay = x1 - d1x / len1 * r1, y1 - d1y / len1 * r1
        bx, by = x1 + d2x / len2 * r2, y1 + d2y / len2 * r2
        d.append(f'L {ax:.1f},{ay:.1f}')
        d.append(f'Q {x1:.1f},{y1:.1f} {bx:.1f},{by:.1f}')
    d.append(f'L {points[-1][0]:.1f},{points[-1][1]:.1f}')
    return ' '.join(d)


def sheet_point(nx: float, ny: float) -> Tuple[float, float]:
    """Normalised (0-1) sheet coordinate -> pixel CENTRE point.

    Mirrors normalizedPointToPixel() in the Canvas's extractedLayout.ts, down
    to EXTRACTED_MARGIN and the usable-size floors, because node positions and
    edge waypoints share this one 0-1 space. Two things were wrong here:
    this used MARGIN (80) where the Canvas uses 24, and the result was treated
    as a node's top-left corner when pixelToNormalized defines it as the
    symbol's CENTRE (cx = px + w/2). Every symbol therefore sat half its own
    size away from the centreline the pipes were drawn along.
    """
    usable_w = max(CANVAS_W - 2 * EXTRACTED_MARGIN, 400)
    usable_h = max(CANVAS_H - 2 * EXTRACTED_MARGIN, 300)
    return (EXTRACTED_MARGIN + float(nx) * usable_w,
            EXTRACTED_MARGIN + float(ny) * usable_h)


def draw_edge(from_pos: Tuple, to_pos: Tuple, kind: str, label: str = '', mid_offset: float = 0,
              from_size: Tuple[float, float] = (NODE_W, NODE_H),
              to_size: Tuple[float, float] = (NODE_W, NODE_H),
              waypoints: Optional[List[Tuple[float, float]]] = None
              ) -> Tuple[str, List[Tuple[float, float]]]:
    """
    H2: Direction-aware orthogonal routing.
    Exit/entry points chosen by relative position and edge kind.

    Returns (svg_markup, routed_points) — the caller needs the points to size
    the canvas around geometry that routing placed outside the node bounds.

    from_size/to_size: real (w, h) of each endpoint node (Canvas getNodeSize),
    so pipes attach to the actual edge of the real-sized symbol instead of a
    fixed 60×45 box — otherwise lines start/end floating off big equipment.

    mid_offset: shifts the orthogonal bend line by this many px. Used when
    several edges share an endpoint (a manifold/header junction) so their
    bends fan out into distinct lines instead of stacking on the exact same
    coordinate — which is what reads as a tangled mess at busy junctions.
    """
    fw, fh = from_size
    tw, th = to_size
    fx_c = from_pos[0] + fw / 2   # from center x
    fy_c = from_pos[1] + fh / 2   # from center y
    tx_c = to_pos[0]  + tw / 2    # to center x
    ty_c = to_pos[1]  + th / 2    # to center y

    dx = tx_c - fx_c
    dy = ty_c - fy_c

    # One resolution for style AND marker — see resolve_edge_kind.
    ekind  = resolve_edge_kind(kind)
    col    = EDGE_COLORS[ekind]
    stroke = col['stroke']
    width  = col['width']
    dash   = f'stroke-dasharray="{col["dash"]}"' if col['dash'] else ''

    if waypoints and len(waypoints) >= 2:
        # A COMPLETE route from the Canvas: buildRoute()'s surviving interior
        # bends with the handle anchor points resolved onto each end. Drawn
        # verbatim so the exported pipe run is the one on screen.
        #
        # Note this is NOT edges.extra_json.waypoints, which are fragments of
        # detected linework — 92 of 94 on p-id-1 hold 2-3 points spanning a
        # median of 30px. Drawing those raw produced diagonal stubs floating
        # between symbols; buildRoute is what turns them into a pipe.
        pts = [(float(px), float(py)) for px, py in waypoints]
        path = _rounded_path(pts)
        mid = pts[len(pts) // 2]
        label_x, label_y = mid[0] + 4, mid[1] - 3

    elif ekind == 'signal':
        # Instrument signal: bottom of source bubble → top of dest bubble
        x1 = fx_c
        y1 = from_pos[1] + fh
        x2 = tx_c
        y2 = to_pos[1]
        mid_y = (y1 + y2) / 2 + mid_offset
        pts = [(x1, y1), (x1, mid_y), (x2, mid_y), (x2, y2)]
        path = _rounded_path(pts)
        label_x, label_y = x1 + 4, mid_y - 3

    elif abs(dy) > abs(dx) * 1.5:
        # Predominantly vertical run
        if dy >= 0:
            # Source above target: exit bottom, enter top
            x1, y1 = fx_c, from_pos[1] + fh
            x2, y2 = tx_c, to_pos[1]
        else:
            # Source below target: exit top, enter bottom
            x1, y1 = fx_c, from_pos[1]
            x2, y2 = tx_c, to_pos[1] + th
        mid_y = (y1 + y2) / 2 + mid_offset
        pts = [(x1, y1), (x1, mid_y), (x2, mid_y), (x2, y2)]
        path = _rounded_path(pts)
        label_x, label_y = x1 + 4, mid_y - 3

    elif dx >= 0:
        # Normal left-to-right flow
        x1 = from_pos[0] + fw
        y1 = fy_c
        x2 = to_pos[0]
        y2 = ty_c
        mid_x = (x1 + x2) / 2 + mid_offset
        pts = [(x1, y1), (mid_x, y1), (mid_x, y2), (x2, y2)]
        path = _rounded_path(pts)
        label_x, label_y = mid_x + 4, min(y1, y2) + abs(y2 - y1) / 2 - 3

    else:
        # Recycle / return: exit left of source, enter right of target
        x1 = from_pos[0]
        y1 = fy_c
        x2 = to_pos[0] + tw
        y2 = ty_c
        # Route around: go left, down/up, then right
        loop_x = min(from_pos[0], to_pos[0]) - GAP_X * 0.5 + mid_offset
        pts = [(x1, y1), (loop_x, y1), (loop_x, y2), (x2, y2)]
        path = _rounded_path(pts)
        label_x, label_y = loop_x + 4, (y1 + y2) / 2 - 3

    parts = [
        f'<path d="{path}" fill="none" stroke="{stroke}" '
        f'stroke-width="{width}" {dash} marker-end="url(#arrow_{ekind})"/>'
    ]

    if label:
        parts.append(
            f'<text x="{label_x:.1f}" y="{label_y:.1f}" font-size="6" '
            f'font-family="Arial" fill="{stroke}" opacity="0.8">{_escape(label[:20])}</text>'
        )

    # Return the routed corner points alongside the markup. The canvas bounds
    # must be computed AFTER routing: a recycle/return edge detours a half-gap
    # outside the node it leaves (loop_x above), and a bounds figure derived
    # from node boxes alone clipped that detour straight off the viewBox.
    return '\n'.join(parts), pts


# ── Main assembler ────────────────────────────────────────────────────────────

def generate_svg_pid(ympl_doc: dict, project_name: str = 'Plant',
                     layers=None, canvas_positions: Optional[dict] = None,
                     view_preset: str = 'control',
                     background: str = 'dark',
                     routes: Optional[dict] = None) -> str:
    """
    Generate a complete ISA-5.1 P&ID SVG from a YMPL document.
    Returns SVG string ready to save or serve.

    layers:           iterable of layer ids to render (see ALL_LAYERS). None
                      renders CONTROL_LAYERS, or ALL_LAYERS when view_preset
                      is 'full'.
    canvas_positions: {node_id: (x, y)} engineer-placed positions in canvas
                      pixels; overrides the computed layout per node, so the
                      export matches what was arranged on screen.
    view_preset:      'control' (default) or 'full' — only widens the default
                      layer set; an explicit `layers` always wins.
    background:       'dark' (Canvas theme, default) or 'light' (print).
    """
    nodes = ympl_doc.get('nodes', [])
    edges = ympl_doc.get('edges', [])

    if not nodes:
        return '<svg xmlns="http://www.w3.org/2000/svg"><text x="10" y="20">No topology data</text></svg>'

    if layers is None:
        layers = ALL_LAYERS if view_preset == 'full' else CONTROL_LAYERS
    layers = set(layers)

    # Layout
    positions = topological_layout(nodes, edges)
    id_to_pos = positions  # reassigned below after title-bar shift

    # Header band height — nodes must start below both the title text AND the
    # legend box, whichever is taller. The legend (drawn top-right, see
    # _draw_legend) is ~190px tall — a title-only reserve of 50px left nodes
    # free to land underneath/inside it whenever real extracted coordinates
    # placed something near the top-right corner, causing visible overlap.
    TITLE_H = 50
    LEGEND_H = len(_LEGEND_ITEMS) * 14 + 12 + 8  # matches _draw_legend's own math
    HEADER_H = max(TITLE_H, LEGEND_H)

    # Engineer-placed positions win over the computed layout, per node, so the
    # export reproduces the arrangement made on screen. Nodes with no saved
    # position keep their laid-out spot rather than collapsing to the origin.
    if canvas_positions:
        known = {n['id'] for n in nodes}
        positions = {
            **positions,
            **{nid: (float(p[0]), float(p[1]))
               for nid, p in canvas_positions.items()
               if nid in known and p and len(p) >= 2},
        }

    # Shift all positions down so nodes clear the title bar and legend.
    #
    # Supplied routes MUST move with them. They are absolute points in the same
    # space as the positions, so shifting only the symbols slid every pipe
    # ~270px up relative to the equipment it connects — pipes ending in space
    # beside their symbol. Invisible whenever routes aren't supplied (the CLI
    # path), which is why it only showed up in the desktop app.
    if positions:
        min_y_pos = min(p[1] for p in positions.values())
        if min_y_pos < HEADER_H + MARGIN:
            shift_down = HEADER_H + MARGIN - min_y_pos
            positions = {k: (x, y + shift_down) for k, (x, y) in positions.items()}
            if routes:
                routes = {k: [(px, py + shift_down) for px, py in pts]
                          for k, pts in routes.items()}
    id_to_pos = positions

    # Per-node real sizes (Canvas getNodeSize) — used for both edge attachment
    # and the canvas-bounds calc so big equipment isn't clipped.
    sizes = {n['id']: _node_size(n) for n in nodes}

    # ── Route edges FIRST, so the canvas can be sized around what routing
    # actually produced. Sizing from node boxes alone clipped every routed
    # detour that left those boxes (the recycle branch in draw_edge).
    # H8: Named layers — edges drawn behind symbols, instruments on top of equipment
    pipe_edges   = [e for e in edges if resolve_edge_kind(e.get('kind', 'stream')) != 'signal']
    signal_edges = [e for e in edges if resolve_edge_kind(e.get('kind', '')) == 'signal']

    def _edge_waypoints(edge: dict):
        """The Canvas's built route for this edge, in sheet pixels.

        Only routes supplied by the caller are used. The raw
        edges.extra_json.waypoints are fragments of detected linework and are
        NOT a drawable path — see the note in draw_edge.
        """
        if not routes:
            return None
        return routes.get((edge.get('from'), edge.get('to')))

    routed_pts: List[Tuple[float, float]] = []
    pipe_offsets = _edge_offsets(pipe_edges)
    piping_parts = []
    for i, edge in enumerate(pipe_edges):
        fp = id_to_pos.get(edge['from'])
        tp = id_to_pos.get(edge['to'])
        if fp and tp:
            markup, pts = draw_edge(
                fp, tp, edge.get('kind', 'stream'), edge.get('label', ''),
                pipe_offsets.get(i, 0),
                sizes.get(edge['from'], (NODE_W, NODE_H)),
                sizes.get(edge['to'], (NODE_W, NODE_H)),
                waypoints=_edge_waypoints(edge),
            )
            piping_parts.append(markup)
            routed_pts.extend(pts)

    signal_parts = []
    for edge in signal_edges:
        fp = id_to_pos.get(edge['from'])
        tp = id_to_pos.get(edge['to'])
        if fp and tp:
            markup, pts = draw_edge(
                fp, tp, 'signal', edge.get('label', ''), 0,
                sizes.get(edge['from'], (NODE_W, NODE_H)),
                sizes.get(edge['to'], (NODE_W, NODE_H)),
                waypoints=_edge_waypoints(edge),
            )
            signal_parts.append(markup)
            routed_pts.extend(pts)

    def _layer(layer_id: str, body: List[str]) -> str:
        """Emit a layer group only when the caller asked for that layer."""
        if layer_id not in layers or not body:
            return ''
        return f'<g id="{layer_id}">\n' + '\n'.join(body) + '\n</g>'

    # Drawing content, built before the header so the canvas can be sized to
    # what was actually drawn.
    content: List[str] = [
        _layer('layer-piping', piping_parts),
        _layer('layer-signals', signal_parts),
    ]

    # Split nodes into kind-based layers. Membership is checked against the
    # NORMALIZED kind — raw YOLO type strings like "Ball_Valve" never equal
    # the canonical 'valve' exactly, so checking node.get('kind') directly
    # here silently dropped most nodes from every layer (no symbol drawn at
    # all, not even a fallback rectangle).
    def _symbol_body(kind_set, node_list, id_to_pos_map) -> List[str]:
        parts: List[str] = []
        for node in node_list:
            if kind_set is not None and normalize_render_kind(node.get('kind')) not in kind_set:
                continue
            pos = id_to_pos_map.get(node['id'])
            if not pos:
                continue
            tag   = _escape(node.get('label', node['id']))
            kind  = node.get('kind', 'default')
            area  = _escape(node.get('area', '') or node.get('drawing', ''))
            parts.append(
                f'<g data-tag="{tag}" data-kind="{kind}" data-area="{area}">'
            )
            parts.append(draw_symbol(node, pos[0], pos[1]))
            parts.append('</g>')
        return parts

    process_kinds = {
        'vessel', 'tank', 'separator', 'heat_exchanger', 'pump', 'compressor',
        'reactor', 'column', 'absorber', 'adsorption', 'filter', 'meter'
    }
    junction_kinds = {'junction'}
    classified = (process_kinds | set(INSTRUMENT_KINDS) | set(MECHANICAL_KINDS)
                  | set(CONNECTOR_KINDS) | junction_kinds)
    # Any node whose normalized kind matches none of the layers above. Without
    # this it was laid out and had pipes routed to it, but no symbol was ever
    # drawn — so those pipes ended in blank space, which reads as a broken
    # connection rather than an unrecognised symbol.
    other_nodes = [n for n in nodes
                   if normalize_render_kind(n.get('kind')) not in classified]

    content.extend([
        _layer('layer-equipment',   _symbol_body(process_kinds,    nodes,       id_to_pos)),
        _layer('layer-instruments', _symbol_body(INSTRUMENT_KINDS, nodes,       id_to_pos)),
        _layer('layer-mechanical',  _symbol_body(MECHANICAL_KINDS, nodes,       id_to_pos)),
        _layer('layer-connectors',  _symbol_body(CONNECTOR_KINDS,  nodes,       id_to_pos)),
        _layer('layer-junctions',   _symbol_body(junction_kinds,   nodes,       id_to_pos)),
        _layer('layer-other',       _symbol_body(None,             other_nodes, id_to_pos)),
    ])

    body = '\n'.join(p for p in content if p)

    # ── Canvas bounds, measured from the drawn content ────────────────────────
    # PAD keeps stroke width, arrowheads and edge labels clear of the edge.
    PAD = 24
    min_x, min_y, max_x, max_y = measure_extents(body)

    # Routing can detour to negative coordinates (draw_edge's recycle branch
    # subtracts half a gap from the leftmost node), and the header band needs
    # room above the drawing. Shift content instead of letting a viewBox that
    # starts at 0 clip it.
    # Deliberately signed: a positive shift pushes content clear of the origin
    # and the header band, a negative one crops empty sheet above/left of the
    # drawing. Clamping these at 0 left the whole unused top-left of the
    # extracted sheet in the viewBox, which shrank the drawing on every
    # fit-to-page view.
    shift_x = PAD - min_x
    shift_y = (HEADER_H + MARGIN) - min_y
    if shift_x or shift_y:
        body = f'<g transform="translate({shift_x:.1f},{shift_y:.1f})">\n{body}\n</g>'

    max_x = max(max_x + shift_x + PAD, 200.0)
    max_y = max(max_y + shift_y + PAD, 200.0)

    # SVG header. defs are always emitted — a marker referenced by a rendered
    # layer must resolve regardless of which layers were selected.
    bg_fill = LIGHT_BG if background == 'light' else CANVAS_BG
    svg_parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'xmlns:xlink="http://www.w3.org/1999/xlink" '
        f'width="{max_x:.1f}" height="{max_y:.1f}" '
        f'viewBox="0 0 {max_x:.1f} {max_y:.1f}">',
        '<defs>',
        # The Canvas's own symbols, referenced by <use> from draw_symbol.
        load_symbol_sprite()[0],
        # Arrow markers per edge kind — one per EDGE_COLORS key, which is
        # exactly the set resolve_edge_kind() can return.
        *[f'''<marker id="arrow_{k}" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto">
  <path d="M0,0 L0,6 L8,3 z" fill="{EDGE_COLORS[k]["stroke"]}"/>
</marker>''' for k in EDGE_COLORS],
        '</defs>',
        _layer('layer-background', [
            f'<rect width="{max_x:.1f}" height="{max_y:.1f}" fill="{bg_fill}"/>',
        ]),
        _layer('layer-grid', [
            '<g opacity="0.06">',
            *[f'<line x1="0" y1="{y_}" x2="{max_x:.1f}" y2="{y_}" stroke="{GRID_COLOR}" stroke-width="0.5"/>'
              for y_ in range(0, int(max_y), 100)],
            '</g>',
        ]),
        _layer('layer-annotations', [
            f'<text x="{MARGIN}" y="{MARGIN-10}" font-size="14" font-family="Arial" '
            f'font-weight="bold" fill="{TEXT_COLOR}">{_escape(project_name)} — P&amp;ID</text>',
            _draw_legend(max_x, MARGIN),
        ]),
        body,
        '</svg>',
    ]
    out = '\n'.join(p for p in svg_parts if p)
    return _apply_light_theme(out) if background == 'light' else out


def _draw_legend(canvas_width: float, y_start: float) -> str:
    """Draw a compact legend in the top-right corner."""
    items = _LEGEND_ITEMS
    lx = canvas_width - 160
    ly = y_start - 8
    parts = [f'<rect x="{lx-8}" y="{ly-8}" width="155" height="{len(items)*14+12}" rx="3" fill="{PANEL_BG}" stroke="{GRID_COLOR}" stroke-width="0.5"/>']
    for i, (kind, name) in enumerate(items):
        col = COLORS.get(kind, COLORS['default'])
        yy = ly + i * 14
        parts.append(f'<rect x="{lx}" y="{yy}" width="12" height="10" rx="1" fill="{col["fill"]}" stroke="{col["stroke"]}" stroke-width="1"/>')
        parts.append(f'<text x="{lx+16}" y="{yy+9}" font-size="8" font-family="Arial" fill="{TEXT_MUTED}">{name}</text>')
    return '\n'.join(parts)
