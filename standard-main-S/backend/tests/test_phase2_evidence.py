"""Phase 2: the evidence rules added to healing, OCR and the LLM contract.

Three separable pieces, all deterministic and offline:
  * _make_gap_evidence_gate — what may and may not be healed across a gap
  * detect_text_from_bytes  — the two-pass OCR union and its provenance
  * the geometry-first guard on LLM-added edges
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

STUDIO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(STUDIO))

np = pytest.importorskip('numpy')
cv2 = pytest.importorskip('cv2')

from services.geometry.line_geometry import (        # noqa: E402
    _make_gap_evidence_gate, _merge_groups, _group_lines, _GAP_INK_THRESH,
)


def _page(w=600, h=300):
    return np.full((h, w), 255, dtype=np.uint8)


# ── gap evidence gate ───────────────────────────────────────────────────────

def test_gate_allows_a_gap_that_still_has_ink():
    g = _page()
    cv2.line(g, (100, 150), (400, 150), 0, 2)
    gate = _make_gap_evidence_gate(g, 'h', [])
    assert gate(150, 200, 230) is True


def test_gate_blocks_a_gap_over_blank_paper():
    g = _page()
    gate = _make_gap_evidence_gate(g, 'h', [])
    assert gate(150, 200, 230) is False


def test_gate_blocks_a_gap_spanned_by_a_symbol_even_with_ink():
    """An inline component is the strongest possible signal that the break is
    real. Ink through the symbol (its own body) must not override it."""
    g = _page()
    cv2.line(g, (100, 150), (400, 150), 0, 2)
    gate = _make_gap_evidence_gate(g, 'h', [(200, 135, 230, 165)])
    assert gate(150, 195, 235) is False


def test_gate_ignores_a_symbol_on_a_different_axis_position():
    g = _page()
    cv2.line(g, (100, 150), (400, 150), 0, 2)
    gate = _make_gap_evidence_gate(g, 'h', [(200, 20, 230, 60)])   # far above
    assert gate(150, 200, 230) is True


def test_gate_always_allows_overlapping_runs():
    """gap_hi <= gap_lo means the two runs already touch or overlap — the same
    stroke split by the vectoriser, never a healing decision."""
    gate = _make_gap_evidence_gate(_page(), 'h', [(0, 0, 600, 300)])
    assert gate(150, 300, 250) is True


def test_gate_without_an_image_falls_back_to_the_symbol_rule_only():
    gate = _make_gap_evidence_gate(None, 'h', [(200, 135, 230, 165)])
    assert gate(150, 195, 235) is False
    assert gate(150, 400, 430) is True


def test_vertical_gate_works_on_the_other_axis():
    g = _page()
    cv2.line(g, (300, 20), (300, 280), 0, 2)
    gate = _make_gap_evidence_gate(g, 'v', [])
    assert gate(300, 100, 140) is True
    gate_blank = _make_gap_evidence_gate(_page(), 'v', [])
    assert gate_blank(300, 100, 140) is False


def test_ink_threshold_is_a_named_constant_not_a_literal():
    assert 0.0 < _GAP_INK_THRESH <= 1.0


# ── per-run axis position ───────────────────────────────────────────────────

def test_runs_keep_their_own_axis_position():
    """_merge_groups used to stamp one group-wide average axis on every run it
    emitted, dragging two runs that never merged onto a shared centreline."""
    items = [(100.0, 0, 100), (102.0, 400, 500)]     # same 2.5px band, far apart
    runs = _merge_groups(_group_lines(list(items), 2.5), 35.0,
                         _make_gap_evidence_gate(_page(), 'h', []))
    assert len(runs) == 2
    axes = sorted(round(r[0], 1) for r in runs)
    assert axes == [100.0, 102.0], f'each run keeps its own axis: {axes}'


def test_merged_run_averages_only_its_own_members():
    g = _page()
    cv2.line(g, (0, 100), (200, 100), 0, 3)
    items = [(100.0, 0, 100), (100.0, 110, 200), (102.0, 450, 550)]
    runs = _merge_groups(_group_lines(list(items), 2.5), 35.0,
                         _make_gap_evidence_gate(g, 'h', []))
    assert len(runs) == 2
    merged = [r for r in runs if r[1] == 0][0]
    lone = [r for r in runs if r[1] == 450][0]
    assert round(merged[0]) == 100
    assert round(lone[0]) == 102


def test_gate_none_preserves_the_original_distance_only_behaviour():
    """_merge_skeleton_lines still calls _merge_groups without a gate; that
    path must behave exactly as it always did."""
    items = [(100.0, 0, 100), (100.0, 120, 200)]
    runs = _merge_groups(_group_lines(list(items), 2.5), 35.0)
    assert len(runs) == 1, 'no gate -> distance-only merge, as before'


# ── OCR two-pass union ──────────────────────────────────────────────────────

class _FakeOcr:
    """Returns scripted hits per call. RapidOCR's shape is
    [[poly, text, score], ...] and it is called once per crop/tile."""

    def __init__(self, per_call):
        self.per_call = list(per_call)
        self.calls = 0

    def __call__(self, img):
        self.calls += 1
        item = self.per_call.pop(0) if self.per_call else []
        return item, None


def _hit(text, x1, y1, x2, y2, score=0.9):
    return [[[x1, y1], [x2, y1], [x2, y2], [x1, y2]], text, score]



def test_vertical_merge_preserves_provenance():
    from services.geometry.text_geometry import _merge_vertical_boxes
    rows = [{'text': 'PT', 'bbox': [10, 10, 40, 25], 'score': 0.9, 'source': 'page'},
            {'text': '101', 'bbox': [10, 27, 40, 42], 'score': 0.9, 'source': 'page'}]
    merged = _merge_vertical_boxes(rows, vertical_thresh=40)
    assert len(merged) == 1
    assert merged[0]['source'] == 'page', 'source must survive the merge'


# ── geometry-first guard on LLM edges ───────────────────────────────────────

def _grounding(geo_graph, edges, geo_pairs):
    """Mirror of the guard in commands.py, exercised in isolation."""
    grounded = set(geo_graph.get('unmatched_symbols', []))
    for s in geo_graph.get('open_stubs', []):
        if s.get('from'):
            grounded.add(s['from'])
        if s.get('candidate_symbol'):
            grounded.add(s['candidate_symbol'])
    grounded |= {j['id'] for j in geo_graph.get('junctions', [])}
    has_amb = bool(geo_graph.get('ambiguous_crossings'))
    kept = []
    for e in edges:
        pair = frozenset((e['from'], e['to']))
        if pair in geo_pairs:
            e['provenance'] = 'geometry'
            kept.append(e)
        elif (e['from'] in grounded or e['to'] in grounded or has_amb
              or not geo_graph.get('edges')):
            e['provenance'] = 'llm'
            kept.append(e)
    return kept


def test_geometry_backed_edge_is_marked_geometry():
    geo = {'edges': [{'from': 'n1', 'to': 'n2'}], 'open_stubs': [],
           'junctions': [], 'unmatched_symbols': [], 'ambiguous_crossings': []}
    kept = _grounding(geo, [{'from': 'n1', 'to': 'n2'}],
                      {frozenset(('n1', 'n2'))})
    assert kept[0]['provenance'] == 'geometry'


def test_llm_add_against_a_stub_is_kept_and_marked_llm():
    geo = {'edges': [{'from': 'n1', 'to': 'n2'}],
           'open_stubs': [{'from': 'n3', 'candidate_symbol': 'n4'}],
           'junctions': [], 'unmatched_symbols': [], 'ambiguous_crossings': []}
    kept = _grounding(geo, [{'from': 'n3', 'to': 'n4'}], {frozenset(('n1', 'n2'))})
    assert len(kept) == 1 and kept[0]['provenance'] == 'llm'


def test_llm_add_against_an_unmatched_symbol_is_kept():
    geo = {'edges': [{'from': 'n1', 'to': 'n2'}], 'open_stubs': [],
           'junctions': [], 'unmatched_symbols': ['n7'], 'ambiguous_crossings': []}
    kept = _grounding(geo, [{'from': 'n1', 'to': 'n7'}], {frozenset(('n1', 'n2'))})
    assert len(kept) == 1 and kept[0]['provenance'] == 'llm'


def test_ungrounded_llm_edge_is_dropped():
    """Geometry saw both symbols, found no segment, no stub, no junction and no
    ambiguity between them. An edge there is invented."""
    geo = {'edges': [{'from': 'n1', 'to': 'n2'}], 'open_stubs': [],
           'junctions': [], 'unmatched_symbols': [], 'ambiguous_crossings': []}
    kept = _grounding(geo, [{'from': 'n8', 'to': 'n9'}], {frozenset(('n1', 'n2'))})
    assert kept == [], 'an ungrounded LLM edge must not survive'


def test_from_scratch_mode_still_accepts_llm_edges():
    """No UNet segments at all -> no candidate graph -> the LLM is the only
    available source and must not be gagged."""
    geo = {'edges': [], 'open_stubs': [], 'junctions': [],
           'unmatched_symbols': [], 'ambiguous_crossings': []}
    kept = _grounding(geo, [{'from': 'n1', 'to': 'n2'}], set())
    assert len(kept) == 1 and kept[0]['provenance'] == 'llm'
