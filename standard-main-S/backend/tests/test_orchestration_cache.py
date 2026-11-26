"""Tests for orchestration.py's cache/usage wiring (E4) — the gap where
cache_check called store.get(key) with a missing pid argument (always
TypeError, always swallowed as a miss) and merge_results/finalize never
called store.put() or reported token/cost usage at all.
"""
import sys
from pathlib import Path

import pytest

STUDIO_DIR = Path(__file__).parent.parent
if str(STUDIO_DIR) not in sys.path:
    sys.path.insert(0, str(STUDIO_DIR))

from agents.extraction.agents import orchestration as O  # noqa: E402


@pytest.fixture()
def hub(tmp_path):
    h = tmp_path / "hub"
    (h / "projects" / "tproj" / "cache").mkdir(parents=True)
    return h


def test_cache_check_misses_when_nothing_cached(hub):
    state = {"pid": "tproj", "hub": str(hub), "file_hash": "abc123"}
    out = O.cache_check(state)
    assert out == {"cache_hit": False}


def test_cache_check_hits_after_merge_results_populates(hub):
    state = {"pid": "tproj", "hub": str(hub), "file_hash": "abc123",
             "source_path": str(hub / "projects" / "tproj" / "drawing.png"),
             "llm_a_result": {"nodes": []},
             "page_pipeline_results": {
                 "0": {"nodes": [{"id": "p0_n1"}],
                      "edges": [{"from": "p0_n1", "to": "p0_n2"}]}}}
    (hub / "projects" / "tproj" / "drawing.png").write_bytes(b"fake")

    merged = O.merge_results.__wrapped__(state)
    assert [n["id"] for n in merged["verified_nodes"]] == ["p0_n1"]

    hit_state = {"pid": "tproj", "hub": str(hub), "file_hash": "abc123"}
    out = O.cache_check(hit_state)
    assert out["cache_hit"] is True
    assert out["status"] == "cached"
    assert [n["id"] for n in out["verified_nodes"]] == ["p0_n1"]
    assert out["verified_edges"] == [{"from": "p0_n1", "to": "p0_n2"}]


def test_cache_check_scoped_per_project(hub):
    """A cache entry for one pid must not leak into another pid's
    cache_check — CacheStore rows are (pid, key) scoped."""
    (hub / "projects" / "other").mkdir(parents=True)
    state_a = {"pid": "proj-a", "hub": str(hub), "file_hash": "same-hash",
               "source_path": str(hub / "projects" / "tproj" / "drawing.png"),
               "llm_a_result": {},
               "page_pipeline_results": {
                   "0": {"nodes": [{"id": "p0_n1"}], "edges": []}}}
    (hub / "projects" / "tproj" / "drawing.png").write_bytes(b"fake")
    O.merge_results.__wrapped__(state_a)

    miss_state = {"pid": "proj-b", "hub": str(hub), "file_hash": "same-hash"}
    out = O.cache_check(miss_state)
    assert out == {"cache_hit": False}


def test_finalize_sums_usage_into_flat_fields():
    state = {
        "verified_nodes": [{"id": "n1"}], "verified_edges": [],
        "usage": [
            {"stage": "llm_verification_a", "input_tokens": 100,
             "output_tokens": 50, "cost_usd": 0.01},
            {"stage": "llm_verification_b", "input_tokens": 40,
             "output_tokens": 10, "cost_usd": 0.005},
        ],
        "status": "running",
    }
    captured = {}

    def fake_emit_stage(name, status, **extra):
        captured["name"] = name
        captured["status"] = status
        captured.update(extra)

    import agents.extraction.agents.orchestration as mod
    orig = mod.emit_stage
    mod.emit_stage = fake_emit_stage
    try:
        out = O.finalize(state)
    finally:
        mod.emit_stage = orig

    assert out == {"status": "complete"}
    assert captured["name"] == "done"
    assert captured["tokens_in"] == 140
    assert captured["tokens_out"] == 60
    assert captured["cost_usd"] == pytest.approx(0.015)
    assert captured["total_nodes"] == 1
    assert captured["total_connections"] == 0


def test_finalize_reports_total_counts_by_category():
    """total_nodes/total_instruments/total_equipment/total_connections
    are additive fields extraction.rs's success gate and the frontend's
    completion summary both read with no fallback — must be correct even
    when _merge() failed to enrich nodes with 'category' (falls back to
    _KIND_TO_CATEGORY the same way _merge() derives it)."""
    state = {
        "verified_nodes": [
            {"id": "n1", "category": "equipment"},   # already enriched
            {"id": "n2", "kind": "transmitter"},      # not enriched -> instrument
            {"id": "n3", "kind": "pump"},              # not enriched -> equipment
            {"id": "n4", "kind": "hand_valve"},        # not enriched -> mechanical
        ],
        "verified_edges": [{"from": "n1", "to": "n2"}, {"from": "n3", "to": "n4"}],
        "status": "running",
    }
    captured = {}

    def fake_emit_stage(name, status, **extra):
        captured.update(extra)

    import agents.extraction.agents.orchestration as mod
    orig = mod.emit_stage
    mod.emit_stage = fake_emit_stage
    try:
        O.finalize(state)
    finally:
        mod.emit_stage = orig

    assert captured["total_nodes"] == 4
    assert captured["total_instruments"] == 1
    assert captured["total_equipment"] == 2
    assert captured["total_connections"] == 2


def test_finalize_zero_usage_when_no_records():
    captured = {}

    def fake_emit_stage(name, status, **extra):
        captured.update(extra)

    import agents.extraction.agents.orchestration as mod
    orig = mod.emit_stage
    mod.emit_stage = fake_emit_stage
    try:
        O.finalize({"status": "running"})
    finally:
        mod.emit_stage = orig

    assert captured["tokens_in"] == 0
    assert captured["tokens_out"] == 0
    assert captured["cost_usd"] == 0
