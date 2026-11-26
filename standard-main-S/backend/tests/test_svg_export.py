"""SVG export regression tests.

Each test here pins a bug that shipped silently — the SVG stayed valid XML and
opened fine in a browser while the drawing itself was wrong, so nothing raised
and nothing looked broken until the output was measured.
"""

from __future__ import annotations

import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

_STUDIO_DIR = Path(__file__).resolve().parents[1]
if str(_STUDIO_DIR) not in sys.path:
    sys.path.insert(0, str(_STUDIO_DIR))

from adapters.svg_pid import (  # noqa: E402
    ALL_LAYERS,
    CONTROL_LAYERS,
    EDGE_COLORS,
    generate_svg_pid,
    measure_extents,
    resolve_edge_kind,
)

SVG_NS = '{http://www.w3.org/2000/svg}'


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _doc(edge_kind: str = 'process') -> dict:
    """Two vessels and an instrument, wired with one pipe and one signal."""
    return {
        'nodes': [
            {'id': 'n1', 'label': 'V-101', 'kind': 'vessel'},
            {'id': 'n2', 'label': 'E-201', 'kind': 'heat_exchanger'},
            {'id': 'n3', 'label': 'FT-101', 'kind': 'transmitter'},
        ],
        'edges': [
            {'from': 'n1', 'to': 'n2', 'kind': edge_kind},
            {'from': 'n3', 'to': 'n2', 'kind': 'signal'},
        ],
    }


def _parse(svg: str):
    return ET.fromstring(svg)


def _marker_ids(root) -> set:
    return {m.get('id') for m in root.iter(SVG_NS + 'marker')}


def _marker_refs(svg: str) -> set:
    return set(re.findall(r'marker-end="url\(#([^)]+)\)"', svg))


# ── 1. process edge → a marker that actually exists ───────────────────────────

def test_process_edge_resolves_to_defined_marker():
    """`process` is the dominant kind in extracted data but was never an
    EDGE_COLORS key, so `url(#arrow_process)` named a marker that was never
    defined and the arrowhead silently vanished."""
    svg = generate_svg_pid(_doc('process'), 'T')
    root = _parse(svg)
    refs, defined = _marker_refs(svg), _marker_ids(root)
    assert refs, 'no marker-end emitted at all'
    assert refs <= defined, f'undefined marker(s): {sorted(refs - defined)}'
    assert 'arrow_process' not in refs, 'process must resolve to a defined marker'


def test_resolve_edge_kind_always_lands_on_a_defined_key():
    for kind in ('process', 'stream', 'signal', 'recycle', 'bypass',
                 'hydraulic', 'pneumatic', 'electrical', 'capillary',
                 'nonsense', '', None):
        assert resolve_edge_kind(kind) in EDGE_COLORS, kind


def test_process_maps_to_stream_styling():
    assert resolve_edge_kind('process') == 'stream'


def test_every_pipe_gets_an_arrowhead():
    """Flow direction is not decoration on a P&ID."""
    svg = generate_svg_pid(_doc('process'), 'T')
    root = _parse(svg)
    pipes = [p for p in root.iter(SVG_NS + 'path') if p.get('marker-end')]
    assert len(pipes) >= 2, f'expected an arrowhead per edge, got {len(pipes)}'


# ── 2. no unresolved references of any kind ───────────────────────────────────

def test_no_unresolved_url_references():
    for kind in ('process', 'stream', 'signal', 'recycle', 'weird_kind'):
        svg = generate_svg_pid(_doc(kind), 'T')
        ids = set(re.findall(r'\sid="([^"]+)"', svg))
        used = set(re.findall(r'url\(#([^)]+)\)', svg))
        assert used <= ids, f'{kind}: dangling {sorted(used - ids)}'


# ── 3. routed geometry outside node bounds stays inside the viewBox ───────────

def test_viewbox_contains_routed_detour():
    """A right-to-left edge routes half a gap OUTSIDE the node it leaves.
    Bounds computed from node boxes alone clipped that detour away."""
    # n2 placed left of n1 forces draw_edge's recycle/return branch.
    doc = {
        'nodes': [
            {'id': 'n1', 'label': 'V-101', 'kind': 'vessel',         'x': 0.80, 'y': 0.80},
            {'id': 'n2', 'label': 'E-201', 'kind': 'heat_exchanger', 'x': 0.10, 'y': 0.15},
        ],
        'edges': [{'from': 'n1', 'to': 'n2', 'kind': 'process'}],
    }
    svg = generate_svg_pid(doc, 'T')
    root = _parse(svg)
    vb = [float(v) for v in root.get('viewBox').split()]
    vw, vh = vb[2], vb[3]

    inner = re.search(r'<g transform="translate\(([-\d.]+),([-\d.]+)\)">(.*)</g>',
                      svg, re.S)
    if inner:
        tx, ty = float(inner.group(1)), float(inner.group(2))
        body = inner.group(3)
    else:
        tx = ty = 0.0
        body = svg
    min_x, min_y, max_x, max_y = measure_extents(body)

    assert min_x + tx >= 0, f'content left of origin: {min_x + tx}'
    assert min_y + ty >= 0, f'content above origin: {min_y + ty}'
    assert max_x + tx <= vw, f'content past right edge: {max_x + tx} > {vw}'
    assert max_y + ty <= vh, f'content past bottom edge: {max_y + ty} > {vh}'


def test_viewbox_matches_width_and_height():
    root = _parse(generate_svg_pid(_doc(), 'T'))
    vb = [float(v) for v in root.get('viewBox').split()]
    assert (vb[0], vb[1]) == (0.0, 0.0)
    assert abs(float(root.get('width')) - vb[2]) < 0.05
    assert abs(float(root.get('height')) - vb[3]) < 0.05


# ── 4. every node is drawn, so no pipe ends in blank space ────────────────────

def test_unclassified_kind_still_draws_a_symbol():
    """A node whose kind matched no layer was laid out and had pipes routed to
    it, but no symbol was ever drawn — the pipe ended at nothing."""
    doc = {
        'nodes': [
            {'id': 'n1', 'label': 'V-101',   'kind': 'vessel'},
            {'id': 'n2', 'label': 'MYSTERY', 'kind': 'some_unmapped_kind'},
        ],
        'edges': [{'from': 'n1', 'to': 'n2', 'kind': 'process'}],
    }
    svg = generate_svg_pid(doc, 'T')
    assert 'layer-other' in svg, 'unclassified node produced no symbol layer'
    assert 'MYSTERY' in svg, 'unclassified node was never drawn'


# ── 5. controller/generator signature stay compatible ─────────────────────────

def test_generate_svg_pid_accepts_the_controllers_call():
    """export_controller called this with layers/canvas_positions/view_preset
    and imported ALL_LAYERS; none existed, so every /export/svg* raised
    ImportError before a single byte was produced."""
    svg = generate_svg_pid(
        _doc(), 'Plant',
        layers=ALL_LAYERS,
        canvas_positions={'n1': (120.0, 300.0)},
        view_preset='full',
    )
    assert svg.startswith('<svg')
    _parse(svg)


def test_export_controller_imports_resolve():
    from adapters.svg_pid import ALL_LAYERS as _AL, generate_svg_pid as _g  # noqa: F401
    from helpers.svg_helper import _svg_for_drawing  # noqa: F401


def test_canvas_positions_override_layout():
    """An engineer-placed position must survive into the export."""
    doc = _doc()
    far = {'n1': (900.0, 700.0)}
    a = generate_svg_pid(doc, 'T')
    b = generate_svg_pid(doc, 'T', canvas_positions=far)
    assert a != b, 'canvas_positions had no effect on the output'


# ── 6. layers and background are selectable ───────────────────────────────────

def test_layer_selection_is_honoured():
    only_pipes = generate_svg_pid(_doc(), 'T', layers={'layer-piping'})
    assert 'layer-piping' in only_pipes
    assert 'layer-equipment' not in only_pipes
    # defs must survive layer filtering or the emitted marker refs dangle
    ids = set(re.findall(r'\sid="([^"]+)"', only_pipes))
    used = set(re.findall(r'url\(#([^)]+)\)', only_pipes))
    assert used <= ids


def test_control_preset_excludes_grid_and_full_includes_it():
    assert 'layer-grid' not in CONTROL_LAYERS
    assert 'layer-grid' in ALL_LAYERS
    assert 'layer-grid' in generate_svg_pid(_doc(), 'T', view_preset='full')
    assert 'layer-grid' not in generate_svg_pid(_doc(), 'T', view_preset='control')


def test_light_background_is_print_friendly():
    dark  = generate_svg_pid(_doc(), 'T', background='dark')
    light = generate_svg_pid(_doc(), 'T', background='light')
    assert '#0B1220' in dark, 'dark canvas theme changed'
    assert '#0B1220' not in light, 'dark ground survived into the light export'
    assert '#FFFFFF' in light
    _parse(light)


def _luminance(hex_colour: str) -> float:
    h = hex_colour.lstrip('#')
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return (0.299 * r + 0.587 * g + 0.114 * b) / 255


def test_light_export_has_no_dark_symbol_bodies():
    """Recolouring only the background left every symbol body dark — the
    palettes carry their own near-black fills, tuned for the dark canvas, so
    the drawing punched black holes in a white sheet."""
    root = _parse(generate_svg_pid(_doc(), 'T', background='light'))
    dark = []
    for el in root.iter():
        tag = el.tag.replace(SVG_NS, '')
        fill = el.get('fill') or ''
        # <text> and <marker> contents are meant to be dark ink on white.
        if tag in ('text', 'marker') or not fill.startswith('#'):
            continue
        if _luminance(fill) < 0.45:
            dark.append((tag, fill))
    # Arrowheads and deliberately-filled ISA elements stay dark; symbol bodies
    # must not. Anything beyond a handful means the palette leaked through.
    assert len(dark) <= 6, f'dark symbol bodies on a white sheet: {dark}'


def test_junction_dots_are_visible_on_the_light_sheet():
    """A junction is where several pipes meet. Its dot was #E5E7EB — fine on
    the dark canvas, invisible on white — so every pipe running into one
    looked like it stopped in mid-air."""
    from adapters.svg_pid import JUNCTION_DOT
    doc = {
        'nodes': [
            {'id': 'n1', 'label': 'V-101', 'kind': 'vessel',   'x': 0.10, 'y': 0.30},
            {'id': 'j1', 'label': '',      'kind': 'junction', 'x': 0.40, 'y': 0.30},
        ],
        'edges': [{'from': 'n1', 'to': 'j1', 'kind': 'process'}],
    }
    light = generate_svg_pid(doc, 'T', background='light')
    assert JUNCTION_DOT not in light, 'dark-canvas junction colour survived'
    root = _parse(light)
    dots = [c for c in root.iter(SVG_NS + 'circle')
            if (c.get('fill') or '').startswith('#') and _luminance(c.get('fill')) < 0.5]
    assert dots, 'no visible junction dot on the light sheet'


def test_light_export_has_no_white_on_white_text():
    """Equipment tags are drawn inside the shape as fill="white" — correct on
    the dark canvas, invisible once the body becomes a near-white tint."""
    light = generate_svg_pid(_doc(), 'T', background='light')
    assert 'fill="white"' not in light


def test_light_remap_covers_every_palette_colour():
    """Derived from the palettes, so a newly added equipment kind or ISA
    letter cannot leave an unmapped dark swatch behind."""
    from adapters.svg_pid import (COLORS, LETTER_COLORS, LETTER_DEFAULT,
                                  VALVE_COLOR, _build_light_remap)
    remap = _build_light_remap()
    for entry in list(COLORS.values()) + list(LETTER_COLORS.values()) + [LETTER_DEFAULT, VALVE_COLOR]:
        for role in ('fill', 'stroke', 'text'):
            if entry.get(role):
                assert entry[role] in remap, f'{role} {entry[role]} has no light equivalent'


# ── 7. general well-formedness ────────────────────────────────────────────────

def test_output_is_well_formed_and_namespaced():
    svg = generate_svg_pid(_doc(), 'T')
    root = _parse(svg)
    assert root.tag == SVG_NS + 'svg'
    assert 'xmlns="http://www.w3.org/2000/svg"' in svg


def test_no_zero_length_or_empty_geometry():
    root = _parse(generate_svg_pid(_doc(), 'T'))
    for ln in root.iter(SVG_NS + 'line'):
        assert not (ln.get('x1') == ln.get('x2') and ln.get('y1') == ln.get('y2'))
    for p in root.iter(SVG_NS + 'path'):
        d = (p.get('d') or '').strip()
        assert d and d[0] in 'Mm', f'malformed path d={d[:40]!r}'


def test_empty_document_is_still_valid_svg():
    _parse(generate_svg_pid({'nodes': [], 'edges': []}, 'T'))


# ── 8. the export must match the Canvas, not re-invent the drawing ────────────

def test_symbol_centre_lands_on_the_extracted_coordinate():
    """The extracted x/y is the symbol's CENTRE (pixelToNormalized stores
    cx = px + w/2), but it was handed to draw_symbol as a top-left corner —
    putting every symbol half its own size down-right of where the Canvas
    draws it, and half a box off its own pipe centreline."""
    from adapters.svg_pid import _node_size, sheet_point, topological_layout
    # A lone node: no edges, so the Y-alignment pass cannot move it.
    nodes = [{'id': 'n1', 'label': 'A', 'kind': 'vessel', 'x': 0.20, 'y': 0.30}]
    pos = topological_layout(nodes, [])
    want_cx, want_cy = sheet_point(0.20, 0.30)
    w, h = _node_size(nodes[0])
    x, y = pos['n1']
    assert abs((x + w / 2) - want_cx) < 0.01, f'centre x {x + w / 2} != {want_cx}'
    assert abs((y + h / 2) - want_cy) < 0.01, f'centre y {y + h / 2} != {want_cy}'


def test_node_sizes_match_the_canvas_getnodesize():
    """svg_pid mirrored rawNodeSize() instead of getNodeSize(), which doubles
    everything outside PIPE_SCALE_EXEMPT — so every vessel, tank, filter,
    pump, exchanger, reactor and column drew at half the size the Canvas
    shows, next to correctly-sized valves. Values from
    frontend/src/domain/isa/classification.ts."""
    from adapters.svg_pid import _node_size
    canvas = {
        # exempt — raw size on both sides
        'junction': (16, 16), 'valve': (54, 50), 'regulator': (54, 50),
        'checkvalve': (46, 36), 'relief': (54, 46), 'outlet': (108, 42),
        'transmitter': (52, 52),
        # scaled by EQUIPMENT_SCALE = 2
        'pump': (124, 124), 'compressor': (140, 140),
        'heat_exchanger': (152, 152), 'vessel': (176, 120),
        'tank': (116, 140), 'reactor': (188, 252),
        'filter': (140, 104), 'column': (124, 304),
    }
    for kind, want in canvas.items():
        assert _node_size({'kind': kind}) == want, kind


def test_equipment_is_larger_than_pipe_fittings():
    """The visible symptom: a tank must read bigger than the ball valve on
    its outlet."""
    from adapters.svg_pid import _node_size
    tank_w, _ = _node_size({'kind': 'tank'})
    valve_w, _ = _node_size({'kind': 'valve'})
    assert tank_w > valve_w * 1.5, f'tank {tank_w} vs valve {valve_w}'


def test_canvas_symbol_sprite_is_present_and_used():
    """The exporter hand-drew 18 kinds while the Canvas rendered 188
    components, so anything else exported as a plain box. It now references
    the Canvas's own symbols, rendered to symbols/canvas_symbols.svg by
    frontend/scripts/gen-symbols.mjs."""
    from adapters.svg_pid import load_symbol_sprite
    defs, ids = load_symbol_sprite()
    assert ids, 'symbol sprite missing — run frontend/scripts/gen-symbols.mjs'
    assert len(ids) > 100, f'sprite has only {len(ids)} symbols'
    for expected in ('ball_valve', 'check_valve', 'tank', 'pcv', 'micron_filter'):
        assert expected in ids, expected

    doc = {
        'nodes': [
            {'id': 'n1', 'label': 'V-101', 'kind': 'Ball_Valve'},
            {'id': 'n2', 'label': 'T-201', 'kind': 'Tank'},
        ],
        'edges': [],
    }
    svg = generate_svg_pid(doc, 'T')
    assert '<use href="#sym-ball_valve"' in svg
    assert '<symbol id="sym-ball_valve"' in svg, 'sprite defs not inlined'
    _parse(svg)


def test_every_use_reference_resolves():
    """A <use> pointing at a symbol the sprite doesn't define renders nothing
    at all — silently, exactly like the arrow_process marker did."""
    doc = {
        'nodes': [
            {'id': 'n1', 'label': 'V-101', 'kind': 'Ball_Valve'},
            {'id': 'n2', 'label': 'T-201', 'kind': 'Tank'},
            {'id': 'n3', 'label': 'F-1',   'kind': 'Filter'},
            {'id': 'n4', 'label': 'PI-1',  'kind': 'indicator'},
            {'id': 'n5', 'label': 'X-9',   'kind': 'totally_unknown_kind'},
        ],
        'edges': [{'from': 'n1', 'to': 'n2', 'kind': 'process'}],
    }
    svg = generate_svg_pid(doc, 'T')
    used = set(re.findall(r'<use href="#([^"]+)"', svg))
    defined = set(re.findall(r'<symbol id="([^"]+)"', svg))
    assert used <= defined, f'dangling <use>: {sorted(used - defined)}'
    assert 'X-9' in svg, 'unknown kind lost its fallback symbol'


def test_instrument_bubbles_keep_their_tag():
    """The sprite's 'instrument' is a bare circle — the Canvas paints the ISA
    letter and loop number in from the tag at render time. Substituting it
    produced empty circles with the tag nowhere on the drawing."""
    doc = {'nodes': [{'id': 'n1', 'label': 'PI 1000', 'kind': 'indicator'}],
           'edges': []}
    svg = generate_svg_pid(doc, 'T')
    assert '<use href="#sym-instrument"' not in svg
    assert 'PI' in svg and '1000' in svg


def test_sheet_mapping_matches_the_canvas():
    """sheet_point mirrors normalizedPointToPixel() in extractedLayout.ts.
    This used the module's own MARGIN (80) where the Canvas uses
    EXTRACTED_MARGIN (24), scaling every extracted coordinate differently
    from the screen."""
    from adapters.svg_pid import (CANVAS_H, CANVAS_W, EXTRACTED_MARGIN,
                                  sheet_point)
    assert EXTRACTED_MARGIN == 24, 'must match the Canvas constant'
    usable_w = max(CANVAS_W - 2 * EXTRACTED_MARGIN, 400)
    usable_h = max(CANVAS_H - 2 * EXTRACTED_MARGIN, 300)
    assert sheet_point(0.0, 0.0) == (EXTRACTED_MARGIN, EXTRACTED_MARGIN)
    assert sheet_point(1.0, 1.0) == (EXTRACTED_MARGIN + usable_w,
                                     EXTRACTED_MARGIN + usable_h)


def test_supplied_canvas_route_is_drawn_verbatim():
    """The Canvas builds each pipe run with buildRoute() — clipping bends that
    fall inside a symbol, dropping jog artifacts, choosing handles from the
    surviving route. None of that is reproducible by re-routing here, so the
    route is computed on the Canvas side and drawn as given."""
    from adapters.svg_pid import _path_points
    pts = [(100.0, 100.0), (100.0, 900.0), (1500.0, 900.0), (1500.0, 1400.0)]
    doc = {
        'nodes': [
            {'id': 'n1', 'label': 'V-101', 'kind': 'vessel',         'x': 0.05, 'y': 0.05},
            {'id': 'n2', 'label': 'E-201', 'kind': 'heat_exchanger', 'x': 0.60, 'y': 0.70},
        ],
        'edges': [{'from': 'n1', 'to': 'n2', 'kind': 'process'}],
    }
    root = _parse(generate_svg_pid(doc, 'T', routes={('n1', 'n2'): pts}))
    pipes = [p for p in root.iter(SVG_NS + 'path') if p.get('marker-end')]
    assert pipes, 'no pipe drawn'
    drawn = _path_points(pipes[0].get('d') or '')

    # The route keeps its SHAPE, not its absolute coordinates: generate_svg_pid
    # shifts the whole drawing down to clear the header band and the route
    # moves with the symbols (see test_supplied_routes_shift_with_the_symbols).
    # Compare each point relative to the first.
    def rel(seq):
        ox, oy = seq[0]
        return [(round(x - ox, 1), round(y - oy, 1)) for x, y in seq]
    want = rel(pts)
    got = rel(drawn)
    for corner in want:
        assert any(abs(corner[0] - g[0]) < 12 and abs(corner[1] - g[1]) < 12
                   for g in got), f'corner {corner} missing from the drawn route'


def test_supplied_routes_shift_with_the_symbols():
    """generate_svg_pid pushes every node down to clear the title/legend band.
    Supplied routes are absolute points in the SAME space, so they have to move
    with it — shifting only the symbols slid every pipe ~270px up relative to
    the equipment it connects, leaving pipes ending in space beside their
    symbol. Only reachable when routes are supplied, i.e. from the desktop app,
    which is why the CLI renders never showed it."""
    from adapters.svg_pid import _node_size, _path_points
    # y well above the header band, so a downward shift is guaranteed
    pos = {'n1': (100.0, 10.0), 'n2': (900.0, 10.0)}
    doc = {
        'nodes': [
            {'id': 'n1', 'label': 'V-101', 'kind': 'vessel'},
            {'id': 'n2', 'label': 'E-201', 'kind': 'heat_exchanger'},
        ],
        'edges': [{'from': 'n1', 'to': 'n2', 'kind': 'process'}],
    }
    w1, h1 = _node_size(doc['nodes'][0])
    w2, h2 = _node_size(doc['nodes'][1])
    route = [(100.0 + w1, 10.0 + h1 / 2), (900.0, 10.0 + h2 / 2)]

    svg = generate_svg_pid(doc, 'T', canvas_positions=pos,
                           routes={('n1', 'n2'): route})
    root = _parse(svg)

    boxes = []
    for g in root.iter(SVG_NS + 'g'):
        if g.get('data-tag') is not None:
            e = measure_extents(ET.tostring(g, encoding='unicode'))
            if e[2] > e[0]:
                boxes.append(e)
    assert boxes, 'no symbols drawn'

    pipes = [p for p in root.iter(SVG_NS + 'path') if p.get('marker-end')]
    assert pipes, 'no pipe drawn'
    for p in pipes:
        pts = _path_points(p.get('d') or '')
        assert pts
        for end in (pts[0], pts[-1]):
            gap = min(max(b[0] - end[0], end[0] - b[2],
                          b[1] - end[1], end[1] - b[3]) for b in boxes)
            assert gap <= 12, (
                f'pipe end {end} is {gap:.0f}px from every symbol — routes did '
                'not move with the header shift')


def test_route_absent_falls_back_to_computed_routing():
    doc = {
        'nodes': [
            {'id': 'n1', 'label': 'V-101', 'kind': 'vessel',         'x': 0.10, 'y': 0.30},
            {'id': 'n2', 'label': 'E-201', 'kind': 'heat_exchanger', 'x': 0.70, 'y': 0.30},
        ],
        'edges': [{'from': 'n1', 'to': 'n2', 'kind': 'process'}],
    }
    root = _parse(generate_svg_pid(doc, 'T', routes={('other', 'pair'): [(0, 0), (1, 1)]}))
    pipes = [p for p in root.iter(SVG_NS + 'path') if p.get('marker-end')]
    assert pipes, 'edge with no supplied route lost its pipe'


def test_waypoints_do_not_become_the_whole_pipe():
    """edges.extra_json waypoints are fragments of detected linework, not
    symbol-to-symbol routes — on p-id-1, 92 of 94 hold 2-3 points spanning a
    median of 30px. Drawing them as the complete path produced short diagonal
    stubs floating between symbols, so the pipe must still run between the two
    symbols it connects."""
    from adapters.svg_pid import _node_size, topological_layout
    doc = {
        'nodes': [
            {'id': 'n1', 'label': 'V-101', 'kind': 'vessel',         'x': 0.10, 'y': 0.30},
            {'id': 'n2', 'label': 'E-201', 'kind': 'heat_exchanger', 'x': 0.70, 'y': 0.30},
        ],
        # a 30px-ish fragment nowhere near either symbol
        'edges': [{'from': 'n1', 'to': 'n2', 'kind': 'process',
                   'waypoints': [[0.40, 0.60], [0.41, 0.61]]}],
    }
    root = _parse(generate_svg_pid(doc, 'T'))
    pipes = [p for p in root.iter(SVG_NS + 'path') if p.get('marker-end')]
    assert pipes, 'no pipe drawn'
    nums = [float(v) for v in re.findall(r'-?\d*\.?\d+', pipes[0].get('d'))]
    span = abs(nums[-2] - nums[0])
    pos = topological_layout(doc['nodes'], doc['edges'])
    gap = pos['n2'][0] - (pos['n1'][0] + _node_size(doc['nodes'][0])[0])
    assert span > gap * 0.5, (
        f'pipe spans {span:.0f}px across a {gap:.0f}px gap — it is a floating '
        'fragment, not a connection')
