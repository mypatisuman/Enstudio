"""services/geometry_store.py: extraction geometry persisted per document."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

STUDIO = Path(__file__).resolve().parent.parent
if str(STUDIO) not in sys.path:
    sys.path.insert(0, str(STUDIO))

from services import geometry_store as G  # noqa: E402

GEO = {
    "lines": [
        {"x1": 0, "y1": 10, "x2": 100, "y2": 10, "direction": "horizontal", "kind": "process"},
        {"x1": 50, "y1": 0, "x2": 50, "y2": 90, "direction": "vertical", "kind": "signal"},
    ],
    "junctions": [{"id": "gj_0", "x": 50.0, "y": 10.0, "degree": 3}],
    "ambiguous_crossings": [{"x": 70.0, "y": 40.0, "line_indices": [0, 1]}],
    "open_stubs": [{"x": 100.0, "y": 10.0, "line_index": 0}],
}
SYMBOLS = [{"bbox": [0, 0, 10, 10], "type": "Vessel"}, {"bbox": [90, 0, 110, 20], "type": "Pump"}]


@pytest.fixture()
def db(tmp_path):
    from adapters import db as dbmod
    dbmod.reset_for_path(tmp_path / "studio.db")
    dbmod.init_db()
    yield dbmod
    dbmod.close_db()


def test_page_geometry_classifies_everything():
    page = G.page_geometry(GEO, SYMBOLS, 800, 600)
    assert page["width"] == 800 and len(page["lines"]) == 2
    assert page["lines"][1]["style"] == "dashed", "signal lines draw dashed"
    kinds = {j["kind"] for j in page["junctions"]}
    assert kinds == {G.T_JUNCTION, G.CROSSOVER, G.OPEN_ENDPOINT}
    assert [s["id"] for s in page["symbols"]] == ["n1", "n2"]


def test_scoping_and_edge_links_share_one_prefix():
    page = G.scope_page(G.page_geometry(GEO, SYMBOLS, 800, 600), "s3_p2_")
    assert page["lines"][0]["id"] == "s3_p2_line_0"
    assert page["junctions"][0]["id"] == "s3_p2_gj_0"
    edges = [{"from": "n1", "to": "n2", "line_indices": [0, 1]}]
    G.link_edges_to_lines(edges, "s3_p2_")
    assert edges[0] == {"from": "n1", "to": "n2", "line_ids": ["s3_p2_line_0", "s3_p2_line_1"]}


def test_symbol_bboxes_stamp_only_matching_nodes():
    page = G.page_geometry(GEO, SYMBOLS, 800, 600)
    nodes = [{"id": "n1"}, {"id": "n9"}]
    G.stamp_symbol_bboxes(nodes, page)
    assert nodes[0]["bbox_px"] == [0.0, 0.0, 10.0, 10.0] and "bbox_px" not in nodes[1]


def test_persist_and_load_round_trip(db):
    page = {"page": 1, **G.scope_page(G.page_geometry(GEO, SYMBOLS, 800, 600), "s1_")}
    stored = G.persist_pages("p", 1, [page])
    assert stored == {"pages": 1, "lines": 2, "junctions": 3}
    loaded = G.load("p")
    assert loaded["pages"][(1, 1)] == {"width": 800, "height": 600}
    assert loaded["lines"][0]["points"] == [[0.0, 10.0], [100.0, 10.0]]
    crossing = next(j for j in loaded["junctions"] if j["kind"] == G.CROSSOVER)
    assert crossing["line_indices"] == [0, 1]


def test_re_persisting_one_document_leaves_others_untouched(db):
    doc1 = {"page": 1, **G.scope_page(G.page_geometry(GEO, SYMBOLS, 800, 600), "s1_")}
    doc2 = {"page": 1, **G.scope_page(G.page_geometry(GEO, SYMBOLS, 800, 600), "s2_")}
    G.persist_pages("p", 1, [doc1])
    G.persist_pages("p", 2, [doc2])
    G.persist_pages("p", 1, [])                       # document 1 re-extracted empty
    loaded = G.load("p")
    assert {ln["source_id"] for ln in loaded["lines"]} == {2}
    assert (2, 1) in loaded["pages"] and (1, 1) not in loaded["pages"]


def test_no_source_id_is_stored_as_document_zero(db):
    G.persist_pages("p", None, [{"page": 1, **G.scope_page(G.page_geometry(GEO, [], 10, 10), "")}])
    assert (0, 1) in G.load("p")["pages"]


def test_agentic_pages_carry_geometry_and_line_links():
    from agents.extraction.workflows.extraction_workflow import _namespace_page_results
    candidate = {**GEO, "edges": [{"from": "n1", "to": "n2", "line_indices": [0]}]}
    out = _namespace_page_results(
        0, {"nodes": [{"id": "n1"}, {"id": "n2"}]},
        {"edges": [{"from": "n1", "to": "n2", "kind": "process"}]},
        source_id=5, total_pages=1, image_size={"width": 800, "height": 600},
        candidate_graph=candidate, symbols=SYMBOLS)
    assert out["geometry"]["lines"][0]["id"] == "s5_line_0"
    assert out["edges"][0]["line_ids"] == ["s5_line_0"]
    assert out["nodes"][0]["bbox_px"] == [0.0, 0.0, 10.0, 10.0]
    assert out["nodes"][0]["id"] == "s5_n1"
