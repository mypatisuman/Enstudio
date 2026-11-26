"""The flow-annotation pass (arrows and electric heat tracing), with the LLM stubbed.

conftest.py switches the pass off for the rest of the suite; these tests turn it
on explicitly.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

STUDIO = Path(__file__).resolve().parent.parent
if str(STUDIO) not in sys.path:
    sys.path.insert(0, str(STUDIO))

import services.llm_flow_annotation_service as FA  # noqa: E402
from services import geometry_store as G  # noqa: E402


def _png(w, h) -> bytes:
    ok, buf = cv2.imencode(".png", np.full((h, w, 3), 255, dtype=np.uint8))
    return buf.tobytes()


def _llm(answer, calls=None):
    def complete(prompt, **kw):
        if calls is not None:
            calls.append((prompt, kw))
        payload = answer(prompt) if callable(answer) else answer
        return SimpleNamespace(text=json.dumps(payload), input_tokens=100, output_tokens=20,
                               cost_usd=0.001)
    return SimpleNamespace(llm=SimpleNamespace(complete_streaming=complete))


@pytest.mark.parametrize("raw, expected", [("", True), ("on", True), ("off", False), ("0", False)])
def test_the_pass_can_be_switched_off(monkeypatch, raw, expected):
    monkeypatch.setenv("STUDIO_FLOW_ANNOTATIONS", raw)
    assert FA.enabled() is expected


@pytest.mark.parametrize("w, h", [(800, 600), (5100, 2920), (1500, 1501)])
def test_crops_cover_every_pixel(w, h):
    covered = np.zeros((h, w), dtype=bool)
    for x0, y0, x1, y1 in FA.crops(w, h):
        assert x1 - x0 <= FA._CROP and y1 - y0 <= FA._CROP
        covered[y0:y1, x0:x1] = True
    assert covered.all()


def test_crop_pixels_map_back_to_page_pixels_after_downscaling(monkeypatch):
    monkeypatch.setattr(FA, "_MAX_EDGE", 700)                    # 1400px crop sent at half size
    calls = []
    s = _llm({"arrows": [{"tip": [100, 50], "tail": [80, 50], "confidence": 0.9}],
              "heat_trace": [{"points": [[10, 10], [60, 10], [60, 40]], "confidence": 0.8}]}, calls)
    out = FA.detect_flow_annotations(s, _png(1400, 1000))
    assert out["arrows"] == [{"tip": [200.0, 100.0], "tail": [160.0, 100.0], "confidence": 0.9}]
    assert out["heat_trace"] == [[20.0, 20.0, 120.0, 20.0], [120.0, 20.0, 120.0, 80.0]]
    assert "700x500 pixels" in calls[0][0] and calls[0][1]["tier"] == "fast"
    assert len(out["usage"]) == 1 and out["crops"] == 1 and out["failed"] == 0


def test_low_confidence_and_malformed_annotations_are_dropped():
    s = _llm({"arrows": [{"tip": [5, 5], "tail": [1, 5], "confidence": 0.3},
                         {"tip": "bad", "tail": [1, 1], "confidence": 0.9},
                         {"tip": [3, 3], "tail": [3, 3], "confidence": 0.9}],
              "heat_trace": [{"points": [[1, 1]], "confidence": 0.9}, "junk"]})
    out = FA.detect_flow_annotations(s, _png(400, 300))
    assert out["arrows"] == [] and out["heat_trace"] == []


def test_a_failing_crop_is_counted_not_fatal():
    state = {"n": 0}

    def answer(prompt):
        state["n"] += 1
        if state["n"] == 1:
            raise RuntimeError("provider 500")
        return {"arrows": [], "heat_trace": []}
    out = FA.detect_flow_annotations(_llm(answer), _png(3000, 1000))
    assert out["crops"] > 1 and out["failed"] == 1


def test_the_same_arrow_from_overlapping_crops_is_kept_once():
    arrows = [{"tip": [100, 100], "tail": [80, 100], "confidence": 0.7},
              {"tip": [104, 101], "tail": [84, 101], "confidence": 0.9},
              {"tip": [104, 101], "tail": [124, 101], "confidence": 0.8}]   # opposite way: distinct
    kept = FA._dedupe_arrows(arrows)
    assert [a["confidence"] for a in kept] == [0.9, 0.8]


def test_the_same_heat_trace_segment_is_kept_once():
    traces = [{"points": [[0, 0], [100, 0]], "confidence": 0.9},
              {"points": [[102, 3], [1, 2]], "confidence": 0.6}]
    assert FA._dedupe_segments(traces) == [[0, 0, 100, 0]]


def test_page_geometry_stores_annotations_after_the_pipe_runs():
    geo = {"lines": [{"x1": 0, "y1": 0, "x2": 10, "y2": 0, "kind": "process"}]}
    ann = {"arrows": [{"tail": [1, 0], "tip": [5, 0], "confidence": 0.9}],
           "heat_trace": [[0, 5, 10, 5]]}
    page = G.page_geometry(geo, [], 100, 100, ann)
    assert [(ln["index"], ln["type"]) for ln in page["lines"]] == [
        (0, "process"), (1, "flow_arrow"), (2, "heat_trace")]
    assert page["lines"][1]["points"] == [[1, 0], [5, 0]]


def test_agentic_pages_run_the_pass_and_bill_it(monkeypatch, tmp_path):
    from agents.extraction.workflows import extraction_workflow as W
    page = tmp_path / "p1.png"
    page.write_bytes(_png(300, 200))
    found = {"arrows": [{"tail": [1, 1], "tip": [9, 1], "confidence": 0.9}], "heat_trace": [],
             "crops": 1, "failed": 0,
             "usage": [SimpleNamespace(input_tokens=10, output_tokens=2, cost_usd=0.01,
                                       model="m", provider="p")]}
    monkeypatch.setattr(FA, "detect_flow_annotations", lambda _s, b: found)
    monkeypatch.setattr("services.llm_symbol_detection_service._studio_module", lambda: None)

    monkeypatch.setenv("STUDIO_FLOW_ANNOTATIONS", "off")
    assert W._flow_annotations(str(page), {"candidate_graph": {}}) == (None, [])

    monkeypatch.setenv("STUDIO_FLOW_ANNOTATIONS", "on")
    assert W._flow_annotations(str(page), {}) == (None, []), "no geometry to attach to"
    annotations, usage = W._flow_annotations(str(page), {"candidate_graph": {}})
    assert annotations is found
    assert usage == [{"stage": "flow_annotations", "provider": "p", "model": "m",
                      "input_tokens": 10, "output_tokens": 2, "cost_usd": 0.01}]

    out = W._namespace_page_results(0, {"nodes": [{"id": "n1"}]}, {"edges": []}, source_id=4,
                                    image_size={"width": 300, "height": 200},
                                    candidate_graph={"lines": []}, symbols=[],
                                    annotations=annotations)
    assert [(ln["id"], ln["type"]) for ln in out["geometry"]["lines"]] == [("s4_line_0", "flow_arrow")]
