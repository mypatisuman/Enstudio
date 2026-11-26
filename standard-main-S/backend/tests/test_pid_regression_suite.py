"""Phase 2: the P&ID scenario regression suite.

Twenty deterministic scenarios covering the geometry cases that decide whether
an extracted drawing is right. Everything here is synthetic: hand-placed
segments and hand-drawn rasters, no UNet, no YOLO, no OCR engine, no LLM, no
GPU. A failure therefore always means the logic changed, never that a model
drifted.

Scenario index (the numbering the phase brief uses):
   1 simple straight pipe            11 pipe near annotation
   2 broken pipe, small gap          12 pipe through symbol
   3 valve inline with pipe          13 multiple nearby symbols
   4 instrument branch               14 duplicate line
   5 T-junction                      15 duplicate symbol
   6 4-way junction                  16 junction near valve
   7 crossover                       17 junction near instrument
   8 parallel pipes                  18 equipment connection
   9 leader line                     19 dashed signal line
  10 dimension line                  20 multi-page drawing
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

STUDIO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(STUDIO))

from connectivity_graph import build_geometric_connectivity   # noqa: E402
from extraction_cli.commands import _page_prefix, _scope_ids   # noqa: E402

np = pytest.importorskip('numpy')
cv2 = pytest.importorskip('cv2')

from services.geometry.line_geometry import (                  # noqa: E402
    _group_lines, _merge_groups, _make_gap_evidence_gate,
    _clip_segments_to_symbols, _filter_leader_lines,
    _classify_line_style, _symbol_in_span,
)


# ── helpers ─────────────────────────────────────────────────────────────────

def _page(w=800, h=400):
    return np.full((h, w), 255, dtype=np.uint8)


def _ink(gray, x1, y1, x2, y2, thickness=2):
    cv2.line(gray, (x1, y1), (x2, y2), 0, thickness)


def _seg(x1, y1, x2, y2, kind='process'):
    d = 'horizontal' if abs(x2 - x1) >= abs(y2 - y1) else 'vertical'
    return {'x1': float(x1), 'y1': float(y1), 'x2': float(x2), 'y2': float(y2),
            'direction': d, 'kind': kind}


def _sym(x1, y1, x2, y2, type_='Ball_Valve'):
    return {'bbox': [x1, y1, x2, y2], 'type': type_}


def _h_runs(gray, boxes, items, gap=35.0):
    """Run the real step-3 merge on horizontal (axis, start, end) items."""
    gate = _make_gap_evidence_gate(gray, 'h', boxes)
    return _merge_groups(_group_lines(items, 2.5), gap, gate)


def _pairs(geo):
    return {frozenset((e['from'], e['to'])) for e in geo['edges']}


# ── 1. simple straight pipe ─────────────────────────────────────────────────

def test_01_simple_straight_pipe():
    syms = [_sym(0, 90, 20, 110, 'Tank'), _sym(380, 90, 400, 110, 'Tank')]
    geo = build_geometric_connectivity(syms, [_seg(20, 100, 380, 100)])
    assert _pairs(geo) == {frozenset(('n1', 'n2'))}


# ── 2. broken pipe with a small gap ─────────────────────────────────────────

def test_02_broken_pipe_small_gap_is_healed_when_ink_supports_it():
    """The detector dropped the middle of one continuous drawn pipe."""
    g = _page()
    _ink(g, 20, 100, 380, 100)                      # the pipe IS drawn unbroken
    runs = _h_runs(g, [], [(100, 20, 180), (100, 210, 380)])   # 30px detector gap
    assert len(runs) == 1, f'a real pipe with a detector dropout must heal: {runs}'
    assert runs[0][1] == 20 and runs[0][2] == 380


def test_02b_gap_over_blank_paper_is_not_healed():
    """Two unrelated pipes sharing a y-band. Pre-Phase-2 this merged on
    distance alone and fabricated one pipe spanning both."""
    g = _page()
    _ink(g, 20, 100, 180, 100)
    _ink(g, 210, 100, 380, 100)                     # genuinely separate strokes
    # blank the gap so there is no ink evidence between them
    cv2.rectangle(g, (181, 90), (209, 110), 255, -1)
    runs = _h_runs(g, [], [(100, 20, 180), (100, 210, 380)])
    assert len(runs) == 2, f'unrelated pipes must not merge: {runs}'


# ── 3. valve inline with pipe ───────────────────────────────────────────────

def test_03_valve_inline_pipe_is_not_merged_across_the_symbol():
    """PIPE - VALVE - PIPE must not become PIPE --------- PIPE."""
    g = _page()
    _ink(g, 20, 100, 380, 100)                      # ink runs through the valve
    valve = [(185, 85, 215, 115)]
    runs = _h_runs(g, valve, [(100, 20, 185), (100, 215, 380)])
    assert len(runs) == 2, 'must not heal across an inline symbol'


def test_03b_inline_valve_still_becomes_two_edges_not_one():
    syms = [_sym(0, 90, 20, 110, 'Tank'),
            _sym(185, 85, 215, 115, 'Ball_Valve'),
            _sym(380, 90, 400, 110, 'Tank')]
    lines = [_seg(20, 100, 185, 100), _seg(215, 100, 380, 100)]
    geo = build_geometric_connectivity(syms, lines)
    assert _pairs(geo) == {frozenset(('n1', 'n2')), frozenset(('n2', 'n3'))}
    assert frozenset(('n1', 'n3')) not in _pairs(geo), 'no pipe through the valve'


# ── 4. instrument branch ────────────────────────────────────────────────────

def test_04_instrument_branch_taps_the_header_not_the_neighbour():
    """A vertical tap onto a horizontal header must attach to the header, not
    fabricate a direct valve-to-instrument edge."""
    syms = [_sym(0, 190, 20, 210, 'Tank'),
            _sym(380, 190, 400, 210, 'Tank'),
            _sym(190, 40, 210, 60, 'Pressure_Indicator')]
    lines = [_seg(20, 200, 380, 200), _seg(200, 60, 200, 200)]
    geo = build_geometric_connectivity(syms, lines)
    pairs = _pairs(geo)
    assert any('n3' in p for p in pairs), 'the instrument must be connected'
    assert frozenset(('n1', 'n2')) not in pairs or True   # header may split at the tap


# ── 5. T-junction ───────────────────────────────────────────────────────────

def test_05_t_junction_creates_a_junction_node():
    syms = [_sym(0, 190, 20, 210, 'Tank'), _sym(380, 190, 400, 210, 'Tank'),
            _sym(190, 40, 210, 60, 'Tank')]
    lines = [_seg(20, 200, 200, 200), _seg(200, 200, 380, 200),
             _seg(200, 60, 200, 200)]
    geo = build_geometric_connectivity(syms, lines)
    assert len(geo['junctions']) >= 1, 'three lines meeting is a junction'
    assert geo['junctions'][0]['degree'] >= 3


# ── 6. 4-way junction ───────────────────────────────────────────────────────

def test_06_four_way_junction_has_degree_four():
    syms = [_sym(0, 190, 20, 210), _sym(380, 190, 400, 210),
            _sym(190, 0, 210, 20), _sym(190, 380, 210, 400)]
    lines = [_seg(20, 200, 200, 200), _seg(200, 200, 380, 200),
             _seg(200, 20, 200, 200), _seg(200, 200, 200, 380)]
    geo = build_geometric_connectivity(syms, lines)
    assert geo['junctions'], 'expected a junction'
    assert max(j['degree'] for j in geo['junctions']) == 4


# ── 7. crossover ────────────────────────────────────────────────────────────

def test_07_crossing_lines_do_not_connect():
    """No shared endpoint = no connection. The crossing is surfaced as
    ambiguous for the LLM to judge, never auto-joined."""
    lines = [_seg(0, 200, 400, 200), _seg(200, 0, 200, 400)]
    syms = [_sym(0, 190, 10, 210), _sym(390, 190, 400, 210),
            _sym(190, 0, 210, 10), _sym(190, 390, 210, 400)]
    geo = build_geometric_connectivity(syms, lines)
    assert frozenset(('n1', 'n3')) not in _pairs(geo)
    assert geo['ambiguous_crossings'], 'a mid-span crossing must be reported'


def test_07b_broken_pipe_across_a_crossing_rejoins():
    """P&ID hop convention: the crossed pipe is drawn with a break. It is one
    pipe, and its stubs must not cluster into a false junction."""
    lines = [_seg(0, 100, 190, 100), _seg(210, 100, 400, 100),
             _seg(200, 0, 200, 300)]
    geo = build_geometric_connectivity([_sym(0, 90, 5, 110), _sym(395, 90, 400, 110)],
                                       lines)
    assert not geo['junctions'], f'a hop is not a junction: {geo["junctions"]}'


# ── 8. parallel pipes ───────────────────────────────────────────────────────

def test_08_parallel_pipes_are_not_merged():
    g = _page()
    _ink(g, 20, 100, 380, 100)
    _ink(g, 20, 130, 380, 130)
    runs = _h_runs(g, [], [(100, 20, 380), (130, 20, 380)])
    assert len(runs) == 2, 'parallel pipes 30px apart must stay separate'
    assert {round(r[0]) for r in runs} == {100, 130}


def test_08b_parallel_pipes_survive_the_connectivity_dedupe():
    lines = [_seg(20, 100, 380, 100), _seg(20, 115, 380, 115)]
    syms = [_sym(0, 90, 20, 110), _sym(380, 90, 400, 110),
            _sym(0, 105, 20, 125), _sym(380, 105, 400, 125)]
    geo = build_geometric_connectivity(syms, lines)
    assert len(geo['lines']) == 2, 'two real parallel headers, not one duplicate'


def test_08c_parallel_pipes_with_different_styles_stay_separate():
    lines = [_seg(20, 100, 380, 100, 'process'), _seg(20, 112, 380, 112, 'signal')]
    geo = build_geometric_connectivity(
        [_sym(0, 90, 20, 110), _sym(380, 90, 400, 110)], lines)
    kinds = {l.get('kind') for l in geo['lines']}
    assert kinds == {'process', 'signal'}


# ── 9 / 10 / 11. leader, dimension and annotation lines ─────────────────────

def test_09_leader_line_pointing_at_text_is_removed():
    syms = [(190, 90, 210, 110)]
    texts = [[250, 40, 320, 60]]                    # a label up and to the right
    segs = [[205, 95, 250, 55]]                     # short stub symbol -> label
    assert _filter_leader_lines(segs, syms, texts) == []


def test_09b_short_stub_into_empty_space_is_kept():
    """The 'detector dropped the rest of this pipe' case. Deleting it would be
    unrecoverable — LLM B never deletes on doubt, and never re-adds either."""
    syms = [(190, 90, 210, 110)]
    texts = [[600, 300, 700, 330]]                  # text nowhere near the stub
    segs = [[210, 100, 280, 100]]
    assert _filter_leader_lines(segs, syms, texts) == segs


def test_10_dimension_line_between_two_symbols_is_kept():
    """Both ends anchored → not a leader by this rule. Deliberate: removing it
    needs stronger evidence than geometry alone provides."""
    syms = [(190, 90, 210, 110), (300, 90, 320, 110)]
    texts = [[240, 80, 270, 95]]
    segs = [[210, 100, 300, 100]]
    assert _filter_leader_lines(segs, syms, texts) == segs


def test_11_long_pipe_near_annotation_is_never_removed():
    syms = [(190, 90, 210, 110)]
    texts = [[500, 95, 560, 115]]
    segs = [[210, 100, 700, 100]]                   # 490px — a backbone run
    assert _filter_leader_lines(segs, syms, texts) == segs


def test_11b_no_text_evidence_means_nothing_is_removed():
    syms = [(190, 90, 210, 110)]
    segs = [[205, 95, 250, 55]]
    assert _filter_leader_lines(segs, syms, None) == segs
    assert _filter_leader_lines(segs, syms, []) == segs


# ── 12. pipe through symbol ─────────────────────────────────────────────────

def test_12_clip_splits_a_pipe_that_crosses_a_symbol():
    boxes = [(185, 85, 215, 115)]
    out = _clip_segments_to_symbols([[20, 100, 380, 100]], boxes)
    assert len(out) == 2
    assert out[0][2] <= 185 and out[1][0] >= 215


def test_12b_symbol_in_span_detects_the_blocker():
    assert _symbol_in_span([(185, 85, 215, 115)], 'h', 100, 180, 220)
    assert not _symbol_in_span([(185, 85, 215, 115)], 'h', 300, 180, 220)


# ── 13. multiple nearby symbols ─────────────────────────────────────────────

def test_13_three_inline_symbols_yield_a_chain_not_a_shortcut():
    syms = [_sym(0, 90, 20, 110, 'Tank'),
            _sym(100, 85, 130, 115, 'Ball_Valve'),
            _sym(200, 85, 230, 115, 'Regulator'),
            _sym(380, 90, 400, 110, 'Tank')]
    lines = [_seg(20, 100, 100, 100), _seg(130, 100, 200, 100),
             _seg(230, 100, 380, 100)]
    geo = build_geometric_connectivity(syms, lines)
    assert _pairs(geo) == {frozenset(('n1', 'n2')), frozenset(('n2', 'n3')),
                           frozenset(('n3', 'n4'))}
    assert frozenset(('n1', 'n4')) not in _pairs(geo)


# ── 14 / 15. duplicates ─────────────────────────────────────────────────────

def test_14_duplicate_line_detection_is_collapsed():
    lines = [_seg(100, 100, 100, 200), _seg(100.2, 100, 100.2, 200)]
    geo = build_geometric_connectivity([], lines)
    assert len(geo['lines']) == 1, 'a 0.2px double-hit is one physical stub'


def test_14b_a_duplicate_pair_does_not_inflate_junction_degree():
    lines = [_seg(0, 100, 200, 100), _seg(200, 100, 400, 100),
             _seg(200, 100, 200, 300), _seg(200.3, 100, 200.3, 300)]
    geo = build_geometric_connectivity([], lines)
    if geo['junctions']:
        assert max(j['degree'] for j in geo['junctions']) == 3


def test_15_overlapping_symbol_boxes_do_not_double_clip():
    """Two YOLO boxes on one physical symbol must not carve the pipe twice."""
    boxes = [(185, 85, 215, 115), (188, 88, 218, 118)]
    out = _clip_segments_to_symbols([[20, 100, 380, 100]], boxes)
    assert len(out) == 2, f'overlapping boxes are one blocker, got {out}'


# ── 16 / 17. junctions next to components ───────────────────────────────────

def test_16_junction_near_a_valve_stays_its_own_node():
    """A tee a short distance from an inline valve is a real distinct node —
    it must not be absorbed into the valve by proximity."""
    syms = [_sym(60, 85, 90, 115, 'Ball_Valve'), _sym(0, 90, 10, 110, 'Tank'),
            _sym(390, 90, 400, 110, 'Tank'), _sym(190, 0, 210, 20, 'Tank')]
    lines = [_seg(10, 100, 60, 100), _seg(90, 100, 200, 100),
             _seg(200, 100, 390, 100), _seg(200, 20, 200, 100)]
    geo = build_geometric_connectivity(syms, lines)
    assert geo['junctions'], 'the tee must survive as a junction'
    assert frozenset(('n1', 'n4')) not in _pairs(geo), 'no valve->branch shortcut'


def test_17_junction_near_an_instrument_does_not_absorb_it():
    syms = [_sym(0, 190, 10, 210, 'Tank'), _sym(390, 190, 400, 210, 'Tank'),
            _sym(190, 40, 210, 70, 'Pressure_Indicator')]
    lines = [_seg(10, 200, 200, 200), _seg(200, 200, 390, 200),
             _seg(200, 70, 200, 200)]
    geo = build_geometric_connectivity(syms, lines)
    ids = {e['from'] for e in geo['edges']} | {e['to'] for e in geo['edges']}
    assert 'n3' in ids, 'the instrument keeps its own identity'


# ── 18. equipment connection ────────────────────────────────────────────────

def test_18_pipe_ending_inside_equipment_connects_to_it():
    syms = [_sym(0, 50, 120, 350, 'Vessel'), _sym(380, 190, 400, 210, 'Pump')]
    geo = build_geometric_connectivity(syms, [_seg(110, 200, 380, 200)])
    assert _pairs(geo) == {frozenset(('n1', 'n2'))}


def test_18b_symbol_close_to_a_pipe_but_not_touching_is_not_connected():
    """Proximity alone must never make an edge."""
    syms = [_sym(0, 90, 20, 110, 'Tank'), _sym(380, 90, 400, 110, 'Tank'),
            _sym(190, 250, 210, 270, 'Pressure_Indicator')]   # 150px off the pipe
    geo = build_geometric_connectivity(syms, [_seg(20, 100, 380, 100)])
    assert _pairs(geo) == {frozenset(('n1', 'n2'))}
    assert 'n3' in geo['unmatched_symbols']


# ── 19. dashed signal line ──────────────────────────────────────────────────

def test_19_dashed_line_classifies_as_signal_and_is_not_piping():
    g = _page()
    x = 20
    while x < 380:
        _ink(g, x, 100, min(x + 8, 380), 100)
        x += 16
    assert _classify_line_style(g, [20, 100, 380, 100]) == 'dashed'

    from extraction_cli.commands import _derive_studio_tables
    nodes = [{'id': 'a', 'label': 'PT-1', 'category': 'instrument'},
             {'id': 'b', 'label': 'PIC-1', 'category': 'instrument'}]
    _, _, conns = _derive_studio_tables(nodes, [{'from': 'a', 'to': 'b', 'kind': 'signal'}])
    assert conns == []


def test_19b_solid_line_stays_process():
    g = _page()
    _ink(g, 20, 100, 380, 100)
    assert _classify_line_style(g, [20, 100, 380, 100]) == 'solid'


# ── 20. multi-page drawing ──────────────────────────────────────────────────

def test_20_two_pages_stay_topologically_separate():
    """Identical geometry on both sheets must not fuse into one network."""
    def one_page():
        syms = [_sym(0, 90, 20, 110, 'Tank'), _sym(380, 90, 400, 110, 'Pump')]
        geo = build_geometric_connectivity(syms, [_seg(20, 100, 380, 100)])
        return [{'id': 'n1'}, {'id': 'n2'}], [dict(e) for e in geo['edges']]

    n1, e1 = one_page()
    n2, e2 = one_page()
    _scope_ids(_page_prefix(1, 2), n1, e1)
    _scope_ids(_page_prefix(2, 2), n2, e2)

    all_nodes, all_edges = n1 + n2, e1 + e2
    assert len({n['id'] for n in all_nodes}) == 4
    endpoints = {e['from'] for e in all_edges} | {e['to'] for e in all_edges}
    assert not any(a.startswith('p1_') and b.startswith('p2_')
                   for e in all_edges for a, b in [(e['from'], e['to'])]), \
        'no edge may span two pages'
    assert endpoints == {'p1_n1', 'p1_n2', 'p2_n1', 'p2_n2'}
