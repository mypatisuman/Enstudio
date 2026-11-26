"""Document-identity parity between the agentic and classic extraction engines.

The agentic pipeline used to namespace page results with its own 0-based
"p{index}_" prefix and stamp nothing else. That diverged from the classic
pipeline in ways that only became reachable once the desktop app could run
the agentic engine:

  * two documents extracted into the same project both produced "p0_n1", and
    the nodes table is keyed (id, pid), so the second extraction replaced the
    first document's rows;
  * nodes carried no `source_id`, so `_merge` could not tell this run's rows
    from another document's;
  * nodes carried no `page` / `page_w` / `page_h` / `drawing`, so the canvas
    had no sheet grouping and no per-sheet aspect ratio.

These tests pin the fixed behaviour against the classic helpers themselves,
so the two engines cannot drift apart again.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

STUDIO = Path(__file__).resolve().parent.parent
if str(STUDIO) not in sys.path:
    sys.path.insert(0, str(STUDIO))

from agents.extraction.workflows.extraction_workflow import (  # noqa: E402
    _namespace_page_results,
)
from extraction_cli.commands import _fallback_drawing, _id_prefix  # noqa: E402


def _llm_a(*ids, drawing=None):
    out = {"nodes": [{"id": i, "label": i.upper()} for i in ids]}
    if drawing is not None:
        out["drawing"] = drawing
    return out


def _llm_b(edges=(), junctions=()):
    return {"edges": [{"from": a, "to": b} for a, b in edges],
            "junctions": [{"id": j, "x": 1, "y": 2} for j in junctions]}


# ── id scoping matches the classic convention exactly ───────────────────────

def test_single_page_without_source_id_is_unprefixed():
    """The historic single-document, single-page case keeps bare ids."""
    out = _namespace_page_results(0, _llm_a("n1", "n2"), _llm_b([("n1", "n2")]),
                                  source_id=None, total_pages=1)
    assert [n["id"] for n in out["nodes"]] == ["n1", "n2"]
    assert out["edges"][0] == {"from": "n1", "to": "n2"}


def test_multi_page_uses_one_based_classic_page_prefix():
    """Classic is 1-based "p{page}_"; the old agentic code was 0-based."""
    p1 = _namespace_page_results(0, _llm_a("n1"), _llm_b(), total_pages=3)
    p2 = _namespace_page_results(1, _llm_a("n1"), _llm_b(), total_pages=3)
    assert p1["nodes"][0]["id"] == "p1_n1"
    assert p2["nodes"][0]["id"] == "p2_n1"


def test_prefix_is_identical_to_the_classic_helper():
    for source_id in (None, 7):
        for total in (1, 4):
            for page_index in range(total):
                out = _namespace_page_results(
                    page_index, _llm_a("n1"), _llm_b(),
                    source_id=source_id, total_pages=total)
                expected = _id_prefix(source_id, page_index + 1, total) + "n1"
                assert out["nodes"][0]["id"] == expected


def test_two_documents_in_one_project_do_not_collide():
    """The bug this closes: both documents produced the same node id."""
    doc1 = _namespace_page_results(0, _llm_a("n1"), _llm_b(),
                                   source_id=1, total_pages=1)
    doc2 = _namespace_page_results(0, _llm_a("n1"), _llm_b(),
                                   source_id=2, total_pages=1)
    ids = {n["id"] for n in doc1["nodes"]} | {n["id"] for n in doc2["nodes"]}
    assert len(ids) == 2, f"ids collided across documents: {ids}"


def test_edge_endpoints_are_scoped_with_their_nodes():
    out = _namespace_page_results(1, _llm_a("n1", "n2"),
                                  _llm_b([("n1", "n2")]),
                                  source_id=3, total_pages=2)
    node_ids = {n["id"] for n in out["nodes"]}
    edge = out["edges"][0]
    assert edge["from"] in node_ids and edge["to"] in node_ids
    assert edge["from"].startswith("s3_p2_")


def test_junctions_are_added_and_scoped():
    out = _namespace_page_results(0, _llm_a("n1"), _llm_b(junctions=["gj_0"]),
                                  source_id=5, total_pages=1)
    ids = [n["id"] for n in out["nodes"]]
    assert ids == ["s5_n1", "s5_gj_0"]


# ── document / page identity is stamped ─────────────────────────────────────

def test_source_id_is_stamped_on_every_node():
    out = _namespace_page_results(0, _llm_a("n1", "n2"), _llm_b(),
                                  source_id=9, total_pages=1)
    assert all(n["source_id"] == 9 for n in out["nodes"])


def test_source_id_absent_when_not_supplied():
    out = _namespace_page_results(0, _llm_a("n1"), _llm_b(), source_id=None)
    assert "source_id" not in out["nodes"][0]


def test_page_number_is_one_based():
    out = _namespace_page_results(2, _llm_a("n1"), _llm_b(), total_pages=3)
    assert out["nodes"][0]["page"] == 3


def test_page_dimensions_are_stamped_from_image_size():
    out = _namespace_page_results(0, _llm_a("n1"), _llm_b(), total_pages=1,
                                  image_size={"width": 1600, "height": 900})
    node = out["nodes"][0]
    assert (node["page_w"], node["page_h"]) == (1600, 900)


def test_missing_image_size_omits_dimensions():
    out = _namespace_page_results(0, _llm_a("n1"), _llm_b(), image_size={})
    assert "page_w" not in out["nodes"][0]


def test_fallback_drawing_matches_the_classic_helper():
    out = _namespace_page_results(0, _llm_a("n1"), _llm_b(),
                                  source_id=4, total_pages=2)
    assert out["nodes"][0]["drawing"] == _fallback_drawing(4, 1, 2)


def test_real_drawing_number_wins_over_the_fallback():
    out = _namespace_page_results(0, _llm_a("n1", drawing={"number": "PID-42"}),
                                  _llm_b(), source_id=4, total_pages=2)
    assert out["nodes"][0]["drawing"] == "PID-42"


# ── isolated-node handling is preserved ─────────────────────────────────────

def test_edges_touching_isolated_nodes_are_dropped():
    llm_a = {"nodes": [{"id": "n1"},
                       {"id": "n2", "isolated_reason": "no connections"}]}
    out = _namespace_page_results(0, llm_a, _llm_b([("n1", "n2")]),
                                  source_id=1, total_pages=1)
    assert out["edges"] == []


# ── the plumbing that carries source_id into the graph ──────────────────────

def test_state_declares_source_id():
    from agents.extraction.state import ExtractionState
    assert "source_id" in ExtractionState.__annotations__


def test_run_extraction_agentic_accepts_source_id():
    import inspect
    from agents.extraction.workflows.extraction_workflow import (
        run_extraction_agentic,
    )
    params = inspect.signature(run_extraction_agentic).parameters
    assert "source_id" in params
    assert params["source_id"].default is None


def test_cli_exposes_source_id_flag():
    src = (STUDIO / "run_agentic.py").read_text(encoding="utf-8")
    assert "--source-id" in src, "run_agentic.py must accept --source-id"


def test_merge_results_forwards_source_id(monkeypatch):
    """_merge must receive the document id, or rows cannot be attributed."""
    from agents.extraction.agents import orchestration as O

    seen = {}

    def _fake_merge(pid, combined, filename, fhash, _s, source_id=None):
        seen["source_id"] = source_id
        return True

    import extraction_cli.commands as C
    monkeypatch.setattr(C, "_merge", _fake_merge)
    monkeypatch.setitem(sys.modules, "main", type(sys)("main"))

    state = {
        "pid": "p", "hub": ".", "source_path": "x.pdf", "file_hash": "h",
        "source_id": 11,
        "page_pipeline_results": {"0": {"nodes": [{"id": "s11_n1"}],
                                        "edges": []}},
    }
    O.merge_results(state)
    assert seen.get("source_id") == 11
