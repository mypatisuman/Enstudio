"""Phase 1: multi-page extraction, id scoping, and status rollup.

No real LLM calls, no GPU, no model weights: every test drives the pure
helpers (_page_prefix / _scope_ids / _derive_studio_tables / rollup) or a
fake LLM callable. PDFs are built in-memory with PyMuPDF.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

STUDIO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(STUDIO))

from extraction_cli.commands import (            # noqa: E402
    _page_prefix, _scope_ids, _derive_studio_tables, _failed_page,
)
from extraction_cli.status import ExtractionStatus, Reason   # noqa: E402

S, P, F = ExtractionStatus.SUCCESS, ExtractionStatus.PARTIAL, ExtractionStatus.FAILED

fitz = pytest.importorskip('fitz', reason='PyMuPDF needed to build test PDFs')

from extraction_cli.pdf import _pdf_page_count, _render_pdf_to_png   # noqa: E402


def _make_pdf(sizes):
    """A PDF with one page per (width, height) in `sizes`, each with ink on it."""
    doc = fitz.open()
    for w, h in sizes:
        page = doc.new_page(width=w, height=h)
        page.draw_line(fitz.Point(10, 10), fitz.Point(w - 10, h - 10))
    data = doc.tobytes()
    doc.close()
    return data


# -- PDF page iteration ------------------------------------------------------

def test_single_page_pdf_reports_one_page():
    assert _pdf_page_count(_make_pdf([(612, 792)])) == 1


def test_three_page_pdf_reports_three_pages():
    assert _pdf_page_count(_make_pdf([(612, 792)] * 3)) == 3


def test_every_page_renders_not_just_the_first():
    """The Phase 1 headline bug: _render_pdf_to_png was hardcoded to doc[0]."""
    pdf = _make_pdf([(612, 792), (400, 400), (1000, 500)])
    rendered = [_render_pdf_to_png(pdf, i) for i in range(3)]
    assert all(len(png) > 0 for png, _, _ in rendered)
    # Distinct page geometry must survive as distinct raster geometry.
    ratios = [round(w / h, 3) for _, w, h in rendered]
    assert ratios[0] != ratios[1]
    assert ratios[1] != ratios[2]


def test_page_dimensions_are_per_page_not_inherited():
    pdf = _make_pdf([(1000, 500), (500, 1000)])
    _, w1, h1 = _render_pdf_to_png(pdf, 0)
    _, w2, h2 = _render_pdf_to_png(pdf, 1)
    assert w1 > h1, 'page 1 is landscape'
    assert h2 > w2, 'page 2 is portrait - it must not inherit page 1 scaling'


def test_out_of_range_page_is_rejected():
    pdf = _make_pdf([(612, 792)])
    with pytest.raises(SystemExit):
        _render_pdf_to_png(pdf, 5)


# -- id scoping --------------------------------------------------------------

def test_single_page_ids_are_unprefixed():
    """Existing single-page projects must keep byte-identical ids."""
    assert _page_prefix(1, 1) == ''
    nodes = [{'id': 'n1'}]
    edges = [{'from': 'n1', 'to': 'n2'}]
    _scope_ids(_page_prefix(1, 1), nodes, edges)
    assert nodes[0]['id'] == 'n1'
    assert edges[0] == {'from': 'n1', 'to': 'n2'}


def test_multi_page_ids_are_namespaced_per_page():
    assert _page_prefix(1, 3) == 'p1_'
    assert _page_prefix(2, 3) == 'p2_'


def test_pages_cannot_collide_on_node_id():
    """Both pages produce 'n1'; after scoping the ids must be distinct, or the
    (id, pid)-keyed nodes table silently REPLACEs page 1 with page 2."""
    p1_nodes = [{'id': 'n1', 'label': 'PT-100'}]
    p2_nodes = [{'id': 'n1', 'label': 'PT-200'}]
    _scope_ids(_page_prefix(1, 2), p1_nodes, [])
    _scope_ids(_page_prefix(2, 2), p2_nodes, [])
    ids = {n['id'] for n in p1_nodes} | {n['id'] for n in p2_nodes}
    assert len(ids) == 2, f'ids collided: {ids}'
    assert ids == {'p1_n1', 'p2_n1'}


def test_scoping_rewrites_edges_refs_and_merges_together():
    nodes = [{'id': 'n1', 'equipment_ref': 'n2', 'merged_from': ['n7', 'n8']}]
    edges = [{'from': 'n1', 'to': 'gj_0'}]
    _scope_ids('p3_', nodes, edges)
    assert nodes[0]['id'] == 'p3_n1'
    assert nodes[0]['equipment_ref'] == 'p3_n2'
    assert nodes[0]['merged_from'] == ['p3_n7', 'p3_n8']
    assert edges[0] == {'from': 'p3_n1', 'to': 'p3_gj_0'}


def test_scoping_keeps_edges_resolvable_against_scoped_nodes():
    """An edge that pointed at a node before scoping must still point at it
    after - otherwise _derive_studio_tables loses every from_tag/to_tag."""
    nodes = [{'id': 'n1', 'label': 'A', 'category': 'equipment'},
             {'id': 'n2', 'label': 'B', 'category': 'equipment'}]
    edges = [{'from': 'n1', 'to': 'n2', 'kind': 'process'}]
    _scope_ids('p2_', nodes, edges)
    _, _, conns = _derive_studio_tables(nodes, edges)
    assert len(conns) == 1
    assert conns[0]['from_tag'] == 'A' and conns[0]['to_tag'] == 'B'


# -- page identity survives into the studio tables ---------------------------

def test_page_and_drawing_reach_the_derived_tables():
    nodes = [
        {'id': 'p1_n1', 'label': 'PT-100', 'category': 'instrument',
         'page': 1, 'drawing': 'D-001', 'type': 'transmitter'},
        {'id': 'p2_n1', 'label': 'V-200', 'category': 'equipment',
         'page': 2, 'drawing': 'D-002'},
    ]
    instruments, equipment, _ = _derive_studio_tables(nodes, [])
    assert instruments['PT-100']['page'] == 1
    assert instruments['PT-100']['drawing'] == 'D-001'
    assert equipment['V-200']['page'] == 2
    assert equipment['V-200']['drawing'] == 'D-002'


def test_signal_edges_are_not_piping_connections():
    nodes = [{'id': 'a', 'label': 'A', 'category': 'equipment'},
             {'id': 'b', 'label': 'B', 'category': 'instrument'}]
    edges = [{'from': 'a', 'to': 'b', 'kind': 'signal'},
             {'from': 'a', 'to': 'b', 'kind': 'process'}]
    _, _, conns = _derive_studio_tables(nodes, edges)
    assert len(conns) == 1


def test_derive_tables_scales_to_a_large_graph():
    """>2000 edges must all survive derivation. The old implementation did a
    linear `next(n for n in nodes ...)` scan per edge, i.e. O(nodes x edges);
    this also pins the dict-lookup replacement."""
    nodes = [{'id': f'n{i}', 'label': f'T-{i}', 'category': 'equipment'}
             for i in range(2600)]
    edges = [{'from': f'n{i}', 'to': f'n{i + 1}', 'kind': 'process'}
             for i in range(2500)]
    _, equipment, conns = _derive_studio_tables(nodes, edges)
    assert len(conns) == 2500
    assert len(equipment) == 2600
    assert conns[0]['from_tag'] == 'T-0'
    assert conns[-1]['to_tag'] == 'T-2500'


# -- status rollup -----------------------------------------------------------

def test_all_pages_good_is_success():
    assert ExtractionStatus.rollup([{'status': S}, {'status': S}]) == (S, None)


def test_one_partial_page_downgrades_the_whole_run():
    status, reason = ExtractionStatus.rollup([
        {'status': S},
        {'status': P, 'reason': Reason.LLM_VERIFICATION_FAILED},
        {'status': S},
    ])
    assert status == P
    assert reason == Reason.LLM_VERIFICATION_FAILED


def test_a_failed_page_among_good_ones_is_partial_not_failed():
    status, _ = ExtractionStatus.rollup([
        {'status': S}, {'status': F, 'reason': Reason.SYMBOL_VERIFICATION_FAILED}])
    assert status == P, 'other pages produced real output - not a total failure'


def test_every_page_failed_is_failed():
    status, reason = ExtractionStatus.rollup([
        {'status': F, 'reason': Reason.SYMBOL_VERIFICATION_FAILED},
        {'status': F, 'reason': Reason.SYMBOL_VERIFICATION_FAILED}])
    assert (status, reason) == (F, Reason.SYMBOL_VERIFICATION_FAILED)


def test_no_pages_is_failed():
    assert ExtractionStatus.rollup([]) == (F, Reason.NO_PAGES)


def test_failed_page_shape_has_no_topology_but_keeps_cv_counts():
    r = _failed_page(F, Reason.LLM_VERIFICATION_FAILED,
                     {'symbols': [1, 2, 3], 'texts': [1], 'lines': []})
    assert r['nodes'] == [] and r['edges'] == []
    assert r['status'] == F and r['reason'] == Reason.LLM_VERIFICATION_FAILED
    assert r['cv']['symbol_count'] == 3
    assert r['usage']['cost_usd'] == 0.0
